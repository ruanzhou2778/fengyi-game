# -*- coding: utf-8 -*-
"""验证：妃嫔举荐秀女系统（资格/公式/三方式/五档结果/入宫/NPC竞争/干扰/补救/存读档）。

运行：python verify_recommend_system.py
"""
import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch

import app as A
from app import app as flask_app
from models import Rank
import recommend_system as R

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


def fresh_state(rank=Rank.妃):
    gs = A.GameState("verify-rec", rank)
    gs.name = "沈语嫣"
    gs.attributes["威望"] = 60
    gs.attributes["宠爱"] = 60
    gs.silver = 1000
    gs.remaining_actions = 20
    from family_backgrounds import generate_player_clan
    gs.player_clan = generate_player_clan("沈", {})
    gs.relationships["皇帝"] = {"好感": 80, "印象": "亲密", "互动次数": 3}
    gs.relationships["太后"] = {"好感": 60, "印象": "和善", "互动次数": 2}
    # GameState 不自带 NPC（/api/start 才生成），手工补两三位供举荐竞争/干扰用
    for i, (nm, rk) in enumerate([("华贵妃", "妃"), ("丽嫔", "嫔"), ("贤妃", "妃")]):
        gs.npcs[nm] = {"name": nm, "rank": rk, "alive": True, "icon": "🌸",
                       "attributes": {"宠爱": 50}, "is_pregnant": False, "children": [],
                       "relationship": {"好感": 10, "印象": "普通", "互动次数": 0},
                       "clan": {"surname": nm[0], "家族威望": 40, "政治倾向": "文官党"}}
    return gs


def next_period_key(gs):
    """跨过开选旬，让 process_draft 真正放榜（开选当旬只公示）。"""
    gs.draft["started_key"] = "0-0-0"


def start_draft_ok(gs):
    msgs = A.start_draft(gs, "大选")
    return msgs


def section(t):
    print(f"\n=== {t} ===")


# 1. 资格与限次
section("1. 资格与限次")
gs = fresh_state()
start_draft_ok(gs)
ok("draft active", gs.draft and gs.draft.get("active"))
ok("no blockers for 妃", R.eligibility_blockers(gs, gs.draft["candidates"][0]) == [],
   R.eligibility_blockers(gs, gs.draft["candidates"][0]))
gs.relationships["皇帝"]["好感"] = 30
ok("favor blocker", any("好感" in b for b in R.eligibility_blockers(gs, gs.draft["candidates"][0])))
gs.relationships["皇帝"]["好感"] = 80
gs.attributes["威望"] = 10
ok("prestige blocker", any("威望" in b for b in R.eligibility_blockers(gs, gs.draft["candidates"][0])))
gs.attributes["威望"] = 60
low = fresh_state(rank=Rank.贵人)
start_draft_ok(low)
ok("贵人 quota 1", R.rank_recommend_max("贵人") == 1)
ok("皇后 quota 3", R.rank_recommend_max("皇后") == 3)
ok("妃 quota 2", R.rank_recommend_max("妃") == 2)

# 2. 成功率公式钳制与方式差异
section("2. 成功率公式")
gs2 = fresh_state()
start_draft_ok(gs2)
c0 = gs2.draft["candidates"][0]
from unittest.mock import patch as _p
# compute_rate 内有 ±10 随机抖动，固定后才能稳定比较方式间加成
with _p('recommend_system.random.randint', return_value=0):
    rates = {k: R.compute_rate(gs2, c0, k) for k in R.METHODS}
ok("rates within [5,95]", all(5 <= v <= 95 for v in rates.values()), rates)
ok("phoenix bonus > public", rates["phoenix"] >= rates["public"], rates)
ok("private bonus > public", rates["private"] >= rates["public"], rates)

# 3. 玩家举荐：成功档（保送 + 知遇 + 族女家族威望）
section("3. 玩家举荐成功")
gs3 = fresh_state()
start_draft_ok(gs3)
clan_cand = next((c for c in gs3.draft["candidates"] if R._cand_surname(c) == "沈"), None)
if clan_cand is None:
    clan_cand = gs3.draft["candidates"][0]
