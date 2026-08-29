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


def heir(name="承煜", age=8, tags=None, stats=None):
    return {"name": name, "gender": "皇子", "age": age, "alive": True,
            "affection": 65, "emperor_favor": 45, "recent_events": [],
            "tags": tags or [], "stats": stats or {}}


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
# 三旬长一岁 → 及冠触发亲政请求（仁厚性格 adult_offset=+2 → 18 岁）
adult_at = D.emperor_adult_age(d2)
ok("亲政年龄随性格", adult_at == 18 and d2["emperor"]["personality"] == "仁厚",
   (adult_at, d2["emperor"].get("personality")))
while d2["emperor"]["age"] < adult_at and d2["periods"] < 40:
    D.dowager_period_tick(gs2)
ok("新帝长岁", d2["emperor"]["age"] == adult_at, d2["emperor"]["age"])
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
d3["emperor"]["age"] = D.emperor_adult_age(d3) + 1
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
d4["emperor"]["age"] = D.emperor_adult_age(d4)
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
# v1.2-D：称制不再直接终局，转入女帝朝政循环
ok("临朝称制成功", ok_ and D.is_regnant(gs4) and not A.is_game_over(gs4), (msg, (gs4.ending or {}).get("key")))
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


# 8. 后宫治理（太后管新帝的后宫）
section("8. 新帝后宫治理")
gs7 = fresh_state()
D.enter_dowager_mode(gs7, heir(age=15))
d7 = D.get_dowager(gs7)
gs7.silver = 3000
gs7.remaining_actions = 30
ok("默认共治", d7["harem_mode"] == "共治", d7["harem_mode"])
ok("共治可管内务府", A.inner_palace_can_manage(gs7) is True)
ok_, msg = D.set_harem_mode(gs7, "共治")
ok("重复设置被拒", ok_ is False, msg)
auth0, aff0 = d7["authority"], d7["emperor"]["affection"]
ok_, msg = D.set_harem_mode(gs7, "亲掌")
ok("切亲掌", ok_ and d7["authority"] == auth0 + 3 and d7["emperor"]["affection"] == aff0 - 4, msg)
ok("亲掌可管内务府", A.inner_palace_can_manage(gs7) is True)
ok_, msg = D.set_harem_mode(gs7, "放权")
ok("切放权", ok_ is True, msg)
ok("放权后交出内务府", A.inner_palace_can_manage(gs7) is False)
ok_, msg = D.harem_action(gs7, "instruct_queen")
ok("放权后不得训诫新后", ok_ is False, msg)
ok_, msg = D.harem_action(gs7, "bless_consort")
ok("放权后仍可抚循妃嫔", ok_ is True, msg)
D.set_harem_mode(gs7, "共治")
ok_, msg = D.harem_action(gs7, "select_draft")
ok("为帝选秀", ok_ and d7.get("grandchild_chance", 0) >= 15, msg)
ok_, msg = D.harem_action(gs7, "select_draft")
ok("每旬限一次", ok_ is False, msg)
q = D.ensure_new_queen(gs7, d7)
ok("立后", bool(q) and d7["new_queen"] == q, q)
qf0 = d7["queen_favor"]
ok_, msg = D.harem_action(gs7, "instruct_queen")
ok("训诫新后（敬顺-）", ok_ and d7["queen_favor"] < qf0, (msg, d7["queen_favor"]))
ok_, msg = D.harem_action(gs7, "arbitrate")
ok("裁断宫争", ok_, msg)
ok_, msg = D.harem_action(gs7, "urge_heir")
ok("催促皇嗣", ok_ and d7["grandchild_chance"] >= 20, msg)
d7["grandchild_chance"] = 100
with patch("dowager_system.random.random", return_value=0.0):
    msgs7 = D.dowager_period_tick(gs7)
ok("皇孙诞生", any("皇长子" in m2 for m2 in msgs7), msgs7)
ok("概率清零", d7["grandchild_chance"] == 0)
d7["queen_favor"] = 10
with patch("dowager_system.random.random", return_value=0.0):
    msgs7b = D.dowager_period_tick(gs7)
