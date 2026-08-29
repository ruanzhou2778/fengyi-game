# -*- coding: utf-8 -*-
"""验证：太后垂帘听政线（进入/奏事裁决/施为/财政民心/新帝成长/三出路/存读档）。

运行：python verify_dowager_system.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch

import app as A
from app import app as flask_app
from models import Rank
import dowager_system as D

PASS = 0
FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def section(t):
    print(f"\n=== {t} ===")


def fresh_state(rank=Rank.皇后):
    gs = A.GameState("verify-dowager", rank)
    gs.name = "测试太后"
    gs.silver = 5000
    gs.remaining_actions = 30
    gs.attributes["威望"] = 400
    gs.attributes["心计"] = 80
    return gs


def heir(name="承煜", age=8):
    return {"name": name, "gender": "皇子", "age": age, "alive": True,
            "affection": 65, "emperor_favor": 45, "recent_events": []}


# 1. 进入垂帘
section("1. 进入垂帘听政")
gs = fresh_state()
ok("初始未垂帘", not D.is_dowager_active(gs))
ok_, msg = D.enter_dowager_mode(gs, heir())
d = D.get_dowager(gs)
ok("进入成功", ok_ and d["active"] is True, msg)
ok("权威由威望推导", 45 <= d["authority"] <= 100, d["authority"])
ok("幼帝建档", d["emperor"]["name"] == "承煜" and d["emperor"]["age"] == 8, d["emperor"])
ok("dowager_mode 同步", gs.dowager_mode is True)
ok("续章清空终局", gs.ending is None)
ok_, msg = D.enter_dowager_mode(gs, heir())
ok("重复进入被拒", not ok_, msg)

# 2. 奏事生成与裁决
section("2. 朝会奏事")
msgs = D.generate_court_affairs(gs)
ok("奏事生成", len(d["pending"]) >= 1, d["pending"])
ev = d["pending"][0]
ok("奏事结构完整", all(k in ev for k in ("id", "title", "desc", "choices")) and len(ev["choices"]) == 3, ev)
auth0, court0, tre0, ppl0 = d["authority"], d["court"], d["treasury"], d["people"]
ok_, narr = D.respond_court_affair(gs, ev["id"], 0)
ok("裁决成功", ok_ and "裁断" in narr, narr)
ok("移出待裁", not any(p["id"] == ev["id"] for p in d["pending"]))
ok("入历史", d["history"] and d["history"][0]["title"] == ev["title"])
changed = (d["authority"], d["court"], d["treasury"], d["people"]) != (auth0, court0, tre0, ppl0)
ok("效果已应用", changed, (auth0, court0, tre0, ppl0))
ok_, err = D.respond_court_affair(gs, "not-exist", 0)
ok("无效奏本404类", ok_ is None, err)
ok_, err = D.respond_court_affair(gs, d["pending"][0]["id"] if d["pending"] else ev["id"], 9)
ok("越界选项被拒", ok_ is False or ok_ is None, err)

# 3. 太后施为
section("3. 太后施为")
gs.remaining_actions = 20
emp_aff0 = d["emperor"]["affection"]
ok_, msg = D.dowager_action(gs, "instruct")
ok("亲授帝学", ok_ and d["emperor"]["affection"] >= emp_aff0, msg)
ok_, msg = D.dowager_action(gs, "instruct")
ok("每旬限一次", not ok_, msg)
silver0 = gs.silver
ok_, msg = D.dowager_action(gs, "grant")
ok("赏赐朝臣扣私帑", ok_ and gs.silver == silver0 - 150, (msg, gs.silver))
tre0 = d["treasury"]
ok_, msg = D.dowager_action(gs, "almsgiving")
ok("施粥用国库", ok_ and d["treasury"] == tre0 - 200, (msg, d["treasury"]))
ok_, msg = D.dowager_action(gs, "audience")
ok("召见宗亲", ok_, msg)
ok_, msg = D.dowager_action(gs, "purge")
ok("整肃朝纲", ok_, msg)
ok_, msg = D.dowager_action(gs, "不存在")
ok("无效举措", ok_ is None, msg)

# 4. 转旬：财政/新帝成长/亲政请求
section("4. 转旬结算")
gs2 = fresh_state()
D.enter_dowager_mode(gs2, heir(age=15))
d2 = D.get_dowager(gs2)
tre_before = d2["treasury"]
msgs2 = D.dowager_period_tick(gs2)
ok("国库有进项", d2["treasury"] != tre_before, (tre_before, d2["treasury"]))
ok("旬数累加", d2["periods"] == 1)
# 三旬长一岁 → 及冠触发亲政请求
for _ in range(2):
    D.dowager_period_tick(gs2)
ok("新帝长岁", d2["emperor"]["age"] == 16, d2["emperor"]["age"])
ok("及冠请亲政", d2["return_requested"] >= 1, d2["return_requested"])
# 积压奏本削权威
d2["pending"] = [{"id": f"x{i}", "tpl": "t", "title": "t", "desc": "", "choices": []} for i in range(3)]
auth_b = d2["authority"]
D.dowager_period_tick(gs2)
ok("积压削权威", d2["authority"] < auth_b, (auth_b, d2["authority"]))

# 5. 三条出路
section("5. 权柄抉择")
# 5a 归政（帝未及冠被拒）
gs3 = fresh_state()
D.enter_dowager_mode(gs3, heir(age=8))
ok_, msg = D.return_power(gs3, "yield")
ok("幼帝不可归政", ok_ is False, msg)
# 5b 归政成功
d3 = D.get_dowager(gs3)
d3["emperor"]["age"] = 17
d3["emperor"]["affection"] = 70
d3["people"] = 60
ok_, msg = D.return_power(gs3, "yield")
ok("归政成功", ok_ and A.is_game_over(gs3), msg)
ok("终局=还政归养", (gs3.ending or {}).get("key") == "还政归养", (gs3.ending or {}).get("key"))
ok("退出垂帘", not D.is_dowager_active(gs3))
# 5c 拒还政
gs4 = fresh_state()
D.enter_dowager_mode(gs4, heir(age=16))
d4 = D.get_dowager(gs4)
d4["return_requested"] = 1
auth_b = d4["authority"]
ok_, msg = D.return_power(gs4, "refuse")
ok("拒还政成功", ok_ and d4["authority"] < auth_b, msg)
ok("请求清零", d4["return_requested"] == 0)
# 5d 临朝称制（条件不足→达标）
ok_, msg = D.return_power(gs4, "regnant")
ok("称制条件不足被拒", ok_ is False, msg)
d4["authority"] = 95
d4["court"] = 90
ok_, msg = D.return_power(gs4, "regnant")
ok("临朝称制成功", ok_ and (gs4.ending or {}).get("key") == "临朝称制", (msg, (gs4.ending or {}).get("key")))
# 5e 失势：权威跌破 → 幽居慈宁
gs5 = fresh_state()
D.enter_dowager_mode(gs5, heir(age=10))
d5 = D.get_dowager(gs5)
d5["authority"] = 20
with patch('dowager_system.random.random', return_value=0.0):
    msgs5 = D.dowager_period_tick(gs5)
ok("失势入终局", A.is_game_over(gs5) and (gs5.ending or {}).get("key") == "幽居慈宁",
   (gs5.ending or {}).get("key"))
# 5f 帝威高+帝心低，亲政逾期 → 幽居慈宁
gs6 = fresh_state()
D.enter_dowager_mode(gs6, heir(age=16))
d6 = D.get_dowager(gs6)
d6["return_requested"] = D.RETURN_POWER_GRACE + 1
d6["emperor"]["majesty"] = 70
d6["emperor"]["affection"] = 20
d6["authority"] = 60
msgs6 = D.dowager_period_tick(gs6)
ok("逾期未决被幽居", (gs6.ending or {}).get("key") == "幽居慈宁", (gs6.ending or {}).get("key"))

# 6. API 冒烟
section("6. API 冒烟")
A.app.config['TESTING'] = True
client = flask_app.test_client()
r = client.post('/api/start', json={"name": "沈太后", "api_base": "", "api_key": "", "api_model": ""})
pid = r.get_json()["player_id"]
sgs = A.sessions[pid]
r = client.get(f'/api/dowager/overview?player_id={pid}')
ov = r.get_json() or {}
ok("未垂帘 overview", r.status_code == 200 and ov.get("active") is False, ov.get("active"))
D.enter_dowager_mode(sgs, heir(age=9))
D.generate_court_affairs(sgs)
r = client.get(f'/api/dowager/overview?player_id={pid}')
ov = r.get_json() or {}
ok("垂帘 overview", ov.get("active") is True and ov.get("emperor"), list(ov)[:6])
if ov.get("pending"):
    r = client.post('/api/dowager/affair', json={"player_id": pid,
                                                 "affair_id": ov["pending"][0]["id"], "choice_index": 1})
    ok("api 裁决", r.status_code == 200 and r.get_json().get("success"), r.get_json())
sgs.remaining_actions = 10
r = client.post('/api/dowager/action', json={"player_id": pid, "action": "instruct"})
ok("api 施为", r.status_code == 200 and r.get_json().get("success"), r.get_json())
r = client.post('/api/dowager/power', json={"player_id": pid, "mode": "yield"})
ok("api 幼帝归政被拒", r.status_code == 400, r.status_code)

# 7. 存读档
section("7. 存读档")
payload = sgs.to_save_data()
ok("to_save_data 含 dowager_state",
   isinstance(payload.get("game_state", {}).get("dowager_state"), dict))
restored = A.GameState.from_save_data(payload)
rd = D.get_dowager(restored)
sd = D.get_dowager(sgs)
ok("垂帘状态恢复", rd["active"] is True and rd["emperor"]["name"] == sd["emperor"]["name"])
ok("数值恢复", rd["authority"] == sd["authority"] and rd["treasury"] == sd["treasury"])
ok("奏事队列恢复", len(rd["pending"]) == len(sd["pending"]))

print(f"\n太后垂帘系统验证: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
