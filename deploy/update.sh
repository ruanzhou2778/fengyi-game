#!/bin/bash
# 服务器上一键更新游戏（先停旧服务再构建，避免小内存机器卡死）
# 用法：cd /root/gongdou && bash deploy/update.sh

set -e

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
BRANCH="${BRANCH:-main}"
CONTAINER_NAME="${CONTAINER_NAME:-fengyi-game}"
STOP_TIMEOUT="${STOP_TIMEOUT:-20}"

cd "$APP_DIR"

echo "========================================"
echo "  凤仪天下 · 更新中..."
echo "========================================"

# 保留存档与环境变量
if [ ! -d saves ]; then
  mkdir -p saves
fi

stop_game() {
  echo ">>> 停止旧容器（释放内存与 5000 端口）..."
  if command -v docker >/dev/null 2>&1; then
    if [ -f docker-compose.yml ]; then
      docker compose stop --timeout "$STOP_TIMEOUT" game 2>/dev/null || true
      docker compose down --remove-orphans --timeout "$STOP_TIMEOUT" 2>/dev/null || true
    fi
    if docker ps -q -f "name=^${CONTAINER_NAME}$" 2>/dev/null | grep -q .; then
      docker stop -t "$STOP_TIMEOUT" "$CONTAINER_NAME" 2>/dev/null || true
      docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
    fi
    sleep 2
    echo ">>> 旧容器已停止"
  else
    echo ">>> 未检测到 docker，跳过停止步骤"
  fi
}

stop_game

if [ -d .git ]; then
  echo ">>> 拉取最新代码 (分支: $BRANCH)..."
  git fetch origin
  git checkout "$BRANCH"
  git pull origin "$BRANCH"
else
  echo ">>> 未检测到 Git 仓库，跳过 git pull"
  echo "    提示：首次可用 deploy/setup-git-deploy.sh 配置 Git 更新"
fi

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo ">>> 已生成 .env，请填写 OPENAI_API_KEY 后重新运行更新"
  exit 1
fi

echo ">>> 构建新镜像（旧服务已停，避免内存不足）..."
docker compose build --pull game

echo ">>> 启动新容器..."
docker compose up -d --remove-orphans game

echo ">>> 等待服务就绪..."
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:5000/api/health" >/dev/null 2>&1; then
    echo ""
    echo "========================================"
    echo "  更新完成 ✓"
    echo "========================================"
    curl -s "http://127.0.0.1:5000/api/health"
    echo ""
    echo "  查看日志: docker compose logs -f --tail=50"
    exit 0
  fi
  sleep 2
done

echo "警告：健康检查超时，请查看日志："
echo "  docker compose logs --tail=50"
exit 1
