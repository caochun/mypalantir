#!/bin/bash

# 启动本地Web服务器来查看地图页面
# 使用方法: ./start-map-server.sh

PORT=${1:-8000}

echo "正在启动Web服务器..."
echo "访问地址: http://localhost:${PORT}/toll-sections-map.html"
echo "按 Ctrl+C 停止服务器"
echo ""

cd "$(dirname "$0")"
python3 -m http.server $PORT