ok("新后抗命反弹", any("哭诉" in m2 for m2 in msgs7b), msgs7b)
ok("payload 含后宫字段", all(k in D.dowager_payload(gs7) for k in
   ("harem_mode", "harem_modes", "harem_actions", "new_queen", "queen_favor")))

# 9. 太后期互动语义改写
section("9. 太后期互动改写")
c2 = flask_app.test_client()
r = c2.post("/api/start", json={"name": "沈太后2", "api_base": "", "api_key": "", "api_model": ""})
pid2 = r.get_json()["player_id"]
g2 = A.sessions[pid2]
g2.remaining_actions = 20
D.enter_dowager_mode(g2, heir(age=15))
r = c2.post("/api/emperor/interact", json={"player_id": pid2, "action": "serve_tea"})
j = r.get_json() or {}
ok("母子相见（非宠爱）", r.status_code == 200 and "母子" in (j.get("narration") or ""), j.get("narration"))
ok("返回垂帘数据", isinstance(j.get("dowager"), dict))
r = c2.post("/api/emperor/interact", json={"player_id": pid2, "action": "request_funding"})
j = r.get_json() or {}
ok("索内帑入私帑", r.status_code == 200 and (j.get("effects") or {}).get("私帑", 0) > 0, j.get("effects"))
r = c2.post("/api/dowager/interact", json={"player_id": pid2, "action": "pay_respects"})
j = r.get_json() or {}
ok("受新后问安（角色反转）", r.status_code == 200 and "问安" in (j.get("narration") or ""), j.get("narration"))
r = c2.post("/api/emperor/flip", json={"player_id": pid2})
ok("太后不得翻牌", r.status_code == 409, r.status_code)
r = c2.post("/api/dowager/harem", json={"player_id": pid2, "mode": "亲掌"})
ok("api 切治理之法", r.status_code == 200 and r.get_json().get("success"), r.get_json())
r = c2.post("/api/dowager/harem", json={"player_id": pid2, "action": "bless_consort"})
ok("api 后宫施为", r.status_code == 200, r.get_json())
r = c2.post("/api/dowager/harem", json={"player_id": pid2})
ok("api 缺参数400", r.status_code == 400, r.status_code)


# 10. 新帝性格分支
section("10. 新帝性格分支")
cases = [
    ("多疑", {"tags": ["孤僻"]}),
    ("暴戾", {"tags": ["尚武"]}),
    ("庸懒", {"tags": ["娇纵"]}),
    ("仁厚", {}),
]
for want, kw in cases:
    got = D.derive_emperor_personality(heir(**kw))
    ok(f"推导性格 {want}", got == want, got)
ok("低心性→多疑", D.derive_emperor_personality(heir(stats={"心性": 20})) == "多疑")
ok("高武略→暴戾", D.derive_emperor_personality(heir(stats={"武略": 80})) == "暴戾")

# 亲政年龄按性格浮动
g10 = fresh_state()
D.enter_dowager_mode(g10, heir(age=10, tags=["孤僻"]))
d10 = D.get_dowager(g10)
ok("多疑帝性格入档", d10["emperor"]["personality"] == "多疑", d10["emperor"])
ok("多疑提前亲政(14)", D.emperor_adult_age(d10) == 14, D.emperor_adult_age(d10))
g10b = fresh_state()
D.enter_dowager_mode(g10b, heir(age=10, tags=["娇纵"]))
ok("庸懒延后亲政(20)", D.emperor_adult_age(D.get_dowager(g10b)) == 20)

# 性格漂移：多疑帝每旬帝心-1、帝威+1、权威-1
aff0 = d10["emperor"]["affection"]
maj0 = d10["emperor"]["majesty"]
auth0 = d10["authority"]
d10["harem_mode"] = "共治"
with patch("dowager_system.random.random", return_value=0.99):
    D.dowager_period_tick(g10)
ok("多疑帝心下滑", d10["emperor"]["affection"] < aff0, (aff0, d10["emperor"]["affection"]))
ok("多疑帝威渐长", d10["emperor"]["majesty"] > maj0, (maj0, d10["emperor"]["majesty"]))

