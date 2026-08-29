# confidant_events.py — 心腹系统随机事件库
# 事件效果仅使用已有系统：忠诚(loyalty) / 威望(prestige) / 把柄(intrigue_dirt) / 背叛清退(betrayal)
import random


def get_confidant_servant(game_state):
    """返回当前心腹宫人对象，无则 None（servants 是列表，不能按名字下标取）。"""
    if not getattr(game_state, "confidant", None):
        return None
    for s in game_state.get_active_servants():
        if s.name == game_state.confidant:
            return s
    return None


def pick_confidant_target(game_state):
    """随机选一位存活妃嫔作为事件目标人物。"""
    targets = [n for n, npc in game_state.npcs.items() if npc.get("alive", True) and n != game_state.name]
    return random.choice(targets) if targets else ""


def _conf_loyalty_in(game_state, lo=None, hi=None):
    cf = get_confidant_servant(game_state)
    if not cf:
        return False
    if lo is not None and cf.loyalty < lo:
        return False
    if hi is not None and cf.loyalty > hi:
        return False
    return True


CONFIDANT_EVENTS = [
    {
        "id": "confidant_intel",
        "name": "心腹密报",
        "trigger": lambda gs: _conf_loyalty_in(gs, lo=70),
        "desc": "你的心腹{name}深夜来报：\"主子，{target}近日频繁出入御花园，似在密会何人。属下已暗中盯梢，可否继续追查？\"",
        "choices": [
            {
                "text": "立即追查",
                "cost": {"actions": 1},
                "effect": lambda gs, name, target: {
                    "narration": f"你命{name}继续追查，三日后{name}带回一条关于{target}的重要把柄。",
                    "intrigue_dirt": {target: 2},
                    "loyalty": {name: 2}
                }
            },
            {
                "text": "暂且观望",
                "effect": lambda gs, name, target: {
                    "narration": f"你让{name}暂且观望，{name}对你的谨慎更为信服。",
                    "loyalty": {name: 2}
                }
            },
            {
                "text": "不必理会",
                "effect": lambda gs, name, target: {
                    "narration": f"你让{name}不必理会此事，{name}应声退下。"
                }
            }
        ]
    },
    {
        "id": "confidant_reward",
        "name": "心腹请赏",
        "trigger": lambda gs: _conf_loyalty_in(gs, hi=50) and gs.silver >= 20,
        "desc": "你的心腹{name}跪地叩首：\"主子，奴婢家中老母病重，急需医药费。若主子肯赏赐，奴婢愿肝脑涂地。\"",
        "choices": [
            {
                "text": "赏银 50 两",
                "cost": {"silver": 50},
                "effect": lambda gs, name, target: {
                    "narration": f"你赏{name}银两五十，{name}感激涕零，忠诚大增。",
                    "loyalty": {name: 15}
                }
            },
            {
                "text": "赏银 20 两",
                "cost": {"silver": 20},
                "effect": lambda gs, name, target: {
                    "narration": f"你赏{name}银两二十，{name}道谢而去。",
                    "loyalty": {name: 8}
                }
            },
            {
                "text": "拒绝",
                "effect": lambda gs, name, target: {
                    "narration": f"你拒绝了{name}的请求，{name}神色黯然。",
                    "loyalty": {name: -10}
                }
            }
        ]
    },
    {
        "id": "confidant_bribed",
        "name": "心腹被收买",
        "trigger": lambda gs: _conf_loyalty_in(gs, hi=40),
        "desc": "你偶然听闻，{target}近日频繁接触你的心腹{name}，似有收买之意。{name}神色慌张，不敢直视于你。",
        "choices": [
            {
                "text": "当面质问",
                "effect": lambda gs, name, target: _bribed_confront(gs, name, target)
            },
            {
                "text": "暗中试探",
                "cost": {"silver": 30},
                "effect": lambda gs, name, target: {
                    "narration": f"你花银两贿赂其他宫人打探，得知{name}尚存犹豫。你好言抚慰，{name}惭愧之余愈加小心。",
                    "loyalty": {name: 5}
                }
            },
            {
                "text": "视而不见",
                "effect": lambda gs, name, target: {
                    "narration": f"你假装不知，{name}的忠诚进一步下滑。",
                    "loyalty": {name: -5}
                }
            }
        ]
    },
    {
        "id": "confidant_assist",
        "name": "心腹献计",
        "trigger": lambda gs: _conf_loyalty_in(gs, lo=80),
        "desc": "宫斗激烈之时，你的心腹{name}突然献上一计：\"主子，{target}有一把柄在奴婢手中，若此时记下，必是重创其的证据！\"",
        "choices": [
            {
                "text": "记为把柄",
                "effect": lambda gs, name, target: {
                    "narration": f"你采纳{name}的建议，将{target}的错处记入把柄簿，日后揭发必有用处。",
                    "intrigue_dirt": {target: 8}
                }
            },
            {
                "text": "暂且保留",
                "effect": lambda gs, name, target: {
                    "narration": f"你让{name}暂且按住此事，以备不时之需，{name}点头称是。"
                }
            },
            {
                "text": "不予采纳",
                "effect": lambda gs, name, target: {
                    "narration": f"你认为此计不妥，{name}默然退下。"
                }
            }
        ]
    },
    {
        "id": "confidant_clan_plea",
        "name": "心腹求情",
        "trigger": lambda gs: _conf_loyalty_in(gs, lo=70),
        "desc": "你的心腹{name}跪地恳求：\"主子，家父近日被弹劾，恐有性命之忧。若主子肯为家父求情，{name}愿世代为奴，永不背叛。\"",
        "choices": [
            {
                "text": "向皇帝求情",
                "cost": {"actions": 1},
                "effect": lambda gs, name, target: {
                    "narration": f"你向皇帝求情，{name}感激涕零，誓死效忠。但此举损耗了你的威望。",
                    "loyalty": {name: 20},
                    "prestige": -5
                }
            },
            {
                "text": "婉言拒绝",
                "effect": lambda gs, name, target: {
                    "narration": f"你婉言拒绝{name}，{name}神色黯然，忠诚下降。",
                    "loyalty": {name: -10}
                }
            },
            {
                "text": "暗中资助",
                "cost": {"silver": 50},
                "effect": lambda gs, name, target: {
                    "narration": f"你暗中资助{name}家中五十两银子，{name}感激不已。",
                    "loyalty": {name: 10}
                }
            }
        ]
    }
]


