# -*- coding: utf-8 -*-
"""验证：出轨/私通 + 揭发利用 + 狸猫换皇子（发展/风险/消解/处置/六阶段/结局/存读档）。

运行：python verify_affair_system.py
"""
import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch

import app as A
import cold_palace as C
from app import app as flask_app
from models import Rank
import affair_system as F

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
    gs = A.GameState("verify-affair", rank)
    gs.name = "测试妃"
    gs.silver = 5000
    gs.remaining_actions = 30
    gs.attributes["威望"] = 80
    gs.attributes["宠爱"] = 70
    gs.attributes["心计"] = 80
    gs.relationships["太后"] = {"好感": 70, "印象": "和善", "互动次数": 2}
    return gs


# 1. 发展与阶段
section("1. 私通发展")
gs = fresh_state()
with patch('affair_system.random.randint', side_effect=lambda a, b: a if a == 1 and b == 100 else b):
    ok_, msg = F.develop_affair(gs, "太医", "summon")
ok("结识成功", ok_, msg)
sr = F.get_affairs(gs)
rel = sr["player"][0]
ok("关系建档", rel["对象类型"] == "太医" and rel["关系阶段"] == "偶遇", rel)
ok("行动点消耗", gs.remaining_actions < 30, gs.remaining_actions)
# 反复推进升阶
with patch('affair_system.random.randint', side_effect=lambda a, b: 1 if (a, b) == (1, 100) else 12):
    for _ in range(3):
        F.develop_affair(gs, "太医", "summon", name=rel["对象"])
ok("情感升阶", rel["情感值"] >= 25 and rel["关系阶段"] in ("熟识", "私交"),
   (rel["情感值"], rel["关系阶段"]))
ok("风险累积", rel["风险值"] > 0, rel["风险值"])
# 银两不足
gs.silver = 0
ok_, msg = F.develop_affair(gs, "外臣", "message")
ok("银两不足拒绝", not ok_, msg)
gs.silver = 5000

# 2. 特殊能力
section("2. 特殊能力")
rel["关系阶段"] = "偶遇"
rel["情感值"] = 10
ok_, msg = F.use_affair_perk(gs, rel["对象"])
ok("低阶关系被拒", ok_ is False, msg)
rel["关系阶段"] = "深交"
rel["情感值"] = 60
gs.attributes["健康"] = 60
hp0 = gs.attributes["健康"]
with patch('affair_system.random.randint', return_value=1):
    F.process_affair_period(gs)
ok("深交每旬健康+2", gs.attributes["健康"] == hp0 + 2)
rel["特殊能力"] = "伪造脉案"
rel["风险值"] = 40
ok_, msg = F.use_affair_perk(gs, rel["对象"])
ok("伪造脉案减风险", ok_ and rel["风险值"] == 30, (ok_, rel["风险值"]))

# 3. 消解
section("3. 消解五式")
rel["风险值"] = 60
ok_, msg = F.mitigate_risk(gs, rel["对象"], "cut")
ok("断绝-30情感归零", ok_ and rel["风险值"] == 30 and rel["情感值"] == 0, (rel["风险值"], rel["情感值"]))
rel["风险值"] = 80
rel["秘密"] = ["旧信"]
silver0 = gs.silver
ok_, msg = F.mitigate_risk(gs, rel["对象"], "bribe_knower")
ok("收买知情者", ok_ and rel["风险值"] == 60 and gs.silver == silver0 - 100, (rel["风险值"], gs.silver))
ok_, msg = F.mitigate_risk(gs, rel["对象"], "silence")
ok("灭口清零", ok_ and rel["风险值"] == 0 and gs.attributes["威望"] == 80 - 15, gs.attributes["威望"])
rel["风险值"] = 50
ok_, msg = F.mitigate_risk(gs, rel["对象"], "confess_dowager")
ok("坦白太后-40", ok_ and rel["风险值"] == 10, rel["风险值"])

# 4. 刺探与处置
section("4. 发现与处置")
gs2 = fresh_state()
gs2.npcs["华妃"] = {"name": "华妃", "rank": "妃", "alive": True, "attributes": {"宠爱": 40},
                    "relationship": {"好感": 10, "印象": "敌视", "互动次数": 1}, "children": [],
                    "clan": {"政治倾向": "武官党"}}
sr2 = F.get_affairs(gs2)
sr2["hidden_npc"]["华妃"] = {"对象": "李侍卫", "对象身份": "禁军侍卫", "关系阶段": "私交",
                             "风险值": 45, "秘密": ["密信三封"], "情感值": 50}
with patch('affair_system.random.random', return_value=0.1), \
     patch('affair_system.random.randint', side_effect=lambda a, b: a):
    ok_, msg = F.probe_npc_affair(gs2)
ok("刺探发现私情", ok_ and "华妃" in sr2["npc"], msg)
ok("证据在手", sr2["npc"]["华妃"]["掌握证据"], sr2["npc"]["华妃"])
wei0 = gs2.attributes["威望"]
ok_, msg = F.dispose_npc_affair(gs2, "华妃", "expose")
ok("揭发贬冷宫", ok_ and "华妃" not in gs2.npcs and gs2.attributes["威望"] > wei0, msg)
ok("接冷宫系统", "华妃" in C.get_cold_palace(gs2)["inmates"])
sr2["npc"]["华妃"] = {"对象": "李侍卫", "对象身份": "禁军侍卫", "关系阶段": "私交",
                      "风险值": 45, "秘密": [], "情感值": 50, "掌握证据": ["抄本"]}
