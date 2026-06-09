"""
微信 → Claude Code Bridge（服务器版）

把微信私聊消息转发给本机的 Claude Code CLI，把回复发回微信。
依赖 Claude Pro 订阅，无需额外 API Key。

用法：
    python bridge.py            # 首次运行扫码登录
    python bridge.py --logout   # 清除登录凭据
    python bridge.py --login    # 强制重新登录
"""

from __future__ import annotations   # Python 3.8+ 兼容 X | Y 类型注解

import argparse
import json
import logging
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import httpx

from ilink_client import ILinkClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 每个微信用户对应一个 Claude Code session_id（持久多轮对话）
_sessions: dict[str, str] = {}
_sessions_lock = threading.Lock()
_SESSIONS_FILE = Path.home() / ".config" / "wechat-bridge" / "sessions.json"


def _load_sessions() -> None:
    if _SESSIONS_FILE.exists():
        try:
            data = json.loads(_SESSIONS_FILE.read_text())
            if isinstance(data, dict):
                _sessions.update(data)
                logger.info("已恢复 %d 个对话 session", len(data))
        except Exception as e:
            logger.warning("读取 sessions 失败: %s", e)


def _save_sessions() -> None:
    try:
        _SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _sessions_lock:
            data = dict(_sessions)
        _SESSIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning("保存 sessions 失败: %s", e)


# 单线程：服务器单核 + 内存有限，不允许多个 Claude Code 进程并发
_executor = ThreadPoolExecutor(max_workers=1)


# ── Markdown → 纯文本 ────────────────────────────────────────────

def md_to_plain(text: str) -> str:
    """微信不渲染 Markdown，去掉常见标记。"""
    text = re.sub(r"```[\w]*\n?", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__",     r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = re.sub(r"_(.+?)_",       r"\1", text)
    text = re.sub(r"`([^`]+)`",     r"\1", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1 (\2)", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*_]{3,}\s*$", "──────", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── 图片下载与解密 ────────────────────────────────────────────────

def _is_image(data: bytes) -> bool:
    """宽松图片头检测：JPEG、PNG、WebP、GIF、BMP。"""
    if len(data) < 4:
        return False
    return (
        data[:3] == b"\xff\xd8\xff"
        or data[:4] == b"\x89PNG"
        or data[:4] == b"RIFF"
        or data[:4] == b"GIF8"
        or data[:2] == b"BM"
    )


def _decrypt_image(data: bytes, aeskey_hex: str, iv: bytes = b"\x00" * 16) -> bytes | None:
    """AES-CBC 解密，去除 PKCS7 填充；失败时返回 None。"""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding as crypto_padding
        key = bytes.fromhex(aeskey_hex)
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        dec = cipher.decryptor()
        raw = dec.update(data) + dec.finalize()
        try:
            unpadder = crypto_padding.PKCS7(128).unpadder()
            return unpadder.update(raw) + unpadder.finalize()
        except Exception:
            return raw
    except Exception as e:
        logger.warning("图片解密失败(iv=%s): %s", iv[:4].hex(), e)
        return None


def _normalize_jpeg(data: bytes) -> bytes:
    """
    把图片数据重新编码为标准 JPEG。
    优先 Pillow，失败则 ffmpeg，再失败返回原始数据。
    """
    import io as _io, subprocess, tempfile, os

    try:
        from PIL import Image, ImageFile
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        Image.MAX_IMAGE_PIXELS = None
        img = Image.open(_io.BytesIO(data), formats=["JPEG", "PNG", "WEBP", "GIF", "BMP"])
        img.load()
        buf = _io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=95)
        result = buf.getvalue()
        logger.info("图片标准化完成(Pillow) %d bytes", len(result))
        return result
    except Exception as e:
        logger.debug("Pillow 标准化失败: %s", e)

    in_fd, in_path = tempfile.mkstemp(suffix=".bin")
    out_path = in_path + ".jpg"
    try:
        os.write(in_fd, data)
        os.close(in_fd)
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", in_path, "-q:v", "3", out_path],
            capture_output=True, timeout=30,
        )
        if r.returncode == 0 and os.path.getsize(out_path) > 0:
            result = open(out_path, "rb").read()
            logger.info("图片标准化完成(ffmpeg) %d bytes", len(result))
            return result
        logger.debug("ffmpeg 失败: %s", r.stderr.decode(errors="replace")[:200])
    except Exception as e:
        logger.debug("ffmpeg 异常: %s", e)
    finally:
        try: os.unlink(in_path)
        except OSError: pass
        try: os.unlink(out_path)
        except OSError: pass

    logger.warning("图片标准化全部失败，使用原始数据 首字节: %s", data[:16].hex())
    return data


