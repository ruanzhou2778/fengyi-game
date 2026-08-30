# -*- coding: utf-8 -*-
"""WD14 tagger 性别判定：SmilingWolf/wd-v1-4-mobilenetv3-tagger-v2 (ONNX, CPU)。

对 _inbox + _nonperson 全量打标，用 1boy/1girl/no humans 等标签重建人物索引：
- 性别：1boy vs 1girl 分数
- 垃圾：no humans / scenery 等 → 不入桶
- 多人图（2girls/1boy1girl 等）照常入桶（可作头像池）
输出 avatars/index.json（新）+ avatars/_wd14_tags.json（全量标签缓存）。
"""
import csv
import io
import json
import os
import shutil
import sys
import time

import numpy as np
from PIL import Image

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # 国内镜像兜底

REPO = "SmilingWolf/wd-vit-tagger-v3"
INBOX = os.path.join("avatars", "_inbox")
NONPERSON = os.path.join(INBOX, "_nonperson")
INDEX = os.path.join("avatars", "index.json")
TAGS_CACHE = os.path.join("avatars", "_wd14_tags.json")
MODEL_DIR = os.path.join(os.environ.get("TEMP", "/tmp"), "wd14_vit_v3")
SIZE = 448

FEMALE_BUCKETS = ["妃嫔", "太后", "公主", "宫女", "女官"]
MALE_BUCKETS = ["皇帝", "皇子", "名臣", "驸马", "侍卫", "男仆"]
ALL_BUCKETS = FEMALE_BUCKETS + MALE_BUCKETS


def ensure_model():
    import huggingface_hub
    os.makedirs(MODEL_DIR, exist_ok=True)
    model_p = os.path.join(MODEL_DIR, "model.onnx")
    tags_p = os.path.join(MODEL_DIR, "selected_tags.csv")
    if not (os.path.isfile(model_p) and os.path.isfile(tags_p)):
        print(f"[下载] {REPO} ...", flush=True)
        huggingface_hub.snapshot_download(
            REPO, local_dir=MODEL_DIR,
            allow_patterns=["model.onnx", "selected_tags.csv"])
    return model_p, tags_p


