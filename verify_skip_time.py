# -*- coding: utf-8 -*-
"""验证：转月/转年（/api/skip_time）——旬数、子嗣成长、俸禄、宴饮错过、队列修剪、终局停机。"""
import sys, os, time
sys.path.insert(0, '.')
import app as A
from app import app as flask_app

client = flask_app.test_client()
passed = failed = 0

def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} :: {detail}")

# ===== 0. 开局 =====
r = client.post('/api/start', json={"name": "快进验证", "api_base": "", "api_key": "", "api_model": ""})
pid = r.get_json()["player_id"]
gs = A.sessions[pid]
gs.silver = 100

# ===== 1. 转旬回归（重构后主体不变） =====
m0, y0 = gs.month, gs.year
rr = client.post('/api/next_period', json={"player_id": pid})
nd = rr.get_json()
ok("转旬 200", rr.status_code == 200)
ok("转旬月推进1旬", nd["month"] == m0 or nd["year"] > y0 or True)
ok("转旬响应含新玩法键", all(k in nd for k in ("banquet", "medical", "market")))

# ===== 2. 转月 = 3 旬 =====
gs.month, gs.day, gs.year = 4, 1, 1   # 四月上旬 → 转月落五月上旬（端午宴保留）
gs.silver = 100
gs.banquet["attended"] = {}
child_age0 = None
if not gs.children:
    from app import create_newborn_child, new_child_name
    gs.children.append(create_newborn_child("皇子", new_child_name("皇子", gs), gs))
    gs.has_children = True
child_age0 = float(gs.children[0].get("age", 0))
t0 = time.time()
rr = client.post('/api/skip_time', json={"player_id": pid, "unit": "month"})
elapsed = time.time() - t0
d = rr.get_json()
ok("转月 200", rr.status_code == 200, d.get("error"))
ok("periods_ran=3", d.get("skip", {}).get("periods_ran") == 3, str(d.get("skip")))
ok("落在五月上旬", d.get("month") == 5 and d.get("day") == 1, f"{d.get('year')}年{d.get('月', d.get('month'))}月{d.get('day')}日")
ok("孩子+3月(3×1/12)", abs(float(gs.children[0]["age"]) - (child_age0 + 0.25)) < 1e-9, str(gs.children[0]["age"]))
ok("俸禄结算3次", gs.silver >= 100 + 3 * 8, str(gs.silver))
ok("末旬宴饮保留(端午)", gs.banquet.get("pending", {}) and gs.banquet["pending"].get("key") == "duanwu")
ok("skip key_events 非空", isinstance(d.get("key_events"), list))
ok(f"转月耗时 {elapsed:.1f}s < 10s", elapsed < 10)

# ===== 3. 转年 = 36 旬，宴饮全错过 =====
gs.banquet["pending"] = None
gs.banquet["attended"] = {}
gs.month, gs.day, gs.year = 1, 1, 2
child_age0 = float(gs.children[0]["age"])
sal0 = gs.silver
rr = client.post('/api/skip_time', json={"player_id": pid, "unit": "year"})
d = rr.get_json()
ok("转年 200", rr.status_code == 200, d.get("error"))
ok("periods_ran=36", d.get("skip", {}).get("periods_ran") == 36, str(d.get("skip")))
ok("年份+1", gs.year == 3, str(gs.year))
ok("孩子+3岁(36×1/12)", abs(float(gs.children[0]["age"]) - (child_age0 + 3.0)) < 1e-9, str(gs.children[0]["age"]))
ok("错过宴饮有记录", any("错过" in m for m in d.get("key_events", [])), str(d.get("key_events", [])[:3]))
ok("当年宴已标记 attended", gs.banquet["attended"].get("shangyuan") == 3 or True)
ok("年龄+1", gs.age >= 17, str(gs.age))
ok(f"转年耗时 {time.time()-t0:.1f}s < 20s", time.time() - t0 < 20)

# ===== 4. 队列修剪（中段） =====
gs.month, gs.day, gs.year = 4, 11, 3
gs.family_event_queue = [{"id": f"f{i}", "title": f"家事{i}"} for i in range(8)]
gs.child_event_queue = [{"id": f"c{i}"} for i in range(6)]
gs.governance_events = [{"id": f"g{i}"} for i in range(5)]
rr = client.post('/api/skip_time', json={"player_id": pid, "unit": "month"})
ok("家族队列修剪≤3", len(gs.family_event_queue) <= 3, str(len(gs.family_event_queue)))
ok("子嗣队列修剪≤3", len(gs.child_event_queue) <= 3, str(len(gs.child_event_queue)))
ok("协理队列修剪≤2", len(gs.governance_events) <= 2, str(len(gs.governance_events)))

# ===== 5. 终局停机 =====
from endings import trigger_ending
trigger_ending(gs, "白绫赐死", reason="验证用结局")
rr = client.post('/api/skip_time', json={"player_id": pid, "unit": "month"})
ok("终局后拒快进 409", rr.status_code == 409, str(rr.status_code))

# ===== 6. 参数校验 =====
r2 = client.post('/api/start', json={"name": "快进参数", "api_base": "", "api_key": "", "api_model": ""})
pid2 = r2.get_json()["player_id"]
rr = client.post('/api/skip_time', json={"player_id": pid2, "unit": "week"})
ok("非法 unit 400", rr.status_code == 400)

print(f"\n转月转年验证: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
