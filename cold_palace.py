# cold_palace.py — 冷宫系统引擎（设计稿 v2.0）
# 冷宫是状态而非终点：在押妃嫔的经营/翻盘，玩家身陷冷宫时的生存循环
import random

COLD_LOG_MAX = 20
COLD_INMATE_DECAY_HEALTH = (2, 5)
COLD_INMATE_DECAY_SPIRIT = (3, 8)
PLAYER_DECAY_HEALTH = (2, 5)
PLAYER_DECAY_SPIRIT = (3, 8)

SELF_ACTIONS = {
    "sort_items": {"name": "整理旧物", "cost": {"actions": 1}, "desc": "翻检旧物，寻旧日线索"},
    "befriend": {"name": "结交冷宫中人", "cost": {"actions": 1}, "desc": "冷宫里也有故人"},
    "send_letter": {"name": "暗中传递消息", "cost": {"actions": 1, "silver": 30}, "desc": "精神≥50方可传出"},
    "blood_book": {"name": "写血书自辩", "cost": {"health": 3}, "desc": "若上达天听，翻身+10%"},
    "hunger_strike": {"name": "绝食明志", "cost": {"health": 8}, "desc": "若被知晓，怜悯翻身+20%"},
    "copy_sutra": {"name": "抄写经书", "cost": {"actions": 1}, "desc": "精神+3，可获太后怜悯"},
    "bribe": {"name": "贿赂看守", "cost": {"silver": 20}, "desc": "换取额外便利"},
}

RELEASE_METHODS = {
    "blood": {"name": "递血书鸣冤", "base": 30, "bonus": "favor", "fail": "death"},
    "dowager": {"name": "托太后求情", "base": 40, "bonus": "dowager", "fail": "worse"},
    "secret": {"name": "用秘密换命", "base": 50, "bonus": "secrets", "fail": "worse"},
    "escape": {"name": "趁乱越宫", "base": 15, "bonus": "spirit", "fail": "death"},
    "child": {"name": "子嗣求情", "base": 20, "bonus": "child", "fail": "worse"},
    "family": {"name": "家族营救", "base": 20, "bonus": "family", "fail": "worse"},
}

INTERACT_ACTIONS = {"visit", "give", "plead", "use_secret", "taiyi", "bribe_guard"}


def default_cold_palace():
    return {
        "inmates": {},
        "events": [],
        "environment": {"条件": "恶劣", "看守类型": "严厉", "银两储备": 0},
        "player": None,   # 玩家身陷冷宫时的状态 dict
        "log": [],
    }


def get_cold_palace(game_state):
    cp = getattr(game_state, "cold_palace", None)
    if not isinstance(cp, dict):
        cp = default_cold_palace()
        game_state.cold_palace = cp
    for k, v in default_cold_palace().items():
        cp.setdefault(k, v)
    return cp


def _log(cp, text):
    cp["log"].insert(0, text)
    del cp["log"][COLD_LOG_MAX:]


def _period_stamp(game_state):
    return f"建元{game_state.year}年{game_state.month}月{game_state.get_calendar_str()[-3:]}"


def is_player_imprisoned(game_state):
    cp = get_cold_palace(game_state)
    p = cp.get("player")
    return isinstance(p, dict) and p.get("imprisoned")


def admit_npc(game_state, name, reason):
    """协理裁决/事败：把妃嫔打入冷宫（从名册移除，档案入冷宫）。"""
    cp = get_cold_palace(game_state)
    npc = (game_state.npcs or {}).get(name)
    if not isinstance(npc, dict) or not npc.get("alive", True):
        return None, "名册查无此人"
    if name in cp["inmates"]:
        return None, "她已在冷宫"
    secrets = []
    for t in random.sample([
        "某妃与外臣书信往来", "有人曾假孕争宠", "某宫夜里有不为人知的进出",
        "有人私藏禁物", "一份未焚毁的旧信", "某个孩子身世的隐情",
    ], k=random.randint(1, 3)):
        secrets.append({"内容": t, "可靠性": random.randint(60, 95)})
    inmate = {
        "原身份": npc.get("rank", "妃"),
        "原家族": (npc.get("family_background", "") or "").split("（")[0][:6] or "不详",
        "入住原因": reason,
        "入住旬": f"{game_state.year}-{game_state.month}",
        "健康状况": int((npc.get("attributes") or {}).get("健康", 60) or 0),
        "精神状态": random.randint(20, 50),
        "掌握的秘密": secrets,
        "关系": int((npc.get("relationship") or {}).get("好感", 0) or 0),
        "衰减减半": False,
        "标记": [],
        "npc_snapshot": npc,
    }
    cp["inmates"][name] = inmate
    game_state.npcs.pop(name, None)
    game_state.relationships.pop(name, None)
    # 子嗣联动（§8）：母妃入冷宫，其子嗣被迫成熟
    for c in (getattr(game_state, "children", []) or []):
        if isinstance(c, dict) and c.get("alive", True) and c.get("birth_mother") == name:
            c["心性"] = min(100, int(c.get("心性", 30) or 0) + 5)
    _log(cp, f"{name}被贬入冷宫（{reason}）")
    return inmate, f"{name}被迁入冷宫：{reason}"


