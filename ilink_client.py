"""
iLink Bot API 客户端
与腾讯 iLink 官方服务器通信，处理登录、收消息、发消息。
"""

from __future__ import annotations   # Python 3.8+ 兼容 X | Y 类型注解

import base64
import json
import logging
import os
import random
import stat
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

ILINK_BASE = "https://ilinkai.weixin.qq.com"
CHANNEL_VER = "1.0.2"
CONFIG_DIR   = Path.home() / ".config" / "wechat-bridge"
TOKEN_FILE   = CONFIG_DIR / "token.json"
CURSOR_FILE  = CONFIG_DIR / "cursor.dat"
POLL_TIMEOUT = 45   # 服务器 hold 约 35s，留余量


# ── 工具函数 ────────────────────────────────────────────────────

def _rand_uin() -> str:
    """生成随机 X-WECHAT-UIN 头（官方要求）。"""
    val = random.randint(0, 0xFFFFFFFF)
    return base64.b64encode(str(val).encode()).decode()


def _safe_base_url(url: str) -> str:
    """只允许 *.weixin.qq.com / *.wechat.com，防止重定向到恶意地址。"""
    p = urlparse(url)
    ok = (".weixin.qq.com", ".wechat.com")
    if p.scheme == "https" and p.hostname and any(p.hostname.endswith(s) for s in ok):
        return url
    logger.warning("拒绝不可信 base_url，回退默认: %s", url)
    return ILINK_BASE


