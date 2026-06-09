#!/usr/bin/env bash
# 前台启动（调试 / 首次登录用）
# 生产环境请用 systemd：sudo bash install-systemd.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

# Claude Code 禁止以 root 身份使用 --dangerously-skip-permissions
if [[ $EUID -eq 0 ]]; then
    echo "[ERROR] 请勿以 root 运行 bridge！Claude Code CLI 会拒绝执行。"
    echo "        请切换到服务用户运行，例如："
    echo "        sudo -u wechat-bridge bash start.sh"
    exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "[ERROR] 虚拟环境不存在，请先运行：sudo bash setup.sh"
    exit 1
fi

# 限制 Node.js（Claude Code）每次最多用 384MB 堆内存
export NODE_OPTIONS="--max-old-space-size=384"

echo "[INFO] 启动 bridge（NODE_OPTIONS=$NODE_OPTIONS，nice=10）"
exec nice -n 10 "$VENV_PYTHON" "$SCRIPT_DIR/bridge.py" "$@"
