#!/bin/bash
# 为低配云服务器添加 Swap，避免 Docker 构建时内存不足卡死
# 用法：bash deploy/setup-swap.sh [大小，默认 2G，例如 4G]

set -e

SWAP_SIZE="${1:-2G}"
SWAP_FILE="${SWAP_FILE:-/swapfile}"
SWAPPINESS="${SWAPPINESS:-10}"

dd_count_mib() {
  if [[ "$SWAP_SIZE" =~ ^([0-9]+)G$ ]]; then
    echo $(( ${BASH_REMATCH[1]} * 1024 ))
  elif [[ "$SWAP_SIZE" =~ ^([0-9]+)M$ ]]; then
    echo "${BASH_REMATCH[1]}"
  else
    echo "2048"
  fi
}

echo "========================================"
echo "  配置 Swap · 大小 ${SWAP_SIZE}"
echo "========================================"

if swapon --show 2>/dev/null | grep -q "$SWAP_FILE"; then
  echo ">>> Swap 已存在：$SWAP_FILE"
  free -h
  swapon --show
  exit 0
fi

if [ -f "$SWAP_FILE" ]; then
  echo ">>> 发现已有文件 $SWAP_FILE，尝试启用..."
  chmod 600 "$SWAP_FILE"
  mkswap "$SWAP_FILE" 2>/dev/null || true
  swapon "$SWAP_FILE" 2>/dev/null && {
    free -h
    exit 0
  }
  echo ">>> 文件无效，将重新创建"
  swapoff "$SWAP_FILE" 2>/dev/null || true
  rm -f "$SWAP_FILE"
fi

echo ">>> 创建交换文件（可能需要几十秒）..."
if command -v fallocate >/dev/null 2>&1; then
  fallocate -l "$SWAP_SIZE" "$SWAP_FILE" || {
    echo ">>> fallocate 失败，改用 dd..."
    dd if=/dev/zero of="$SWAP_FILE" bs=1M count="$(dd_count_mib)" status=progress
  }
else
  dd if=/dev/zero of="$SWAP_FILE" bs=1M count="$(dd_count_mib)" status=progress
fi

chmod 600 "$SWAP_FILE"
mkswap "$SWAP_FILE"
swapon "$SWAP_FILE"

if ! grep -q "^${SWAP_FILE} " /etc/fstab; then
  echo "${SWAP_FILE} none swap sw 0 0" >> /etc/fstab
  echo ">>> 已写入 /etc/fstab（重启后自动启用）"
fi

sysctl -w "vm.swappiness=${SWAPPINESS}" >/dev/null
echo "vm.swappiness=${SWAPPINESS}" > /etc/sysctl.d/99-swap.conf

echo ""
echo "========================================"
echo "  Swap 配置完成"
echo "========================================"
free -h
echo ""
swapon --show
echo ""
echo "建议接着更新游戏：bash deploy/update.sh"
