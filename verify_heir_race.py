# -*- coding: utf-8 -*-
"""夺嫡暗流系统验证脚本。

覆盖：
1. models：default_heir_race / normalize_heir_race（旧档兼容、势头钳制）
2. app：势头基础值计算、逐旬结算、呼声/立储触发、造势/打压逻辑
"""
import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import models
import app


PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")


def test_models():
    print("== models: default_heir_race / normalize_heir_race ==")
    d = models.default_heir_race()
    check("默认未激活", d["active"] is False)
    check("默认候选为空", d["candidates"] == [])
    check("默认势头为空", d["momentum"] == {})
    check("默认 outcome 为 None", d["outcome"] is None)

    n = models.normalize_heir_race(None)
    check("None 归一化为默认", n == models.default_heir_race())

    raw = {"active": True, "candidates": [1, 2],
           "momentum": {"1": 150, "2": -20, "x": "bad"},
           "events": ["a"], "outcome": "weird"}
    n2 = models.normalize_heir_race(raw)
    check("active 保留", n2["active"] is True)
    check("candidates 转字符串", n2["candidates"] == ["1", "2"])
    check("势头上钳到100", n2["momentum"]["1"] == 100)
    check("势头下钳到0", n2["momentum"]["2"] == 0)
    check("非法势头被丢弃", "x" not in n2["momentum"])
    check("events 保留", n2["events"] == ["a"])
    check("非法 outcome 归 None", n2["outcome"] is None)

    n3 = models.normalize_heir_race({"outcome": "settled"})
    check("合法 outcome settled 保留", n3["outcome"] == "settled")


def build_state(num_princes=3, player_prince=True):
    from models import GameState, Rank
    gs = GameState("test-player", start_rank=Rank.妃)
    gs.name = "苏婉"
    gs.children = []
    gs.npcs = {}
    gs.emperor = {"alive": True, "health": 80, "name": "萧景琰"}
    gs.heir_status = {}
    gs.heir_race = models.default_heir_race()

    ages = [16, 12, 9, 7]
    for i in range(num_princes):
        owner_player = player_prince and i == 0
        child = {
            "name": f"皇子{i+1}",
            "gender": "皇子",
            "age": ages[i % len(ages)],
            "alive": True,
            "emperor_favor": 50 + i * 5,
            "birth_mother": gs.name if owner_player else f"贵人{i}",
        }
        app.ensure_child_fields(child)
        app.ensure_child_uid(gs, child)
        if owner_player:
            gs.children.append(child)
        else:
            mother = f"贵人{i}"
            gs.npcs[mother] = {"rank": "贵人", "children": [child], "好感": 40}
    return gs


def test_momentum_base():
    print("== app: compute_heir_momentum_base ==")
    gs = build_state()
    child = gs.children[0]
    base = app.compute_heir_momentum_base(gs, child, gs.name)
    check("基础值为正数", base > 0)
    young = dict(child)
    young["age"] = 5
    base_young = app.compute_heir_momentum_base(gs, young, gs.name)
    check("年幼皇子基础值更低", base_young < base)


def test_process_activate():
    print("== app: process_heir_race 激活与势头 ==")
    random.seed(42)
    gs = build_state(num_princes=3)
    events = app.process_heir_race(gs)
    check("储君空悬时激活", gs.heir_race["active"] is True)
    check("首旬有开场事件", any("夺嫡" in e for e in events))
    check("候选皇子数=3", len(gs.heir_race["candidates"]) == 3)
    check("每个候选都有势头",
          all(uid in gs.heir_race["momentum"] for uid in gs.heir_race["candidates"]))
    for uid, m in gs.heir_race["momentum"].items():
        check(f"势头钳制范围 {uid}", 0 <= m <= 100)

    ev2 = app.process_heir_race(gs)
    check("第二旬不再重复开场", not any("夺嫡之争已然开启" in e for e in ev2))


def test_min_age_filter():
    print("== app: 年龄过滤 ==")
    random.seed(1)
    gs = build_state(num_princes=4)  # 7岁不参与
    app.process_heir_race(gs)
    check("7岁皇子不入候选", len(gs.heir_race["candidates"]) == 3)


def test_heir_already_set():
    print("== app: 已立储则休眠 ==")
    gs = build_state()
    gs.heir_status = {"heir_id": "999", "heir_name": "太子"}
    app.process_heir_race(gs)
    check("已立储 active=False", gs.heir_race["active"] is False)
    check("已立储 outcome=settled", gs.heir_race["outcome"] == "settled")


def test_emperor_dead():
    print("== app: 皇帝崩逝则休眠 ==")
    gs = build_state()
    gs.emperor = {"alive": False}
    app.process_heir_race(gs)
    check("皇帝崩逝 active=False", gs.heir_race["active"] is False)


def test_settle_trigger():
    print("== app: 高势头 + 皇帝病重触发立储 ==")
    gs = build_state(num_princes=1)
    gs.emperor = {"alive": True, "health": 30, "name": "萧景琰"}
    app.process_heir_race(gs)
    top_uid = gs.heir_race["candidates"][0]
    # 势头基础值自然上限约70，无法靠漂移达到95；
    # 造势/持续经营才能推高。测试中临时抬高基础值，使漂移维持在95+。
    orig = app.compute_heir_momentum_base
    app.compute_heir_momentum_base = lambda gs_, c, m: 99
    try:
        settled = False
        for _ in range(80):
            gs.heir_race["momentum"][top_uid] = 99
            gs.heir_status = {}
            app.process_heir_race(gs)
            if gs.heir_status.get("heir_id"):
                settled = True
                break
    finally:
        app.compute_heir_momentum_base = orig
    check("高势头+病重可触发立储", settled)
    if settled:
        check("立储后 outcome=settled", gs.heir_race["outcome"] == "settled")


def test_settle_writes_heir_status():
    print("== app: _heir_race_settle 写入 heir_status ==")
    gs = build_state(num_princes=1)
    child = gs.children[0]
    cuid = app.ensure_child_uid(gs, child)
    gs.heir_status = {"deposed": ["旧废太子"]}
    app._heir_race_settle(gs, cuid, child, gs.name)
    check("heir_id 写入", gs.heir_status.get("heir_id") == str(cuid))
    check("heir_name 写入", gs.heir_status.get("heir_name") == child["name"])
    check("deposed 列表保留", gs.heir_status.get("deposed") == ["旧废太子"])
    check("玩家亲子威望+15", gs.attributes.get("威望", 0) >= 15)


def test_find_prince():
    print("== app: _find_prince_by_uid ==")
    gs = build_state(num_princes=3)
    puid = app.ensure_child_uid(gs, gs.children[0])
    c, m = app._find_prince_by_uid(gs, puid)
    check("找到玩家亲子", c is not None and m == gs.name)
    c2, m2 = app._find_prince_by_uid(gs, "no-such-uid")
    check("未知 uid 返回 None", c2 is None)


def main():
    test_models()
    test_momentum_base()
    test_process_activate()
    test_min_age_filter()
    test_heir_already_set()
    test_emperor_dead()
    test_settle_trigger()
    test_settle_writes_heir_status()
    test_find_prince()
    print(f"\n==== 结果: {PASS} passed, {FAIL} failed ====")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

