#!/usr/bin/env bash
# 把 wechat-bridge.service 安装到 systemd 并启动
# 需要 root 权限
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_USER="${WECHAT_BRIDGE_USER:-wechat-bridge}"
SERVICE_DST="/etc/systemd/system/wechat-bridge.service"

if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] 请用 sudo 运行：sudo bash install-systemd.sh"
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/.venv/bin/python" ]]; then
    echo "[ERROR] 虚拟环境不存在，请先运行：sudo bash setup.sh"
    exit 1
fi

# 检查服务用户是否已登录微信
TOKEN_FILE="/home/$SERVICE_USER/.config/wechat-bridge/token.json"
if [[ ! -f "$TOKEN_FILE" ]]; then
    echo "[WARN] 未找到微信登录凭据：$TOKEN_FILE"
    echo "       请先以服务用户完成登录："
    echo "       sudo -u $SERVICE_USER bash $SCRIPT_DIR/start.sh --login"
    echo ""
    read -r -p "确认已登录？继续安装 systemd 服务？[y/N] " ans
    if [[ ! "$ans" =~ ^[Yy]$ ]]; then
        echo "已取消。"
        exit 0
    fi
fi

# 替换 service 模板中的占位符
sed -e "s|PLACEHOLDER_DIR|$SCRIPT_DIR|g" \
    -e "s|PLACEHOLDER_USER|$SERVICE_USER|g" \
    "$SCRIPT_DIR/wechat-bridge.service" > "$SERVICE_DST"

echo "[INFO] 已写入 $SERVICE_DST"

systemctl daemon-reload
systemctl enable wechat-bridge
systemctl restart wechat-bridge

echo ""
echo "✓ 服务已启动！（以用户 $SERVICE_USER 运行）"
echo ""
echo "  查看实时日志：journalctl -u wechat-bridge -f"
echo "  查看服务状态：systemctl status wechat-bridge"
echo "  停止服务：    sudo systemctl stop wechat-bridge"
echo "  卸载服务：    sudo systemctl disable wechat-bridge && sudo rm $SERVICE_DST"
