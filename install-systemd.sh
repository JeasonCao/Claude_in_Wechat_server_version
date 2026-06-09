#!/usr/bin/env bash
# 把 wechat-bridge.service 安装到 systemd 并启动
# 需要 sudo 权限
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_SRC="$SCRIPT_DIR/wechat-bridge.service"
SERVICE_DST="/etc/systemd/system/wechat-bridge.service"

if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] 请用 sudo 运行：sudo bash install-systemd.sh"
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/.venv/bin/python" ]]; then
    echo "[ERROR] 虚拟环境不存在，请先运行：bash setup.sh"
    exit 1
fi

# 把模板里的 PLACEHOLDER_DIR 替换为实际路径
sed "s|PLACEHOLDER_DIR|$SCRIPT_DIR|g" "$SERVICE_SRC" > "$SERVICE_DST"
echo "[INFO] 已写入 $SERVICE_DST"

systemctl daemon-reload
systemctl enable wechat-bridge
systemctl restart wechat-bridge

echo ""
echo "✓ 服务已启动！"
echo ""
echo "  查看实时日志：journalctl -u wechat-bridge -f"
echo "  查看服务状态：systemctl status wechat-bridge"
echo "  停止服务：    sudo systemctl stop wechat-bridge"
echo "  卸载服务：    sudo systemctl disable wechat-bridge && sudo rm $SERVICE_DST"
