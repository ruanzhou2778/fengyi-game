# -*- coding: utf-8 -*-
"""验证：①身份分桶头像分配 ②inbox/ui 路由 ③NPC 主动上门。"""
import sys, os, json
sys.path.insert(0, '.')
import app as A
from app import app as flask_app

client = flask_app.test_client()
passed = failed = 0
from tools.avatar_classifier import ALL_BUCKETS as _ALL_BUCKETS

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} :: {detail}")

# === ① 分桶分配 ===
idx = A._load_avatar_index()
has_index = idx is not None and any(isinstance(idx.get(b), list) and idx[b] for b in _ALL_BUCKETS)
if has_index:
    url = A._bucket_pick(idx, ["名妃", "妃嫔"], "npc:测试")
    check("分桶取图返回 inbox URL", url and url.startswith("/avatars/inbox/"), str(url))
    url2 = A._bucket_pick(idx, ["名妃", "妃嫔"], "npc:测试")
    check("同 key 确定性（两次一致）", url == url2)
    check("空桶回退返回 None", A._bucket_pick(idx, ["不存在的桶"], "x") is None)
    # URL 编码：# 不得裸露
    for entry in (idx.get("妃嫔") or [])[:30]:
        fname = entry.get("file", "")
        if "#" in fname:
            enc = A._bucket_pick(idx, ["妃嫔"], "t#" + fname)
            check("含#文件名已编码", enc and "#" not in enc, enc)
            break
else:
    print("  [INFO] avatars/index.json 不存在或为空 —— 验证回退逻辑")
    check("_load_avatar_index 返回 None 不报错", idx is None)

# 全链路：开局 → avatar_payload → 角色拿到头像
r = client.post('/api/start', json={"name": "分桶测试", "api_base": "", "api_key": "", "api_model": ""})
pid = r.get_json()["player_id"]
gs = A.sessions[pid]
gs.npcs["柳妃"] = {"name": "柳妃", "alive": True, "rank": "妃", "age": 24}
import os as _os
has_pack = any(f.endswith((".jpg", ".png")) for f in (_os.listdir("avatars/pack") if _os.path.isdir("avatars/pack") else []))
payload = A.avatar_payload(gs)
npc_url = payload.get("npc:柳妃", "")
if has_index or has_pack:
    check("NPC 分到头像 URL", bool(npc_url), str(payload))
    check("有 index 时 NPC 用 inbox 图", (not has_index) or npc_url.startswith("/avatars/inbox/"), npc_url)
    check("无 index 时回退 pack 图", has_index or npc_url.startswith("/avatars/pack/"), npc_url)
else:
    print("  [INFO] 无 index 也无 pack —— 分配静默跳过（不报错即通过）")
    check("空图源不报错", isinstance(payload, dict))

# 子嗣按性别
gs.children.append({"uid": 1, "gender": "皇子", "name": "承泰", "alive": True})
gs.children.append({"uid": 2, "gender": "公主", "name": "明玥", "alive": True})
payload = A.avatar_payload(gs)
if has_index or has_pack:
    check("皇子分到头像", bool(payload.get("child:1")))
    check("公主分到头像", bool(payload.get("child:2")))
else:
    check("空图源子嗣不报错", isinstance(payload, dict))

# === ② 路由 ===
if has_index:
    all_files = []
    for b in _ALL_BUCKETS:
        all_files += [e["file"] for e in (idx.get(b) or [])]
    if all_files:
        import urllib.parse
        sample = all_files[0]
        rr = client.get(f"/avatars/inbox/{urllib.parse.quote(sample)}")
        check(f"inbox 路由可取图 ({sample[:20]}...)", rr.status_code == 200, f"status={rr.status_code}")
rr = client.get("/avatars/ui/scene1.jpg")
check("ui 路由 scene1.jpg", rr.status_code == 200 and rr.content_length and rr.content_length > 10000, f"status={rr.status_code}")
rr = client.get("/avatars/ui/不存在.jpg")
check("ui 路由 404", rr.status_code == 404)

# === ③ NPC 主动上门 ===
def reset_att(att):
    gs.npcs["柳妃"]["attitude"] = dict(att)

gs.silver = 100
gs.rivalries.clear()
reset_att({"好感": 30, "信任": 30, "畏惧": 0, "爱慕": 80, "敌意": 0})
import random as _r
got_love = False
for seed in range(30):
    _r.seed(seed)
    msgs = A.generate_npc_visits(gs)
    if any("主动来访" in m or "赏花" in m for m in msgs):
        got_love = True
        break
check("爱慕≥60 触发来访（30 种子内）", got_love)

reset_att({"好感": 30, "信任": 30, "畏惧": 0, "爱慕": 0, "敌意": 80})
got_hate = False
for seed in range(30):
    _r.seed(seed)
    gs.rivalries.clear()
    msgs = A.generate_npc_visits(gs)
    if any("敌意" in m for m in msgs):
        got_hate = True
        check("敌意≥60 涨仇敌值", gs.rivalries.get("柳妃", 0) > 0, str(gs.rivalries))
        break
check("敌意路径 30 种子内可触发", got_hate)

reset_att({"好感": 30, "信任": 30, "畏惧": 0, "爱慕": 0, "敌意": 0})
_r.seed(7)
check("无阈值不触发", A.generate_npc_visits(gs) == [])

reset_att({"好感": 30, "信任": 30, "畏惧": 0, "爱慕": 0, "敌意": 0})
gs.npcs["柳妃"]["alive"] = False
check("死亡 NPC 不触发", A.generate_npc_visits(gs) == [])
gs.npcs["柳妃"]["alive"] = True

# next_period 全链路含上门消息
reset_att({"好感": 30, "信任": 30, "畏惧": 0, "爱慕": 80, "敌意": 0})
found_visit = False
for seed in range(20):
    _r.seed(seed)
    d = client.post('/api/next_period', json={"player_id": pid}).get_json()
    lst = d.get("intelligence_list") or []
    if any("主动来访" in m or "赏花" in m for m in lst):
        found_visit = True
        break
check("next_period 情报中含主动上门", found_visit)

print(f"\n{'='*40}\n结果: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
