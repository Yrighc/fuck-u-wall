# Cloudflare IP 白名单管理工具

一个轻量级的 Web 应用，用于自动将当前 IP 地址添加到 Cloudflare 的防火墙白名单中。

## 功能特性

- 🌐 自动检测当前 IP 地址
- 🔐 TOTP 动态验证码保护
- ☁️ 自动添加到 Cloudflare 白名单
- 🐳 Docker 容器化部署
- 💾 占用资源小（Python + Flask + slim 镜像）

## 快速开始

### 1. 获取 Cloudflare 配置信息

#### 步骤 1：获取 API Token（API 令牌）

1. **登录 Cloudflare 控制台**
   - 访问 [https://dash.cloudflare.com](https://dash.cloudflare.com)
   - 使用您的账号登录

2. **进入 API 令牌页面**
   - 点击右上角的头像图标
   - 在下拉菜单中选择 **"我的个人资料"** 或 **"My Profile"**
   - 在左侧菜单中找到并点击 **"API 令牌"** 或 **"API Tokens"**

3. **创建自定义令牌**
   - 点击 **"创建令牌"** 或 **"Create Token"** 按钮
   - 选择 **"创建自定义令牌"** 或 **"Create Custom Token"**

4. **配置令牌权限**
   - **令牌名称**：输入一个便于识别的名称，如 "IP白名单管理"
   - **权限设置**：需要添加以下权限：
     - **区域（Zone）** > **区域（Zone）** > **读取（Read）**
     - **区域（Zone）** > **WAF** > **编辑（Edit）**
   - **区域资源**：选择 **"包括 - 特定区域"**，然后选择您要管理的域名

   > **注意**：本工具基于新版 Rulesets API（Security → 安全规则），需要 **Zone WAF** 权限。旧版 Firewall Rules 权限已被 Cloudflare 弃用（API 已进入 maintenance mode）。

5. **创建并复制令牌**
   - 点击 **"继续以显示摘要"** 或 **"Continue to summary"**
   - 确认权限无误后，点击 **"创建令牌"** 或 **"Create Token"**
   - **重要**：立即复制生成的 API Token，它只会显示一次！请妥善保存。

#### 步骤 2：获取 Zone ID（区域 ID）

1. **进入域名管理页面**
   - 在 Cloudflare 控制台首页，点击您要管理的域名

2. **找到 Zone ID**
   - 进入域名详情页面后，在右侧边栏的 **"API"** 部分
   - 可以看到 **"区域 ID"** 或 **"Zone ID"**
   - 点击右侧的复制图标即可复制 Zone ID

   > **提示**：如果右侧边栏没有显示，也可以向下滚动页面，在页面底部找到 Zone ID。

#### 配置信息汇总

完成以上步骤后，您应该获得：
- ✅ **CLOUDFLARE_API_TOKEN**：刚才创建的 API 令牌
- ✅ **CLOUDFLARE_ZONE_ID**：域名的区域 ID
- ✅ **SUBDOMAIN**：子域名（支持多个用逗号分隔，如 api.example.com,admin.example.com，必需）

### 2. 使用 Docker 运行

```bash
# 构建镜像
docker build -t wall-demo .

# 运行容器（单个子域名）
docker run -d \
  -p 8080:8080 \
  -e PORT=8080 \
  -e FLASK_SECRET_KEY=your-secret-key-here \
  -e CLOUDFLARE_API_TOKEN=your-api-token \
  -e CLOUDFLARE_ZONE_ID=your-zone-id \
  -e SUBDOMAIN=api.example.com \
  --name wall-demo \
  wall-demo

# 运行容器（多个子域名，用逗号分隔）
docker run -d \
  -p 8080:8080 \
  -e PORT=8080 \
  -e FLASK_SECRET_KEY=your-secret-key-here \
  -e CLOUDFLARE_API_TOKEN=your-api-token \
  -e CLOUDFLARE_ZONE_ID=your-zone-id \
  -e SUBDOMAIN=api.example.com,admin.example.com,dashboard.example.com \
  --name wall-demo \
  wall-demo
```

### 3. 使用 Docker Compose（推荐，从 GHCR 拉取镜像）

项目根目录已提供 `docker-compose.yml`，默认从 GitHub Container Registry 拉取最新镜像：

```yaml
version: '3.8'

services:
  fuck-u-wall:
    image: ghcr.io/yrighc/fuck-u-wall:latest
    ports:
      - "127.0.0.1:10003:8080"
    environment:
      - PORT=${PORT:-8080}
      - FLASK_SECRET_KEY=${FLASK_SECRET_KEY:-}
      - TOTP_SECRET=${TOTP_SECRET:-}
      - CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN}
      - CLOUDFLARE_ZONE_ID=${CLOUDFLARE_ZONE_ID}
      - SUBDOMAIN=${SUBDOMAIN}
    restart: unless-stopped
```

变量通过 `${VAR}` 从环境变量或 `.env` 文件（与 `docker-compose.yml` 同目录）读取：

```bash
# 方式 A：创建 .env 文件（推荐，与 docker-compose.yml 同目录）
cat > .env <<'EOF'
SUBDOMAIN=api.example.com,admin.example.com
FLASK_SECRET_KEY=your-secret-key
TOTP_SECRET=your-totp-secret
CLOUDFLARE_API_TOKEN=your-token
CLOUDFLARE_ZONE_ID=your-zone-id
EOF

# 方式 B：或直接 export
# export SUBDOMAIN=api.example.com,admin.example.com

docker-compose up -d
```

> 优先级：shell 环境变量 > `.env` 文件 > yaml 默认值。
> 镜像由 GitHub Actions 在每次 push 到 main 时自动构建发布。
> 本地构建模式见 `README_DOCKER.md` 方式 3/4。

### 4. 访问应用

打开浏览器访问 `http://localhost:10003`

## 环境变量说明

| 变量名 | 说明 | 必需 | 默认值 |
|--------|------|------|--------|
| `PORT` | 服务端口 | 否 | 8080 |
| `FLASK_SECRET_KEY` | Flask Session 密钥 | 否 | 自动生成 |
| `TOTP_SECRET` | TOTP 动态验证码密钥 | 否 | 自动生成（首次运行打印） |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API Token | 是 | - |
| `CLOUDFLARE_ZONE_ID` | Cloudflare Zone ID | 是 | - |
| `SUBDOMAIN` | 子域名（支持多个用逗号分隔，如 api.example.com,admin.example.com） | 是 | - |

## 本地开发

```bash
# 安装依赖
uv sync

# 创建配置文件（APP_ENV 默认为 dev，应用会自动读取 .env.dev）
cp .env.example .env.dev
# 编辑 .env.dev，填入你的配置

# 运行
uv run wall start
```

> **提示**：也可以直接 export 环境变量启动，`.env.dev` 并非必需。

## 镜像大小

使用 Python slim 镜像，最终镜像大小约 **120-150MB**。

## 子域名支持

本工具**仅支持子域名级别的白名单**，支持配置多个子域名。

**工作原理**：
- 支持配置多个子域名，用逗号分隔
- 点击“添加到白名单”时，会创建/更新两条规则（位于 Security → 安全规则）：
  1. **白名单规则**：名单内 IP 跳过剩余自定义规则，直接放行
  2. **黑名单规则**：名单外 IP 访问配置的子域名时拦截
- 本工具创建的规则以 `wall-auto` 前缀标识，**每次更新只替换自身规则，不影响你在控制台手动创建的其他安全规则**
- 无论配置多少个子域名，都只创建 2 条规则，节省 Cloudflare 规则配额
- 规则仅应用到配置的子域名，不会影响其他子域名

**示例**：
- 保护单个子域名：设置 `SUBDOMAIN=api.example.com`
- 保护多个子域名：设置 `SUBDOMAIN=api.example.com,admin.example.com,dashboard.example.com`
- 每次添加 IP 时，仅更新本工具管理的 `wall-auto` 规则，其余规则保持不变

## 安全措施

本应用已实现以下安全措施：

1. **TOTP 动态验证码**：
   - 每次提交需输入 6 位 TOTP 动态验证码（兼容主流 Authenticator 应用）
   - 验证码 30 秒过期，允许前后一个时间窗口
   - 防止自动化攻击和暴力破解

2. **安全响应头**：
   - X-Content-Type-Options: nosniff
   - X-Frame-Options: DENY
   - X-XSS-Protection: 1; mode=block
   - Strict-Transport-Security
   - Content-Security-Policy

3. **验证机制**：
   - 服务端校验 TOTP 验证码 + IP 格式（IPv4/IPv6）
   - 建议在生产环境使用 HTTPS，避免验证码明文传输

## 安全建议

1. **使用 HTTPS**：
   - 生产环境必须使用 HTTPS（通过反向代理如 Nginx 或使用 Cloudflare）
   - 不要在 HTTP 环境下使用，验证码会明文传输

2. **TOTP 密钥**：
   - `TOTP_SECRET` 请妥善保管，泄露等于验证码失效
   - 如怀疑泄露，更换密钥并重新绑定 Authenticator

3. **网络隔离**：
   - 建议将应用部署在内网，通过 VPN 或 Cloudflare Tunnel 访问
   - 不要将应用直接暴露在公网

4. **监控和告警**：
   - 监控失败尝试日志
   - 设置异常访问告警

## 注意事项

1. 确保 Cloudflare API Token 有足够的权限（需要 **Zone WAF 编辑**权限）
2. TOTP 密钥请妥善保管，不要泄露
3. **本工具只管理 `wall-auto` 前缀的规则**，不会动你在控制台手动创建的其他安全规则
4. **会同时创建白名单和黑名单规则**：
   - 白名单：名单内 IP 跳过剩余自定义规则，直接放行
   - 黑名单：名单外 IP 禁止访问
5. **必须设置 `SUBDOMAIN` 环境变量**，否则应用无法启动
6. 支持多个子域名，用逗号分隔，如：`api.example.com,admin.example.com`
7. 请确保所有子域名已经在 Cloudflare 中正确配置
8. **生产环境必须使用 HTTPS**，否则验证码会明文传输

## 许可证

MIT
