#!/usr/bin/env bash
# 服务器一键安装脚本
# 适用：Ubuntu 20.04+，不依赖 conda，使用 venv
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# ── 1. 找到 Python 3.8+（代码用 from __future__ import annotations，3.8 即可）──
echo "[INFO] 检查 Python 版本..."
PYTHON=""
for py in python3.12 python3.11 python3.10 python3.9 python3.8 python3; do
    if command -v "$py" &>/dev/null; then
        # 验证版本 >= 3.8
        if "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" 2>/dev/null; then
            PYTHON="$py"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "[ERROR] 未找到 Python 3.8+，请手动安装："
    echo "        apt-get install -y python3.8 python3.8-venv"
    exit 1
fi

# 确保对应版本的 venv 模块可用
PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if ! "$PYTHON" -m venv --help &>/dev/null 2>&1; then
    echo "[INFO] 安装 python${PY_VER}-venv..."
    apt-get install -y "python${PY_VER}-venv" || true
fi

echo "[INFO] 使用: $($PYTHON --version)"

# ── 2. 创建虚拟环境 ──────────────────────────────────────────────
if [[ -d "$VENV_DIR" ]]; then
    echo "[INFO] 虚拟环境已存在，跳过创建。"
else
    echo "[INFO] 创建虚拟环境: $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR"
fi

# ── 3. 安装依赖 ──────────────────────────────────────────────────
echo "[INFO] 安装 Python 依赖..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

# ── 4. 配置 Claude Code 权限 ────────────────────────────────────
echo "[INFO] 配置 Claude Code 权限（服务器无人值守模式）..."
"$VENV_DIR/bin/python3" - <<'EOF'
import json, os, sys
from pathlib import Path

settings_file = Path.home() / ".claude" / "settings.json"
settings_file.parent.mkdir(parents=True, exist_ok=True)

try:
    settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
except Exception:
    settings = {}

perms = settings.setdefault("permissions", {})
allow = perms.setdefault("allow", [])

needed = ["Read", "Edit", "Write", "Bash(git *)", "Bash(python *)", "Bash(pip *)"]
added = [r for r in needed if r not in allow]
allow.extend(added)

perms["defaultMode"] = "acceptEdits"
perms.setdefault("additionalDirectories", []).extend(
    d for d in ["/tmp"] if d not in perms.get("additionalDirectories", [])
)

settings_file.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
if added:
    print(f"[INFO] 已添加权限: {added}")
else:
    print("[INFO] Claude Code 权限已是最新，无需修改。")
EOF

# ── 5. 安装 Claude Code CLI（如果还没有）──────────────────────────
if ! command -v claude &>/dev/null; then
    if command -v npm &>/dev/null; then
        echo "[INFO] 安装 Claude Code CLI..."
        npm install -g @anthropic-ai/claude-code
    else
        echo "[WARN] 未找到 npm，请手动安装 Claude Code CLI："
        echo "       https://docs.anthropic.com/zh-CN/docs/claude-code"
    fi
else
    echo "[INFO] Claude Code CLI 已安装: $(claude --version 2>/dev/null || echo '版本未知')"
fi

echo ""
echo "✓ 安装完成！"
echo ""
echo "下一步："
echo "  1. 首次登录（需要终端交互）："
echo "     $VENV_DIR/bin/python bridge.py --login"
echo ""
echo "  2. 登录成功后，用 systemd 守护进程运行："
echo "     sudo bash install-systemd.sh"
echo ""
echo "  3. 或者直接前台运行（测试用）："
echo "     bash start.sh"
