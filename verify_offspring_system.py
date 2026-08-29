# -*- coding: utf-8 -*-
"""婚后子嗣系统验证脚本：皇子/公主/东宫内宅 怀孕 → 分娩 → 催生。
运行：python verify_offspring_system.py
"""
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as appmod
from app import (
    process_offspring_for_holder,
    process_offspring_system,
    ensure_offspring_fields,
    serialize_offspring_holder,
    PROGENY_URGE_COST,
    PROGENY_URGE_BOOST,
    PREGNANCY_STEP,
)


class FakeState:
    """轻量游戏状态替身，仅满足子嗣系统所需字段。"""

    def __init__(self):
        self.year = 1
        self.month = 1
        self.day = 1
        self.silver = 1000
        self.remaining_actions = 5
        self.max_actions = 5
        self.children = []
        self.npc_children = []
        self.heir_state = {"heir_id": "heir_1", "heir_name": "太子明", "consorts": []}
        self._mem = []

    def add_memory(self, text):
        self._mem.append(text)


def make_consort(name="王妃甲", fertility=80):
    return {"name": name, "faction": "文官党", "favor": 60, "fertility": fertility}


def make_prince(uid="p1", name="皇子弘", married=True):
    return {
        "uid": uid, "name": name, "gender": "皇子", "age": 18, "alive": True,
        "is_own": True, "marriage_status": "已婚" if married else "未婚",
        "consort": make_consort(), "marriage_events": [], "recent_events": [],
    }


def make_princess(uid="pr1", name="公主华", mode="已嫁"):
    return {
        "uid": uid, "name": name, "gender": "公主", "age": 16, "alive": True,
        "is_own": True, "marriage_status": mode,
        "consort": make_consort(name="驸马乙"), "marriage_events": [], "recent_events": [],
    }

# ---------- 测试 1：单对象怀孕→分娩→孙辈成长 ----------
def test_pregnancy_to_birth():
    print("\n=== 测试 1：怀胎 → 分娩 → 孙辈成长 ===")
    gs = FakeState()
    holder = make_consort(fertility=90)
    ensure_offspring_fields(holder)
    holder["is_pregnant"] = True
    holder["pregnancy_month"] = 0.0

    births = 0
    from unittest.mock import patch as _patch1
    with _patch1('app.random.random', return_value=0.0):
        # PREGNANCY_STEP=10/30，孕满需 30 旬；固定随机排除流产/受孕波动
        for i in range(31):
            msgs = process_offspring_for_holder(gs, holder, "皇子弘", holder["name"], "皇子", True)
            for m in msgs:
                print(f"  旬{i+1}: {m}")
            if any("喜得" in m for m in msgs):
                births += 1

    kids = holder.get("offspring", [])
    assert births >= 1, "应至少分娩一次"
    assert len(kids) >= 1, "孙辈列表不应为空"
    gc = kids[0]
    assert gc["relation"] in ("皇孙", "皇孙女"), f"皇子之孙应为皇孙/皇孙女，实为 {gc['relation']}"
    assert gc["father"] == "皇子弘"
    assert gc["spouse"] == holder["name"]
    print(f"  ✓ 分娩 {births} 次，首个孙辈：{gc['name']}（{gc['relation']}，{gc['sex']}）")

    age_before = gc["age"]
    process_offspring_for_holder(gs, holder, "皇子弘", holder["name"], "皇子", True)
    assert kids[0]["age"] > age_before, "孙辈年龄应增长"
    return True
# ---------- 测试 3：公主出降生外孙 ----------
def test_princess_grandchild():
    print("\n=== 测试 3：公主出降 → 外孙/外孙女 ===")
    gs = FakeState()
    holder = make_consort(name="驸马乙", fertility=90)
    ensure_offspring_fields(holder)
    holder["is_pregnant"] = True
    from unittest.mock import patch as _patch3
    with _patch3('app.random.random', return_value=0.0):
        for _ in range(32):  # 孕满需 30 旬
            process_offspring_for_holder(gs, holder, "公主华", "驸马乙", "公主", False)
    kids = holder.get("offspring", [])
    assert len(kids) >= 1
    rel = kids[0]["relation"]
    assert rel in ("外孙", "外孙女"), f"公主之孙应为外孙/外孙女，实为 {rel}"
    print(f"  ✓ 公主所生：{kids[0]['name']}（{rel}）")
    return True


# ---------- 测试 4：序列化输出孙辈字段 ----------
def test_serialize():
    print("\n=== 测试 4：序列化输出孙辈 / 怀孕 / 生育力 ===")
    holder = make_consort()
    ensure_offspring_fields(holder)
    holder["is_pregnant"] = True
    holder["pregnancy_month"] = 3.0
    holder["offspring"] = [{"name": "孙甲", "relation": "皇孙", "alive": True, "age": 1.0}]
    s = serialize_offspring_holder(holder)
    assert s["is_pregnant"] is True
    assert s["pregnancy_month"] == 3.0
    assert len(s["offspring"]) == 1
    assert "fertility" in s and "conceive_boost" in s and "postpartum_cooldown" in s
    print(f"  ✓ 序列化字段齐全：offspring={len(s['offspring'])} pregnant={s['is_pregnant']} month={s['pregnancy_month']}")
    return True


