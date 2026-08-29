# -*- coding: utf-8 -*-
"""把 avatars/_inbox 中已分类的 4598 张人物立绘压缩成可入库的副本。

输出 avatars/pool/<桶名>/b####.jpg（320px，JPEG q82，约 25KB/张，总量约 110MB）。
- 文件重命名为安全名（原名含 #/@/空格/中文，不适合 git 与 URL）
- avatars/pool/ 会被 git 跟踪（.gitignore 已放行），clone 后无需原图即可随机立绘
"""
import json
import os
import sys

from PIL import Image

INBOX = os.path.join("avatars", "_inbox")
POOL = os.path.join("avatars", "pool")
INDEX = os.path.join("avatars", "index.json")
BUCKETS = ["妃嫔", "名妃", "太后", "公主", "宫女", "女官", "皇子", "名臣", "驸马", "侍卫", "男仆"]
MAX_SIDE = 320
QUALITY = 82


def main():
    with open(INDEX, encoding="utf-8") as f:
        idx = json.load(f)

    os.makedirs(POOL, exist_ok=True)
    total_out = 0
    total_in = 0
    n_ok = n_skip = 0
    seq = 0
    for bucket in BUCKETS:
        out_dir = os.path.join(POOL, bucket)
        os.makedirs(out_dir, exist_ok=True)
        for e in (idx.get(bucket) or []):
            src = os.path.join(INBOX, e["file"])
            if not os.path.isfile(src):
                n_skip += 1
                continue
            seq += 1
            dst = os.path.join(out_dir, f"b{seq:04d}.jpg")
            try:
                im = Image.open(src)
                if im.mode != "RGB":
                    im = im.convert("RGB")
                w, h = im.size
                scale = min(1.0, MAX_SIDE / max(w, h))
                if scale < 1.0:
                    im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
                im.save(dst, "JPEG", quality=QUALITY, optimize=True)
                total_out += os.path.getsize(dst)
                total_in += os.path.getsize(src)
                n_ok += 1
            except Exception as ex:
                n_skip += 1
                print(f"[skip] {e['file']}: {ex}")
        print(f"  {bucket}: 累计 {seq} 张", flush=True)

    print(f"\n完成：成功 {n_ok}，跳过 {n_skip}")
    print(f"体积：{total_in/1024/1024:.0f}MB 原图 -> {total_out/1024/1024:.0f}MB 压缩池")
    print(f"输出：{POOL}/")


if __name__ == "__main__":
    sys.exit(main())