# 多疑/暴戾：亲政逾期会提前夺权
g11 = fresh_state()
D.enter_dowager_mode(g11, heir(age=14, tags=["尚武"]))
d11 = D.get_dowager(g11)
d11["emperor"]["age"] = D.emperor_adult_age(d11)
d11["return_requested"] = D.RETURN_POWER_GRACE + 1
d11["emperor"]["majesty"] = 30      # 未达旧的 60 门槛
d11["emperor"]["affection"] = 60    # 帝心也不低
d11["authority"] = 70
with patch("dowager_system.random.random", return_value=0.0):
    msgs11 = D.dowager_period_tick(g11)
ok("暴戾帝提前夺权", (g11.ending or {}).get("key") == "幽居慈宁", (g11.ending or {}).get("key"))
ok("夺权叙事带性格", any("禁军" in m or "先下手" in m for m in msgs11), msgs11)

# 仁厚帝不会提前夺权
g12 = fresh_state()
D.enter_dowager_mode(g12, heir(age=14))
d12 = D.get_dowager(g12)
d12["emperor"]["age"] = D.emperor_adult_age(d12)
d12["return_requested"] = D.RETURN_POWER_GRACE + 1
d12["emperor"]["majesty"] = 30
d12["emperor"]["affection"] = 60
with patch("dowager_system.random.random", return_value=0.0):
    D.dowager_period_tick(g12)
ok("仁厚帝不夺权", not A.is_game_over(g12), (g12.ending or {}).get("key"))

# 暴戾帝低帝心时归政有专属叙事
g13 = fresh_state()
D.enter_dowager_mode(g13, heir(age=14, tags=["尚武"]))
d13 = D.get_dowager(g13)
d13["emperor"]["age"] = D.emperor_adult_age(d13) + 1
d13["emperor"]["affection"] = 30
ok_, msg13 = D.return_power(g13, "yield")
ok("暴戾帝抢先撤帘叙事", ok_ and "保命" in msg13, msg13)

# 庸懒帝归政专属叙事
g14 = fresh_state()
D.enter_dowager_mode(g14, heir(age=14, tags=["娇纵"]))
d14 = D.get_dowager(g14)
d14["emperor"]["age"] = D.emperor_adult_age(d14) + 1
d14["emperor"]["affection"] = 60
ok_, msg14 = D.return_power(g14, "yield")
ok("庸懒帝仍来问政叙事", ok_ and "怎么办" in msg14, msg14)

# obedient 影响反弹幅度
g15 = fresh_state()
D.enter_dowager_mode(g15, heir(age=15))          # 仁厚 obedient
d15 = D.get_dowager(g15)
g15.remaining_actions = 10
D.ensure_new_queen(g15, d15)
qf0 = d15["queen_favor"]
D.harem_action(g15, "instruct_queen")
soft = qf0 - d15["queen_favor"]
g16 = fresh_state()
D.enter_dowager_mode(g16, heir(age=15, tags=["孤僻"]))   # 多疑 不 obedient
d16 = D.get_dowager(g16)
g16.remaining_actions = 10
D.ensure_new_queen(g16, d16)
qf1 = d16["queen_favor"]
D.harem_action(g16, "instruct_queen")
hard = qf1 - d16["queen_favor"]
ok("多疑帝下训诫反弹更大", hard > soft, (soft, hard))

# payload 暴露性格
pl = D.dowager_payload(g10)
ok("payload 含性格", (pl.get("emperor_personality") or {}).get("name") == "多疑", pl.get("emperor_personality"))
ok("payload 含实际亲政年龄", pl.get("adult_age_actual") == 14, pl.get("adult_age_actual"))


# 11. 三方势力干政
section("11. 外戚/宗室/权臣干政")
g20 = fresh_state()
D.enter_dowager_mode(g20, heir(age=12))
d20 = D.get_dowager(g20)
ok("三方势力初值", all(isinstance(d20.get(k), int) for k in ("clan_power", "royal_power", "minister_power")),
   {k: d20.get(k) for k in ("clan_power", "royal_power", "minister_power")})
