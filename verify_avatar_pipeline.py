# -*- coding: utf-8 -*-
"""验证：①pool 分桶头像分配 ②pool/ui 路由 ③NPC 主动上门。"""
import sys, os
sys.path.insert(0, '.')
import app as A
from app import app as flask_app

client = flask_app.test_client()
passed = failed = 0

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} :: {detail}")

# === ① pool 分桶 ===
pools = A._load_bucket_pools()
has_pool = bool(pools) and any(pools.values())
check("pool 目录扫描非空", has_pool, str({k: len(v) for k, v in list(pools.items())[:3]}))
if has_pool:
    url = A._bucket_pick(pools, ["名妃", "妃嫔"], "npc:测试")
    check("分桶取图返回 pool URL", url and url.startswith("/avatars/pool/"), str(url))
    check("同 key 确定性（两次一致）", url == A._bucket_pick(pools, ["名妃", "妃嫔"], "npc:测试"))
    check("空桶链返回 None", A._bucket_pick(pools, ["不存在的桶"], "x") is None)
    # 安全文件名（无 # 空格等）
    bad = [f for files in pools.values() for f in files if any(c in f for c in "#?&% ")]
    check("pool 文件名全部安全", not bad, str(bad[:3]))
    # 薄桶回退链覆盖
    for alias, chain in [("npc_太后", A.BUCKET_ALIASES["npc_太后"]), ("child_m", A.BUCKET_ALIASES["child_m"]),
                         ("servant_太监", A.BUCKET_ALIASES["servant_太监"])]:
        check(f"回退链可用 {alias}", A._bucket_pick(pools, chain, alias) is not None)

# 全链路：开局 → avatar_payload
r = client.post('/api/start', json={"name": "分桶测试", "api_base": "", "api_key": "", "api_model": ""})
pid = r.get_json()["player_id"]
gs = A.sessions[pid]
gs.npcs["柳妃"] = {"name": "柳妃", "alive": True, "rank": "妃", "age": 24}
payload = A.avatar_payload(gs)
npc_url = payload.get("npc:柳妃", "")
if has_pool:
    check("NPC 分到 pool 头像", npc_url.startswith("/avatars/pool/"), npc_url)
gs.children.append({"uid": 1, "gender": "皇子", "name": "承泰", "alive": True})
gs.children.append({"uid": 2, "gender": "公主", "name": "明玥", "alive": True})
payload = A.avatar_payload(gs)
if has_pool:
    check("皇子分到头像", bool(payload.get("child:1")))
    check("公主分到头像", bool(payload.get("child:2")))
    check("皇子取男桶", "/avatars/pool/" in (payload.get("child:1") or ""))

# === ② 路由 ===
if has_pool:
    first_bucket = next(b for b, files in pools.items() if files)
    sample = f"/avatars/pool/{first_bucket}/{pools[first_bucket][0]}"
    rr = client.get(sample)
    check(f"pool 路由可取图 ({first_bucket})", rr.status_code == 200, f"{sample} status={rr.status_code}")
# 皇帝头像（皇帝桶或回退链）
emp_url = payload.get("emperor", "")
check("皇帝头像存在", bool(emp_url) and emp_url.startswith("/avatars/pool/"), str(emp_url))
if "皇帝" in pools and pools["皇帝"]:
    check("皇帝优先取 皇帝 桶", "/%E7%9A%87%E5%B8%9D/" in emp_url or "/皇帝/" in emp_url, emp_url)
rr = client.get("/avatars/ui/scene1.jpg")
check("ui 路由 scene1.jpg", rr.status_code == 200, f"status={rr.status_code}")
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