def _save_token(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, stat.S_IRWXU)
    except OSError:
        pass
    TOKEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    try:
        os.chmod(TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _load_token() -> dict | None:
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except Exception as e:
            logger.warning("读取 token 失败: %s", e)
    return None


# ── 主类 ─────────────────────────────────────────────────────────

class ILinkClient:
    def __init__(self) -> None:
        self.bot_token: str | None = None
        self.base_url:  str        = ILINK_BASE
        self._cursor:   str        = ""

        self._http = httpx.Client(timeout=POLL_TIMEOUT + 5)
        self._restore_token()
        self._cursor = self._load_cursor()

    # ── 登录态 ───────────────────────────────────────────────────

    def _restore_token(self) -> None:
        data = _load_token()
        if data:
            self.bot_token = data.get("bot_token")
            self.base_url  = _safe_base_url(data.get("base_url", ILINK_BASE))
            logger.info("已恢复登录 token")

    @property
    def logged_in(self) -> bool:
        return self.bot_token is not None

    def _headers(self) -> dict:
        if not self.bot_token:
            raise RuntimeError("未登录，请先调用 login()")
        return {
            "Content-Type":      "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN":      _rand_uin(),
            "Authorization":     f"Bearer {self.bot_token}",
        }

    # ── 扫码登录 ─────────────────────────────────────────────────

    def login(self) -> None:
        """在终端显示二维码，等待微信扫码确认。"""
        resp = self._http.get(
            f"{ILINK_BASE}/ilink/bot/get_bot_qrcode",
            params={"bot_type": "3"},
        )
        resp.raise_for_status()
        data = resp.json()

        qrcode_id  = data["qrcode"]
        qr_content = data.get("qrcode_img_content", qrcode_id)

        self._show_qr(qr_content)
        print("等待微信扫码……")

        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            r = self._http.get(
                f"{ILINK_BASE}/ilink/bot/get_qrcode_status",
                params={"qrcode": qrcode_id},
                headers={"iLink-App-ClientVersion": "1"},
            )
            r.raise_for_status()
            s = r.json()
            status = s.get("status", "")

            if status == "confirmed":
                self.bot_token = s["bot_token"]
                self.base_url  = _safe_base_url(s.get("baseurl", ILINK_BASE))
                _save_token({
                    "bot_token":  self.bot_token,
                    "base_url":   self.base_url,
                    "login_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                })
                print("✅ 登录成功！")
                return
            elif status == "expired":
                raise TimeoutError("二维码已过期，请重新运行")

            time.sleep(2)

        raise TimeoutError("扫码超时（5分钟），请重新运行")

    def _show_qr(self, content: str) -> None:
        """在终端渲染二维码，同时保存为 PNG。"""
        try:
            import qrcode as qr_lib
            qr = qr_lib.QRCode(border=1)
            qr.add_data(content)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
            print("用微信扫描上方二维码")

            qr_path = CONFIG_DIR / "qr.png"
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            qr_lib.make(content).save(str(qr_path))
            print(f"（二维码图片已保存至 {qr_path}）")
        except Exception:
            print(f"二维码内容（请复制到二维码生成器）：\n{content}")

    def logout(self) -> None:
        self.bot_token = None
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
        print("已退出登录")

    # ── 游标持久化 ───────────────────────────────────────────────

    def _load_cursor(self) -> str:
        try:
            if CURSOR_FILE.exists():
                return CURSOR_FILE.read_text().strip()
        except OSError:
            pass
        return ""

    def _save_cursor(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CURSOR_FILE.write_text(self._cursor)
        try:
            os.chmod(CURSOR_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    # ── 收消息（长轮询） ─────────────────────────────────────────

    def poll(self) -> list[dict]:
        """长轮询，返回新的私聊消息列表（message_type=1）。"""
        resp = self._http.post(
            f"{self.base_url}/ilink/bot/getupdates",
            headers=self._headers(),
            json={
                "get_updates_buf": self._cursor,
                "base_info": {"channel_version": CHANNEL_VER},
            },
            timeout=POLL_TIMEOUT + 5,
        )
        resp.raise_for_status()

        try:
            data = resp.json()
        except Exception:
            logger.warning("getupdates 返回非 JSON")
            return []

        if data.get("ret", 0) != 0:
            logger.warning("getupdates 错误: ret=%s msg=%s",
                           data.get("ret"), data.get("errmsg", ""))
            return []

        new_cursor = data.get("get_updates_buf", "")
        if new_cursor:
            self._cursor = new_cursor
            self._save_cursor()

        return [m for m in data.get("msgs", []) if m.get("message_type") == 1]

    # ── 发消息 ───────────────────────────────────────────────────

    def send(self, to_user: str, context_token: str, text: str) -> bool:
        """发送文本回复，超长自动分段。"""
        for chunk in _split(text, 4000):
            payload = {
                "msg": {
                    "from_user_id":  "",
                    "to_user_id":    to_user,
                    "client_id":     f"wechat-bridge:{uuid.uuid4().hex[:16]}",
                    "message_type":  2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": [{"type": 1, "text_item": {"text": chunk}}],
                },
                "base_info": {"channel_version": CHANNEL_VER},
            }
            r = self._http.post(
                f"{self.base_url}/ilink/bot/sendmessage",
                headers=self._headers(),
                json=payload,
            )
            try:
                rd = r.json()
            except Exception:
                logger.error("sendmessage 返回非 JSON (status=%d)", r.status_code)
                return False
            if r.status_code != 200 or rd.get("ret", 0) != 0:
                logger.error("发送失败: ret=%s errmsg=%s",
                             rd.get("ret"), rd.get("errmsg", ""))
                return False
        return True

    def close(self) -> None:
        self._http.close()

    # ── 消息解析工具 ─────────────────────────────────────────────

    @staticmethod
    def extract_text(msg: dict) -> str:
        """从消息 item_list 中提取纯文本。"""
        parts = []
        for item in msg.get("item_list", []):
            if item.get("type") == 1:
                parts.append(item.get("text_item", {}).get("text", ""))
        return "\n".join(parts).strip()

    @staticmethod
    def extract_images(msg: dict) -> list[dict]:
        """从消息 item_list 中提取图片信息列表。"""
        images = []
        for item in msg.get("item_list", []):
            if item.get("type") == 2:
                img = item.get("image_item", {})
                url = img.get("media", {}).get("full_url", "")
                aeskey = img.get("aeskey", "")
                if url:
                    images.append({"url": url, "aeskey": aeskey})
        return images


# ── 工具：消息分段 ───────────────────────────────────────────────

def _split(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = max_len
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks
