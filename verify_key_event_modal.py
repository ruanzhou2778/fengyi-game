# -*- coding: utf-8 -*-
"""验证：重要事件串行弹窗（后端分级 key_events + 前端队列结构）。

运行：python verify_key_event_modal.py
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as A
from app import app as flask_app

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


# 1. 分级规则
section("1. 事件分级")
L1 = ["⚔️ 晋王私藏甲胄，事败伏诛！", "👑 新帝登基，尊你为太后",
      "🕯️ 白绫送进宫来", "⛓️ 慈宁宫的门从外面锁上了（幽居）",
      "🔥 复辟兵起，神器倾覆"]
for t in L1:
    got = A.classify_key_events([t])
    ok(f"一级: {t[:12]}", got and got[0]["level"] == 1, got)
L2 = ["📜 晋封为嫔", "👶 你诞下皇子承泰", "🎊 大选放榜，沈玉棠入宫",
      "🏚️ 华妃被贬入冷宫"]
for t in L2:
    got = A.classify_key_events([t])
    ok(f"二级: {t[:12]}", got and got[0]["level"] == 2, got)
# 用引擎真实产出的文案，避免测试自造串与规则错配
L3 = ["⚠️ 心腹忠诚低迷，似被人收买",
      "🏛️ 萧承弘入宫朝见，皇帝赐金千两，宗室与有荣焉",
      "🏛️ 母家请官：兄弟谋一实缺"]
for t in L3:
    got = A.classify_key_events([t])
    ok(f"三级: {t[:12]}", got and got[0]["level"] == 3, got)

# 2. 琐事不弹窗
section("2. 琐事过滤")
trivial = ["📌 御膳房今日份例照旧", "🌿 御花园的花开了", "领取俸禄12银两", "宫中岁月静好"]
got = A.classify_key_events(trivial)
ok("琐事一律不弹窗", got == [], got)

# 3. 排序与上限
section("3. 排序与上限")
mixed = ["⚠️ 有人察觉了", "📜 晋封为妃", "⚔️ 谋逆伏诛", "👶 诞下皇子", "🏵️ 宗室朝见"]
got = A.classify_key_events(mixed)
levels = [e["level"] for e in got]
ok("按级别升序", levels == sorted(levels), levels)
ok("一级最先", got and got[0]["level"] == 1, levels)
many = A.classify_key_events(mixed * 4)
ok(f"上限{A.KEY_EVENT_MAX}条", len(many) <= A.KEY_EVENT_MAX, len(many))
ok("空输入安全", A.classify_key_events([]) == [] and A.classify_key_events(None) == [])
ok("脏数据安全", A.classify_key_events(["", None, "   "]) == [])

# 4. 结构完整
section("4. 结构")
one = A.classify_key_events(["📜 晋封为嫔"])[0]
ok("四字段齐备", set(one) >= {"level", "icon", "title", "text"}, one)
ok("图标与标题非空", bool(one["icon"]) and bool(one["title"]), one)

# 5. API 返回
section("5. 转旬 API")
client = flask_app.test_client()
r = client.post("/api/start", json={"name": "沈妃", "api_base": "", "api_key": "", "api_model": ""})
pid = r.get_json()["player_id"]
r = client.post("/api/next_period", json={"player_id": pid})
d = r.get_json() or {}
ok("转旬 200", r.status_code == 200, r.status_code)
ok("含 key_events", isinstance(d.get("key_events"), list), list(d)[:8])
ok("key_events 结构", all(set(e) >= {"level", "icon", "title", "text"} for e in d["key_events"]), d["key_events"][:2])
ok("仍保留 intelligence_list", isinstance(d.get("intelligence_list"), list))

# 6. 前端串行队列
section("6. 前端队列")
html = io.open("index.html", encoding="utf-8").read()
ok("有队列变量", "_modalQueue" in html and "_modalActive" in html)
ok("有入队函数", "function enqueueModal(" in html and "function enqueueKeyEvents(" in html)
ok("有推进函数", "function _pumpModal(" in html)
ok("closeModal 触发下一层", re.search(r"function closeModal\(\)\{[^}]*_modalQueue\.length", html) is not None)
ok("转旬调用队列", "enqueueKeyEvents(d.key_events)" in html)
ok("选秀事件走队列", "enqueueKeyEvents(_dm)" in html)
ok("显示剩余条数", "还有 ${_modalQueue.length} 条待阅" in html)
# 串行语义：入队时若已有弹窗在显示则不抢占
ok("入队不抢占", "if(!_modalActive)_pumpModal();" in html)

print(f"\n重要事件弹窗验证: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
