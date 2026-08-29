# endings.py
"""结局系统（失败向）。

集中管理终局判定、结局文案与一生回顾。

当前实现的都是「失败 / 迟暮」类结局：失宠幽闭、身死、年老无依。
登顶类正统结局（皇后善终、母凭子贵、太后线）留待后续扩展，
扩展时把新条目加入 ENDINGS 并在 evaluate_period_endings 中补判定即可。
"""
import random

from models import RANK_POWER, get_rank_power
from heir_content import HEIR_ABSURD_ENDINGS

# ---- 触发阈值 ----
NEGLECT_FAVOR_THRESHOLD = 10   # 宠爱低于此值算失宠
NEGLECT_LIMIT = 6              # 连续失宠旬数达到此值被打入冷宫
NEGLECT_WARN_AT = 3            # 连续失宠旬数达到此值开始预警
SCANDAL_DEATH_LIMIT = 5        # 丑闻累积达到此值被赐死
SCANDAL_WARN_AT = 3
HEALTH_DEATH_AT = 0            # 健康归零必死
HEALTH_CRITICAL_AT = 5         # 健康濒危，每旬有概率病逝
HEALTH_CRITICAL_CHANCE = 0.30
HEALTH_WARN_AT = 15
AGE_TWILIGHT = 60              # 迟暮之年
TWILIGHT_MAX_POWER = RANK_POWER["嫔"]  # 低于嫔位的迟暮者结局
AGE_WARN_AT = 55

ENDING_CATEGORY_FALL = "失势"
ENDING_CATEGORY_DEATH = "身死"
ENDING_CATEGORY_TWILIGHT = "迟暮"
ENDING_CATEGORY_TRIUMPH = "登顶"

ENDINGS = {
    "母仪天下": {
        "icon": "👑",
        "category": ENDING_CATEGORY_TRIUMPH,
        "headline": "母仪天下，垂范后宫",
        "default_reason": "皇帝驾崩，你的子嗣继位为帝，尊你为太后",
        "narration": (
            "先帝驾崩的哀钟还在梁间回荡，新帝的登基诏书已经颁行天下。"
            "你换上明黄的太后朝服，在百官山呼中一步步走向御座之侧。"
            "那个曾经在御花园里追风筝的孩子，如今端坐在龙椅上。"
            "他看向你的目光，和当年一模一样。"
        ),
        "epitaph": "从深宫妃嫔到一国太后，这一路，你走得比谁都远。",
    },
    "冷宫幽闭": {
        "icon": "🏚️",
        "category": ENDING_CATEGORY_FALL,
        "headline": "圣心已弃，永巷无期",
        "default_reason": "圣宠断绝多时，终被移居冷宫",
        "narration": (
            "宫门在身后合上，铜锁落下的声响格外清楚。"
            "从此再无人来传膳、请安、通报圣驾，只有檐下的雨声一年一年地响。"
            "你曾在御前跳过的那支舞，如今连自己都记不清了。"
        ),
        "epitaph": "深宫一入，此生再无春秋。",
    },
    "狸猫之祸": {
        "icon": "🕯️",
        "category": ENDING_CATEGORY_DEATH,
        "headline": "换子的真相，性命的代价",
        "default_reason": "狸猫换子事败，钦命赐死",
        "narration": (
            "白绫送进宫来的那日，你出奇地平静。"
            "那个孩子被人抱走时哭得撕心裂肺，他不会记得，"
            "曾经有个女人用性命换过他一条锦绣前程。"
            "三尺白绫，两世为人，一局输尽的豪赌。"
        ),
        "epitaph": "以命为注，赌输了这一局的，从来不止你一个。",
    },
    "废为庶人": {
        "icon": "🚪",
        "category": ENDING_CATEGORY_FALL,
        "headline": "褪去钗环，永出宫门",
        "default_reason": "罪己陈情，废为庶人，逐出宫外",
        "narration": (
            "你摘下所有钗环，最后一眼望向那座困了你半生的宫城。"
            "孩子被宗人府的人抱走了，啼哭声越来越远。"
            "宫门外天高地阔，从此你只是个无名无姓的庶人——"
            "但你还活着，这已是你在那场豪赌里能赢回的全部。"
        ),
        "epitaph": "一步踏错半生局，出门已是自由身。",
    },
    "狸猫天子": {
        "icon": "👑",
        "category": ENDING_CATEGORY_TRIUMPH,
        "headline": "龙椅之上，无人知晓",
        "default_reason": "狸猫换子，孩子登基为帝而真相从未揭开",
        "narration": (
            "新帝登基，百官朝贺。你站在帘后，看着龙椅上那个你亲手换来的孩子。"
            "他叫你母后。这江山，是你的。无人知道真相——"
            "除了一张泛黄的太医手记，藏在某个再也不会有人翻开的角落里。"
        ),
        "epitaph": "史上只会写：帝幼敏慧，母孝慈，天下大治。",
    },
    "药石无医": {
        "icon": "🕯️",
        "category": ENDING_CATEGORY_DEATH,
        "headline": "沉疾难起，薨于寝宫",
        "default_reason": "久病不起，太医束手",
        "narration": (
            "汤药一碗一碗地端进来，又一碗一碗地凉透。"
            "太医院换了三批人，跪在帘外的话越来越轻。"
            "最后那日窗纸透进一线薄光，你想抬手，却连帐子都没能碰到。"
        ),
        "epitaph": "红颜未老恩先断，一病竟成千古。",
    },
    "白绫赐死": {
        "icon": "⚪",
        "category": ENDING_CATEGORY_DEATH,
        "headline": "罪证俱在，赐白绫自尽",
        "default_reason": "宫中丑闻累积，终究瞒不过圣听",
        "narration": (
            "内侍捧着托盘进来，白绫叠得整齐，连一句多余的话都没有。"
            "你做过的事一件一件被念出来，桩桩有据。"
            "殿外守着的人不看你，只看着地面——他们都知道该等什么。"
        ),
        "epitaph": "机谋一世，反算了自身。",
    },
    "血溅椒房": {
        "icon": "🩸",
        "category": ENDING_CATEGORY_DEATH,
        "headline": "产厄难过，力竭而亡",
        "default_reason": "生产时血流不止，终未熬过这一关",
        "narration": (
            "疼了整整一昼夜，稳婆的声音一次比一次急。"
            "你听见有人喊「见血了」，又听见有人跪下去求皇上恩典。"
            "意识散开之前，你只想再看一眼那个哭声很轻的孩子。"
        ),
        "epitaph": "以命换命，母子只见一面。",
    },
    "鹤顶红": {
        "icon": "🍷",
        "category": ENDING_CATEGORY_DEATH,
        "headline": "杯中有毒，暴毙宫中",
        "default_reason": "毒计防不胜防，中毒不治",
        "narration": (
            "那杯茶是照例呈上来的，温度、颜色、气味都对。"
            "喉间的甜味泛起时你就明白了，可宫人已经退得一个不剩。"
            "你想喊一声，喊出来的只是自己的名字。"
        ),
        "epitaph": "算尽旁人，独漏了这一杯。",
    },
    "迟暮宫墙": {
        "icon": "🍂",
        "category": ENDING_CATEGORY_TWILIGHT,
        "headline": "华年尽负，老于宫墙",
        "default_reason": "年华老去，位份未显，终老于深宫",
        "narration": (
            "又是一年选秀，新人从长街那头进来，衣裳鲜亮，笑声清脆。"
            "有人低声问「那位是哪宫的」，无人答得上来。"
            "你坐在檐下晒药，忽然想起自己入宫那年，也是这样的天气。"
        ),
        "epitaph": "一生守着一堵墙，墙外不曾有人来。",
    },
}

