# 使用 Python 3.12 (与 pyproject.toml 保持一致)
FROM python:3.12-slim

# 1. 安装 uv (从官方镜像复制二进制文件)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 设置工作目录
WORKDIR /app

# 环境变量设置
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    # 告诉 uv 将环境安装到系统或指定位置，这里我们让 uv 管理 .venv，然后加到 PATH
    UV_LINK_MODE=copy

# 2. 复制依赖定义文件
COPY pyproject.toml uv.lock ./

# 3. 安装依赖 (不包含项目本身，利用缓存)
# --frozen: 严格按照 uv.lock 安装
# --no-dev: 仅安装生产依赖
# --no-install-project: 这一步只装依赖库，不装本项目代码
RUN uv sync --frozen --no-dev --no-install-project

# 4. 复制项目源码
COPY src ./src
COPY README.md ./

# 5. 安装项目本身
RUN uv sync --frozen --no-dev

# 6. 将虚拟环境加入 PATH
ENV PATH="/app/.venv/bin:$PATH"

# 暴露端口
EXPOSE 8080

# 启动命令 (使用 pyproject.toml 中定义的 scripts)
CMD ["wall", "start"]