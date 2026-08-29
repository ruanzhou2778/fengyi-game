# -*- coding: utf-8 -*-
"""验证：冷宫系统（进入/在押衰减/玩家互动/管理/玩家冷宫循环/翻身/结局/存读档）。

运行：python verify_cold_palace.py
"""
import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch

import app as A
from app import app as flask_app
from models import Rank
import cold_palace as C

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
    gs = A.GameState("verify-cold", rank)
    gs.name = "测试妃"
    gs.silver = 3000
    gs.remaining_actions = 30
    gs.attributes["威望"] = 90
    gs.attributes["宠爱"] = 80
    return gs


def make_npc(name="华妃", rank="妃"):
    return {"name": name, "rank": rank, "alive": True, "icon": "🌸",
            "attributes": {"健康": 60, "宠爱": 40},
            "relationship": {"好感": -10, "印象": "敌视", "互动次数": 1},
            "children": [], "family_background": "李氏（嫡）女", "压力": 30}


# 1. 收押与档案
section("1. 收押")
gs = fresh_state()
gs.npcs["华妃"] = make_npc()
gs.children.append({"name": "其子", "gender": "皇子", "age": 5, "alive": True, "心性": 30,
                    "birth_mother": "华妃", "recent_events": []})
inmate, msg = C.admit_npc(gs, "华妃", "陷害妃嫔，罪证确凿")
ok("收押成功", inmate is not None, msg)
ok("移出名册", "华妃" not in gs.npcs)
ok("秘密生成", 1 <= len(inmate["掌握的秘密"]) <= 3)
ok("子嗣心性+5", gs.children[0]["心性"] == 35, gs.children[0]["心性"])
inmate2, msg = C.admit_npc(gs, "华妃", "again")
ok("重复收押拒绝", inmate2 is None, msg)

# 2. 玩家互动
section("2. 玩家互动")
gs.remaining_actions = 10
ok_, msg = C.interact_inmate(gs, "华妃", "visit")
ok("探视得秘密", ok_ and "秘密" in msg, msg)
silver0 = gs.silver
ok_, msg = C.interact_inmate(gs, "华妃", "give")
ok("递送扣银", ok_ and gs.silver == silver0 - 20, gs.silver)
ok_, msg = C.interact_inmate(gs, "华妃", "use_secret")
ok("利用秘密", ok_ and "把柄" in msg, msg)
ok("秘密入流言", any(r.get("source") == "cold_palace" for r in gs.intrigue.get("rumors", [])))
ok("把柄入 dirt", gs.intrigue["dirt"], gs.intrigue["dirt"])
ok_, msg = C.interact_inmate(gs, "华妃", "taiyi")
ok("太医", ok_, msg)
ok_, msg = C.interact_inmate(gs, "华妃", "bribe_guard")
ok("买通看守减衰减", ok_ and C.get_cold_palace(gs)["inmates"]["华妃"]["衰减减半"] is True)
ok_, msg = C.interact_inmate(gs, "不存在", "visit")
ok("查无此人404类", ok_ is None)

# 3. 管理（皇后亲裁）
section("3. 冷宫管理")
gs_m = fresh_state(rank=Rank.皇后)
gs_m.npcs["华妃"] = make_npc()
C.admit_npc(gs_m, "华妃", "陷害妃嫔，罪证确凿")
ok_, msg = C.cold_manage(gs_m, "improve")
ok("改善条件", ok_ and C.get_cold_palace(gs_m)["environment"]["条件"] == "一般", msg)
ok_, msg = C.cold_manage(gs_m, "search", "华妃")
ok("搜查", ok_ and "密辛" in msg, msg)
ok_, msg = C.cold_manage(gs_m, "admit", "丽嫔")  # 名册无此人 → 失败
ok("裁决查无此人", ok_ is False, msg)
gs_m.npcs["丽嫔"] = make_npc("丽嫔", "嫔")
ok_, msg = C.cold_manage(gs_m, "admit", "丽嫔")
ok("裁决收押", ok_ and "丽嫔" in C.get_cold_palace(gs_m)["inmates"], msg)
ok_, msg = C.cold_manage(gs_m, "pardon", "丽嫔")
ok("特赦回宫", ok_ and "丽嫔" in gs_m.npcs and gs_m.npcs["丽嫔"]["标记"] == ["冷宫归来"], msg)
low = fresh_state(rank=Rank.贵人)
low.npcs["华妃"] = make_npc()
ok_, msg = C.cold_manage(low, "improve")
ok("非协理拒绝", ok_ is None and "协理" in msg, msg)