def enter_cold_palace(game_state, reason):
    """玩家主动避居/顶罪入冷宫。"""
    cp = get_cold_palace(game_state)
    if is_player_imprisoned(game_state):
        return False, "你已在冷宫之中"
    cp["player"] = {
        "imprisoned": True,
        "原因": reason,
        "入宫旬": _period_stamp(game_state),
        "健康": int(game_state.attributes.get("健康", 60) or 0),
        "精神状态": random.randint(30, 55),
        "银两": min(200, int(game_state.silver // 2)),
        "线索": [],
        "人脉": [],
        "翻身概率": 15,
        "抄经怜悯": False,
        "血书": False,
        "装疯": False,
        "旬数": 0,
        "原位份": game_state.rank.name,
    }
    game_state.silver -= min(200, int(game_state.silver // 2))
    _log(cp, f"你迁居冷宫（{reason}）")
    game_state.add_memory(f"你迁入冷宫（{reason}）")
    return True, f"你脱下钗环，迁入冷宫（{reason}）。宫墙内外，从此两个世界。"


def release_player(game_state, cp, method_name, degrade=True):
    p = cp["player"]
    p["imprisoned"] = False
    game_state.neglect_periods = 0
    game_state.attributes["宠爱"] = max(20, int(game_state.attributes.get("宠爱", 0) or 0))
    wei = max(0, game_state.attributes.get("威望", 0) - 10)
    game_state.attributes["威望"] = wei
    game_state.add_memory(f"冷宫归来（{method_name}）")
    flags = getattr(game_state, "story_flags", [])
    if isinstance(flags, list) and "冷宫归来" not in flags:
        flags.append("冷宫归来")
    cp["log"].insert(0, f"你经「{method_name}」重返后宫（{'位份降一级' if degrade else '复位'}）")
    return True, (f"🌤️ 冷宫大门为你打开。你重新踏足后宫，鬓边已见霜色——人人称你「{method_name}」而归，"
                  f"眼里多了些从前没有的东西。（威望-10，获「冷宫归来」标签）")


def player_release_attempt(game_state, method_key):
    """冷宫翻身（§6.2 六式）。"""
    cp = get_cold_palace(game_state)
    p = cp.get("player")
    if not isinstance(p, dict) or not p.get("imprisoned"):
        return None, "你不在冷宫之中"
    spec = RELEASE_METHODS.get(method_key)
    if not spec:
        return None, "无效的翻身方式"
    if p["精神状态"] < 60 and method_key not in ("blood",):
        return False, "精神萎靡（需≥60），撑不起这一搏"
    rate = spec["base"]
    if spec["bonus"] == "favor":
        rate += game_state.relationships.get("皇帝", {}).get("好感", 10) / 5
    elif spec["bonus"] == "dowager":
        rate += game_state.relationships.get("太后", {}).get("好感", 25) / 3
        if p.get("抄经怜悯"):
            rate += 10
    elif spec["bonus"] == "secrets":
        value = sum(s["可靠性"] for s in p.get("线索", []) if isinstance(s, dict))
        rate += value / 10
    elif spec["bonus"] == "spirit":
        rate += p["精神状态"] / 10
    elif spec["bonus"] == "child":
        sons = [c for c in (getattr(game_state, "children", []) or [])
                if isinstance(c, dict) and c.get("alive", True) and float(c.get("age", 0) or 0) >= 6]
        rate += (max((int(c.get("emperor_favor", 30) or 0) for c in sons), default=20)) / 5
    elif spec["bonus"] == "family":
        clan = getattr(game_state, "player_clan", None) or {}
        rate += int(clan.get("家族威望", 40) or 40) / 10
    if p.get("装疯"):
        rate -= 15
    if p.get("血书"):
        rate += 10
    rate = max(5, min(90, int(rate)))
    if random.randint(1, 100) > rate:
        if spec["fail"] == "death":
            from app import trigger_ending
            trigger_ending(game_state, "冷宫幽闭", f"{spec['name']}败露，钦命赐死")
            return True, f"🕯️ {spec['name']}事败。旨意传来那夜，冷宫落了锁。（终局：冷宫幽闭）"
        p["精神状态"] = max(0, p["精神状态"] - 15)
        p["健康"] = max(1, p["健康"] - 5)
        cp["environment"]["条件"] = "恶劣"
        return True, f"💔 {spec['name']}未被采纳，反遭看管加严（精神-15，健康-5）。再来，或等下一次窗口。"
    degrade = spec["name"] in ("托太后求情", "子嗣求情", "家族营救")
    ok, msg = release_player(game_state, cp, spec["name"], degrade=degrade)
    return ok, msg


def player_self_action(game_state, action):
    """冷宫生存动作（§4.1 七式）。"""
    cp = get_cold_palace(game_state)
    p = cp.get("player")
    if not isinstance(p, dict) or not p.get("imprisoned"):
        return None, "你不在冷宫之中"
    spec = SELF_ACTIONS.get(action)
    if not spec:
        return None, "无效的冷宫行动"
    if "actions" in spec["cost"]:
        from app import check_and_consume_action
        ok2, _left = check_and_consume_action(game_state)
        if not ok2:
            return False, "行动点不足，且行且歇"
    if "silver" in spec["cost"]:
        if p["银两"] < spec["cost"]["silver"]:
            return False, f"私房银两不足（需{spec['cost']['silver']}两）"
        p["银两"] -= spec["cost"]["silver"]
    if "health" in spec["cost"]:
        p["健康"] = max(1, p["健康"] - spec["cost"]["health"])
    if action == "sort_items":
        n = random.randint(1, 3)
        for _ in range(n):
            p["线索"].append({"内容": random.choice([
                "半张烧残的宫门条子", "一枚刻字银簪", "一页没署名的血书",
                "看守醉后漏的一句话", "前朝宫人留下的名册角", "一只不该出现在这里的耳坠",
            ]), "可靠性": random.randint(40, 85)})
        p["翻身概率"] = min(60, p["翻身概率"] + n * 2)
        return True, f"📦 你翻检旧物，理出{n}条旧日线索（翻身概率+{n * 2}%）"
    if action == "befriend":
        who = random.choice(["疯癫的前朝才人", "守冷的老公人", "同屋的病嫔", "浣衣局来的老嬷嬷"])
        p["人脉"].append(who)
        p["精神状态"] = min(100, p["精神状态"] + 5)
        return True, f"🤝 你与{who}搭上了话。冷宫里的情分，有时比宫里的真（精神+5）"
    if action == "send_letter":
        if p["精神状态"] < 50:
            p["健康"] = max(1, p["健康"] - 5)
            p["精神状态"] = max(0, p["精神状态"] - 10)
            return True, "✉️ 密信被看守截获！你挨了一顿训斥（健康-5，精神-10）"
        p["翻身概率"] = min(60, p["翻身概率"] + 5)
        return True, "✉️ 密信随浆洗的衣物送了出去。但愿它落到该落的人手里（翻身概率+5%）"
    if action == "blood_book":
        p["血书"] = True
        return True, "🩸 你咬破手指写下血书，字字恳切。若它能上达天听……（翻身判定+10%）"
    if action == "hunger_strike":
        p["精神状态"] = min(100, p["精神状态"] + 5)
        p["翻身概率"] = min(70, p["翻身概率"] + 20)
        return True, "🥢 你绝食三日明志，看守慌了，上头也惊动了（翻身判定+20%）"
    if action == "copy_sutra":
        p["精神状态"] = min(100, p["精神状态"] + 3)
        p["抄经怜悯"] = True
        return True, "📿 你一笔一划抄完一卷《地藏经》，托人送往太后宫中（精神+3，太后怜悯已记下）"
    if action == "bribe":
        p["翻身概率"] = min(70, p["翻身概率"] + 3)
        return True, "🪙 看守收了银子，眼睛只当没看见（翻身概率+3%）"
    return None, "无效的冷宫行动"


def interact_inmate(game_state, name, action):
    """玩家在宫中时与冷宫妃嫔的互动（§七）。"""
    from app import guard_action, check_and_consume_action
    cp = get_cold_palace(game_state)
    inmate = cp["inmates"].get(name)
    if not inmate:
        return None, "冷宫中查无此人"
    if is_player_imprisoned(game_state):
        return None, "你自己也在冷宫之中"
    if action == "visit":
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
        inmate["精神状态"] = min(100, inmate["精神状态"] + 5)
        inmate["关系"] = inmate.get("关系", 0) + 5
        secrets = inmate.get("掌握的秘密", [])
        parts = "；".join(f"{s['内容']}（可靠{s['可靠性']}%）" for s in secrets) or "她讳莫如深"
        return True, (f"🚪 你探视了{name}。她形容枯槁，聊起旧事时眼底有光——"
                      f"她知道的秘密：{parts}")
    if action == "give":
        if game_state.silver < 20:
            return False, "银两不足（需20两）"
        game_state.silver -= 20
        inmate["精神状态"] = min(100, inmate["精神状态"] + 5)
        inmate["关系"] = inmate.get("关系", 0) + 10
        return True, f"🎁 你托人给{name}捎去了衣物吃食，她朝你宫墙的方向磕了个头（关系+10）"
    if action == "plead":
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
        ok2, _ = check_and_consume_action(game_state)
        if not ok2:
            return False, "行动点不足（求情需2点）"
        chance = 30 + game_state.relationships.get("皇帝", {}).get("好感", 10) // 3
        if random.randint(1, 100) <= chance:
            back = release_inmate(game_state, name, "妃嫔求情")
            game_state.attributes["威望"] = min(game_state.get_attr_max("威望"),
                                                game_state.attributes.get("威望", 0) + 10)
            return True, f"📜 你冒陈情之险为她求情，皇帝准了。{name}出冷宫，对你感恩戴德（威望+10）"
        inmate["精神状态"] = max(0, inmate["精神状态"] - 5)
        return True, f"📜 你为她求情，皇帝未置可否。希望落了空（她的精神-5）"
    if action == "use_secret":
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
        secrets = inmate.get("掌握的秘密", [])
        if not secrets:
            return False, "她暂时没有可用的秘密"
        s = secrets.pop(0)
        targets = [n for n, c in (game_state.npcs or {}).items()
                   if isinstance(c, dict) and c.get("alive", True) and n != game_state.name]
        target = random.choice(targets) if targets else ""
        from app import _append_intrigue_rumor, get_intrigue_state
        rumor = {"target": target or "后宫", "type": "npc", "severity": 2,
                 "turns_left": 3, "text": f"🗝️ 冷宫传出的话：{s['内容']}（涉及{target}）",
                 "source": "cold_palace"}
        _append_intrigue_rumor(game_state, rumor)
        dirt = get_intrigue_state(game_state).setdefault("dirt", {})
        payload = dirt.setdefault(target or "后宫", {"points": 0, "age": 0, "label": "冷宫密辛"})
        payload["points"] = int(payload.get("points", 0) or 0) + s["可靠性"] // 30
        gain = random.randint(4, 8)
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"),
                                            game_state.attributes.get("威望", 0) + gain)
        inmate["关系"] = inmate.get("关系", 0) - 5
        return True, (f"🗡️ 你把{name}的秘密递了出去——{s['内容']}（涉及{target}）。"
                      f"把柄+1条，威望+{gain}。{name}知道后沉默了很久（关系-5）")
    if action == "taiyi":
        if game_state.silver < 30:
            return False, "银两不足（需30两）"
        game_state.silver -= 30
        heal = random.randint(5, 10)
        inmate["健康状况"] = min(100, inmate["健康状况"] + heal)
        inmate["关系"] = inmate.get("关系", 0) + 10
        return True, f"💊 你重金请太医以诊别的名义去了一趟冷宫，{name}的病有了起色（健康+{heal}）"
    if action == "bribe_guard":
        if game_state.silver < 50:
            return False, "银两不足（需50两）"
        game_state.silver -= 50
        inmate["衰减减半"] = True
        return True, f"🪙 你买通了看守，{name}的日子好过些了（此后状态衰减减半）"
    return None, "无效的互动"


def release_inmate(game_state, name, by="特赦"):
    """在押妃嫔出冷宫：位份降一级，记「冷宫归来」。"""
    cp = get_cold_palace(game_state)
    inmate = cp["inmates"].pop(name, None)
    if not inmate:
        return None
    npc = inmate.get("npc_snapshot") or {}
    npc["alive"] = True
    old_rank = inmate.get("原身份", "答应")
    from app import RANK_LEVELS, get_prev_rank
    idx = RANK_LEVELS.get(old_rank, 3)
    prev = get_prev_rank(old_rank) if by != "复位" else old_rank
    npc["rank"] = prev or old_rank
    npc["attributes"]["健康"] = max(20, inmate.get("健康状况", 40))
    rel = npc.setdefault("relationship", {"好感": 0, "印象": "陌生", "互动次数": 0})
    rel["好感"] = min(100, inmate.get("关系", 0) + 40)
    rel["印象"] = "死忠"
    npc["attributes"]["宠爱"] = min(100, int(npc["attributes"].get("宠爱", 20) or 0))
    game_state.npcs[name] = npc
    game_state.relationships[name] = npc["relationship"]
    marks = npc.setdefault("标记", [])
    if "冷宫归来" not in marks:
        marks.append("冷宫归来")
    _log(cp, f"{name}经「{by}」离开冷宫（位份{'复位' if prev == old_rank else '降为' + str(prev)}）")
    return npc


def cold_period_tick(game_state):
    """转旬：在押者衰减与翻身尝试 + 事件池 + 玩家冷宫循环。返回消息列表。"""
    cp = get_cold_palace(game_state)
    msgs = []
    halve = cp["environment"].get("条件") != "恶劣"
    for name, inm in list(cp["inmates"].items()):
        k = 0.5 if inm.get("衰减减半") else 1.0
        if halve:
            k *= 0.5
        inm["健康状况"] = max(0, inm["健康状况"] - round(random.randint(*COLD_INMATE_DECAY_HEALTH) * k))
        inm["精神状态"] = max(0, inm["精神状态"] - round(random.randint(*COLD_INMATE_DECAY_SPIRIT) * k))
        if inm["健康状况"] <= 10:
            cp["inmates"].pop(name, None)
            msgs.append(f"🕯️ {name}病殁于冷宫，无人吊唁（原{inm['原身份']}）")
            _log(cp, f"{name}病殁于冷宫")
            continue
        if inm["精神状态"] >= 60 and random.random() < 0.06:
            back = release_inmate(game_state, name, "圣意回转")
            if back is not None:
                msgs.append(f"🌤️ 圣意回转，{name}蒙恩出冷宫（位份降一级，怀恨或怀恩，唯她自知）")
    # 事件池（§五，代表事件）
    if cp["inmates"] and random.random() < 0.4:
        name = random.choice(list(cp["inmates"].keys()))
        inm = cp["inmates"][name]
        roll = random.random()
        if roll < 0.3:
            s = {"内容": random.choice(["先帝年间的一桩旧案", "某位娘娘嫁入宫前的旧事", "宗室里一笔烂账"]),
                 "可靠性": random.randint(55, 90)}
            inm.setdefault("掌握的秘密", []).append(s)
            msgs.append(f"🌑 冷宫深夜有哭声，{name}循声挖出了前人埋下的秘密")
        elif roll < 0.5:
            inm["精神状态"] = min(100, inm["精神状态"] + 10)
            msgs.append(f"📦 有旧仆冒死给{name}送了冬衣，她精神好了些")
        elif roll < 0.65:
            inm["健康状况"] = max(0, inm["健康状况"] - 5)
            msgs.append(f"🌧️ 冷宫漏雨，{name}染了风寒（健康-5）")
        else:
            inm["精神状态"] = max(0, inm["精神状态"] - 8)
            msgs.append(f"🕸️ 看守克扣了{name}的份例，她彻夜无眠（精神-8）")
    # 玩家冷宫循环
    p = cp.get("player")
    if isinstance(p, dict) and p.get("imprisoned"):
        p["旬数"] += 1
        k = 0.5 if cp["environment"].get("条件") != "恶劣" else 1.0
        p["健康"] = max(0, p["健康"] - round(random.randint(*PLAYER_DECAY_HEALTH) * k))
        p["精神状态"] = max(0, p["精神状态"] - round(random.randint(*PLAYER_DECAY_SPIRIT) * k))
        if p["银两"] > 0:
            p["银两"] = max(0, p["银两"] - 5)
        else:
            p["健康"] = max(0, p["健康"] - 3)
        if p["健康"] <= 15:
            msgs.append("🕯️ 你在冷宫里咳出血来——再这样下去，怕是熬不过这个冬天了")
        elif p["精神状态"] <= 0:
            msgs.append("🕸️ 你开始整夜整夜地睡不着，听见墙外每一阵风都像旨意")
        elif p["精神状态"] >= 70 and p["旬数"] >= 2:
            msgs.append("🌤️ 你忽然想明白了什么，心里镇定下来——是时候筹谋出去了（可尝试翻身）")
        if random.random() < 0.35:
            msgs.append(random.choice([
                "🌑 冷宫的夜格外长，隔壁传来断断续续的哭声",
                "🐀 耗子从床底跑过，你已懒得睁眼",
                "🍜 今天的饭里照旧没有油星，你慢慢吃完了",
                "🍂 墙头最后一片叶子也落了",
            ]))
    return msgs


# ---- 冷宫管理（协理权限） ----
def cold_manage(game_state, action, name=None):
    cp = get_cold_palace(game_state)
    from app import chonghua_permission
    if chonghua_permission(game_state) != "full":
        return None, "冷宫管理需皇后亲裁或协理六宫权限"
    if action == "improve":
        if game_state.silver < 100:
            return False, "银两不足（需100两）"
        game_state.silver -= 100
        cp["environment"]["条件"] = "一般"
        for inm in cp["inmates"].values():
            inm["精神状态"] = min(100, inm["精神状态"] + 5)
        return True, "🏚️ 你命人修葺冷宫、添了炭盆棉被。连看守的脸色都和缓了（条件→一般）"
    if action == "pardon":
        if not name or name not in cp["inmates"]:
            return False, "冷宫中查无此人"
        release_inmate(game_state, name, "凤印特赦")
        return True, f"📜 你以凤印之名特赦{name}。她出冷宫那日，朝你深深一拜"
    if action == "search":
        if not name or name not in cp["inmates"]:
            return False, "冷宫中查无此人"
        inm = cp["inmates"][name]
        found = inm.get("掌握的秘密", [])
        inm["精神状态"] = max(0, inm["精神状态"] - 10)
        silver_found = random.randint(0, 30)
        game_state.silver += silver_found
        cp["environment"]["银两储备"] = cp["environment"].get("银两储备", 0) + silver_found
        items = "；".join(s["内容"] for s in found) or "并无要紧物件"
        return True, f"🔍 你搜查了{name}的居所，抄得白银{silver_found}两，起获密辛：{items}（她精神-10）"
    if action == "admit":
        inmate, msg = admit_npc(game_state, name or "", "协理裁决：宫规处置")
        if inmate is None:
            return False, msg
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"),
                                            game_state.attributes.get("威望", 0) + 3)
        return True, f"⚖️ 你裁决{name}迁居冷宫（{msg}）。威望+3，宫中肃然"
    return None, "无效的管理动作"


def cold_overview_payload(game_state):
    cp = get_cold_palace(game_state)
    p = cp.get("player")
    return {
        "inmates": [{
            "name": name,
            "原身份": i.get("原身份", ""),
            "入住旬": i.get("入住旬", ""),
            "健康状况": i.get("健康状况", 0),
            "精神状态": i.get("精神状态", 0),
            "secrets": len(i.get("掌握的秘密", [])),
            "关系": i.get("关系", 0),
        } for name, i in cp["inmates"].items()],
        "environment": dict(cp["environment"]),
        "player": ({k: p.get(k) for k in ("imprisoned", "原因", "健康", "精神状态", "银两",
                                          "线索", "人脉", "旬数", "翻身概率", "原位份")}
                   if isinstance(p, dict) else None),
        "log": list(cp["log"])[:8],
    }
