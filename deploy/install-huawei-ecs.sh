#!/bin/bash
# 华为云 ECS 一键部署脚本（Ubuntu 22.04 / 24.04）
# 在服务器上执行：
#   curl -fsSL <你的仓库raw地址>/deploy/install-huawei-ecs.sh | bash
# 或上传项目后：
#   cd /opt/fengyi-game && sudo bash deploy/install-huawei-ecs.sh

set -e

APP_DIR="${APP_DIR:-/opt/fengyi-game}"
DOMAIN="${DOMAIN:-}"

echo "========================================"
echo "  凤仪天下 · 华为云 ECS 部署"
echo "========================================"

if [ "$(id -u)" -ne 0 ]; then
  echo "请使用 root 或 sudo 运行此脚本"
  exit 1
fi

apt-get update -qq
apt-get install -y -qq curl git nginx

if ! command -v docker >/dev/null 2>&1; then
  echo ">>> 安装 Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker
  systemctl start docker
fi

if ! docker compose version >/dev/null 2>&1; then
  apt-get install -y -qq docker-compose-plugin || true
fi

mkdir -p "$APP_DIR/saves"
cd "$APP_DIR"

if [ ! -f docker-compose.yml ]; then
  echo "错误：未找到 $APP_DIR/docker-compose.yml"
  echo "请先将项目上传到 $APP_DIR"
  exit 1
fi

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo ">>> 已生成 .env，请编辑 OPENAI_API_KEY："
  echo "    nano $APP_DIR/.env"
fi

echo ">>> 构建并启动容器..."
docker compose down 2>/dev/null || true
docker compose up -d --build

echo ">>> 配置 Nginx 反向代理..."
cp deploy/nginx-fengyi.conf /etc/nginx/sites-available/fengyi
if [ -n "$DOMAIN" ]; then
  sed -i "s/server_name _;/server_name $DOMAIN;/" /etc/nginx/sites-available/fengyi
fi
ln -sf /etc/nginx/sites-available/fengyi /etc/nginx/sites-enabled/fengyi
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl reload nginx

PUBLIC_IP=$(curl -s --max-time 3 ifconfig.me || curl -s --max-time 3 icanhazip.com || echo "你的公网IP")

echo ""
echo "========================================"
echo "  部署完成"
echo "========================================"
echo "访问地址：http://${DOMAIN:-$PUBLIC_IP}"
echo "健康检查：http://${DOMAIN:-$PUBLIC_IP}/api/health"
echo ""
echo "常用命令："
echo "  一键更新：cd $APP_DIR && bash deploy/update.sh"
echo "  查看日志：cd $APP_DIR && docker compose logs -f"
echo "  重启服务：cd $APP_DIR && docker compose restart"
echo "  停止服务：cd $APP_DIR && docker compose down"
echo ""
echo "后续更新（推荐 Git）："
echo "  1) 首次：sudo bash deploy/setup-git-deploy.sh <你的Git仓库地址>"
echo "  2) 以后：bash deploy/update.sh"
echo "  3) 或配置 GitHub Actions，push 后自动部署"
echo ""
echo "华为云安全组请放行：22、80、443"
echo "如需 HTTPS，可安装 certbot："
echo "  apt install certbot python3-certbot-nginx -y"
echo "  certbot --nginx -d 你的域名"
echo "========================================"
