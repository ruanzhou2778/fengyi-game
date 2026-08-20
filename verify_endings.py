# verify_endings.py
"""结局系统回归脚本。

不依赖 HTTP 服务，直接构造 GameState 走判定逻辑，覆盖：
1. 六种失败结局的触发条件
2. 预警文案在未触发时出现
3. 结局落定后的幂等性（不会被二次覆盖）
4. 一生回顾字段完整性
5. 存档往返（to_dict / from_save_data）保留结局字段
6. 旧存档缺字段时的兼容

用法：python verify_endings.py
"""
import sys
import random

from models import GameState, Rank
from endings import (
    ENDINGS, ensure_ending_fields, is_game_over, trigger_ending,
    evaluate_period_endings, build_life_summary,
    check_player_childbirth_death, check_player_poison_death,
    NEGLECT_LIMIT, SCANDAL_DEATH_LIMIT, AGE_TWILIGHT,
    ENDING_CATEGORY_DEATH, ENDING_CATEGORY_FALL, ENDING_CATEGORY_TWILIGHT,
)

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label} {detail}")


def new_state(rank=Rank.嫔, **attrs):
    gs = GameState("verify-ending", rank)
    gs.name = "林婉儿"
    gs.npcs = {}
    for k, v in attrs.items():
        gs.attributes[k] = v
    ensure_ending_fields(gs)
    return gs


def section(title):
    print(f"\n=== {title} ===")


# ------------------------------------------------------------
section("1. 结局配置表")
# ------------------------------------------------------------
expected_keys = {"冷宫幽闭", "药石无医", "白绫赐死", "血溅椒房", "鹤顶红", "迟暮宫墙"}
check("六种失败结局齐备", set(ENDINGS) == expected_keys, f"实际 {set(ENDINGS)}")
for key, meta in ENDINGS.items():
    check(f"{key} 字段完整",
          all(meta.get(f) for f in ("icon", "category", "headline", "default_reason", "narration", "epitaph")))
categories = {m["category"] for m in ENDINGS.values()}
check("覆盖三类结局", categories == {ENDING_CATEGORY_DEATH, ENDING_CATEGORY_FALL, ENDING_CATEGORY_TWILIGHT},
      f"实际 {categories}")

# ------------------------------------------------------------
section("2. 健康归零 → 药石无医")
# ------------------------------------------------------------
gs = new_state(健康=0, 宠爱=80)
ending, warns = evaluate_period_endings(gs)
check("触发结局", ending is not None)
check("结局为药石无医", ending and ending["key"] == "药石无医", ending and ending["key"])
check("标记为死亡结局", ending and ending["is_death"] is True)
check("状态已锁定", is_game_over(gs))
check("行动点清零", gs.remaining_actions == 0, gs.remaining_actions)
check("ending_unlocked 已写入", gs.ending_unlocked == "药石无医", gs.ending_unlocked)

# ------------------------------------------------------------
section("3. 丑闻累积 → 白绫赐死")
# ------------------------------------------------------------
gs = new_state(健康=70, 宠爱=60)
gs.scandal_strikes = SCANDAL_DEATH_LIMIT
ending, warns = evaluate_period_endings(gs)
check("触发结局", ending is not None)
check("结局为白绫赐死", ending and ending["key"] == "白绫赐死", ending and ending["key"])
check("原因含丑闻桩数", ending and str(SCANDAL_DEATH_LIMIT) in ending["reason"], ending and ending["reason"])

# ------------------------------------------------------------
section("4. 长期失宠 → 冷宫幽闭")
# ------------------------------------------------------------
gs = new_state(健康=70, 宠爱=5)
triggered = None
for i in range(NEGLECT_LIMIT + 2):
    ending, warns = evaluate_period_endings(gs)
    if ending:
        triggered = (i + 1, ending)
        break
check("最终触发结局", triggered is not None)
check("结局为冷宫幽闭", triggered and triggered[1]["key"] == "冷宫幽闭", triggered and triggered[1]["key"])
check(f"第 {NEGLECT_LIMIT} 旬触发", triggered and triggered[0] == NEGLECT_LIMIT, triggered and triggered[0])
check("归类为失势", triggered and triggered[1]["category"] == ENDING_CATEGORY_FALL)

# 宠爱回升可重置计数
gs2 = new_state(健康=70, 宠爱=5)
evaluate_period_endings(gs2)
evaluate_period_endings(gs2)
check("失宠计数已累积", gs2.neglect_periods == 2, gs2.neglect_periods)
gs2.attributes["宠爱"] = 50
evaluate_period_endings(gs2)
check("宠爱回升后计数归零", gs2.neglect_periods == 0, gs2.neglect_periods)

# ------------------------------------------------------------
section("5. 年老位低 → 迟暮宫墙")
# ------------------------------------------------------------
gs = new_state(Rank.常在, 健康=70, 宠爱=50)
gs.age = AGE_TWILIGHT
ending, warns = evaluate_period_endings(gs)
check("触发结局", ending is not None)
check("结局为迟暮宫墙", ending and ending["key"] == "迟暮宫墙", ending and ending["key"])
check("非死亡结局", ending and ending["is_death"] is False)

# 高位份不触发迟暮
gs = new_state(Rank.贵妃, 健康=70, 宠爱=50)
gs.age = AGE_TWILIGHT + 5
ending, warns = evaluate_period_endings(gs)
check("贵妃高龄不触发迟暮结局", ending is None, ending and ending["key"])

# ------------------------------------------------------------
section("6. 预警文案")
# ------------------------------------------------------------
gs = new_state(健康=12, 宠爱=60)
gs.scandal_strikes = 3
ending, warns = evaluate_period_endings(gs)
check("未触发结局", ending is None, ending and ending["key"])
check("产生预警", len(warns) >= 2, warns)
check("含健康预警", any("性命之忧" in w for w in warns), warns)
check("含丑闻预警", any("白绫" in w for w in warns), warns)

gs = new_state(健康=90, 宠爱=90)
ending, warns = evaluate_period_endings(gs)
check("状态良好时无预警", ending is None and not warns, warns)

# ------------------------------------------------------------
section("7. 生产致死 / 中毒致死")
# ------------------------------------------------------------
random.seed(20250820)
birth_ending = None
for _ in range(80):
    g = new_state(健康=5, 宠爱=60)
    birth_ending = check_player_childbirth_death(g, survived_child=False)
    if birth_ending:
        break
check("难产可致结局", birth_ending is not None)
check("结局为血溅椒房", birth_ending and birth_ending["key"] == "血溅椒房", birth_ending and birth_ending["key"])

poison_ending = None
for _ in range(80):
    g = new_state(健康=10, 宠爱=60, 福运=10)
    poison_ending = check_player_poison_death(g, "华妃")
    if poison_ending:
        break
check("中毒可致结局", poison_ending is not None)
check("结局为鹤顶红", poison_ending and poison_ending["key"] == "鹤顶红", poison_ending and poison_ending["key"])
check("记录下毒者", poison_ending and poison_ending.get("killer") == "华妃", poison_ending and poison_ending.get("killer"))

g = new_state(健康=80, 宠爱=60)
check("健康充足时中毒不致死", check_player_poison_death(g, "华妃") is None)

# ------------------------------------------------------------
section("8. 结局幂等")
# ------------------------------------------------------------
gs = new_state(健康=70, 宠爱=60)
first = trigger_ending(gs, "白绫赐死", "测试原因")
second = trigger_ending(gs, "冷宫幽闭", "不应生效")
check("首次触发成功", first is not None)
check("二次触发被拒", second is None)
check("结局未被覆盖", gs.ending["key"] == "白绫赐死", gs.ending["key"])
ending3, warns3 = evaluate_period_endings(gs)
check("已终局时转旬判定返回原结局", ending3 is gs.ending)
check("已终局时不再产生预警", warns3 == [], warns3)
check("未知 key 返回 None", trigger_ending(new_state(), "不存在的结局") is None)

# ------------------------------------------------------------
section("9. 一生回顾")
# ------------------------------------------------------------
gs = new_state(Rank.妃, 健康=60, 宠爱=88, 威望=120, 心计=77)
gs.nobletitle = "贤"
gs.age = 32
gs.year = 9
gs.silver = 640
gs.children = [
    {"name": "承祐", "gender": "皇子", "alive": True},
    {"name": "明玥", "gender": "公主", "alive": True},
    {"name": "早殇", "gender": "皇子", "alive": False},
]
gs.npcs = {
    "华妃": {"alive": False, "death_cause": "中毒", "death_killer": "林婉儿"},
    "沈眉庄": {"alive": False, "death_cause": "病逝"},
    "安陵容": {"alive": True},
}
gs.rivalries = {"安陵容": 40, "旧敌": 0}
gs.alliances = {"沈眉庄": 60}
gs.intrigue = {"heat": 30, "rumors": [], "dirt": {"安陵容": ["私通"]}, "last_action": None}
gs.important_memories = [f"[第{i}天] 事件{i}" for i in range(1, 13)]