ok("权臣命名", bool(D.ensure_minister(g20, d20)), d20.get("minister"))
with patch("dowager_system.random.random", return_value=0.0):
    msgs20 = D.generate_meddle_events(g20)
ok("干政事件生成", len(d20["meddle"]) == 1, d20["meddle"])
ev20 = d20["meddle"][0]
ok("事件三选", len(ev20["choices"]) == 3 and ev20["kind"] in D.MEDDLE_KINDS, ev20["kind"])
ok("模板变量已填", "{minister}" not in ev20["desc"], ev20["desc"][:40])
before = {k: d20[k] for k in ("clan_power", "royal_power", "minister_power", "authority")}
ok_, narr20 = D.respond_meddle(g20, ev20["id"], 0)
ok("干政裁决", ok_ and "处置" in narr20, narr20)
ok("移出队列", not d20["meddle"])
ok("势力已变", {k: d20[k] for k in before} != before, (before, {k: d20[k] for k in before}))
ok_, err20 = D.respond_meddle(g20, "nope", 0)
ok("无效事件404类", ok_ is None, err20)
# 队列满 → 削权威
d20["meddle"] = [{"id": "a", "tpl": "x", "kind": "外戚", "title": "t", "desc": "", "choices": []},
                 {"id": "b", "tpl": "y", "kind": "宗室", "title": "t", "desc": "", "choices": []}]
auth_b = d20["authority"]
with patch("dowager_system.random.random", return_value=0.99):
    msgs20b = D.dowager_period_tick(g20)
ok("积压请托削权威", d20["authority"] < auth_b, (auth_b, d20["authority"]))
# 权臣坐大
d20["meddle"] = []
d20["minister_power"] = 90
auth_c, court_c = d20["authority"], d20["court"]
with patch("dowager_system.random.random", return_value=0.99):
    msgs20c = D.dowager_period_tick(g20)
ok("权臣坐大压帘", any("权势已成" in x for x in msgs20c), msgs20c)
ok("权臣坐大扣双项", d20["authority"] < auth_c and d20["court"] < court_c)
# 外戚势盛损民心
d20["minister_power"] = 40
d20["clan_power"] = 85
ppl_c = d20["people"]
with patch("dowager_system.random.random", return_value=0.99):
    msgs20d = D.dowager_period_tick(g20)
ok("外戚势盛损民心", d20["people"] < ppl_c, (ppl_c, d20["people"]))
ok("payload 含势力字段", all(k in D.dowager_payload(g20) for k in
   ("clan_power", "royal_power", "minister_power", "minister", "meddle")))

# 12. 新帝妃嫔名册
section("12. 新帝妃嫔名册")
g21 = fresh_state()
D.enter_dowager_mode(g21, heir(age=15))
d21 = D.get_dowager(g21)
g21.remaining_actions = 40
g21.silver = 5000
roster = D.ensure_new_harem(g21, d21)
ok("名册铺开", 3 <= len(roster) <= 5, len(roster))
ok("名册字段", all(k in roster[0] for k in ("name", "rank", "favor", "respect", "children")), roster[0])
c21 = roster[0]
c21["rank"] = "常在"
r0 = c21["respect"]
ok_, msg21 = D.consort_action(g21, c21["name"], "promote")
ok("提拔妃嫔", ok_ and c21["rank"] == "贵人" and c21["respect"] > r0, (msg21, c21["rank"]))
ok_, msg21b = D.consort_action(g21, c21["name"], "demote")
ok("贬黜妃嫔", ok_ and c21["rank"] == "常在", (msg21b, c21["rank"]))
ok_, msg21c = D.consort_action(g21, c21["name"], "comfort")
ok("抚慰妃嫔", ok_ and g21.silver == 5000 - 60, (msg21c, g21.silver))
c21["children"] = 1
ok_, msg21d = D.consort_action(g21, c21["name"], "dismiss")
ok("有子不得遣出", ok_ is False, msg21d)
c21["children"] = 0
ok_, msg21e = D.consort_action(g21, c21["name"], "dismiss")
ok("遣出宫", ok_ and D.find_consort(d21, c21["name"]) is None, msg21e)
ok_, err21 = D.consort_action(g21, "查无此人", "promote")
ok("查无此人", err21 and ok_ is None, err21)
# 放权后不得升降
D.set_harem_mode(g21, "放权")
c21b = (d21.get("consorts") or [])[1] if len(d21.get("consorts") or []) > 1 else None
if c21b:
    ok_, msg21f = D.consort_action(g21, c21b["name"], "promote")
    ok("放权后不得升降", ok_ is False, msg21f)
    ok_, msg21g = D.consort_action(g21, c21b["name"], "comfort")
    ok("放权后仍可抚慰", ok_ is True, msg21g)