# ---- 太子登基后的「不正经」结局（素材见 heir_content.HEIR_ABSURD_ENDINGS） ----
# 这些结局仍属登顶线：你确实成了太后，只是你养出来的皇帝不太正经。
for _key, _cfg in HEIR_ABSURD_ENDINGS.items():
    ENDINGS[_key] = dict(_cfg, category=ENDING_CATEGORY_TRIUMPH)
del _key, _cfg


# ---- 不正经结局的触发阈值 ----
ABSURD_BANQUET_MERIT = -30      # 贤明值低于此值且沉溺享乐 → 昏君传
ABSURD_INCOGNITO_COUNT = 5      # 微服私访次数达此值 → 隐士皇帝
ABSURD_COOKING_COUNT = 3        # 下厨/膳事次数达此值 → 厨神皇帝
ABSURD_PET_COUNT = 3            # 养兽次数达此值 → 驯兽师皇帝


def resolve_heir_succession_ending(game_state):
    """太子登基时决定落哪一个结局。

    返回 (ending_key, reason)。默认「母仪天下」；
    若太子的成长轨迹已经跑偏（特质 / 计数器 / 贤明值），改判 4 个不正经结局之一。
    判定按「跑偏程度」排序：兽 > 厨 > 隐 > 昏，同时满足时取最先命中的一条。
    """
    hs = getattr(game_state, "heir_status", None) or {}
    traits = hs.get("heir_traits") or []
    counters = hs.get("heir_counters") or {}
    try:
        merit = int(hs.get("regency_merit", 0) or 0)
    except (TypeError, ValueError):
        merit = 0

    def cnt(key):
        try:
            return int(counters.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    heir_name = hs.get("heir_name") or "太子"

    # ---- 1. 驯兽师皇帝：痴于禽兽 ----
    if "爱兽" in traits or cnt("pets") >= ABSURD_PET_COUNT:
        return "驯兽师皇帝", f"{heir_name}登基后广辟兽苑，朝臣入见须先过虎鹰之侧"
    # ---- 2. 厨神皇帝：耽于庖厨 ----
    if "庖厨" in traits or cnt("cooking") >= ABSURD_COOKING_COUNT:
        return "厨神皇帝", f"{heir_name}登基后亲执勺于御膳房，朝会常不及半个时辰"
    # ---- 3. 隐士皇帝：恋慕市井 ----
    if "市井" in traits or cnt("incognito") >= ABSURD_INCOGNITO_COUNT:
        return "隐士皇帝", f"{heir_name}登基未及三年，挂冠而去，只留下一张字条"
    # ---- 4. 昏君传：荒政享乐 ----
    if merit <= ABSURD_BANQUET_MERIT or "昏聩" in traits or "暴虐" in traits:
        return "昏君传", f"{heir_name}登基后沉溺声乐，奏本一日堆过一日，无人上朝"

    return "母仪天下", ""



# ============================================================
#  状态兼容
# ============================================================
def ensure_ending_fields(game_state):
    """旧存档缺字段时补默认值。所有结局相关读写都先走这里。"""
    if not isinstance(getattr(game_state, "ending", None), dict):
        game_state.ending = None
    if not isinstance(getattr(game_state, "neglect_periods", None), int):
        game_state.neglect_periods = 0
    return game_state


def is_game_over(game_state):
    ensure_ending_fields(game_state)
    return bool(game_state.ending)


def ending_payload(game_state):
    """给前端的结局数据，未结束时返回 None。"""
    ensure_ending_fields(game_state)
    return game_state.ending


# ============================================================
#  结局落定
# ============================================================
def trigger_ending(game_state, key, reason="", extra=None):
    """判定结局。已结束或 key 未知则返回 None。"""
    ensure_ending_fields(game_state)
    if game_state.ending:
        return None
    meta = ENDINGS.get(key)
    if not meta:
        return None

    ending = {
        "key": key,
        "icon": meta["icon"],
        "category": meta["category"],
        "headline": meta["headline"],
        "reason": reason or meta["default_reason"],
        "narration": meta["narration"],
        "epitaph": meta["epitaph"],
        "is_death": meta["category"] == ENDING_CATEGORY_DEATH,
        "calendar": game_state.get_calendar_str(),
        "year": game_state.year,
        "age": getattr(game_state, "age", 16),
        "summary": build_life_summary(game_state),
    }
    if extra:
        ending.update(extra)

    game_state.ending = ending
    game_state.ending_unlocked = key
    game_state.remaining_actions = 0
    game_state.add_memory(f"{meta['icon']} 【{key}】{ending['reason']}")
    return ending


# ============================================================
#  一生回顾
# ============================================================
def build_life_summary(game_state):
    """聚合已有状态，生成一生回顾。纯读取，不改状态。"""
    attrs = getattr(game_state, "attributes", {}) or {}
    npcs = getattr(game_state, "npcs", {}) or {}
    children = getattr(game_state, "children", []) or []

    alive_children = [c for c in children if c.get("alive", True)]
    princes = [c for c in alive_children if c.get("gender") == "皇子"]
    princesses = [c for c in alive_children if c.get("gender") == "公主"]

    killed_by_player = []
    for name, npc in npcs.items():
        if npc.get("alive", True):
            continue
        if npc.get("death_killer") == getattr(game_state, "name", None):
            killed_by_player.append({"name": name, "cause": npc.get("death_cause", "不明")})

    rivalries = getattr(game_state, "rivalries", {}) or {}
    alliances = getattr(game_state, "alliances", {}) or {}
    intrigue = getattr(game_state, "intrigue", {}) or {}

    return {
        "name": getattr(game_state, "name", "未命名"),
        "final_rank": game_state.get_display_rank(),
        "age": getattr(game_state, "age", 16),
        "years_in_palace": max(1, game_state.year),
        "family_background": getattr(game_state, "family_background", "未知"),
        "silver": getattr(game_state, "silver", 0),
        "favor": attrs.get("宠爱", 0),
        "prestige": attrs.get("威望", 0),
        "health": attrs.get("健康", 0),
        "scheme": attrs.get("心计", 0),
        "children_total": len(alive_children),
        "princes": len(princes),
        "princesses": len(princesses),
        "child_names": [c.get("name") for c in alive_children if c.get("name")],
        "rival_count": len([v for v in rivalries.values() if v > 0]),
        "ally_count": len([v for v in alliances.values() if v > 0]),
        "killed_count": len(killed_by_player),
        "killed_list": killed_by_player,
        "dirt_count": len(intrigue.get("dirt", {}) or {}),
        "scandal_strikes": getattr(game_state, "scandal_strikes", 0),
        "memories": list(getattr(game_state, "important_memories", []) or [])[-8:],
    }


# ============================================================
#  转旬判定
# ============================================================
def _update_neglect(game_state):
    """维护连续失宠旬数，返回当前值。"""
    favor = (getattr(game_state, "attributes", {}) or {}).get("宠爱", 0)
    if favor < NEGLECT_FAVOR_THRESHOLD:
        game_state.neglect_periods = getattr(game_state, "neglect_periods", 0) + 1
    else:
        game_state.neglect_periods = 0
    return game_state.neglect_periods


def evaluate_period_endings(game_state):
    """转旬时的终局与预警判定。

    返回 (ending, warnings)：ending 为结局字典或 None，warnings 为提示文案列表。
    判定顺序按「不可逆程度」排列，死亡优先于失势。
    """
    ensure_ending_fields(game_state)
    if game_state.ending:
        return game_state.ending, []

    attrs = getattr(game_state, "attributes", {}) or {}
    health = attrs.get("健康", 60)
    strikes = getattr(game_state, "scandal_strikes", 0)
    age = getattr(game_state, "age", 16)
    neglect = _update_neglect(game_state)
    warnings = []

    # ---- 1. 健康崩溃 ----
    if health <= HEALTH_DEATH_AT:
        return trigger_ending(game_state, "药石无医", "健康彻底崩溃，缠绵病榻再无起色"), warnings
    if health <= HEALTH_CRITICAL_AT and random.random() < HEALTH_CRITICAL_CHANCE:
        return trigger_ending(game_state, "药石无医", f"沉疾日久（健康{health}），终究没能熬过这一旬"), warnings

    # ---- 2. 丑闻累积 ----
    if strikes >= SCANDAL_DEATH_LIMIT:
        return trigger_ending(game_state, "白绫赐死", f"劣迹累积{strikes}桩，御前再无转圜之地"), warnings

    # ---- 3. 长期失宠 ----
    if neglect >= NEGLECT_LIMIT:
        return trigger_ending(game_state, "冷宫幽闭", f"连续{neglect}旬圣宠断绝，终被移入冷宫"), warnings

    # ---- 4. 迟暮无依 ----
    if age >= AGE_TWILIGHT and get_rank_power(game_state.rank.name, game_state.nobletitle) < TWILIGHT_MAX_POWER:
        return trigger_ending(
            game_state, "迟暮宫墙",
            f"年已{age}，位仅「{game_state.get_display_rank()}」，此生再无起复之望",
        ), warnings

    # ---- 预警（未触发结局时才提示）----
    if health <= HEALTH_WARN_AT:
        warnings.append(f"⚠️ 你形容枯槁，太医私下摇头（健康{health}），若再不休养恐有性命之忧")
    if strikes >= SCANDAL_WARN_AT:
        warnings.append(f"⚠️ 你身上已积下{strikes}桩劣迹，只需再有一次落实，便是白绫加身之祸")
    if neglect >= NEGLECT_WARN_AT:
        warnings.append(f"⚠️ 圣驾已连续{neglect}旬未曾踏入你的殿门，宫人私议你将被移居冷宫")
    if age >= AGE_WARN_AT and get_rank_power(game_state.rank.name, game_state.nobletitle) < TWILIGHT_MAX_POWER:
        warnings.append(f"⚠️ 你已{age}岁，位份仍低，再无所出便只能老死宫墙之内")

    return None, warnings


def check_player_childbirth_death(game_state, survived_child=True):
    """玩家生产时的死亡判定，返回结局或 None。

    与 palace_extra.try_childbirth_death 同一套风险口径，
    但玩家死亡意味着终局，所以走结局系统而非 kill_consort。
    """
    ensure_ending_fields(game_state)
    if game_state.ending:
        return None
    health = (getattr(game_state, "attributes", {}) or {}).get("健康", 50)
    risk = 0.04 + max(0, (40 - health) / 200)
    if not survived_child:
        risk += 0.15
    if random.random() >= risk:
        return None
    reason = "诞下皇嗣后血流不止，力竭而亡" if survived_child else "小产血崩，未能挽回"
    return trigger_ending(game_state, "血溅椒房", reason)


def check_player_poison_death(game_state, poisoner=None):
    """玩家被下毒时的死亡判定，返回结局或 None。"""
    ensure_ending_fields(game_state)
    if game_state.ending:
        return None
    health = (getattr(game_state, "attributes", {}) or {}).get("健康", 50)
    luck = (getattr(game_state, "attributes", {}) or {}).get("福运", 30)
    if health > 20:
        return None
    chance = 0.55 - luck / 300
    if random.random() >= max(0.15, chance):
        return None
    who = poisoner or "不知何人"
    return trigger_ending(game_state, "鹤顶红", f"{who}所下之毒终究要了你的命", extra={"killer": poisoner})
