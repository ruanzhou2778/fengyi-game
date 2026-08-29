# -*- coding: utf-8 -*-
"""头像分类器（纯 numpy 启发式，不依赖 face_recognition/dlib）。
- 人脸：肤色 YCrCb 掩码 (Cr 133-173, Cb 77-127) + 连通域
- 身份桶：妃嫔/名妃/太后/公主/宫女/女官 + 皇子/名臣/驸马/侍卫/男仆
- 无脸图（背景/拆分立绘/图标）不复制，只记录进 index.json 的 _review 列表
- 输出 avatars/index.json（不入 git）
"""
import os, json, time, urllib.parse
from collections import Counter, defaultdict
from PIL import Image
import numpy as np

INBOX  = os.path.join("avatars", "_inbox")
OUT    = os.path.join("avatars", "index.json")

FEMALE_BUCKETS = ["妃嫔", "名妃", "太后", "公主", "宫女", "女官"]
MALE_BUCKETS   = ["皇子", "名臣", "驸马", "侍卫", "男仆"]
ALL_BUCKETS    = FEMALE_BUCKETS + MALE_BUCKETS

ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
SKIP_KEYWORDS = ["背景", "未命名", "伴读", "拆分", "局部", "未使用", "草稿", "废稿", "线稿", "待替换"]
RESIZE_TARGET = 260   # 识别尺寸（人脸启发式足够）
CC_DOWNSAMPLE = 3     # 连通域在 1/3 掩码上跑（提速 ~9x）


def list_inbox():
    out = []
    for f in os.listdir(INBOX):
        if f.startswith(".") or f.startswith("_"):
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext not in ALLOWED_EXTS:
            continue
        path = os.path.join(INBOX, f)
        try:
            if os.path.getsize(path) < 1024:
                continue
        except OSError:
            continue
        low = f.lower()
        if any(kw in low for kw in SKIP_KEYWORDS):
            continue
        out.append(path)
    return out


def _rgb_to_ycrcb(arr):
    r = arr[:, :, 0].astype(np.float32)
    g = arr[:, :, 1].astype(np.float32)
    b = arr[:, :, 2].astype(np.float32)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cr = (r - y) * 0.713 + 128
    cb = (b - y) * 0.564 + 128
    return np.stack([y, cr, cb], axis=-1).astype(np.uint8)


def _dilate(mask, k=2):
    m = mask.astype(np.uint8)
    out = np.zeros_like(m)
    H, W = m.shape
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            ys0, ys1 = max(0, dy), H + min(0, dy)
            xs0, xs1 = max(0, dx), W + min(0, dx)
            yo0, yo1 = max(0, -dy), H + min(0, -dy)
            xo0, xo1 = max(0, -dx), W + min(0, -dx)
            out[yo0:yo1, xo0:xo1] |= m[ys0:ys1, xs0:xs1]
    return out.astype(bool)


def _connected_boxes(mask, min_area, scale):
    """在降采样掩码上做 4 连通两遍扫描，返回放大回原坐标的 bbox 列表。"""
    m = mask.astype(np.uint8)
    H, W = m.shape
    labels = np.zeros((H, W), dtype=np.int32)
    parent = {}

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    cur = 0
    for y in range(H):
        row = m[y]
        for x in range(W):
            if row[x] == 0:
                continue
            nbs = []
            if y > 0 and labels[y - 1, x] > 0:
                nbs.append(labels[y - 1, x])
            if x > 0 and labels[y, x - 1] > 0:
                nbs.append(labels[y, x - 1])
            if not nbs:
                cur += 1
                labels[y, x] = cur
                parent[cur] = cur
            else:
                lab = min(nbs)
                labels[y, x] = lab
                for n in nbs:
                    if n != lab:
                        rn, rl = find(n), find(lab)
                        if rn != rl:
                            parent[rn] = rl
    boxes = {}
    for y in range(H):
        for x in range(W):
            lab = labels[y, x]
            if lab == 0:
                continue
            b = boxes.get(lab)
            if b is None:
                boxes[lab] = [x, y, x, y]
            else:
                if x < b[0]: b[0] = x
                if y < b[1]: b[1] = y
                if x > b[2]: b[2] = x
                if y > b[3]: b[3] = y
    out = []
    for lab, (x0, y0, x1, y1) in boxes.items():
        if find(lab) != lab:
            continue
        area = (x1 - x0 + 1) * (y1 - y0 + 1)
        if area < min_area:
            continue
        out.append((x0 * scale, y0 * scale, (x1 + 1) * scale, (y1 + 1) * scale))
    return out