def _is_well_formed_jpeg(data: bytes) -> bool:
    """JFIF APP0（长度=16）结束后偏移 20 必须是 0xFF。"""
    if data[:3] != b"\xff\xd8\xff":
        return False
    if len(data) > 20 and data[2:4] == b"\xff\xe0" and data[4:6] == b"\x00\x10":
        return data[20] == 0xFF
    return True


def _try_decrypt(data: bytes, aeskey_hex: str) -> bytes | None:
    """
    依次尝试多种解密方案，优先返回通过严格 JPEG 结构验证的结果。
    方案 0（最优先）：全文件 AES-ECB——微信图片实际使用的加密方式。
    方案 1：只解密首块（ECB）——"仅头部加密"格式。
    方案 2-4：全文件 AES-CBC（不同 IV）——兜底。
    """
    try:
        key_bytes = bytes.fromhex(aeskey_hex)
    except Exception:
        return None

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    from cryptography.hazmat.primitives.ciphers import modes as cry_modes
    from cryptography.hazmat.primitives import padding as crypto_padding

    candidates: list[tuple[bytes, str]] = []

    # 方案 0：全文件 AES-ECB
    try:
        dec = Cipher(algorithms.AES(key_bytes), cry_modes.ECB()).decryptor()
        raw = dec.update(data) + dec.finalize()
        try:
            unpadder = crypto_padding.PKCS7(128).unpadder()
            result = unpadder.update(raw) + unpadder.finalize()
        except Exception:
            result = raw
        candidates.append((result, "全文件ECB"))
    except Exception as e:
        logger.debug("全文件ECB失败: %s", e)

    # 方案 1：仅首块 AES-ECB
    if len(data) >= 16:
        try:
            dec = Cipher(algorithms.AES(key_bytes), cry_modes.ECB()).decryptor()
            first_block = dec.update(data[:16]) + dec.finalize()
            candidates.append((first_block + data[16:], "首块ECB"))
        except Exception as e:
            logger.debug("首块ECB失败: %s", e)

    # 方案 2-4：全文件 AES-CBC
    for iv, label in [
        (b"\x00" * 16,                                        "全文件iv=0"),
        (key_bytes[:16] if len(key_bytes) >= 16 else None,    "全文件iv=key[:16]"),
        (key_bytes[-16:] if len(key_bytes) >= 16 else None,   "全文件iv=key[-16:]"),
    ]:
        if iv is None:
            continue
        result = _decrypt_image(data, aeskey_hex, iv)
        if result:
            candidates.append((result, label))

    for strict in (True, False):
        for cand, label in candidates:
            ok = _is_well_formed_jpeg(cand) if strict else _is_image(cand)
            if ok:
                logger.debug("解密成功(%s%s) 首字节: %s",
                             label, "" if strict else "(宽松)", cand[:8].hex())
                return cand
    return None


