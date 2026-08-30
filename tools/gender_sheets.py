# -*- coding: utf-8 -*-
"""性别校准工具：对每张图计算特征 + 输出拼图（缩略图网格，带特征值标注），供人工查看校准阈值。

特征：
- jaw      脸框宽高比（肤色框）
- beard    胡须深色占比（鼻尖~下巴 区域）
- hair     长发覆盖（脸颊外侧+头顶上方非肤色占比）
- lip      唇红度

用法：
  python tools/gender_sheets.py sort beard   # 按 beard 特征排序出 4 张拼图（最男~最女）
  python tools/gender_sheets.py sample 200   # 随机 200 张分 4 页
输出 avatars/_sheets/sheet_*.png
"""
import json
import os
import sys
import random
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw

INBOX = os.path.join("avatars", "_inbox")
INDEX = os.path.join("avatars", "index.json")
SHEETS = os.path.join("avatars", "_sheets")


def skin_mask(arr):
    r = arr[:, :, 0].astype(np.float32); g = arr[:, :, 1].astype(np.float32); b = arr[:, :, 2].astype(np.float32)
    y = 0.299*r + 0.587*g + 0.114*b
    cr = (r - y) * 0.713 + 128
    cb = (b - y) * 0.564 + 128
    return (cr > 133) & (cr < 173) & (cb > 77) & (cb < 127)


def face_box(mask):
    ys, xs = np.where(mask)
    if len(xs) < 300:
        return None
    x0, x1 = np.percentile(xs, [3, 97]).astype(int)
    y0, y1 = np.percentile(ys, [3, 97]).astype(int)
    if x1 <= x0 or y1 <= y0:
        return None
    return int(x0), int(y0), int(x1), int(y1)