def has_face_box(img_array):
    """返回 [(top,right,bottom,left), ...]（原坐标系）。"""
    h, w = img_array.shape[:2]
    ycc = _rgb_to_ycrcb(img_array)
    Cr, Cb = ycc[:, :, 1], ycc[:, :, 2]
    mask = (Cr > 133) & (Cr < 173) & (Cb > 77) & (Cb < 127)
    if mask.sum() < 150:
        return []
    mask = _dilate(mask, 2)
    # 降采样后跑连通域
    small = mask[::CC_DOWNSAMPLE, ::CC_DOWNSAMPLE]
    if small.sum() < 30:
        return []
    raw_boxes = _connected_boxes(small, min_area=45, scale=CC_DOWNSAMPLE)
    out = []
    for (x0, y0, x1, y1) in raw_boxes:
        bw, bh = x1 - x0, y1 - y0
        if bh == 0:
            continue
        ratio = bw / bh
        if not (0.55 <= ratio <= 1.10):
            continue
        if not (0.10 * h <= bh <= 0.75 * h and 0.04 * w <= bw <= 0.65 * w):
            continue
        pad = max(2, int(bh * 0.1))
        out.append((max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad), max(0, x0 - pad)))
    return out


def face_gender_hint(box):
    top, right, bottom, left = box
    w, h = right - left, bottom - top
    if h == 0:
        return "?"
    ratio = w / h
    if ratio < 0.78:
        return "f"
    if ratio > 0.86:
        return "m"
    return "?"


