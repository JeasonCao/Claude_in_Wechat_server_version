#!/usr/bin/env bash
# 服务器一键安装脚本（需要 root 运行，安装系统依赖）
# 适用：Ubuntu 20.04+
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_USER="${WECHAT_BRIDGE_USER:-wechat-bridge}"   # 可通过环境变量覆盖

# ── 必须以 root 运行（安装系统包）──────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] 请用 root 或 sudo 运行此脚本（安装系统依赖需要权限）"
    echo "        sudo bash setup.sh"
    exit 1
fi

# ── 1. 安装 Python 3.8-venv ────────────────────────────────────────
echo "[INFO] 安装 python3.8-venv..."
apt-get install -y python3.8-venv

# ── 2. 安装 Node.js 20+（系统自带版本太低）────────────────────────
if node --version 2>/dev/null | grep -qE '^v(2[0-9]|[3-9][0-9])'; then
    echo "[INFO] Node.js 已满足要求: $(node --version)"
else
    echo "[INFO] 安装 Node.js 20（通过 NodeSource）..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
    echo "[INFO] Node.js 安装完成: $(node --version)"
fi

# ── 3. 安装 Claude Code CLI ────────────────────────────────────────
if command -v claude &>/dev/null; then
    echo "[INFO] Claude Code CLI 已安装: $(claude --version 2>/dev/null || echo '版本未知')"
else
    echo "[INFO] 安装 Claude Code CLI..."
    npm install -g @anthropic-ai/claude-code
fi

# ── 4. 创建服务专用用户（Claude Code 禁止 root 使用 --dangerously-skip-permissions）──
if id "$SERVICE_USER" &>/dev/null; then
    echo "[INFO] 用户 '$SERVICE_USER' 已存在，跳过创建。"
else
    echo "[INFO] 创建服务用户: $SERVICE_USER"
    useradd -m -s /bin/bash "$SERVICE_USER"
fi

# ── 5. 设置项目目录权限 ───────────────────────────────────────────
chown -R "$SERVICE_USER:$SERVICE_USER" "$SCRIPT_DIR"
echo "[INFO] 项目目录已归属 $SERVICE_USER: $SCRIPT_DIR"

# ── 6. 以服务用户身份创建 venv、安装依赖 ──────────────────────────
echo "[INFO] 创建虚拟环境并安装依赖（以 $SERVICE_USER 身份运行）..."
sudo -u "$SERVICE_USER" bash -c "
    set -e
    cd '$SCRIPT_DIR'
    python3.8 -m venv .venv
    .venv/bin/pip install --upgrade pip -q
    .venv/bin/pip install -r requirements.txt -q
    echo '[INFO] Python 依赖安装完成'
"

# ── 7. 以服务用户身份配置 Claude Code 权限 ────────────────────────
echo "[INFO] 配置 Claude Code 权限..."
sudo -u "$SERVICE_USER" bash -c "
python3 - <<'PYEOF'
import json, os
from pathlib import Path

settings_file = Path.home() / '.claude' / 'settings.json'
settings_file.parent.mkdir(parents=True, exist_ok=True)

try:
    settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
except Exception:
    settings = {}

perms = settings.setdefault('permissions', {})
allow = perms.setdefault('allow', [])
needed = ['Read', 'Edit', 'Write', 'Bash(git *)', 'Bash(python *)', 'Bash(pip *)']
added = [r for r in needed if r not in allow]
allow.extend(added)
perms['defaultMode'] = 'acceptEdits'
dirs = perms.setdefault('additionalDirectories', [])
if '/tmp' not in dirs:
    dirs.append('/tmp')

settings_file.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + '\n')
print(f'[INFO] Claude Code 权限配置完成（新增: {added if added else \"无变化\"}）')
PYEOF
"

echo ""
echo "✓ 系统依赖安装完成！"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  下一步：以服务用户登录微信（必须在终端交互）"
echo ""
echo "  sudo -u $SERVICE_USER bash start.sh --login"
echo ""
echo "  扫码成功后按 Ctrl+C，再运行："
echo "  sudo bash install-systemd.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
