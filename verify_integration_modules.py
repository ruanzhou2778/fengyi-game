# -*- coding: utf-8 -*-
"""验证：五模块整合（驸马朝堂声望 / 省亲带外孙 / 关系网→情报流言 / 统一归属管理 / 每日行动AI化冒烟）。

运行：python verify_integration_modules.py
"""
import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch

import app as A
from app import app as flask_app
from models import Rank

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


def fresh_state(rank=Rank.妃):
    gs = A.GameState("verify-mod", rank)
    gs.name = "测试妃"
    gs.silver = 2000
    gs.remaining_actions = 20
    return gs


def make_princess(name="明瑶", status="已嫁"):
    return {
        "name": name, "gender": "公主", "age": 18, "alive": True,
        "marriage_status": status, "affection": 40, "mood": "开心",
        "consort": {"name": "驸马沈钰", "faction": "文官党", "family_score": 90},
        "mansion": {"name": "明瑶公主府", "level": 2, "income": 0, "reputation": 50},
        "marriage_events": [], "recent_events": [], "children": [],
    }


# 1. 模块一：驸马每旬朝堂声望
section("1. 驸马朝堂声望")
gs = fresh_state()
gs.court_faction_favor = A.normalize_court_faction_favor(None)
gs.court_faction_favor["文官党"] = 50
gs.children.append(make_princess())
before = gs.court_faction_favor["文官党"]
mem_before = len(gs.get_recent_memories(50))
A.process_princess_marriage_events(gs)
after = gs.court_faction_favor["文官党"]
ok("faction favor increases", after > before, f"{before} -> {after}")
ok("favor gain in range", 1 <= after - before <= 5, after - before)
# 同月第二旬不再记记忆（节流）
mem_mid = len(gs.get_recent_memories(50))
A.process_princess_marriage_events(gs)
ok("memory throttled within month", len(gs.get_recent_memories(50)) == mem_mid,
   len(gs.get_recent_memories(50)) - mem_mid)
# 无派系驸马不加分
gs.children = [make_princess(status="未议")]
before2 = gs.court_faction_favor["文官党"]
A.process_princess_marriage_events(gs)
ok("unmarried princess skipped", gs.court_faction_favor["文官党"] == before2)

# 2. 模块一：省亲带外孙
section("2. 省亲带外孙")
gs2 = fresh_state()
gs2.children.append(make_princess())
n_before = len(gs2.children)
with patch('app.random.random', return_value=0.0):  # 28% 省亲与 8% 带孙全部必中
    events = A.process_princess_marriage_events(gs2)
ok("visit event fired", any("省亲" in e for e in events), events)
grand = [c for c in gs2.children if c.get("adopted") and c.get("adoptive_mother") == gs2.name
         and c.get("birth_mother") == "明瑶"]
ok("grandchild added", len(grand) == 1, len(gs2.children) - n_before)
if grand:
    g = grand[0]
    ok("grandchild fields", g.get("mood") == "开心" and g.get("affection") == 50 and g.get("age") == 0,
       {k: g.get(k) for k in ("mood", "affection", "age")})
    ok("grandchild has events", any("省亲" in e for e in g.get("recent_events", [])), g.get("recent_events"))
ok("has_children flag", gs2.has_children is True)

# 3. 模块五：关系网大事 → 情报流言
section("3. 关系网事件同步流言")
gs3 = fresh_state(rank=Rank.嫔)
for nm in ("甲妃", "乙妃", "丙妃"):
    gs3.npcs[nm] = {"name": nm, "rank": "嫔", "alive": True, "attributes": {"宠爱": 50},
                    "relationship": {"好感": 20, "印象": "普通", "互动次数": 0},
                    "personality": "温婉贤淑", "children": [], "压力": 10}
gs3.day = 1  # day<=10 触发每月大事分支
with patch('app.random.random', return_value=0.0):  # 御花园偶遇(0.30)必中
    A.process_npc_relationships(gs3)