def _download_image(img_info: dict) -> str | None:
    """下载微信图片，返回临时文件路径（调用方负责删除）。"""
    url    = img_info.get("url", "")
    aeskey = img_info.get("aeskey", "")
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        data = resp.content

        logger.debug("图片原始首字节: %s (%d bytes)", data[:8].hex(), len(data))
        if aeskey:
            decrypted = _try_decrypt(data, aeskey)
            if decrypted:
                data = decrypted
            elif not _is_image(data):
                logger.warning("图片无法解密，首字节: %s (%d bytes)", data[:8].hex(), len(data))
                return None
            else:
                logger.debug("解密未产生有效图片，使用原始数据")
        elif not _is_image(data):
            logger.warning("图片格式无法识别，首字节: %s", data[:8].hex())
            return None

        data = _normalize_jpeg(data)
        tmp = Path(f"/tmp/wechat_img_{uuid.uuid4().hex[:8]}.jpg")
        tmp.write_bytes(data)
        logger.info("图片已下载: %s (%d bytes)", tmp.name, len(data))
        return str(tmp)
    except Exception as e:
        logger.warning("图片下载失败: %s", e)
        return None


# ── Claude Code 调用 ──────────────────────────────────────────────

def _find_claude() -> str | None:
    return shutil.which("claude")


def call_claude(message: str, user_id: str, image_paths: list[str] | None = None) -> str:
    """调用本机 Claude Code CLI，返回回复文本。"""
    binary = _find_claude()
    if not binary:
        return "[错误：找不到 claude 命令，请先安装 Claude Code CLI]"

    with _sessions_lock:
        session_id = _sessions.get(user_id)

    cmd = [
        binary, "-p",
        "--output-format", "json",
        "--dangerously-skip-permissions",   # 服务器无人值守，预配置权限后跳过弹窗
    ]
    if session_id:
        cmd.extend(["--resume", session_id])

    if image_paths:
        paths_str = "\n".join(f"- {p}" for p in image_paths)
        message = (
            f"[用户发来了图片，请使用 Read 工具查看以下路径后回答]\n{paths_str}\n\n{message}"
            if message else
            f"[用户发来了图片，请使用 Read 工具查看并描述]\n{paths_str}"
        )

    logger.info("调用 Claude (session=%s%s)",
                session_id[:8] if session_id else "new",
                f", {len(image_paths)}张图片" if image_paths else "")

    try:
        result = subprocess.run(
            cmd,
            input=message,
            capture_output=True,
            text=True,
            timeout=120,   # 服务器单核，2 分钟上限
        )
    except subprocess.TimeoutExpired:
        return "[超时：Claude Code 超过 2 分钟未响应]"
    except FileNotFoundError:
        return "[错误：claude 命令不存在]"

    if result.returncode != 0:
        err = result.stderr.lower()
        if session_id and "session" in err and "not found" in err:
            logger.warning("Session 已过期，清除后重试")
            with _sessions_lock:
                _sessions.pop(user_id, None)
            cmd2 = [binary, "-p", "--output-format", "json",
                    "--dangerously-skip-permissions"]
            try:
                result = subprocess.run(
                    cmd2, input=message, capture_output=True,
                    text=True, timeout=120,
                )
            except subprocess.TimeoutExpired:
                return "[超时：Claude Code 超过 2 分钟未响应]"

        if result.returncode != 0:
            logger.error("Claude Code 退出码 %d: %s",
                         result.returncode, result.stderr[:300])
            return "[Claude Code 出错，请查看日志]"

    return _parse_output(result.stdout, user_id)


def _parse_output(stdout: str, user_id: str) -> str:
    """解析 Claude Code JSON 输出，保存 session_id，返回文本。"""
    if not stdout.strip():
        return "[Claude Code 无输出]"

    try:
        data = json.loads(stdout)
        sid = data.get("session_id")
        if sid:
            with _sessions_lock:
                _sessions[user_id] = sid
            _save_sessions()
        return data.get("result") or data.get("text") or str(data)
    except json.JSONDecodeError:
        pass

    parts = []
    for line in stdout.strip().splitlines():
        try:
            obj = json.loads(line)
            if obj.get("type") == "result":
                sid = obj.get("session_id")
                if sid:
                    with _sessions_lock:
                        _sessions[user_id] = sid
                    _save_sessions()
                parts.append(obj.get("result", ""))
            elif obj.get("type") == "assistant":
                for block in obj.get("content", []):
                    if block.get("type") == "text":
                        parts.append(block["text"])
        except (json.JSONDecodeError, TypeError):
            parts.append(line)

    return "\n".join(parts).strip() or stdout.strip()