def dominant_color_palette(img_array, k=4):
    small = np.array(Image.fromarray(img_array).resize((48, 48)))
    pixels = small.reshape(-1, 3).astype(np.float32)
    binned = (pixels // 32).astype(int)
    cnt = Counter(tuple(x) for x in binned)
    out = []
    for (r, g, b), _ in cnt.most_common(k):
        out.append((int(r) * 32 + 16, int(g) * 32 + 16, int(b) * 32 + 16))
    return out


def clothing_complexity(img_array):
    h, w = img_array.shape[:2]
    lower = img_array[h // 2:, :, :]
    if lower.size == 0:
        return 1
    small = np.array(Image.fromarray(lower).resize((40, 40)))
    pixels = small.reshape(-1, 3).astype(np.float32)
    binned = (pixels // 40).astype(int)
    cnt = Counter(tuple(x) for x in binned)
    nz = sum(1 for _, c in cnt.items() if c >= 8)
    if nz <= 3:
        return 1
    if nz <= 8:
        return 2
    return 3


def background_complexity(img_array):
    h, w = img_array.shape[:2]
    ch, cw = h // 6, w // 6
    if ch < 4 or cw < 4:
        return 0
    patches = [img_array[:ch, :cw], img_array[:ch, -cw:], img_array[-ch:, :cw], img_array[-ch:, -cw:]]
    diffs = []
    for p in patches:
        if p.size == 0:
            continue
        ps = np.array(Image.fromarray(p).resize((20, 20))).astype(np.int32)
        gx = np.abs(np.diff(ps, axis=1)).sum()
        gy = np.abs(np.diff(ps, axis=0)).sum()
        diffs.append((gx + gy) / (20 * 20 * 3))
    if not diffs:
        return 0
    avg = float(np.mean(diffs))
    if avg < 5:
        return 0
    if avg < 15:
        return 1
    return 2


def main_color_name(rgb):
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


def classify_one(path):
    try:
        im = Image.open(path)
        if im.mode != "RGB":
            im = im.convert("RGB")
        w0, h0 = im.size
        scale = min(1.0, RESIZE_TARGET / max(w0, h0))
        if scale < 1.0:
            im = im.resize((max(1, int(w0 * scale)), max(1, int(h0 * scale))))
        arr = np.array(im)
    except Exception as e:
        return {"_err": str(e)}

    faces = has_face_box(arr)
    fc = len(faces)
    if fc == 0:
        return {"_review": "no_face", "face_count": 0, "size": (w0, h0)}

    box = max(faces, key=lambda b: (b[2] - b[0]) * (b[1] - b[3]))
    gender = face_gender_hint(box)
    palette = dominant_color_palette(arr, k=4)
    palette_names = [main_color_name(c) for c in palette]
    cloth_c = clothing_complexity(arr)
    bg_c = background_complexity(arr)
    main_cloth = Counter(palette_names).most_common(1)[0][0]

    if gender == "f":
        if bg_c >= 2 and "黄/金" in palette_names and cloth_c >= 2:
            bucket = "太后"
        elif cloth_c == 3 and bg_c >= 1:
            bucket = "名妃"
        elif cloth_c >= 2 and any(c in palette_names for c in ("白", "红")) and "黄/金" not in palette_names and bg_c <= 1:
            bucket = "公主"
        elif bg_c == 0 and cloth_c == 1:
            bucket = "女官"
        elif cloth_c <= 1 and bg_c == 0:
            bucket = "宫女"
        else:
            bucket = "妃嫔"
    elif gender == "m":
        if cloth_c >= 2 and "黄/金" in palette_names:
            bucket = "皇子"
        elif cloth_c == 1 and bg_c == 0:
            bucket = "男仆"
        elif bg_c == 0 and cloth_c <= 1:
            bucket = "侍卫"
        elif bg_c >= 2 and cloth_c >= 2:
            bucket = "名臣"
        elif "白" in palette_names and cloth_c >= 2:
            bucket = "驸马"
        else:
            bucket = "名臣"
    else:
        bucket = "妃嫔" if cloth_c >= 2 else "宫女"

    return {
        "gender": gender, "bucket": bucket, "face_count": fc, "size": (w0, h0),
        "palette": palette_names, "main_cloth": main_cloth,
        "cloth_c": cloth_c, "bg_c": bg_c,
    }


def main():
    if not os.path.isdir(INBOX):
        print(f"[ERR] {INBOX} not found")
        return
    files = list_inbox()
    print(f"[扫描] {len(files)} 张图", flush=True)
    if not files:
        print("[ERR] 没有可用图")
        return

    by_bucket = defaultdict(list)
    reviews = []
    errs = []
    t0 = time.time()
    for i, fp in enumerate(files):
        r = classify_one(fp)
        if r is None:
            continue
        if r.get("_err"):
            errs.append((os.path.basename(fp), r["_err"]))
        elif r.get("_review"):
            reviews.append(os.path.basename(fp))
        else:
            by_bucket[r["bucket"]].append({
                "file": os.path.basename(fp),
                "gender": r["gender"],
                "face": r["face_count"],
                "palette": r["palette"],
                "main": r["main_cloth"],
                "cloth_c": r["cloth_c"],
                "bg_c": r["bg_c"],
            })
        if (i + 1) % 300 == 0:
            el = time.time() - t0
            eta = el / (i + 1) * (len(files) - i - 1)
            print(f"  进度 {i+1}/{len(files)}  已用 {int(el)}s  预计剩余 {int(eta)}s", flush=True)

    out = {b: by_bucket.get(b, []) for b in ALL_BUCKETS}
    out["_review"] = reviews
    out["_meta"] = {
        "total": len(files),
        "errs": [f"{f}: {e}" for f, e in errs[:20]],
        "errs_count": len(errs),
        "reviews_count": len(reviews),
        "elapsed_sec": int(time.time() - t0),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    print("\n========== 分 类 总 结 ==========")
    for b in ALL_BUCKETS:
        print(f"  {b:6s} : {len(by_bucket.get(b, [])):5d}")
    print(f"  丢弃(错) : {len(errs):5d}")
    print(f"  难图     : {len(reviews):5d} (仅记录在 index.json._review)")
    print(f"\n  总计：{len(files)} 张 | 用时 {int(time.time()-t0)}s")
    print(f"  索引：{OUT} ({os.path.getsize(OUT)//1024} KB)")
    print("\n========== 9 张抽样 ==========")
    samples = []
    for b in ALL_BUCKETS:
        if by_bucket.get(b):
            samples.append((b, by_bucket[b][0]))
        if len(samples) >= 9:
            break
    for b, s in samples:
        print(f"  [{b}] {s['file']}  face={s['face']} 主色={s['main']}/{s['palette']} 服饰复杂度={s['cloth_c']} 背景={s['bg_c']}")


if __name__ == "__main__":
    main()
