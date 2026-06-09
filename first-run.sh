#!/usr/bin/env bash
# 首次登录配置（以服务用户身份运行，不能是 root）
# 完成：① Claude Code 认证  ② 微信扫码登录
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ $EUID -eq 0 ]]; then
    echo "[ERROR] 请勿以 root 运行此脚本！"
    echo "        先切换用户：su - wechat-bridge"
    echo "        再运行：bash $SCRIPT_DIR/first-run.sh"
    exit 1
fi

if [[ ! -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    echo "[ERROR] 虚拟环境不存在，请先以 root 运行：sudo bash setup.sh"
    exit 1
fi

# ── 第一步：Claude Code 认证 ──────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  第一步：Claude Code 认证"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 检查是否已认证（尝试一个最简单的调用）
if claude --version &>/dev/null 2>&1; then
    echo "[INFO] 检测到 Claude Code CLI，尝试验证登录状态..."
    # 用一个极短的 prompt 测试是否已认证，能拿到 exit 0 就算通过
    if echo "hi" | claude -p --output-format json --dangerously-skip-permissions 2>/dev/null | grep -q "session_id"; then
        echo "[INFO] Claude Code 已登录，跳过认证步骤。"
    else
        echo ""
        echo "需要登录 Claude Code。运行后会显示一个链接，"
        echo "用手机或电脑的浏览器打开该链接完成授权即可。"
        echo ""
        claude auth login || claude  # 不同版本命令不同，二选一
    fi
else
    echo "[ERROR] 找不到 claude 命令，请先以 root 运行：sudo bash setup.sh"
    exit 1
fi

# ── 第二步：微信 iLink Bot 扫码登录 ──────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  第二步：微信扫码登录"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "即将显示二维码，请用微信扫描。"
echo "（登录成功后程序会自动退出，或按 Ctrl+C）"
echo ""

"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/bridge.py" --login

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ 登录完成！"
echo ""
echo "  最后一步：安装 systemd 服务（保持当前用户，直接 sudo）"
echo ""
echo "    sudo bash $SCRIPT_DIR/install-systemd.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
