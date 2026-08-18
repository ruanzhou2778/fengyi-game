#!/bin/bash
# 服务器上一键更新游戏
# 用法：cd /opt/fengyi-game && bash deploy/update.sh

set -e

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
BRANCH="${BRANCH:-main}"

cd "$APP_DIR"

echo "========================================"
echo "  凤仪天下 · 更新中..."
echo "========================================"

# 保留存档与环境变量
if [ ! -d saves ]; then
  mkdir -p saves
fi

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

echo ">>> 重新构建并启动容器..."
docker compose up -d --build --remove-orphans

echo ">>> 等待服务就绪..."
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:5000/api/health" >/dev/null 2>&1; then
    echo ""
    echo "========================================"
    echo "  更新完成 ✓"
    echo "========================================"
    curl -s "http://127.0.0.1:5000/api/health"
    echo ""
    exit 0
  fi
  sleep 2
done

echo "警告：健康检查超时，请查看日志："
echo "  docker compose logs --tail=50"
exit 1