# ── 消息处理 ──────────────────────────────────────────────────────

HELP_TEXT = """\
可用命令：
  /reset   — 清除对话历史，开始新会话
  /status  — 查看 bridge 状态
  /help    — 显示此帮助
其他消息直接发给 Claude。"""


def handle_message(client: ILinkClient, msg: dict) -> None:
    """处理一条微信私聊消息（在线程池中运行）。"""
    from_user     = msg.get("from_user_id", "unknown")
    context_token = msg.get("context_token", "")
    text   = client.extract_text(msg).strip()
    images = client.extract_images(msg)

    if not text and not images:
        return

    if images:
        logger.info("收到图片消息 from=%s (%d张)%s",
                    from_user[:12], len(images), f": {text[:40]}" if text else "")
    else:
        logger.info("收到消息 from=%s: %s", from_user[:12], text[:60])

    cmd = text.lower()

    if cmd == "/reset":
        with _sessions_lock:
            _sessions.pop(from_user, None)
        _save_sessions()
        client.send(from_user, context_token, "已清除对话历史，开始新会话。")
        return

    if cmd == "/status":
        with _sessions_lock:
            sid = (_sessions.get(from_user, "")[:8] or "无")
        claude_ok = "✅ 已安装" if _find_claude() else "❌ 未找到"
        client.send(
            from_user, context_token,
            f"Bridge 状态：运行中\nClaude Code：{claude_ok}\n当前 Session：{sid}",
        )
        return

    if cmd == "/help":
        client.send(from_user, context_token, HELP_TEXT)
        return

    image_paths: list[str] = []
    try:
        for img_info in images:
            path = _download_image(img_info)
            if path:
                image_paths.append(path)

        if not text and not image_paths:
            return

        reply = call_claude(text, from_user, image_paths or None)
        reply = md_to_plain(reply)
    except Exception as e:
        logger.error("call_claude 异常: %s", e, exc_info=True)
        reply = "[内部错误，请稍后重试]"
    finally:
        for p in image_paths:
            Path(p).unlink(missing_ok=True)

    client.send(from_user, context_token, reply)
    logger.info("已回复 from=%s (%d 字)", from_user[:12], len(reply))


# ── 主循环 ────────────────────────────────────────────────────────

def run() -> None:
    client = ILinkClient()

    if not client.logged_in:
        print("未找到登录信息，开始扫码登录……\n")
        client.login()

    _load_sessions()
    print("\n=== 微信 Claude Bridge 已启动（服务器版）===")
    print("监听私聊消息中……（Ctrl+C 停止）\n")

    err_count = 0
    try:
        while True:
            try:
                messages = client.poll()
                err_count = 0
                for msg in messages:
                    _executor.submit(handle_message, client, msg)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                err_count += 1
                logger.error("轮询出错 (%d): %s", err_count, e)
                if "401" in str(e) or "unauthorized" in str(e).lower():
                    logger.warning("Token 可能已失效，请用 --login 重新登录")
                if err_count >= 10:
                    logger.critical("连续出错 10 次，停止运行")
                    break
                time.sleep(min(2 ** err_count, 60))
    except KeyboardInterrupt:
        print("\n正在停止……")
    finally:
        _executor.shutdown(wait=False)
        client.close()
        print("已停止。")


# ── 入口 ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="微信 ClawBot <-> Claude Code Bridge（服务器版）")
    parser.add_argument("--logout", action="store_true", help="清除登录凭据")
    parser.add_argument("--login",  action="store_true", help="强制重新扫码登录")
    args = parser.parse_args()

    client = ILinkClient()

    if args.logout:
        client.logout()
        client.close()
        return

    if args.login:
        client.logout()
        client.login()
        client.close()
        return

    run()


if __name__ == "__main__":
    main()
