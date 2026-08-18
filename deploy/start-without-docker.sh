#!/bin/bash
# 不用 Docker，直接用 Python 启动（镜像拉取失败时的备用方案）
set -e

APP_DIR="${APP_DIR:-/root/gongdou}"
cd "$APP_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "请先编辑 .env 填写 OPENAI_API_KEY: nano $APP_DIR/.env"
  exit 1
fi

echo ">>> 安装依赖..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

echo ">>> 停止旧进程..."
pkill -f "gunicorn app:app" 2>/dev/null || true

echo ">>> 启动游戏..."
cd "$APP_DIR"
nohup "$APP_DIR/venv/bin/gunicorn" app:app \
  --chdir "$APP_DIR" \
  --bind 0.0.0.0:5000 \
  --workers 1 \
  --timeout 120 \
  > "$APP_DIR/run.log" 2>&1 &

sleep 2
curl -fsS http://127.0.0.1:5000/api/health && echo ""
echo "启动完成。日志: tail -f /root/gongdou/run.log"