def features(arr):
    h, w = arr.shape[:2]
    scale = min(1.0, 420.0 / max(h, w))
    if scale < 1.0:
        arr = np.array(Image.fromarray(arr).resize((int(w*scale), int(h*scale))))
    h, w = arr.shape[:2]
    mask = skin_mask(arr)
    box = face_box(mask)
    if not box:
        return None
    x0, y0, x1, y1 = box
    fw, fh = x1 - x0, y1 - y0
    jaw = fw / max(fh, 1)
    # 胡须区：口鼻下方到下巴（y: 68%~97% 脸高，x: 25%~75% 脸宽）
    bx0 = x0 + int(fw*0.25); bx1 = x0 + int(fw*0.75)
    by0 = y0 + int(fh*0.68); by1 = y0 + int(fh*0.97)
    beard = 0.0
    if bx1 > bx0 and by1 > by0:
        blk = arr[by0:by1, bx0:bx1].astype(np.float32)
        lum = 0.299*blk[:,:,0] + 0.587*blk[:,:,1] + 0.114*blk[:,:,2]
        beard = float((lum < 95).mean())
    # 长发：脸颊外侧两块 + 头顶块 的非肤色占比
    hair = 0.0
    for cx, cy in [(x0 - fw*0.15, y0 + fh*0.55), (x1 + fw*0.15, y0 + fh*0.55), ((x0+x1)//2, y0 - fh*0.08)]:
        hw = int(fw*0.12)
        cx0, cy0 = int(cx - hw), int(cy - hw)
        cx1, cy1 = int(cx + hw), int(cy + hw)
        if cx0 < 0 or cy0 < 0 or cx1 > w or cy1 > h:
            continue
        blk = arr[cy0:cy1, cx0:cx1].astype(np.float32)
        lum = 0.299*blk[:,:,0] + 0.587*blk[:,:,1] + 0.114*blk[:,:,2]
        sat = blk.max(axis=2) - blk.min(axis=2)
        nonskin = float(((lum < 95) | (sat > 60)).mean())
        hair = max(hair, nonskin)
    # 唇红
    lip = 0.0
    lx0, lx1 = x0 + int(fw*0.35), x0 + int(fw*0.65)
    ly0, ly1 = y0 + int(fh*0.55), y0 + int(fh*0.72)
    if lx1 > lx0 and ly1 > ly0:
        blk = arr[ly0:ly1, lx0:lx1].astype(np.float32)
        lip = float(blk[:, :, 0].mean() - blk[:, :, 1].mean())
    # 垃圾度量：脸框占全图比例、框内亮度（暗场景/特写场景=垃圾）
    area_frac = (fw * fh) / (w * h)
    bx0, bx1 = max(0,x0), min(w,x1); by0, by1 = max(0,y0), min(h,y1)
    blk = arr[by0:by1, bx0:bx1].astype(np.float32)
    luma = float((0.299*blk[:,:,0] + 0.587*blk[:,:,1] + 0.114*blk[:,:,2]).mean()) if blk.size else 0.0
    return {"jaw": round(jaw, 3), "beard": round(beard, 3), "hair": round(hair, 3), "lip": round(lip, 1),
            "area": round(area_frac, 3), "luma": round(luma, 1)}


def load_entries():
    with open(INDEX, encoding="utf-8") as f:
        idx = json.load(f)
    out = []
    for b in list(idx.keys()):
        if b.startswith("_"):
            continue
        for e in (idx.get(b) or []):
            out.append({"file": e["file"], "bucket": b})
    return out


def make_sheet(items, path, cols=6, thumb=150):
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols*thumb, rows*(thumb+16)), (24, 30, 28))
    dr = ImageDraw.Draw(sheet)
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        try:
            im = Image.open(os.path.join(INBOX, it["file"])).convert("RGB")
            im.thumbnail((thumb, thumb))
            sheet.paste(im, (c*thumb + (thumb-im.width)//2, r*(thumb+16)))
        except Exception:
            continue
        f = it.get("f") or {}
        label = f"b{f.get('beard',0):.2f} h{f.get('hair',0):.2f} j{f.get('jaw',0):.2f}"
        dr.text((c*thumb+2, r*(thumb+16)+thumb+1), label, fill=(230, 220, 190))
    sheet.save(path)
    print(f"[sheet] {path} ({len(items)} 张)")


def main():
    os.makedirs(SHEETS, exist_ok=True)
    entries = load_entries()
    mode = sys.argv[1] if len(sys.argv) > 1 else "sample"
    # 预计算特征（带缓存）
    cache_path = os.path.join(SHEETS, "_features.json")
    if os.path.isfile(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            feats = json.load(f)
    else:
        feats = {}
    todo = [e["file"] for e in entries if e["file"] not in feats]
    print(f"[特征] 缓存 {len(feats)}，需计算 {len(todo)}", flush=True)
    for i, fn in enumerate(todo):
        try:
            im = Image.open(os.path.join(INBOX, fn)).convert("RGB")
            arr = np.array(im)
        except Exception:
            continue
        f = features(arr)
        if f:
            feats[fn] = f
        if (i+1) % 500 == 0:
            print(f"  特征 {i+1}/{len(todo)}", flush=True)
            with open(cache_path, "w", encoding="utf-8") as f2:
                json.dump(feats, f2, ensure_ascii=False)
    with open(cache_path, "w", encoding="utf-8") as f2:
        json.dump(feats, f2, ensure_ascii=False)

    if mode == "sort":
        key = sys.argv[2] if len(sys.argv) > 2 else "beard"
        cand = [e | {"f": feats[e["file"]]} for e in entries if e["file"] in feats]
        cand.sort(key=lambda x: x["f"].get(key, 0))
        n = len(cand)
        make_sheet(cand[:24], os.path.join(SHEETS, f"sheet_{key}_min.png"))
        make_sheet(cand[n//2-12:n//2+12], os.path.join(SHEETS, f"sheet_{key}_mid.png"))
        make_sheet(cand[-24:], os.path.join(SHEETS, f"sheet_{key}_max.png"))
    else:
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 200
        random.seed(123)
        pick = random.sample([e for e in entries if e["file"] in feats], min(n, len(entries)))
        for p in range(0, len(pick), 36):
            make_sheet([e | {"f": feats[e["file"]]} for e in pick[p:p+36]],
                       os.path.join(SHEETS, f"sheet_sample_{p//36}.png"))
    print("DONE")


if __name__ == "__main__":
    main()
