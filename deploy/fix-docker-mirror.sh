#!/bin/bash
# 修复 Docker 拉取 python 镜像失败（中科大等镜像源失效）
set -e

if [ "$(id -u)" -ne 0 ]; then
  echo "请使用 sudo 运行"
  exit 1
fi

echo ">>> 备份原配置..."
mkdir -p /etc/docker
[ -f /etc/docker/daemon.json ] && cp /etc/docker/daemon.json /etc/docker/daemon.json.bak.$(date +%s)

echo ">>> 写入可用镜像源..."
cat > /etc/docker/daemon.json << 'EOF'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me"
  ]
}
EOF

systemctl daemon-reload
systemctl restart docker
sleep 2

echo ">>> 测试拉取 python:3.12-slim ..."
if docker pull python:3.12-slim; then
  echo "镜像拉取成功"
  exit 0
fi

echo ">>> 镜像源仍失败，尝试直连 Docker Hub..."
cat > /etc/docker/daemon.json << 'EOF'
{}
EOF
systemctl daemon-reload
systemctl restart docker
sleep 2
docker pull python:3.12-slim

echo "完成"