# 4. 玩家入冷宫 + 生存
section("4. 玩家冷宫循环")
gs2 = fresh_state()
ok_, msg = C.enter_cold_palace(gs2, "主动避居")
ok("避居成功", ok_ and C.is_player_imprisoned(gs2), msg)
ok("私房银随行", C.get_cold_palace(gs2)["player"]["银两"] == 200)
p = C.get_cold_palace(gs2)["player"]
p["健康"] = 80
p["精神状态"] = 80
gs2.remaining_actions = 10
ok_, msg = C.player_self_action(gs2, "sort_items")
ok("整理旧物得线索", ok_ and len(p["线索"]) >= 1, msg)
ok_, msg = C.player_self_action(gs2, "blood_book")
ok("血书", ok_ and p["血书"] is True and p["健康"] == 77, (msg, p["健康"]))
ok_, msg = C.player_self_action(gs2, "send_letter")
ok("高精神传信成功", ok_ and "截获" not in msg, msg)
# 常规行动被闸门拦截
client = flask_app.test_client()
A.app.config['TESTING'] = True
A.sessions[gs2.player_id] = gs2
r = client.post('/api/action', json={"player_id": gs2.player_id, "action": "rest"})
ok("常规行动423拦截", r.status_code == 423, r.status_code)

# 5. 翻身
section("5. 翻身")
p["精神状态"] = 80
p["线索"].append({"内容": "先帝密旨", "可靠性": 90})
with patch('cold_palace.random.randint', return_value=1):
    ok_, msg = C.player_release_attempt(gs2, "dowager")
ok("太后求情翻身", ok_ and not C.is_player_imprisoned(gs2), msg)
ok("复位+标签", "冷宫归来" in (gs2.story_flags or []) and gs2.neglect_periods == 0, gs2.story_flags)
# 失败→终局
gs3 = fresh_state()
C.enter_cold_palace(gs3, "顶罪")
p3 = C.get_cold_palace(gs3)["player"]
p3["精神状态"] = 90
with patch('cold_palace.random.randint', return_value=100):
    ok_, msg = C.player_release_attempt(gs3, "escape")
ok("越宫失败入终局", ok_ and A.is_game_over(gs3), msg)
ok("终局为冷宫幽闭", (gs3.ending or {}).get("key") == "冷宫幽闭", (gs3.ending or {}).get("key"))

# 6. 转旬衰减
section("6. 转旬衰减")
gs4 = fresh_state()
gs4.npcs["华妃"] = make_npc()
C.admit_npc(gs4, "华妃", "试")
inm = C.get_cold_palace(gs4)["inmates"]["华妃"]
inm["健康状况"] = 8
with patch('cold_palace.random.randint', side_effect=lambda a, b: b):  # 最大衰减
    msgs = C.cold_period_tick(gs4)
ok("病殁移除", "华妃" not in C.get_cold_palace(gs4)["inmates"], msgs)
ok("病殁叙事", any("病殁" in m for m in msgs), msgs)

# 7. 存读档
section("7. 存读档")
payload = gs_m.to_save_data()
ok("to_save_data includes cold_palace", isinstance(payload.get("game_state", {}).get("cold_palace"), dict))
restored = A.GameState.from_save_data(payload)
ok("inmates restored", "华妃" in restored.cold_palace["inmates"])
ok("environment restored", restored.cold_palace["environment"].get("条件") == "一般")

print(f"\n冷宫系统验证: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