silver0 = gs2.silver
ok_, msg = F.dispose_npc_affair(gs2, "华妃", "blackmail")
ok("勒索得银", ok_ and gs2.silver > silver0, msg)
ok_, msg = F.dispose_npc_affair(gs2, "华妃", "control")
ok("控制成棋子", ok_ and sr2["npc"]["华妃"].get("被控制") is True)

# 5. 狸猫六阶段
section("5. 狸猫换子")
gs3 = fresh_state()
el = F.swap_eligibility(gs3)
ok("资格不足有提示", not el["ok"] and el["blockers"], el)
gs3.rank = Rank.嫔
el = F.swap_eligibility(gs3)
ok("无内应提示", not el["ok"] and any("内应" in b for b in el["blockers"]), el["blockers"])
with patch('affair_system.random.randint', side_effect=lambda a, b: 1 if (a, b) == (1, 100) else 12):
    F.develop_affair(gs3, "太医", "summon")
sr3 = F.get_affairs(gs3)
ins = sr3["player"][0]
ins["关系阶段"] = "私交"
ins["忠诚度"] = 80
ok("资格达成", F.swap_eligibility(gs3)["ok"], F.swap_eligibility(gs3)["blockers"])
silver0 = gs3.silver
ok_, msg = F.swap_start_plan(gs3, ins["对象"])
ok("密谋开始", ok_ and F.get_affairs(gs3)["swap"]["phase"] == "plan", msg)
ok("银两-200", gs3.silver == silver0 - 200)
# 孕程推进 6 旬
for _ in range(6):
    with patch('affair_system.random.random', return_value=0.99):
        F.process_affair_period(gs3)
ok("孕满待产", F.get_affairs(gs3)["swap"]["phase"] == "ready")
with patch('affair_system.random.randint', return_value=1):
    ok_, msg = F.swap_execute(gs3)
sw = F.get_affairs(gs3)["swap"]
ok("执行成功", ok_ and sw["phase"] == "executed", msg)
ok("换入子嗣", len(gs3.children) == 1 and gs3.children[0].get("血统") == "换入", gs3.children)
ok("晋封一级", gs3.rank.name == "妃", gs3.rank.name)
ok("知情者在册", set(sw["知情者"]) == {ins["对象"], "接生稳婆"}, sw["知情者"])
ok("风险25起步", sw["风险值"] == 25, sw["风险值"])
ok_, msg = F.swap_aftercare(gs3, "silence_witness")
ok("善后-30清零", ok_ and sw["风险值"] == 0 and "接生稳婆" not in sw["知情者"],
   (sw["风险值"], sw["知情者"]))  # 25-30 钳至 0
# 6. 案发与结局
section("6. 案发三选")
sw["风险值"] = 85
sw["案发"] = True
with patch('affair_system.random.randint', return_value=1):
    ok_, msg = F.swap_case_respond(gs3, "deny")
ok("抵死不认成功脱身", ok_ and not sw["案发"] and "皇帝疑心" in (gs3.story_flags or []), msg)
sw["案发"] = True
ok_, msg = F.swap_case_respond(gs3, "confess")
ok("坦白→废为庶人终局", ok_ and A.is_game_over(gs3) and (gs3.ending or {}).get("key") == "废为庶人", msg)

# 7. 继位狸猫天子（结局改判钩子）
section("7. 狸猫天子")
gs4 = fresh_state(rank=Rank.皇贵妃)
F.get_affairs(gs4)
gs4.children.append({"name": "承祧", "gender": "皇子", "age": 4, "alive": True,
                     "血统": "换入", "birth_mother": gs4.name, "recent_events": []})
A.ensure_child_uid(gs4, gs4.children[0])
sw4 = F.get_affairs(gs4)["swap"]
sw4["phase"] = "executed"
sw4["child_uid"] = gs4.children[0]["uid"]
# 立储为换入子嗣
from models import default_heir_status
hst = default_heir_status()
hst["heir_id"] = gs4.children[0]["uid"]
hst["heir_name"] = "承祧"
gs4.heir_status = hst
# 触发继位分支（直接调结局判定段难以单测，验证钩子条件成立）
hc = A.get_heir_child(gs4)
ok("换入子嗣被认作储君", hc and hc.get("uid") == sw4["child_uid"], hc)
ok("钩子条件成立", str(sw4.get("child_uid")) == str(hc.get("uid") or "") and not sw4.get("案发"))

# 8. 存读档
section("8. 存读档")
payload = gs3.to_save_data()
ok("to_save_data includes secrets", isinstance(payload.get("game_state", {}).get("secret_relationships"), dict))
restored = A.GameState.from_save_data(payload)
ok("rel restored", len(restored.secret_relationships["player"]) == len(sr3["player"]))
ok("swap restored", restored.secret_relationships["swap"]["child_uid"] == sw["child_uid"])

print(f"\n出轨/狸猫系统验证: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
