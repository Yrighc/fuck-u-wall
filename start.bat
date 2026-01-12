@echo off
REM Windows 启动脚本：删除旧镜像并重新构建

echo 🛑 停止并删除容器...
docker-compose down

echo 🗑️  删除本地镜像...
docker rmi wall-demo:0.0.1 2>nul || echo 镜像不存在，跳过删除

echo 🔨 重新构建镜像并启动...
docker-compose up --build -d

echo ✅ 启动完成！
echo 📋 查看日志: docker-compose logs -f
echo 🌐 访问地址: http://localhost:10003

pause
