# 使用 Python 官方 slim 镜像，减小镜像大小
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖（包括字体库，用于生成验证码）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libfreetype6-dev \
    libjpeg-dev \
    zlib1g-dev \
    fonts-dejavu-core \
    fonts-liberation && \
    rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app.py .
COPY ip_parser.py .

# 暴露端口
EXPOSE 8080

# 运行应用
CMD ["python", "app.py"]