is_clan_cand = R._cand_surname(clan_cand) == "沈"
clan_prestige_before = gs3.player_clan["家族威望"]
before_prestige = gs3.attributes["威望"]
with patch('recommend_system.random.randint', side_effect=lambda a, b: 1 if (a, b) == (1, 100) else 1):
    res = R.player_recommend(gs3, clan_cand["name"], "private")
ok("recommend success", res.get("success") is True, res)
ok("tier granted", res.get("tier") in ("圣心大悦", "欣然应允", "勉强同意"), res.get("tier"))
ok("candidate guaranteed", clan_cand.get("guaranteed_admit") is True)
ok("favor offset applied", clan_cand.get("favor_offset", 0) > 0, clan_cand.get("favor_offset"))
ok("quota consumed", gs3.recommendations["player_used"] == 1, gs3.recommendations["player_used"])
ok("cooldown set", gs3.recommendations["cooldown_left"] == R.RECOMMEND_COOLDOWN_PERIODS)
if is_clan_cand:
    ok("clan prestige +5", gs3.player_clan["家族威望"] == min(95, clan_prestige_before + 5),
       f'{clan_prestige_before} -> {gs3.player_clan["家族威望"]}')

# 放榜：保送必入选、位份来自档位池、知遇折入好感
next_period_key(gs3)
rec_msgs = A.process_draft(gs3)[0]
ok("admitted into npcs", clan_cand["name"] in gs3.npcs, list(gs3.npcs)[:5])
if clan_cand["name"] in gs3.npcs:
    admitted_npc = gs3.npcs[clan_cand["name"]]
    ok("rank from pool", admitted_npc["rank"] in ("答应", "常在", "贵人", "官女子"), admitted_npc["rank"])
    ok("favor offset folded", gs3.relationships[clan_cand["name"]]["好感"] >= 5,
       gs3.relationships[clan_cand["name"]])
    ok("impression 知遇", gs3.relationships[clan_cand["name"]]["印象"] == "知遇")

# 4. 玩家举荐失败 + 补救
section("4. 举荐失败与补救")
gs4 = fresh_state()
start_draft_ok(gs4)
c1 = gs4.draft["candidates"][0]
with patch('recommend_system.random.randint', side_effect=lambda a, b: 1 if (a, b) == (-10, 10) else 100):
    res4 = R.player_recommend(gs4, c1["name"], "public")
ok("recommend failed", res4.get("success") is False, res4)
ok("fail tier", res4.get("tier") in ("沉吟不语", "龙颜不悦"), res4.get("tier"))
ok("candidate marked failed", c1.get("rec_failed") is True)
ok("virtue not granted (failed)", not c1.get("virtue_tag"))
# 再次举荐（补救）：失败者可重试，-10% 罚
with patch('recommend_system.random.randint', side_effect=lambda a, b: 1 if (a, b) == (1, 100) else 1):
    res4b = R.player_recommend(gs4, c1["name"], "private", retry=True)
ok("retry success", res4b.get("success") is True, res4b)
ok("retry silver charged", gs4.silver == 1000 - R.RECOMMEND_RETRY_COST, gs4.silver)
ok("retry counts a use", gs4.recommendations["player_used"] == 2, gs4.recommendations["player_used"])
# 偶遇与太后说情
c2 = next(c for c in gs4.draft["candidates"] if not c.get("guaranteed_admit") and not c.get("rec_failed"))
res4c = R.remedy(gs4, "meet", c2["name"])
ok("meet needs authority blocked for 妃", res4c.get("error"), res4c)
gs4_backup_rank = gs4.rank
gs4.rank = Rank.皇后
res4d = R.remedy(gs4, "meet", c2["name"])
ok("meet ok for queen", "narration" in res4d, res4d)
ok("impression bonus", c2.get("impression_bonus") == R.RECOMMEND_MEET_BONUS, c2.get("impression_bonus"))
favor_before_plea = gs4.relationships["皇帝"]["好感"]
res4e = R.remedy(gs4, "dowager")
ok("dowager plea ok", "narration" in res4e, res4e)
ok("emp favor +5", gs4.relationships["皇帝"]["好感"] == favor_before_plea + 5,
   gs4.relationships["皇帝"]["好感"])