# 妃嫔生育
D.set_harem_mode(g21, "共治")
for c in d21["consorts"]:
    c["pregnant"] = True
auth_e = d21["authority"]
with patch("dowager_system.random.random", return_value=0.0):
    msgs21 = D.dowager_period_tick(g21)
ok("妃嫔诞下皇嗣", any("诞下皇嗣" in x for x in msgs21), msgs21)
ok("生育提权威", d21["authority"] >= auth_e)

# 13. 女帝称制循环
section("13. 女帝称制循环")
g22 = fresh_state()
D.enter_dowager_mode(g22, heir(age=12))
d22 = D.get_dowager(g22)
ok_, msg22 = D.return_power(g22, "regnant")
ok("条件不足不得称制", ok_ is False, msg22)
d22["authority"] = 95
d22["court"] = 90
ok_, msg22b = D.return_power(g22, "regnant")
ok("称制成功", ok_ and D.is_regnant(g22), msg22b)
ok("称制不直接终局", not A.is_game_over(g22), (g22.ending or {}).get("key"))
ok("年号已定", bool(d22["reign_name"]), d22["reign_name"])
ok("三维初值", all(isinstance(d22.get(k), int) for k in ("stability", "sovereignty", "legacy")))
# 国是生成与裁决
with patch("dowager_system.random.random", return_value=0.0):
    msgs22 = D.generate_reign_agenda(g22)
ok("国是生成", len(d22["agenda"]) == 1, d22["agenda"])
ag = d22["agenda"][0]
ok("国是三选", len(ag["choices"]) == 3, ag["title"])
st0, so0, lg0 = d22["stability"], d22["sovereignty"], d22["legacy"]
ok_, narr22 = D.respond_reign_agenda(g22, ag["id"], 0)
ok("国是裁决", ok_ and "降旨" in narr22, narr22)
ok("三维已变", (d22["stability"], d22["sovereignty"], d22["legacy"]) != (st0, so0, lg0))
ok_, err22 = D.respond_reign_agenda(g22, "nope", 0)
ok("无效国是", ok_ is None, err22)
# tick 分流到称制循环
p0 = d22["reign_periods"]
with patch("dowager_system.random.random", return_value=0.99):
    D.dowager_period_tick(g22)
ok("tick 走称制循环", d22["reign_periods"] == p0 + 1, d22["reign_periods"])
# 传位过早被拒
g23 = fresh_state()
D.enter_dowager_mode(g23, heir(age=12))
d23 = D.get_dowager(g23)
d23["authority"], d23["court"] = 95, 90
D.return_power(g23, "regnant")
ok_, msg23 = D.reign_abdicate(g23)
ok("改元未久不得传位", ok_ is False, msg23)
# 功成传位
d23["reign_periods"] = 14
d23["legacy"] = 80
d23["stability"] = 60
ok_, msg23b = D.reign_abdicate(g23)
ok("功成传位", ok_ and (g23.ending or {}).get("key") == "女帝功成", (g23.ending or {}).get("key"))
ok("称制退出", not D.is_regnant(g23))
# 倾覆
g24 = fresh_state()
D.enter_dowager_mode(g24, heir(age=12))
d24 = D.get_dowager(g24)
d24["authority"], d24["court"] = 95, 90
D.return_power(g24, "regnant")
d24["reign_periods"] = 10
d24["stability"] = 20
with patch("dowager_system.random.random", return_value=0.0):
    msgs24 = D.reign_period_tick(g24)