def load_tags(csv_path):
    names = []
    with open(csv_path, "r", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        for row in rd:
            names.append(row["name"])
    return names


def preprocess(path):
    try:
        im = Image.open(path)
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im).convert("RGB")
        # 白底 pad 成正方形再缩放
        w, h = im.size
        s = max(w, h)
        canvas = Image.new("RGB", (s, s), (255, 255, 255))
        canvas.paste(im, ((s - w) // 2, (s - h) // 2))
        canvas = canvas.resize((SIZE, SIZE))
        arr = np.asarray(canvas, dtype=np.float32)[:, :, ::-1]  # RGB→BGR
        return np.expand_dims(arr, 0)
    except Exception:
        return None


def cloth_palette(path):
    try:
        im = Image.open(path).convert("RGB")
        if max(im.size) > 160:
            im = im.resize((160, 160))
        arr = np.array(im)
    except Exception:
        return 1, ["杂"]
    from collections import Counter
    h, w = arr.shape[:2]
    lower = arr[h // 2:, :, :]
    if lower.size == 0:
        return 1, ["杂"]
    small = np.array(Image.fromarray(lower).resize((40, 40)))
    pixels = small.reshape(-1, 3).astype(np.float32)
    binned = (pixels // 40).astype(int)
    cnt = Counter(tuple(x) for x in binned)
    nz = sum(1 for _, c in cnt.items() if c >= 8)
    cloth_c = 1 if nz <= 3 else (2 if nz <= 8 else 3)

    def color_name(rgb):
        r, g, b = rgb
        if r > 180 and g < 100 and b < 100: return "红"
        if r > 200 and g > 150 and b < 100: return "黄/金"
        if r > 200 and g > 200 and b > 200: return "白"
        if r < 80 and g < 80 and b < 80:    return "黑"
        if g > r and g > b and g > 120:     return "绿"
        if b > r and b > g:                 return "蓝"
        if r > 150 and g > 120 and b < 100: return "橙/赭"
        if r > 100 and g > 100 and b < 80:  return "棕"
        return "杂"
    small_full = np.array(Image.fromarray(arr).resize((48, 48)))
    pb = (small_full.reshape(-1, 3).astype(np.float32) // 32).astype(int)
    pc = Counter(tuple(x) for x in pb)
    palette = [color_name((int(r)*32+16, int(g)*32+16, int(b)*32+16)) for (r, g, b), _ in pc.most_common(4)]
    return cloth_c, palette


def main():
    model_p, tags_p = ensure_model()
    import onnxruntime as ort
    sess = ort.InferenceSession(model_p, providers=["CPUExecutionProvider"])
    tag_names = load_tags(tags_p)
    idx_of = {n: i for i, n in enumerate(tag_names)}

    # 全集范围：默认只跑 inbox（池子够用）；"all" 追加 nonperson 赎回
    roots = (INBOX, NONPERSON) if (len(sys.argv) > 1 and sys.argv[1] == "all") else (INBOX,)
    files = []
    for root in roots:
        for fn in os.listdir(root):
            p = os.path.join(root, fn)
            if os.path.isfile(p) and fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
                files.append(p)
    print(f"[扫描] 共 {len(files)} 张（范围: {roots}）", flush=True)

    # 断点续跑缓存
    cache = {}
    if os.path.isfile(TAGS_CACHE):
        with open(TAGS_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    todo = [p for p in files if os.path.basename(p) not in cache]
    print(f"[推理] 已缓存 {len(cache)}，待跑 {len(todo)}", flush=True)

    t0 = time.time()
    for i, p in enumerate(todo):
        x = preprocess(p)
        if x is None:
            cache[os.path.basename(p)] = {}
            continue
        inp = {sess.get_inputs()[0].name: x}
        out = sess.run(None, inp)[0][0]
        # 只存有用标签（>0.30），控制缓存体积
        keep = {}
        for j, v in enumerate(out):
            if v > 0.30 and j < len(tag_names):
                keep[tag_names[j]] = round(float(v), 3)
        cache[os.path.basename(p)] = keep
        if (i + 1) % 500 == 0:
            el = time.time() - t0
            print(f"  进度 {i+1}/{len(todo)} 已用 {int(el)}s 预计剩 {int(el/(i+1)*(len(todo)-i-1))}s", flush=True)
            with open(TAGS_CACHE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
    with open(TAGS_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)

    # ===== 分桶 =====
    by_bucket = {b: [] for b in ALL_BUCKETS}
    nonperson = []
    uncertain = []
    n_src = {"inbox": 0, "nonperson": 0}
    for p in files:
        fn = os.path.basename(p)
        tags = cache.get(fn) or {}
        girl = tags.get("1girl", 0.0)
        boy = tags.get("1boy", 0.0)
        nohuman = tags.get("no humans", 0.0)
        if nohuman > 0.5 or (girl < 0.30 and boy < 0.30):
            nonperson.append(fn)
            if p.startswith(NONPERSON):
                n_src["nonperson"] += 1
            else:
                n_src["inbox"] += 1
            continue
        if girl < 0.5 and boy < 0.5:
            uncertain.append({"file": fn, "girl": girl, "boy": boy})
            continue
        gender = "f" if girl >= boy else "m"
        if p.startswith(NONPERSON):
            n_src["nonperson"] += 1
        else:
            n_src["inbox"] += 1
        cloth_c, palette = cloth_palette(p)
        if gender == "m":
            if "黄/金" in palette and cloth_c >= 2:
                bucket = "皇帝" if cloth_c == 3 else "皇子"
            elif "白" in palette and cloth_c >= 2:
                bucket = "驸马"
            elif cloth_c == 1:
                bucket = "侍卫"
            else:
                bucket = "名臣"
        else:
            if "黄/金" in palette and cloth_c >= 2:
                bucket = "太后"
            elif cloth_c >= 2 and any(c in palette for c in ("白", "红")) and "黄/金" not in palette:
                bucket = "公主"
            elif cloth_c == 1:
                bucket = "宫女"
            else:
                bucket = "妃嫔"
        by_bucket[bucket].append({
            "file": fn, "gender": gender, "face": 1,
            "palette": palette, "main": palette[0] if palette else "",
            "cloth_c": cloth_c, "bg_c": 0,
            "wd": {"girl": girl, "boy": boy},
        })

    out = {b: by_bucket[b] for b in ALL_BUCKETS}
    out["_uncertain"] = uncertain
    out["_review"] = []
    out["_meta"] = {"total": len(files), "method": "wd14_mobilenetv3",
                    "nonperson": len(nonperson), "uncertain": len(uncertain),
                    "from_nonperson_rescued": n_src["nonperson"]}
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    print("\n========== WD14 分桶 ==========")
    for b in ALL_BUCKETS:
        print(f"  {b:4s} : {len(by_bucket[b]):5d}")
    print(f"  垃圾     : {len(nonperson)}")
    print(f"  低信心   : {len(uncertain)}")
    print(f"  从 nonperson 赎回: {n_src['nonperson']}")

    # 垃圾图统一挪到 _nonperson（赎回的从那边拿回来）
    rescued = 0
    for e in sum(by_bucket.values(), []):
        src = os.path.join(NONPERSON, e["file"])
        dst = os.path.join(INBOX, e["file"])
        if os.path.isfile(src) and not os.path.isfile(dst):
            shutil.move(src, dst)
            rescued += 1
    moved = 0
    for fn in nonperson:
        src = os.path.join(INBOX, fn)
        dst = os.path.join(NONPERSON, fn)
        if os.path.isfile(src) and not os.path.isfile(dst):
            shutil.move(src, dst)
            moved += 1
    print(f"  赎回 {rescued} 张，移入垃圾 {moved} 张")


if __name__ == "__main__":
    main()