def _bribed_confront(game_state, name, target):
    """当面质问：随机一次判定坦白或投奔，叙述与结果保持一致。"""
    if random.random() < 0.5:
        return {
            "narration": f"你当面质问{name}，{name}跪地求饶，坦白并发誓永不背叛。",
            "loyalty": {name: 10}
        }
    return {
        "narration": f"你当面质问{name}，{name}畏罪供认不讳，当夜便投奔{target}去了！",
        "betrayal": True
    }


def get_random_confidant_event(game_state):
    """随机抽取一个符合触发条件的心腹事件。"""
    available = [e for e in CONFIDANT_EVENTS if e["trigger"](game_state)]
    if not available:
        return None
    return random.choice(available)


def trigger_confidant_event(game_state, event_id, choice_index, target=None):
    """触发心腹事件并执行选项效果。"""
    event = next((e for e in CONFIDANT_EVENTS if e["id"] == event_id), None)
    if not event:
        return {"error": "事件不存在"}
    if not isinstance(choice_index, int) or not (0 <= choice_index < len(event["choices"])):
        return {"error": "无效的选项"}
    choice = event["choices"][choice_index]

    name = game_state.confidant
    if not name or not get_confidant_servant(game_state):
        return {"error": "你当前没有心腹"}

    if not target or target == name or target not in game_state.npcs \
            or not game_state.npcs[target].get("alive", True):
        target = pick_confidant_target(game_state) or "某位妃嫔"

    cost = choice.get("cost", {})
    if cost.get("actions", 0) > game_state.remaining_actions:
        return {"error": "行动点不足"}
    if cost.get("silver", 0) > game_state.silver:
        return {"error": "银两不足"}
    game_state.remaining_actions -= cost.get("actions", 0)
    game_state.silver -= cost.get("silver", 0)

    effect = choice["effect"](game_state, name, target)

    cf = get_confidant_servant(game_state)
    if "loyalty" in effect and cf:
        for who, delta in effect["loyalty"].items():
            if who == cf.name:
                cf.loyalty = max(0, min(100, cf.loyalty + delta))

    if "prestige" in effect:
        attr = game_state.attributes.get("威望", 0)
        game_state.attributes["威望"] = max(0, min(game_state.get_attr_max("威望"), attr + effect["prestige"]))

    if "intrigue_dirt" in effect:
        dirt_map = game_state.intrigue.setdefault("dirt", {})
        for who, points in effect["intrigue_dirt"].items():
            payload = dirt_map.setdefault(who, {"points": 0, "age": 0, "label": "私下错处"})
            payload["points"] = int(payload.get("points", 0) or 0) + points

    if effect.get("betrayal") and cf:
        cf.is_active = False
        game_state.confidant = None
        loss = 8
        game_state.attributes["威望"] = max(0, game_state.attributes.get("威望", 0) - loss)
        game_state.add_memory(f"心腹{name}背叛，投奔{target}，威望-{loss}")
        from app import remember_confidant_event
        remember_confidant_event(game_state, f"{name}背叛，投奔{target}，威望-{loss}")

    return {
        "success": True,
        "narration": effect.get("narration", ""),
        "effect": effect
    }