s = build_life_summary(gs)
check("最终位份含封号", s["final_rank"] == "贤妃", s["final_rank"])
check("在宫年数", s["years_in_palace"] == 9, s["years_in_palace"])
check("存活子嗣计数", s["children_total"] == 2, s["children_total"])
check("皇子数", s["princes"] == 1, s["princes"])
check("公主数", s["princesses"] == 1, s["princesses"])
check("子嗣名单不含亡故", "早殇" not in s["child_names"], s["child_names"])
check("手上人命只算自己所杀", s["killed_count"] == 1, s["killed_count"])
check("人命清单含死因", s["killed_list"][0]["cause"] == "中毒", s["killed_list"])
check("仇敌只算正值", s["rival_count"] == 1, s["rival_count"])
check("盟友计数", s["ally_count"] == 1, s["ally_count"])
check("把柄计数", s["dirt_count"] == 1, s["dirt_count"])
check("记事截断为 8 条", len(s["memories"]) == 8, len(s["memories"]))
check("属性快照", (s["favor"], s["prestige"], s["scheme"]) == (88, 120, 77),
      (s["favor"], s["prestige"], s["scheme"]))

ending = trigger_ending(gs, "冷宫幽闭")
check("结局内嵌一生回顾", isinstance(ending.get("summary"), dict))
check("回顾位份与结局一致", ending["summary"]["final_rank"] == "贤妃")
check("结局记入重要记忆", any("冷宫幽闭" in m for m in gs.important_memories))

# ------------------------------------------------------------
section("10. 存档往返")
# ------------------------------------------------------------
gs = new_state(健康=70, 宠爱=4)
evaluate_period_endings(gs)   # neglect_periods -> 1
evaluate_period_endings(gs)   # neglect_periods -> 2
trigger_ending(gs, "白绫赐死", "存档测试")
data = gs.to_save_data()
saved = data["game_state"]
check("to_dict 含 ending", saved.get("ending") is not None)
check("to_dict 含 neglect_periods", saved.get("neglect_periods") == 2, saved.get("neglect_periods"))
check("to_dict 含 ending_unlocked", saved.get("ending_unlocked") == "白绫赐死", saved.get("ending_unlocked"))

restored = GameState.from_save_data(data)
check("读档后仍为终局", is_game_over(restored))
check("读档后结局 key 一致", restored.ending["key"] == "白绫赐死", restored.ending["key"])
check("读档后原因一致", restored.ending["reason"] == "存档测试", restored.ending["reason"])
check("读档后失宠计数一致", restored.neglect_periods == 2, restored.neglect_periods)
check("读档后回顾仍在", isinstance(restored.ending.get("summary"), dict))
check("读档后不会二次触发新结局", evaluate_period_endings(restored)[0]["key"] == "白绫赐死")

# ------------------------------------------------------------
section("11. 旧存档兼容")
# ------------------------------------------------------------
legacy = gs.to_save_data()
legacy["game_state"].pop("ending", None)
legacy["game_state"].pop("ending_unlocked", None)
legacy["game_state"].pop("neglect_periods", None)
old = GameState.from_save_data(legacy)
ensure_ending_fields(old)
check("旧存档 ending 为 None", old.ending is None)
check("旧存档失宠计数为 0", old.neglect_periods == 0, old.neglect_periods)
check("旧存档未终局", not is_game_over(old))

legacy["game_state"]["ending"] = "不是字典"
bad = GameState.from_save_data(legacy)
ensure_ending_fields(bad)
check("非法 ending 被丢弃", bad.ending is None, bad.ending)

legacy["game_state"]["ending"] = None
legacy["game_state"]["neglect_periods"] = "abc"
bad2 = GameState.from_save_data(legacy)
ensure_ending_fields(bad2)
check("非法 neglect_periods 归零", bad2.neglect_periods == 0, bad2.neglect_periods)

# ------------------------------------------------------------
section("12. HTTP 层：终局锁死与存读档")
# ------------------------------------------------------------
import json
import os

import app as srv

CLIENT_ID = "verify-endings-client"


def _post(c, path, payload):
    return c.post(path, data=json.dumps(payload, ensure_ascii=False),
                  headers={"Content-Type": "application/json", "X-Client-ID": CLIENT_ID})