# ---------- 测试 5：产后休养期不可连续怀孕 ----------
def test_postpartum_cooldown():
    print("\n=== 测试 5：产后休养期阻止连续怀孕 ===")
    gs = FakeState()
    holder = make_consort(fertility=99)
    ensure_offspring_fields(holder)
    holder["is_pregnant"] = True
    from unittest.mock import patch as _patch5
    with _patch5('app.random.random', return_value=0.0):
        for _ in range(31):  # 孕满需 30 旬；第 31 旬留 1 旬休养期
            process_offspring_for_holder(gs, holder, "皇子弘", holder["name"], "皇子", True)
    assert len(holder["offspring"]) >= 1
    assert holder["postpartum_cooldown"] >= 1, "分娩后应有休养期"
    cd = holder["postpartum_cooldown"]
    holder["is_pregnant"] = False
    random.seed(1)
    for _ in range(cd):
        process_offspring_for_holder(gs, holder, "皇子弘", holder["name"], "皇子", True)
    assert not holder["is_pregnant"], "休养期内不应受孕"
    print(f"  ✓ 产后休养 {cd} 旬内未受孕")
    return True


# ---------- 测试 6：催生 API（Flask 测试客户端）----------
def test_urge_api():
    print("\n=== 测试 6：/api/progeny/urge 催生 API ===")
    appmod.app.config['TESTING'] = True
    client = appmod.app.test_client()
    pid = None  # /api/start 自行生成 player_id
    try:
        p = os.path.join(appmod.SAVE_DIR, f"{pid}_default.json")
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass

    resp = client.post('/api/start', json={
        "player_id": pid, "name": "测试妃", "age": 18,
        "appearance": 80, "talent": 70, "personality": "温婉",
        "background": "小家碧玉",
    })
    data = resp.get_json()
    assert data and data.get("player_id"), f"启动失败：{data}"
    pid = data["player_id"]
    gs = appmod.sessions.get(pid)
    assert gs is not None, "会话未建立"

    prince = make_prince(uid="p_urge", name="皇子弘")
    gs.children.append(prince)
    gs.silver = 500
    gs.remaining_actions = 3

    resp = client.post('/api/progeny/urge', json={
        "player_id": pid, "scope": "prince", "child_uid": "p_urge",
    })
    res = resp.get_json()
    assert res and res.get("success"), f"催生失败：{res}"
    assert res["silver"] == 500 - PROGENY_URGE_COST, "银两应扣除"
    consort = prince["consort"]
    assert consort.get("conceive_boost") == 1, "conceive_boost 应置 1"
    print(f"  ✓ 催生成功：{res['message']}")
    print(f"  ✓ 银两 {500} → {res['silver']}（-{PROGENY_URGE_COST}）")
    print(f"  ✓ conceive_boost={consort['conceive_boost']} urged={consort.get('urged_this_period')}")

    resp2 = client.post('/api/progeny/urge', json={
        "player_id": pid, "scope": "prince", "child_uid": "p_urge",
    })
    res2 = resp2.get_json()
    assert not res2.get("success"), "本旬重复催生应被拒"
    print(f"  ✓ 本旬重复催生被拒：{res2.get('error')}")

    consort["conceive_boost"] = 0
    consort["urged_this_period"] = False
    process_offspring_for_holder(gs, consort, "皇子弘", consort["name"], "皇子", True)
    assert consort["conceive_boost"] == 0, "转旬后催生加成应清零"
    print("  ✓ 转旬后催生加成清零")
    return True


def main():
    tests = [
        test_pregnancy_to_birth,
        test_urge_boost,
        test_princess_grandchild,
        test_serialize,
        test_postpartum_cooldown,
        test_urge_api,
    ]
    passed = 0
    for t in tests:
        try:
            if t():
                passed += 1
        except AssertionError as e:
            print(f"  ✗ 失败：{e}")
        except Exception as e:
            import traceback
            print(f"  ✗ 异常：{e}")
            traceback.print_exc()
    print(f"\n========== 结果：{passed}/{len(tests)} 通过 ==========")
    return 0 if passed == len(tests) else 1


# ---------- 测试 2：催生加成受孕概率 ----------
def test_urge_boost():
    print("\n=== 测试 2：催生加成提升受孕概率 ===")
    base_chance = 0.10 * (0.6 + 50 / 200.0)
    urged_chance = base_chance + PROGENY_URGE_BOOST
    assert urged_chance > base_chance
    print(f"  ✓ 基础受孕率 {base_chance:.3f} → 催生后 {urged_chance:.3f}（+{PROGENY_URGE_BOOST}）")
    random.seed(42)
    n = 2000
    base_hits = sum(1 for _ in range(n) if random.random() < base_chance)
    urged_hits = sum(1 for _ in range(n) if random.random() < urged_chance)
    print(f"  ✓ {n} 次抽样：对照组 {base_hits} 孕 / 催生组 {urged_hits} 孕")
    assert urged_hits > base_hits, "催生组受孕次数应多于对照组"
    return True


if __name__ == "__main__":
    sys.exit(main())