ok("dowager once per edition", R.remedy(gs4, "dowager").get("error"))
gs4.rank = gs4_backup_rank

# 5. NPC 举荐竞争 + 干扰
section("5. NPC 举荐与干扰")
gs5 = fresh_state()
start_draft_ok(gs5)
rec = R.get_recommendations(gs5)
npc_name = next(n for n, c in gs5.npcs.items()
                if isinstance(c, dict) and c.get("alive", True)
                and n not in ("太后", "皇后") and n != gs5.name)
pending_cand = next(c for c in gs5.draft["candidates"] if not c.get("npc_rec_pending"))
pending_cand["npc_rec_pending"] = npc_name
rec["npc_recommendations"] = [{"npc": npc_name, "candidate": pending_cand["name"],
                               "base_rate": 1.0, "rate_mod": 0, "period": "t"}]
resolve_msgs = R.resolve_npc_recommendations(gs5)
ok("npc rec resolved msg", any(npc_name in m for m in resolve_msgs), resolve_msgs)
ok("npc guaranteed admit", pending_cand.get("guaranteed_admit") is True)
ok("npc rel -2 (10->8)", gs5.npcs[npc_name]["relationship"]["好感"] == 8,
   gs5.npcs[npc_name]["relationship"])
next_period_key(gs5)
msgs5 = A.process_draft(gs5)[0]
ok("npc candidate admitted", pending_cand["name"] in gs5.npcs)

# 失败 + 谗言 → 家族结怨（-15）
gs5f = fresh_state()
start_draft_ok(gs5f)
rec5f = R.get_recommendations(gs5f)
c5f = next(c for c in gs5f.draft["candidates"] if not c.get("npc_rec_pending"))
npc5f = next(n for n in gs5f.npcs if n not in ("太后", "皇后") and n != gs5f.name)
c5f["npc_rec_pending"] = npc5f
rec5f["npc_recommendations"] = [{"npc": npc5f, "candidate": c5f["name"],
                                 "base_rate": 0.0, "rate_mod": 0, "period": "t"}]
R.interfere_npc_rec(gs5f, npc5f, "whisper")
ok("whisper -30% applied", rec5f["npc_recommendations"][0]["rate_mod"] == -30,
   rec5f["npc_recommendations"])
ok("competition pending marked", c5f.get("npc_rec_pending") == npc5f)
R.resolve_npc_recommendations(gs5f)
ok("fail + whisper grudge (10->-5)", gs5f.npcs[npc5f]["relationship"]["好感"] == -5,
   gs5f.npcs[npc5f]["relationship"])
ok("fail not guaranteed", not c5f.get("guaranteed_admit"))

gs5b = fresh_state()
start_draft_ok(gs5b)
rec5b = R.get_recommendations(gs5b)
c5b = gs5b.draft["candidates"][0]
npc5b = next(n for n in gs5b.npcs if n not in ("太后", "皇后") and n != gs5b.name)
rec5b["npc_recommendations"] = [{"npc": npc5b, "candidate": c5b["name"],
                                 "base_rate": 1.0, "rate_mod": 0, "period": "t"}]
c5b["npc_rec_pending"] = npc5b
before_silver = gs5b.silver
res5b = R.interfere_npc_rec(gs5b, npc5b, "intercept")
ok("intercept ok", "narration" in res5b, res5b)
ok("intercept cost", gs5b.silver == before_silver - R.NPC_INTERCEPT_COST)
ok("pending removed", rec5b["npc_recommendations"] == [])
res5c = R.interfere_npc_rec(gs5b, npc5b, "warn")
ok("warn without pending blocked", res5c.get("error"))
c5c = next(c for c in gs5b.draft["candidates"] if not c.get("npc_rec_pending"))
rec5b["npc_recommendations"] = [{"npc": npc5b, "candidate": c5c["name"],
                                 "base_rate": 1.0, "rate_mod": 0, "period": "t"}]