rumors = [r for r in gs3.intrigue.get("rumors", []) if r.get("source") == "relationship_net"]
ok("rumor synced", len(rumors) >= 1, len(rumors))
if rumors:
    r0 = rumors[0]
    ok("rumor shape", r0.get("target") == "后宫" and r0.get("type") == "npc"
       and 2 <= r0.get("turns_left", 0) <= 4 and bool(r0.get("text")), r0)
ok("rumor_count counts net rumors", A.summarize_intrigue(gs3)["rumor_count"] >= 1)

# 4. 模块三：统一归属管理
section("4. 统一归属校验与变更")
gs4 = fresh_state(rank=Rank.贵妃)
npc = {"name": "贫妃", "rank": "答应", "alive": True, "children": [
    {"name": "幼子", "gender": "公主", "age": 3, "alive": True, "affection": 40,
     "adopted_count": 0, "recent_events": []}]}
gs4.npcs["贫妃"] = npc
child = npc["children"][0]
err = A.validate_ownership_transfer(gs4, child, A.RANK_LEVELS["贵妃"])
ok("valid transfer passes", err is None, err)
old_child = dict(child, age=15)
ok("age blocker", A.validate_ownership_transfer(gs4, old_child, A.RANK_LEVELS["贵妃"]) is not None)
gs4.children = [{"alive": True} for _ in range(A.ADOPT_MAX_CHILDREN)]
ok("quota blocker", A.validate_ownership_transfer(gs4, child, A.RANK_LEVELS["贵妃"]) is not None)
gs4.children = []
multi = dict(child, adopted_count=A.ADOPT_MAX_TRANSFERS)
ok("transfers blocker", A.validate_ownership_transfer(gs4, multi, A.RANK_LEVELS["贵妃"]) is not None)
prince = dict(child, gender="皇子")
gs4.attributes["宠爱"] = 0
ok("prince favor blocker", A.validate_ownership_transfer(gs4, prince, A.RANK_LEVELS["贵妃"]) is not None)
gs4.attributes["宠爱"] = 80
ok("low rank blocker", A.validate_ownership_transfer(gs4, prince, A.RANK_LEVELS["答应"]) is not None)
# 共用归属变更机制
silver_before = gs4.silver
A.apply_child_ownership_transfer(gs4, child, source_npc=npc, source_index=0,
                                 mode_label="收养", cost=40, cost_note="过继仪式40两", from_name="贫妃")
ok("source list popped", npc["children"] == [])
ok("child appended to player", gs4.children and gs4.children[-1] is child)
ok("flags written", child["adopted"] is True and child["adopted_count"] == 1
   and child["adoptive_mother"] == gs4.name and child["adopted_age"] == 3, child.get("adopted_count"))
ok("birth_mother preserved", child.get("birth_mother") == "贫妃", child.get("birth_mother"))
ok("history recorded", child["adoption_history"][0]["action"] == "收养"
   and child["adoption_history"][0]["note"] == "过继仪式40两", child.get("adoption_history"))
ok("silver deducted", gs4.silver == silver_before - 40, gs4.silver)

# API 全链路：收养他人之子
client = flask_app.test_client()
A.app.config['TESTING'] = True
r = client.post('/api/start', json={"name": "沈贵人", "api_base": "", "api_key": "", "api_model": ""})
pid = r.get_json()["player_id"]
sgs = A.sessions[pid]
sgs.rank = Rank.贵妃
sgs.attributes["宠爱"] = 80
sgs.attributes["威望"] = 100
sgs.silver = 1000
sgs.remaining_actions = 10
sgs.npcs["贫妃"] = {"name": "贫妃", "rank": "答应", "alive": True, "children": [
    {"name": "庶女", "gender": "公主", "age": 2, "alive": True, "affection": 40,
     "adopted_count": 0, "recent_events": []}],
    "relationship": {"好感": 60, "印象": "友善", "互动次数": 2}, "压力": 10}
r = client.post('/api/child/adopt', json={"player_id": pid, "direction": "in",
                                          "mother_name": "贫妃", "child_index": 0})
