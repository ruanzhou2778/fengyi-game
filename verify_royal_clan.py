# -*- coding: utf-8 -*-
"""验证：宗室系统（世系生成/立场演化/谋逆链/爵位流转/玩法接口/选秀注入/存读档）。

运行：python verify_royal_clan.py
"""
import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch

import app as A
from app import app as flask_app
from models import Rank
import royal_clan as R

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


def fresh_state(rank=Rank.贵妃):
    gs = A.GameState("verify-royal", rank)
    gs.name = "测试妃"
    gs.silver = 2000
    gs.remaining_actions = 30
    gs.attributes["威望"] = 80
    gs.attributes["宠爱"] = 80
    return gs


# 1. 世系生成
section("1. 世系生成")
gs = fresh_state()
rc = R.seed_royal_clan(gs)
males = R.alive_males(rc)
females = R.alive_females(rc)
n_prince = len([m for m in males if m["爵位"] == "亲王" and m["generation"] != "长辈"])
n_junwang = len([m for m in males if m["爵位"] == "郡王" and m["generation"] != "长辈"])
ok("亲王 3~4", 3 <= n_prince <= 4, n_prince)
ok("郡王 6~8", 6 <= n_junwang <= 8, n_junwang)
ok("长辈 1~2", 1 <= len([m for m in males if m["generation"] == "长辈"]) <= 2)
ok("长公主 1~2", 1 <= len([f for f in females if f["称号"] == "长公主"]) <= 2)
ok("宗室女 2~3", 2 <= len([f for f in females if f["称号"] == "宗室女"]) <= 3)
ok("大宗正已定", rc["dazongzheng"] in rc["males"], rc["dazongzheng"])
ok("郡主父系挂接", all(rc["males"].get(f["父系"]) for f in females if f["称号"] in ("郡主", "县主") and f["父系"]))
ok("立场推导有效", all(m["立场"] in ("拥皇", "中立", "反皇") for m in males))
for i, m in enumerate(males[:4]):
    m["关系"] = 30 + i * 15  # 显式设置关系，避免种子导致无人达到动作门槛
ok("再次 seed 幂等", len(R.seed_royal_clan(gs)["males"]) == len(rc["males"]))

# 2. 玩法接口（男）
section("2. 宗室男动作")
ally_target = next(m for m in males if m["爵位"] == "亲王")
ally_target["关系"] = 40
ok_, msg = R.royal_male_action(gs, rc, ally_target, "ally")
ok("结盟成功", ok_ and ally_target["name"] in rc["allies"], msg)
ok_, msg = R.royal_male_action(gs, rc, ally_target, "ally")
ok("重复结盟被拒", not ok_, msg)
low = next(m for m in males if m["关系"] < 20)
ok_, msg = R.royal_male_action(gs, rc, low, "advise")
ok("献计关系不足被拒", not ok_, msg)
rel_ok = next(m for m in males if m["关系"] >= 20 and m is not ally_target)
before_fav = gs.relationships.setdefault("皇帝", {"好感": 50})["好感"]
ok_, msg = R.royal_male_action(gs, rc, rel_ok, "advise")
ok("献计成功", ok_, msg)
ok("献计耗行动点", gs.remaining_actions < 30, gs.remaining_actions)
aid_target = next(m for m in males if m["爵位"] in ("亲王", "郡王"))
aid_target["关系"] = 60
aid_target["实力"] = 60
silver0 = gs.silver
ok_, msg = R.royal_male_action(gs, rc, aid_target, "aid")
ok("求援得银", ok_ and gs.silver > silver0, (ok_, msg, gs.silver))
ok_, msg = R.royal_male_action(gs, rc, aid_target, "aid")
ok("求援每旬一次", not ok_, msg)
# 联姻
gs.children.append({"name": "昭阳", "gender": "公主", "age": 17, "alive": True,
                    "marriage_status": "未议", "recent_events": []})