c5c["npc_rec_pending"] = npc5b
roster_before = len(gs5b.draft["candidates"])
gs5b.npcs[npc5b]["relationship"]["好感"] = 10  # 重置，规避截留 50% 被察觉的随机扣减
res5d = R.interfere_npc_rec(gs5b, npc5b, "warn")
ok("warn removes candidate", len(gs5b.draft["candidates"]) == roster_before - 1, res5d)
ok("warn npc grudge (10->-10)", gs5b.npcs[npc5b]["relationship"]["好感"] == -10,
   gs5b.npcs[npc5b]["relationship"])

# 6. 届次切换重置 + 冷却递减
section("6. 届次与冷却")
gs6 = fresh_state()
start_draft_ok(gs6)
R.get_recommendations(gs6)["player_used"] = 1
R.get_recommendations(gs6)["cooldown_left"] = 3
gs6.draft = None
gs6.recommendations["edition"] = None
start_draft_ok(gs6)
ok("edition reset used", R.get_recommendations(gs6)["player_used"] == 0)
R.tick_recommendations(gs6)
ok("cooldown decrements", R.get_recommendations(gs6)["cooldown_left"] == 2)

# 7. API 冒烟（预览 + 举荐 + 干扰 + 补救）
section("7. API 冒烟")
A.app.config['TESTING'] = True
client = flask_app.test_client()
r = client.post('/api/start', json={"name": "沈玉棠", "api_base": "", "api_key": "", "api_model": ""})
d = r.get_json()
pid = d["player_id"]
sgs = A.sessions[pid]
sgs.rank = Rank.妃
sgs.attributes["威望"] = 80
sgs.attributes["宠爱"] = 70
sgs.silver = 1000
sgs.remaining_actions = 20
sgs.relationships["皇帝"] = {"好感": 80, "印象": "亲密", "互动次数": 3}
sgs.relationships["太后"] = {"好感": 60, "印象": "和善", "互动次数": 2}
A.start_draft(sgs, "大选")
cand = sgs.draft["candidates"][0]
r = client.get(f'/api/draft/recommend?player_id={pid}&candidate={cand["name"]}')
pv = r.get_json() or {}
ok("preview ok", r.status_code == 200 and pv.get("eligible") is True, pv)
ok("preview 3 methods", len(pv.get("methods", [])) == 3, len(pv.get("methods", [])))
ok("preview rates", all(m.get("rate") is not None for m in pv.get("methods", [])))
with patch('recommend_system.random.randint', return_value=1):
    r = client.post('/api/draft/recommend', json={"player_id": pid, "candidate": cand["name"], "method": "private"})
rr = r.get_json() or {}
ok("api recommend ok", r.status_code == 200 and rr.get("success"), rr)
ok("api narration", "举荐" in (rr.get("narration") or ""), rr.get("narration"))
ok("api panel refresh", isinstance(rr.get("draft_panel"), dict))
r = client.post('/api/draft/remedy', json={"player_id": pid, "kind": "dowager"})
ok("api remedy", r.status_code in (200, 400), r.get_json())

# 8. 存读档持久化
section("8. 存读档")
payload = sgs.to_save_data()
ok("to_save_data includes recommendations",
   isinstance(payload.get("game_state", {}).get("recommendations"), dict))
restored = A.GameState.from_save_data(payload)
ok("from_save_data restores recs", restored.recommendations["player_used"] == sgs.recommendations["player_used"])
ok("history persisted", len(restored.recommendations["recommendation_history"]) ==
   len(sgs.recommendations["recommendation_history"]))

print(f"\n妃嫔举荐系统验证: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