def _get(c, path):
    return c.get(path, headers={"X-Client-ID": CLIENT_ID})


created_saves = []
random.seed(7)
with srv.app.test_client() as c:
    r = _post(c, "/api/start", {
        "scenario": "才女入宫", "name": "结局验证",
        "attributes": {"心计": 15, "威望": 15},
        "character": {"appearance": "清丽", "talent": "琴艺", "personality": "沉静", "traits": []},
    })
    started = r.get_json() or {}
    pid = started.get("player_id")
    check("开局成功", r.status_code == 200 and bool(pid), r.status_code)

    live = srv.sessions.get(pid)
    check("开局会话存在", live is not None)
    check("开局无结局", live is not None and live.ending is None)

    # /api/ending 未终局时也给实时回顾
    r = _get(c, f"/api/ending?player_id={pid}")
    e = r.get_json() or {}
    check("/api/ending 可用", r.status_code == 200, r.status_code)
    check("未终局 game_over 为 false", e.get("game_over") is False, e.get("game_over"))
    check("未终局仍返回 summary", isinstance(e.get("summary"), dict))
    check("返回结局图鉴 6 条", len(e.get("catalog") or []) == 6, len(e.get("catalog") or []))

    # 手动落定结局，验证行动类路由被锁
    srv.ensure_ending_fields(live)
    forced = trigger_ending(live, "药石无医", "HTTP 验证")
    check("服务端结局落定", forced is not None)

    r = _post(c, "/api/act", {"player_id": pid, "action": "四处看看", "choice": "四处看看"})
    a = r.get_json() or {}
    check("/api/act 返回 409", r.status_code == 409, r.status_code)
    check("/api/act 带 game_over", a.get("game_over") is True, a.get("game_over"))
    check("/api/act 带 ending", (a.get("ending") or {}).get("key") == "药石无医", a.get("ending"))

    r = _post(c, "/api/next_period", {"player_id": pid})
    n = r.get_json() or {}
    check("/api/next_period 被拦截", r.status_code == 409, r.status_code)
    check("/api/next_period 带 ending", (n.get("ending") or {}).get("key") == "药石无医", n.get("ending"))

    r = _get(c, f"/api/state/{pid}")
    s = r.get_json() or {}
    check("/api/state 仍可读", r.status_code == 200, r.status_code)
    check("/api/state 含 game_over", s.get("game_over") is True, s.get("game_over"))
    check("/api/state 含 ending", (s.get("ending") or {}).get("key") == "药石无医", s.get("ending"))

    r = _get(c, f"/api/ending?player_id={pid}")
    e2 = r.get_json() or {}
    check("终局后 /api/ending 返回结局", (e2.get("ending") or {}).get("key") == "药石无医")
    check("终局后 summary 取自结局", e2.get("summary") == forced["summary"])

    # 存档 → 清会话 → 读档，结局不应丢失
    r = _post(c, "/api/save", {"player_id": pid, "slot_name": "ending_check"})
    check("存档成功", r.status_code == 200, r.get_json())
    save_path = os.path.join(srv.SAVE_DIR, f"{pid}_ending_check.json")
    created_saves.append(save_path)
    created_saves.append(os.path.join(srv.SAVE_DIR, f"{pid}_default.json"))
    check("存档文件生成", os.path.exists(save_path), save_path)

    srv.sessions.pop(pid, None)
    r = _post(c, "/api/load", {"player_id": pid, "slot_name": "ending_check"})
    l = r.get_json() or {}
    check("读档成功", r.status_code == 200 and l.get("success"), r.status_code)
    loaded_gs = (l.get("game_state") or {})
    check("读档响应含 ending", (loaded_gs.get("ending") or {}).get("key") == "药石无医", loaded_gs.get("ending"))
    check("读档后会话仍为终局", srv.is_game_over(srv.sessions.get(pid)))

    r = _post(c, "/api/act", {"player_id": pid, "action": "四处看看", "choice": "四处看看"})
    check("读档后行动仍被拦截", r.status_code == 409, r.status_code)

for p in created_saves:
    try:
        if os.path.exists(p):
            os.remove(p)
    except OSError:
        pass
check("测试存档已清理", all(not os.path.exists(p) for p in created_saves))

# ------------------------------------------------------------
print(f"\n结果：{PASS} 通过 / {FAIL} 失败（共 {PASS + FAIL} 项）")
sys.exit(1 if FAIL else 0)
