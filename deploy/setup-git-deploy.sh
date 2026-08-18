#!/bin/bash
# 首次在华为云 ECS 上配置 Git 拉取更新
# 用法：
#   sudo bash deploy/setup-git-deploy.sh https://github.com/你的用户名/你的仓库.git

set -e

REPO_URL="${1:-}"
APP_DIR="${APP_DIR:-/opt/fengyi-game}"
BRANCH="${BRANCH:-main}"

if [ -z "$REPO_URL" ]; then
  echo "用法: sudo bash deploy/setup-git-deploy.sh <Git仓库地址>"
  echo "示例: sudo bash deploy/setup-git-deploy.sh https://github.com/user/fengyi-game.git"
  exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "请使用 root 或 sudo 运行"
  exit 1
fi

apt-get update -qq
apt-get install -y -qq git

mkdir -p "$APP_DIR"
cd "$APP_DIR"

# 备份已有配置
if [ -f .env ]; then
  cp .env /tmp/fengyi-env.bak
fi
if [ -d saves ]; then
  cp -a saves /tmp/fengyi-saves.bak 2>/dev/null || true
fi

if [ -d .git ]; then
  echo ">>> 已是 Git 仓库，更新远程地址..."
  git remote set-url origin "$REPO_URL"
  git fetch origin
  git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH" "origin/$BRANCH"
  git pull origin "$BRANCH"
else
  echo ">>> 克隆仓库到 $APP_DIR ..."
  if [ "$(ls -A "$APP_DIR" 2>/dev/null | grep -v '^saves$' | head -1)" ]; then
    # 目录非空：在临时目录克隆后合并
    TMP_DIR=$(mktemp -d)
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$TMP_DIR"
    cp -a "$TMP_DIR"/. "$APP_DIR"/
    rm -rf "$TMP_DIR"
  else
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" .
  fi
fi

# 恢复配置
if [ -f /tmp/fengyi-env.bak ]; then
  cp /tmp/fengyi-env.bak .env
fi
if [ -d /tmp/fengyi-saves.bak ]; then
  rm -rf saves
  cp -a /tmp/fengyi-saves.bak saves
fi

chmod +x deploy/*.sh 2>/dev/null || true

echo ""
echo "Git 配置完成。以后更新只需执行："
echo "  cd $APP_DIR && bash deploy/update.sh"
echo ""
echo "或配置 GitHub Actions 后，本地 push 即自动部署。"
