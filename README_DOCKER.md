# Docker 部署说明

## 环境变量配置

应用需要以下环境变量：

| 变量名 | 说明 | 必需 | 默认值 |
|--------|------|------|--------|
| `PORT` | 服务端口 | 否 | 8080 |
| `HOST` | 监听地址（容器内保持 0.0.0.0） | 否 | 0.0.0.0 |
| `FLASK_SECRET_KEY` | Flask Session 密钥 | 否 | 自动生成 |
| `TOTP_SECRET` | TOTP 动态验证码密钥 | 否 | 自动生成（首次运行会打印） |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API Token | **是** | - |
| `CLOUDFLARE_ZONE_ID` | Cloudflare Zone ID | **是** | - |
| `SUBDOMAIN` | 子域名（多个用逗号分隔） | **是** | - |
| `MAX_FAILED_ATTEMPTS` | TOTP 爆破防护：单 IP 最大失败次数 | 否 | 5 |
| `LOCKOUT_MINUTES` | TOTP 爆破防护：锁定时长（分钟） | 否 | 15 |
| `HOST` | 监听地址（容器内保持 0.0.0.0） | 否 | 0.0.0.0 |
| `TURNSTILE_SITEKEY` | Turnstile 站点 key（前端） | **是** | - |
| `TURNSTILE_SECRET` | Turnstile 后端密钥（仅服务端可见） | **是** | - |
| `TURNSTILE_HOSTNAMES` | 允许的前端域名白名单（逗号分隔） | **是** | - |

## 使用方式

### 方式1：使用 docker-compose 从 GHCR 拉取（推荐，直接使用 CI 发布的镜像）

项目根目录已提供 `docker-compose.yml`，默认从 GitHub Container Registry 拉取最新镜像：

```bash
# 拉取 ghcr.io/yrighc/fuck-u-wall:latest 并启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

> 镜像由 GitHub Actions 在每次 push 到 main 时自动构建发布，无需本地构建。
> 从 GHCR 拉取需要镜像为公开（Package visibility = Public），或先执行
> `echo "$TOKEN" | docker login ghcr.io -u 用户名 --password-stdin` 登录。

### 方式2：使用启动脚本（本地构建）

**Linux/Mac:**
```bash
./start.sh
```

**Windows:**
```cmd
start.bat
```

启动脚本会自动：
1. 停止并删除容器
2. 删除旧镜像
3. 重新构建镜像
4. 启动服务

### 方式3：手动 docker-compose 本地构建

1. **创建 `.env` 文件**（可选，但推荐）：
   ```bash
   PORT=8080
   FLASK_SECRET_KEY=your-flask-secret-key-here
   TOTP_SECRET=your-totp-secret-here
   CLOUDFLARE_API_TOKEN=your-cloudflare-api-token
   CLOUDFLARE_ZONE_ID=your-zone-id
   SUBDOMAIN=api.example.com,admin.example.com
   ```

2. **本地构建镜像**：
   ```bash
   docker build -t wall-demo:0.0.1 .
   ```

3. **将 docker-compose.yml 中的镜像指向本地构建**：把
   `image: ghcr.io/yrighc/fuck-u-wall:latest` 改为 `image: wall-demo:0.0.1`，
   并取消 `build` 块注释，然后启动：
   ```bash
   docker-compose up -d
   ```

4. **查看日志**：
   ```bash
   docker-compose logs -f
   ```

5. **停止服务**：
   ```bash
   docker-compose down
   ```

### 方式4：直接使用 Dockerfile 构建

1. **构建镜像**：
   ```bash
   docker build -t wall-demo:0.0.1 .
   ```

2. **运行容器**：
   ```bash
   docker run -d \
     --name wall-demo \
     -p 10003:8080 \
     -e PORT=8080 \
     -e FLASK_SECRET_KEY=your-flask-secret-key \
     -e TOTP_SECRET=your-totp-secret \
     -e CLOUDFLARE_API_TOKEN=your-token \
     -e CLOUDFLARE_ZONE_ID=your-zone-id \
     -e SUBDOMAIN=api.example.com,admin.example.com \
     wall-demo:0.0.1
   ```

3. **或者使用 .env 文件**：
   ```bash
   docker run -d \
     --name wall-demo \
     -p 10003:8080 \
     --env-file .env \
     wall-demo:0.0.1
   ```

## 环境变量生效说明

### docker-compose.yml

- ✅ **环境变量会生效**
- 环境变量可以通过以下方式传递：
  1. **直接在 docker-compose.yml 中设置**（已配置）
  2. **使用 `.env` 文件**（需要取消注释 `env_file` 部分）
  3. **从系统环境变量读取**（`${VARIABLE_NAME}` 语法）

### Dockerfile

- ✅ **环境变量会生效**
- 运行时通过 `-e` 参数或 `--env-file` 传递的环境变量会生效
- Dockerfile 中设置的环境变量（`ENV`）也会生效

## 注意事项

1. **必需的环境变量**：
   - `CLOUDFLARE_API_TOKEN`：必须设置，否则应用启动会失败
   - `CLOUDFLARE_ZONE_ID`：必须设置，否则应用启动会失败
   - `SUBDOMAIN`：必须设置，否则应用启动会失败

2. **可选的环境变量**：
   - `FLASK_SECRET_KEY`：如果不设置，每次重启会生成新的，导致 session 失效
   - `TOTP_SECRET`：如果不设置，首次运行会生成并打印，需要保存到环境变量中

3. **TOTP_SECRET 首次运行**：
   - 如果未设置 `TOTP_SECRET`，应用首次运行时会自动生成
   - 查看日志获取生成的密钥：`docker-compose logs | grep TOTP_SECRET`
   - 将密钥添加到环境变量中，重启容器

4. **端口映射**：
   - docker-compose.yml 中映射的是 `127.0.0.1:10003:8080`
   - 访问地址：`http://localhost:10003`
   - 如需修改，编辑 `docker-compose.yml` 中的 `ports` 部分

## 验证环境变量是否生效

启动容器后，查看日志：

```bash
docker-compose logs wall-demo
```

如果看到以下错误，说明环境变量未正确设置：
- `ValueError: 请设置 CLOUDFLARE_API_TOKEN 和 CLOUDFLARE_ZONE_ID 环境变量`
- `ValueError: 请设置 SUBDOMAIN 环境变量`

## 使用 .env 文件（推荐）

1. 在项目根目录创建 `.env` 文件
2. 取消 `docker-compose.yml` 中的 `env_file` 注释
3. 启动服务：`docker-compose up -d`

这样更安全，不会在命令行中暴露敏感信息。