A.ensure_child_uid(gs, gs.children[0])
marry_target = next(m for m in males if m["爵位"] == "郡王" and not m["妻妾"])
marry_target["关系"] = 40
ok_, msg = R.royal_male_action(gs, rc, marry_target, "marry_off")
ok("联姻成功", ok_, msg)
ok("公主嫁入王府", gs.children[0]["consort"]["name"] == marry_target["name"]
   and gs.children[0]["marriage_status"] == "已嫁", gs.children[0].get("consort"))
ok("联姻入盟", marry_target["name"] in rc["allies"])
# 举报
report_target = next((m for m in males if m["野心"] >= 70), None)
if report_target:
    report_target["野心"] = 80
    report_target["立场"] = "反皇"
    report_target["帝眷"] = min(report_target["帝眷"], 25)
    fav0 = gs.attributes["宠爱"]
    ok_, msg = R.royal_male_action(gs, rc, report_target, "report")
    ok("举报成功", ok_, msg)
    ok("举报得宠", gs.attributes["宠爱"] > fav0)
else:
    ok("存在野心≥70宗室", False, "生成异常")

# 3. 玩法接口（女）
section("3. 宗室女动作")
fs = R.alive_females(rc)
f_candidate = next(f for f in fs if f["称号"] == "宗室女")
f_candidate["关系"] = 40
silver0 = gs.silver
ok_, msg = R.royal_female_action(gs, rc, f_candidate, "befriend")
ok("结交成功", ok_ and gs.silver == silver0 - 20, msg)
ok_, msg = R.royal_female_action(gs, rc, f_candidate, "recommend")
ok("推荐入宫", ok_ and f_candidate["name"] in rc.get("draft_inject", []), msg)
f_jz = next((f for f in fs if f["称号"] in ("郡主", "县主")), None)
if f_jz:
    f_jz["关系"] = 40
    f_jz["父系"] = next((m["name"] for m in males if m["爵位"] in ("亲王", "郡王")), "")
    rc["males"].setdefault(f_jz["父系"], {"name": f_jz["父系"], "爵位": "亲王", "帝眷": 50, "立场": "中立", "实力": 40, "alive": True, "generation": "同辈", "关系": 0, "标记": [], "妻妾": [], "子女": 0, "年龄": 40, "野心": 30, "封地": ""})
    dj0 = rc["males"][f_jz["父系"]]["帝眷"]
    ok_, msg = R.royal_female_action(gs, rc, f_jz, "pull")
    ok("拉拢父系", ok_ and rc["males"][f_jz["父系"]]["帝眷"] == dj0 + 2, msg)
gs.remaining_actions = 10
ok_, msg = R.royal_female_action(gs, rc, f_candidate, "intel")
ok("情报入流言", ok_ and any(r.get("source") == "royal_clan" for r in gs.intrigue.get("rumors", [])), msg)
f_bond = next(f for f in fs if f["称号"] == "长公主")
f_bond["关系"] = 40
ok_, msg = R.royal_female_action(gs, rc, f_bond, "bond")
ok("手帕交", ok_ and f_bond["name"] in rc["handkerchief"], msg)

# 4. 谋逆链 + 爵位流转
section("4. 谋逆与爵位")
traitor = next(m for m in R.alive_males(rc) if m["爵位"] == "亲王")
traitor["野心"] = 80
traitor["帝眷"] = 20
traitor["立场"] = "反皇"
traitor["reported"] = True
daughter = R._make_female(gs, set(), "郡主", father=traitor["name"], 身份=f"{traitor['name']}之女")
rc["females"][daughter["name"]] = daughter
msgs = R._rebellion_chain(gs, rc, traitor)
ok("谋逆伏诛", not traitor["alive"], msgs)
ok("举报得赏叙事", any("密告" in m or "忠慎" in m for m in msgs), msgs)
ok("其女降等", daughter["称号"] == "县主", daughter["称号"])
father_m = next(m for m in R.alive_males(rc) if m["爵位"] == "郡王" and m["年龄"] >= 12)
son = R._make_male(gs, set(rc["males"].keys()), "国公", father=father_m["name"], generation="子侄", age=15)
son["father"] = father_m["name"]
rc["males"][son["name"]] = son
msgs2 = R._succeed_title(gs, rc, father_m)
ok("父亡子袭爵", not father_m["alive"] and son["爵位"] == "郡王", (msgs2, son["爵位"]))

