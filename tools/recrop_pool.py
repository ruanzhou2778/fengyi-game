# -*- coding: utf-8 -*-
"""把图池重建成"以脸为中心的正方形头像"。

问题：原图多为 16:9 横版场景截图（320×180），人物只占中间一小块。
前端用 object-fit:cover 塞进圆形时被迫按高度放大 → 只能看到被放大的一条竖切片（"头很大"）。

方案：从 _inbox 原图检测人物头部（肤色 YCrCb 掩码 + 连通域），
以头部为中心裁一个正方形（含肩部余量），输出 256×256 → 圆形头像里就是正常的头肩像。
检测不到脸时退化为"上部中央正方形"。
"""
import os
import sys
from collections import Counter

import numpy as np
from PIL import Image

INBOX = os.path.join("avatars", "_inbox")
NONPERSON = os.path.join(INBOX, "_nonperson")
POOL = os.path.join("avatars", "pool")
OUT_SIZE = 256
QUALITY = 86


def skin_mask(arr):
    r = arr[:, :, 0].astype(np.float32)
    g = arr[:, :, 1].astype(np.float32)
    b = arr[:, :, 2].astype(np.float32)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cr = (r - y) * 0.713 + 128
    cb = (b - y) * 0.564 + 128
    return (cr > 133) & (cr < 173) & (cb > 77) & (cb < 127)


def head_center(arr):
    """返回头部中心 (cx, cy) 与头宽估计 hw；找不到返回 None。"""
    h, w = arr.shape[:2]
    m = skin_mask(arr)
    if m.sum() < 120:
        return None
    # 只在上 70% 画面找脸（躯干/手也会命中肤色）
    m_top = m.copy()
    m_top[int(h * 0.72):, :] = False
    if m_top.sum() < 80:
        m_top = m
    ys, xs = np.where(m_top)
    if len(xs) < 80:
        return None
    # 用中位数抗离群（背景暖色块）
    cx = int(np.median(xs))
    cy = int(np.median(ys))
    # 头宽：肤色点横向 10~90 分位跨度
    x0, x1 = np.percentile(xs, [10, 90])
    hw = max(12, int(x1 - x0))
    return cx, cy, hw


def crop_square(im):
    """按头部位置裁正方形；返回 PIL.Image。"""
    arr = np.array(im)
    h, w = arr.shape[:2]
    hc = head_center(arr)
    if hc:
        cx, cy, hw = hc
        # 正方形边长：头宽的 3.2 倍（含肩），并夹在合理范围
        side = int(min(min(w, h), max(hw * 3.2, min(w, h) * 0.45)))
        # 头部略偏上：中心下移 side 的 12%
        top = cy - int(side * 0.38)
        left = cx - side // 2
    else:
        side = min(w, h)
        left = (w - side) // 2
        top = int((h - side) * 0.15)   # 偏上
    left = max(0, min(left, w - side))
    top = max(0, min(top, h - side))
    return im.crop((left, top, left + side, top + side)).resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)


def find_source(fname):
    for root in (INBOX, NONPERSON):
        p = os.path.join(root, fname)
        if os.path.isfile(p):
            return p
    return None


def main():
    import json
    # 可选桶过滤：python tools/recrop_pool.py 名臣 驸马 公主 宫女
    only = set(sys.argv[1:])
    with open(os.path.join("avatars", "index.json"), encoding="utf-8") as f:
        idx = json.load(f)
    # 已人工/检测确认无头的输出路径永久跳过，避免重建图池时再次生成无头头像
    faceless_path = os.path.join("avatars", "_faceless_pool.txt")
    faceless = set()
    if os.path.isfile(faceless_path):
        with open(faceless_path, encoding="utf-8") as f:
            faceless = {line.strip().replace("\\", "/") for line in f if line.strip()}

    n_ok = n_face = n_nohead = n_miss = 0
    total_bytes = 0
    for bucket in [b for b in idx.keys() if not b.startswith("_") and (not only or b in only)]:
        entries = idx.get(bucket) or []
        if not entries:
            continue
        out_dir = os.path.join(POOL, bucket)
        os.makedirs(out_dir, exist_ok=True)
        # 清掉旧的（避免残留旧比例图）
        for old in os.listdir(out_dir):
            if old.endswith(".jpg"):
                os.remove(os.path.join(out_dir, old))
        for i, e in enumerate(entries, 1):
            out_name = f"b{i:04d}.jpg"
            if f"{bucket}/{out_name}" in faceless:
                n_nohead += 1
                continue
            src = find_source(e["file"])
            if not src:
                n_miss += 1
                continue
            try:
                im = Image.open(src).convert("RGB")
                sq = crop_square(im)
                dst = os.path.join(out_dir, out_name)
                sq.save(dst, "JPEG", quality=QUALITY, optimize=True)
                total_bytes += os.path.getsize(dst)
                n_ok += 1
                n_face += 1
            except Exception:
                n_miss += 1
        print(f"  {bucket}: {len(entries)} 张", flush=True)

    print(f"\n完成：输出 {n_ok} 张（{OUT_SIZE}×{OUT_SIZE} 正方形）")
    print(f"  按脸定位 {n_face} / 无头跳过 {n_nohead} / 源缺失 {n_miss}")
    print(f"  体积 {total_bytes/1024/1024:.0f}MB")


if __name__ == "__main__":
    main()
