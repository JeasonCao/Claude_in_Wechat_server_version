#!/usr/bin/env bash
# 拉取最新代码并重启服务，无需重新部署
set -e
cd "$(dirname "$0")"
git pull
sudo systemctl restart wechat-bridge
echo "✓ 已更新并重启。查看日志：journalctl -u wechat-bridge -f"
