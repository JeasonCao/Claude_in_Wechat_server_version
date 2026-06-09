#!/usr/bin/env bash
# 系统依赖安装脚本（需要 root 权限）
# 完成后按提示切换到服务用户，再运行 first-run.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_USER="${WECHAT_BRIDGE_USER:-wechat-bridge}"

if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] 请用 root 或 sudo 运行：sudo bash setup.sh"
    exit 1
fi

# ── 1. Python 3.8+（优先用已有的高版本）──────────────────────────
echo "[INFO] 检查 Python 版本..."
PYTHON=""
for py in python3.12 python3.11 python3.10 python3.9 python3.8 python3; do
    if command -v "$py" &>/dev/null; then
        if "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" 2>/dev/null; then
            PYTHON="$py"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "[INFO] 未找到 Python 3.8+，安装 python3.8-venv..."
    apt-get install -y python3.8 python3.8-venv
    PYTHON=python3.8
else
    PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "[INFO] Python 已满足要求：$("$PYTHON" --version)，检查 venv 模块..."
    # 确保 venv 模块可用（部分系统需要单独安装）
    if ! "$PYTHON" -m venv --help &>/dev/null 2>&1; then
        echo "[INFO] 安装 python${PY_VER}-venv..."
        apt-get install -y "python${PY_VER}-venv" || apt-get install -y python3-venv
    fi
fi

# ── 2. Node.js 20+（Claude Code CLI 的运行时）────────────────────
echo "[INFO] 检查 Node.js 版本..."
NODE_OK=false
if command -v node &>/dev/null; then
    NODE_VER=$(node --version | grep -oE '[0-9]+' | head -1)
    if [[ "$NODE_VER" -ge 20 ]]; then
        echo "[INFO] Node.js 已满足要求：$(node --version)"
        NODE_OK=true
    else
        echo "[INFO] Node.js 版本过低（$(node --version)），需要 20+，升级中..."
    fi
fi

if [[ "$NODE_OK" == false ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
    echo "[INFO] Node.js 安装完成：$(node --version)"
fi

# ── 3. Claude Code CLI ────────────────────────────────────────────
echo "[INFO] 检查 Claude Code CLI..."
if command -v claude &>/dev/null; then
    echo "[INFO] Claude Code CLI 已安装：$(claude --version 2>/dev/null || echo '版本未知')"
else
    echo "[INFO] 安装 Claude Code CLI..."
    npm install -g @anthropic-ai/claude-code
    echo "[INFO] Claude Code CLI 安装完成"
fi

# ── 4. 创建服务专用用户 ───────────────────────────────────────────
# Claude Code 禁止 root 使用 --dangerously-skip-permissions
if id "$SERVICE_USER" &>/dev/null; then
    echo "[INFO] 用户 '$SERVICE_USER' 已存在，跳过创建。"
else
    echo "[INFO] 创建服务用户：$SERVICE_USER"
    useradd -m -s /bin/bash "$SERVICE_USER"
fi

# ── 5. 设置项目目录权限 ───────────────────────────────────────────
chown -R "$SERVICE_USER:$SERVICE_USER" "$SCRIPT_DIR"

# ── 6. 以服务用户身份创建 venv、安装依赖 ──────────────────────────
echo "[INFO] 创建虚拟环境并安装依赖（以 $SERVICE_USER 身份）..."
sudo -u "$SERVICE_USER" bash -c "
    set -e
    cd '$SCRIPT_DIR'
    '$PYTHON' -m venv .venv
    .venv/bin/pip install --upgrade pip -q
    .venv/bin/pip install -r requirements.txt -q
    echo '[INFO] Python 依赖安装完成'
"

# ── 7. 配置 Claude Code 权限（以服务用户身份）────────────────────
echo "[INFO] 配置 Claude Code 权限..."
sudo -u "$SERVICE_USER" python3 - <<'PYEOF'
import json
from pathlib import Path

f = Path.home() / ".claude" / "settings.json"
f.parent.mkdir(parents=True, exist_ok=True)
try:
    s = json.loads(f.read_text()) if f.exists() else {}
except Exception:
    s = {}

p = s.setdefault("permissions", {})
allow = p.setdefault("allow", [])
needed = ["Read", "Edit", "Write", "Bash(git *)", "Bash(python *)", "Bash(pip *)"]
added = [r for r in needed if r not in allow]
allow.extend(added)
p["defaultMode"] = "acceptEdits"
dirs = p.setdefault("additionalDirectories", [])
if "/tmp" not in dirs:
    dirs.append("/tmp")

f.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n")
print(f"[INFO] 权限配置完成（新增: {added if added else '无变化'}）")
PYEOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ 系统依赖安装完成！"
echo ""
echo "  下一步：切换到服务用户，完成登录"
echo ""
echo "    su - $SERVICE_USER"
echo "    cd $SCRIPT_DIR"
echo "    bash first-run.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