ok("稳固崩坏倾覆", (g24.ending or {}).get("key") == "神器倾覆", (g24.ending or {}).get("key"))
ok("倾覆叙事", any("复辟" in x for x in msgs24), msgs24)
# 主动传位但稳固过低 → 倾覆
g25 = fresh_state()
D.enter_dowager_mode(g25, heir(age=12))
d25 = D.get_dowager(g25)
d25["authority"], d25["court"] = 95, 90
D.return_power(g25, "regnant")
d25["reign_periods"] = 8
d25["stability"] = 20
d25["legacy"] = 30
ok_, msg25 = D.reign_abdicate(g25)
ok("低稳固传位=倾覆", ok_ and (g25.ending or {}).get("key") == "神器倾覆", (g25.ending or {}).get("key"))

# 14. v1.2 API 冒烟
section("14. v1.2 API")
c3 = flask_app.test_client()
r = c3.post("/api/start", json={"name": "沈太后3", "api_base": "", "api_key": "", "api_model": ""})
pid3 = r.get_json()["player_id"]
g3 = A.sessions[pid3]
g3.remaining_actions = 40
g3.silver = 5000
D.enter_dowager_mode(g3, heir(age=15))
d3 = D.get_dowager(g3)
with patch("dowager_system.random.random", return_value=0.0):
    D.generate_meddle_events(g3)
if d3.get("meddle"):
    r = c3.post("/api/dowager/meddle", json={"player_id": pid3,
                                             "meddle_id": d3["meddle"][0]["id"], "choice_index": 1})
    ok("api 干政裁决", r.status_code == 200 and r.get_json().get("success"), r.get_json())
D.ensure_new_harem(g3, d3)
nm = (d3.get("consorts") or [{}])[0].get("name")
r = c3.post("/api/dowager/consort", json={"player_id": pid3, "name": nm, "action": "comfort"})
ok("api 妃嫔处置", r.status_code == 200 and r.get_json().get("success"), r.get_json())
r = c3.post("/api/dowager/consort", json={"player_id": pid3, "name": "无此人", "action": "promote"})
ok("api 妃嫔404", r.status_code == 404, r.status_code)
d3["authority"], d3["court"] = 95, 90
r = c3.post("/api/dowager/power", json={"player_id": pid3, "mode": "regnant"})
ok("api 称制", r.status_code == 200 and r.get_json().get("success"), r.get_json())
ov3 = c3.get(f"/api/dowager/overview?player_id={pid3}").get_json() or {}
ok("api overview 含称制", ov3.get("regnant") is True and ov3.get("reign_name"), ov3.get("reign_name"))
with patch("dowager_system.random.random", return_value=0.0):
    D.generate_reign_agenda(g3)
ag3 = (D.get_dowager(g3).get("agenda") or [{}])[0].get("id")
if ag3:
    r = c3.post("/api/reign/action", json={"player_id": pid3, "agenda_id": ag3, "choice_index": 2})
    ok("api 国是裁决", r.status_code == 200 and r.get_json().get("success"), r.get_json())
r = c3.post("/api/reign/action", json={"player_id": pid3})
ok("api 缺参数400", r.status_code == 400, r.status_code)
r = c3.post("/api/reign/action", json={"player_id": pid3, "action": "abdicate"})
ok("api 传位过早400", r.status_code == 400, r.status_code)

# 15. v1.2 存读档
section("15. v1.2 存读档")
payload3 = g3.to_save_data()
rest3 = A.GameState.from_save_data(payload3)
rd3 = D.get_dowager(rest3)
sd3 = D.get_dowager(g3)
ok("称制状态恢复", rd3.get("regnant") is True and rd3.get("reign_name") == sd3.get("reign_name"))
ok("三维恢复", (rd3["stability"], rd3["sovereignty"], rd3["legacy"]) ==
   (sd3["stability"], sd3["sovereignty"], sd3["legacy"]))
ok("妃嫔名册恢复", len(rd3.get("consorts") or []) == len(sd3.get("consorts") or []))
ok("势力恢复", rd3.get("minister") == sd3.get("minister"))

print(f"\n太后垂帘系统验证: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
