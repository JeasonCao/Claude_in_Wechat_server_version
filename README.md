# Claude in WeChat（服务器版）

通过微信私聊和 Claude AI 对话的桥接服务，部署在个人服务器上长期运行。

- 支持图片识别（自动解密微信图片）
- 每个用户独立的多轮对话记忆
- 崩溃自动重启，开机自动启动
- 支持两种后端：Claude Pro 订阅 或 Anthropic API Key

---

> **操作账号说明**：请以**普通用户（有 sudo 权限）**进行操作，不要全程使用 root。
> 如果你的服务器默认登录的是 root，建议先创建一个普通用户：
> ```bash
> useradd -m -s /bin/bash yourname && passwd yourname
> usermod -aG sudo yourname
> su - yourname
> ```

## 准备什么

| 项目 | 说明 |
|------|------|
| 服务器 | Ubuntu 20.04+，至少 1GB 内存，有 SSH 登录权限 |
| Claude 账号 | Claude Pro 订阅（CLI 模式）**或** Anthropic API Key（API 模式） |
| 微信账号 | 用于扫码登录，建议用小号 |

---

## 部署步骤

### 第一步：SSH 登录服务器，克隆代码

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/JeasonCao/Claude_in_Wechat_server_version.git /opt/wechat-bridge
cd /opt/wechat-bridge
```

> 克隆到 `/opt/`，所有用户均可访问，不依赖任何人的 home 目录。

### 第二步：安装系统依赖

> 需要 root 权限。脚本会自动检测已有环境，版本已满足则跳过安装。

```bash
sudo bash setup.sh
```

这一步会自动完成：
- 检查 Python 3.8+，不足时安装
- 检查 Node.js 20+，不足时从 NodeSource 安装
- 安装 Claude Code CLI（`npm install -g @anthropic-ai/claude-code`）
- 创建专用服务账号 `wechat-bridge`（Claude Code 不允许在 root 下运行）
- 安装 Python 依赖到虚拟环境
- 配置 Claude Code 权限文件

完成后按提示切换到服务用户（setup.sh 已在该用户 home 下建好 `~/bridge` 软链接）：

```bash
su - wechat-bridge
```

### 第三步：完成登录

```bash
bash ~/bridge/first-run.sh
```

这一步会引导你完成两个登录：

1. **Claude Code 认证**：终端会显示一个链接，用手机或电脑浏览器打开完成授权
2. **微信扫码**：终端显示二维码，用微信扫描，扫完自动保存登录状态

登录完成后，按提示退回 root：

```bash
exit
```

### 第四步：安装系统服务

```bash
sudo bash install-systemd.sh
```

完成后服务在后台自动运行，开机自启，崩溃自动重启。

### 验证

```bash
journalctl -u wechat-bridge -f
```

看到滚动的轮询日志说明运行正常。用微信给机器人发一条消息测试。

---

## 日常使用

直接给机器人发消息即可，支持文字和图片。

| 命令 | 效果 |
|------|------|
| `/reset` | 清除对话历史，开始新会话 |
| `/status` | 查看当前运行状态和后端模式 |
| `/help` | 显示帮助 |

---

## 切换到 API 模式

默认使用 Claude Code CLI（需要 Claude Pro 订阅）。如果你有 Anthropic API Key，可以切换到 API 模式——内存占用更低，响应更快。

编辑 systemd 服务配置：

```bash
sudo systemctl edit wechat-bridge
```

在打开的文件中添加：

```ini
[Service]
Environment=CLAUDE_BACKEND=api
Environment=ANTHROPIC_API_KEY=sk-ant-你的key
```

然后重启：

```bash
sudo systemctl restart wechat-bridge
```

---

## 服务管理

```bash
# 查看实时日志
journalctl -u wechat-bridge -f

# 查看服务状态
systemctl status wechat-bridge

# 重启服务
sudo systemctl restart wechat-bridge

# 停止服务
sudo systemctl stop wechat-bridge

# 微信 token 过期，重新登录
sudo systemctl stop wechat-bridge
sudo -u wechat-bridge bash ~/bridge/first-run.sh   # 只需执行第二步（微信扫码）
sudo systemctl start wechat-bridge
```

---

## 常见问题

**Q：`claude` 命令提示权限错误**  
A：不能用 root 运行 bridge。确认已通过 `su - wechat-bridge` 切换用户。

**Q：安装 python3.10-venv 失败**  
A：不需要 Python 3.10，系统自带的 Python 3.8 即可。直接运行：
```bash
apt-get install -y python3.8-venv
```

**Q：Node.js 安装失败（404 错误）**  
A：先更新包索引：`apt-get update`，再重试。

**Q：微信 token 过期（日志出现 401）**  
A：重新扫码登录，参见上方「服务管理」。

**Q：内存不够用**  
A：切换到 API 模式（见上方），内存占用从 ~300MB/次 降至 ~10MB/次。
