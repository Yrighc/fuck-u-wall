# ============================================================
# 多阶段构建:builder 负责安装依赖,runner 只保留 .venv
# 避免 uv 二进制 (~44MB) 和 uv 下载缓存 (~43MB) 进入最终镜像
# ============================================================

# ---- 构建阶段 ----
FROM python:3.12-slim AS builder

# 安装 uv (从官方镜像复制二进制文件)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# 1. 复制依赖定义文件
COPY pyproject.toml uv.lock ./

# 2. 安装依赖 (不包含项目本身,利用缓存)
# --frozen: 严格按照 uv.lock 安装
# --no-dev: 仅安装生产依赖
# --no-install-project: 这一步只装依赖库,不装本项目代码
RUN uv sync --frozen --no-dev --no-install-project

# 3. 复制项目源码,安装项目本身
COPY src ./src
COPY README.md ./
# --no-editable: 实体安装项目到 site-packages,runner 阶段无需保留 src 目录
RUN uv sync --frozen --no-dev --no-editable

# ---- 运行阶段 ----
FROM python:3.12-slim

WORKDIR /app

# 4. 从构建阶段只拷贝虚拟环境 (项目已安装到 site-packages,wall 命令可用)
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# 暴露端口
EXPOSE 8080

# 启动命令 (使用 pyproject.toml 中定义的 scripts)
CMD ["wall", "start"]