# 5. 转旬引擎
section("5. 转旬引擎")
gs2 = fresh_state()
rc2 = R.seed_royal_clan(gs2)
for m in R.alive_males(rc2):
    m["帝眷"] = 90
    m["立场"] = "中立"
for npc_name in ("宗妃甲",):
    gs2.npcs[npc_name] = {"name": npc_name, "rank": "妃", "alive": True,
                          "attributes": {"宠爱": 90},
                          "relationship": {"好感": 0, "印象": "普通", "互动次数": 0},
                          "children": [], "royal_father": next(iter(rc2["males"]))}
target_m = rc2["males"][gs2.npcs["宗妃甲"]["royal_father"]]
with patch('royal_clan.random.random', return_value=0.99), \
     patch('royal_clan.random.randint', side_effect=lambda a, b: a):
    R.process_royal_clan_period(gs2)
ok("受宠女反馈父系帝眷", target_m["帝眷"] == 91, target_m["帝眷"])
ok("高帝眷偏拥皇", target_m["立场"] == "拥皇", target_m["立场"])
ok("事件池运行", isinstance(R.process_royal_clan_period(gs2), list))

# 6. 选秀注入 + API 冒烟
section("6. 选秀注入与 API")
r = flask_app.test_client().post('/api/start', json={"name": "沈妃", "api_base": "", "api_key": "", "api_model": ""})
pid = r.get_json()["player_id"]
sgs = A.sessions[pid]
sgs.rank = Rank.妃
sgs.attributes["威望"] = 90
sgs.silver = 3000
sgs.remaining_actions = 20
rc3 = R.seed_royal_clan(sgs)
f3 = next(f for f in R.alive_females(rc3) if f["称号"] == "宗室女")
f3["关系"] = 50
R.royal_female_action(sgs, rc3, f3, "recommend")
A.start_draft(sgs, "大选")
names = [c["name"] for c in sgs.draft["candidates"]]
ok("宗室女入册", f3["name"] in names, names)
ok("候选标记", "已入候选" in f3["标记"], f3["标记"])
A.app.config['TESTING'] = True
client = flask_app.test_client()
r = client.get(f'/api/royal/overview?player_id={pid}')
ov = r.get_json() or {}
ok("overview ok", r.status_code == 200 and ov.get("males") and ov.get("females") is not None, list(ov)[:5])
rc3["males"][ov["males"][0]["name"]]["关系"] = 50  # API 动作有关系门槛
r = client.post('/api/royal/action', json={"player_id": pid, "kind": "male",
                                           "name": ov["males"][0]["name"], "action": "advise"})
ok("action ok", r.status_code == 200, r.get_json())
r = client.post('/api/royal/action', json={"player_id": pid, "kind": "male", "name": "不存在", "action": "ally"})
ok("404 unknown", r.status_code == 404, r.status_code)

# 7. 存读档
section("7. 存读档")
payload = sgs.to_save_data()
ok("to_save_data includes royal_clan", isinstance(payload.get("game_state", {}).get("royal_clan"), dict))
restored = A.GameState.from_save_data(payload)
rc4 = R.get_royal_clan(restored)
ok("roster restored", len(rc4["males"]) == len(rc3["males"]) and rc4.get("seeded") is True)
ok("pending restored", len(rc4.get("pending", [])) == len(rc3.get("pending", [])))

print(f"\n宗室系统验证: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