res = r.get_json() or {}
ok("api adopt in", r.status_code == 200 and res.get("success"), res)
ok("api adopt moved child", any(c.get("name") == "庶女" for c in sgs.children))

# 5. 模块二：每日行动冒烟（/api/act 可用，/api/action 备用仍在）
section("5. 每日行动路由")
r = client.post('/api/act', json={"player_id": pid, "choice": "我要绣花", "current_time": "辰时"})
ok("api/act responds", r.status_code == 200, r.status_code)
r = client.post('/api/action', json={"player_id": pid, "action": "embroidery"})
ok("api/action kept as fallback", r.status_code == 200, r.status_code)

# 6. 王府/东宫后代折叠面板
section("6. 王府后代面板")
gs6 = fresh_state(rank=Rank.皇后)
prince_child = {"name": "承煜", "gender": "皇子", "age": 20, "alive": True,
                "marriage_status": "已婚", "mood": "平静", "recent_events": [],
                "mansion": {"name": "雍王府", "level": 2, "income": 10, "reputation": 60},
                "consort": {"name": "王妃", "faction": "文官党", "family_score": 70,
                            "offspring": [{"name": "萧承泰", "sex": "男", "relation": "皇孙",
                                           "age": 3, "father": "承煜", "spouse": "王妃", "alive": True}]}}
gs6.children.append(prince_child)
A.ensure_child_uid(gs6, prince_child)
puid = prince_child["uid"]
A.sessions[gs6.player_id] = gs6  # 路由经 session_or_404，需先注册会话
client6 = flask_app.test_client()
r = client6.get(f'/api/mansion/descendants?player_id={gs6.player_id}&child_uid={puid}')
d6 = r.get_json() or {}
ok("descendants listed", r.status_code == 200 and len(d6.get("descendants", [])) == 1, d6)
g0 = (d6.get("descendants") or [{}])[0]
ok("descendant serialized", g0.get("uid") and g0.get("安置状态") == "在府"
   and "文治" in (g0.get("stats") or {}), g0)
ok("queen can manage", d6.get("can_manage") is True, d6.get("can_manage"))
silver6 = gs6.silver
r = client6.post('/api/mansion/descendant/admit',
                 json={"player_id": gs6.player_id, "child_uid": puid, "descendant_uid": g0.get("uid")})
res6 = r.get_json() or {}
ok("admit ok", r.status_code == 200 and res6.get("success"), res6)
gc6 = prince_child["consort"]["offspring"][0]
ok("placement updated", gc6.get("安置状态") == "已入重华宫" and gc6.get("in_chonghua") is True, gc6.get("安置状态"))
ok("upkeep deducted", gs6.silver == silver6 - A.CHONGHUA_UPKEEP_PER_CHILD, gs6.silver)
r = client6.post('/api/mansion/descendant/admit',
                 json={"player_id": gs6.player_id, "child_uid": puid, "descendant_uid": g0.get("uid")})
ok("double admit blocked", r.status_code == 400, r.status_code)
# 非协理者 403
gs7 = fresh_state(rankRank := Rank.妃) if False else fresh_state(rank=Rank.妃)
gs7.children.append({"name": "皇儿", "gender": "皇子", "age": 18, "alive": True,
                     "marriage_status": "已婚", "mood": "平静", "recent_events": [],
                     "mansion": {"name": "别府", "level": 1, "income": 5, "reputation": 40},
                     "consort": {"name": "侧妃", "faction": "武官党", "family_score": 50,
                                 "offspring": [{"name": "幼孙", "sex": "男", "relation": "皇孙",
                                                "age": 2, "father": "皇儿", "spouse": "侧妃", "alive": True}]}})
A.ensure_child_uid(gs7, gs7.children[0])
A.sessions[gs7.player_id] = gs7
client7 = flask_app.test_client()
r = client7.post('/api/mansion/descendant/admit',
                 json={"player_id": gs7.player_id, "child_uid": gs7.children[0]["uid"], "descendant_uid": ""})
ok("non-manager 403", r.status_code == 403, r.status_code)

print(f"\n五模块整合验证: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
