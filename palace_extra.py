# palace_extra.py — 易次元风格：争锋 / 祈福掌祀 / 闲聊试探 / 压力
import random
from names import extract_surname
from family_backgrounds import get_family_score as _clan_family_score

DUEL_SKILLS = {
    "持宠生娇": {"attr": "宠爱", "desc": "比圣宠深浅"},
    "金枝玉叶": {"attr": "家世", "desc": "比出身门第"},
    "破口大骂": {"attr": "健康", "desc": "比体质气势"},
    "绵里藏针": {"attr": "心计", "desc": "比城府心机"},
    "才压群芳": {"attr": "才情", "desc": "比才学辞章"},
    "位高权重": {"attr": "位份", "desc": "比位份高低"},
    "群起攻之": {"attr": "人手", "desc": "比宫人多寡"},
    "沉默不语": {"attr": "福运", "desc": "以静制动"},
}

DRAIN_OPTIONS = {
    "降其心智": {"self": "心计", "target": "心计", "favor": -12, "desc": "你心计渐长，对方城府受损"},
    "辱其自尊": {"self": "威望", "target": "威望", "favor": -18, "desc": "你威望抬升，对方颜面尽失"},
    "摧其斗志": {"self": "倾向", "target": "倾向", "favor": 0, "desc": "你气势更盛，对方斗志消磨"},
    "以理服人": {"self": "all", "target": "all", "favor": -8, "desc": "同时吸取心计、威望与倾向"},
}

RANK_ORDER_LOCAL = ["更衣", "官女子", "答应", "常在", "贵人", "才人", "美人", "婕妤", "嫔", "妃", "贵妃", "皇贵妃", "皇后"]


def _rank_level(rank_name):
    try:
        return RANK_ORDER_LOCAL.index(rank_name)
    except ValueError:
        return 3


def _family_score(family, family_meta=None):
    return _clan_family_score(family, family_meta)


def _stat_value(game_state, who, attr_key, is_player):
    if is_player:
        attrs = game_state.attributes
        rank = game_state.rank.name if hasattr(game_state.rank, "name") else str(game_state.rank)
        family = game_state.family_background
        family_meta = getattr(game_state, "family_meta", None)
        people = len(game_state.get_active_servants()) * 12
    else:
        npc = game_state.npcs.get(who, {})
        attrs = npc.get("attributes", {})
        rank = npc.get("rank", "答应")
        family = npc.get("family_background", "未知")
        family_meta = npc.get("family_meta")
        people = random.randint(8, 40)
    mapping = {
        "宠爱": attrs.get("宠爱", 30),
        "健康": attrs.get("健康", 60),
        "心计": attrs.get("心计", 40),
        "才情": attrs.get("才情", 40),
        "福运": attrs.get("福运", 30),
        "家世": _family_score(family, family_meta) + attrs.get("威望", 20) * 0.25,
        "位份": _rank_level(rank) * 8 + 10,
        "人手": people,
    }
    return float(mapping.get(attr_key, 40))


def available_skills(rank_name):
    n = 2 + _rank_level(rank_name) // 3
    n = max(2, min(5, n))
    keys = list(DUEL_SKILLS.keys())
    # 低位先给基础技，高位解锁后排
    return keys[:n]


def period_key(game_state):
    return f"{game_state.year}-{game_state.month}-{game_state.day}"


def start_duel(game_state, target):
    existing = getattr(game_state, "_active_duel", None)
    if existing and not existing.get("finished"):
        return existing, None
    if target not in game_state.npcs:
        return None, "目标不存在"
    npc = game_state.npcs[target]
    if not npc.get("alive", True) or not npc.get("is_active", True):
        return None, "对方已不在后宫"
    last = getattr(game_state, "last_duel_period", None)
    if last == period_key(game_state):
        return None, "本旬已主动争锋一次，下旬再来"
    p_skills = available_skills(game_state.rank.name if hasattr(game_state.rank, "name") else "答应")
    n_skills = available_skills(npc.get("rank", "答应"))
    duel = {
        "target": target,
        "player_score": 0,
        "npc_score": 0,
        "player_left": p_skills[:],
        "npc_left": n_skills[:],
        "log": [f"你邀约{extract_surname(target)}{npc.get('rank','妃嫔')}争锋，帘后对坐，茶未凉而杀机已起。"],
        "finished": False,
    }
    game_state._active_duel = duel
    return duel, None


def play_duel_skill(game_state, skill_key):
    duel = getattr(game_state, "_active_duel", None)
    if not duel or duel.get("finished"):
        return None, "当前没有进行中的争锋"
    if skill_key not in duel["player_left"]:
        return None, "这招已经用过，或你尚未习得"
    target = duel["target"]
    skill = DUEL_SKILLS[skill_key]
    p_val = _stat_value(game_state, game_state.name, skill["attr"], True)
    n_val = _stat_value(game_state, target, skill["attr"], False)
    luck = random.uniform(0.88, 1.12)
    p_hit = p_val * luck
    n_hit = n_val * random.uniform(0.88, 1.12)
    delta = int(abs(p_hit - n_hit) / 6) + 8
    if p_hit >= n_hit:
        duel["player_score"] += delta
        line = f"【{skill_key}】{skill['desc']}——你占上风（{int(p_val)} vs {int(n_val)}），评分 +{delta}"
    else:
        duel["npc_score"] += delta
        line = f"【{skill_key}】{skill['desc']}——对方更胜一筹（{int(p_val)} vs {int(n_val)}），对方评分 +{delta}"
    duel["player_left"].remove(skill_key)
    duel["log"].append(line)

    # NPC 回招
    if duel["npc_left"]:
        npc_skill = random.choice(duel["npc_left"])
        ns = DUEL_SKILLS[npc_skill]
        p2 = _stat_value(game_state, game_state.name, ns["attr"], True)
        n2 = _stat_value(game_state, target, ns["attr"], False)
        d2 = int(abs(p2 - n2) / 6) + 8
        if n2 * random.uniform(0.9, 1.1) >= p2:
            duel["npc_score"] += d2
            duel["log"].append(f"对方使出【{npc_skill}】，{ns['desc']}，对方评分 +{d2}")
        else:
            duel["player_score"] += d2
            duel["log"].append(f"对方使出【{npc_skill}】，反被你压过，你评分 +{d2}")
        duel["npc_left"].remove(npc_skill)

    if not duel["player_left"] or (not duel["npc_left"] and not duel["player_left"]):
        duel["finished"] = True
        if duel["player_score"] > duel["npc_score"]:
            duel["winner"] = "player"
            duel["log"].append(f"争锋落幕。你 {duel['player_score']} : {duel['npc_score']} 对方。可择处置。")
        elif duel["player_score"] < duel["npc_score"]:
            duel["winner"] = "npc"
            duel["log"].append(f"争锋落幕。你 {duel['player_score']} : {duel['npc_score']} 对方。此番受挫。")
        else:
            duel["winner"] = "draw"
            duel["log"].append(f"争锋落幕。平手 {duel['player_score']}。帘外风停，各自散去。")
    return duel, None


def resolve_duel(game_state, drain_key=None):
    duel = getattr(game_state, "_active_duel", None)
    if not duel or not duel.get("finished"):
        return None, "争锋尚未结束"
    target = duel["target"]
    npc = game_state.npcs.get(target, {})
    nattrs = npc.setdefault("attributes", {})
    pattrs = game_state.attributes
    margin = abs(duel["player_score"] - duel["npc_score"])
    steal = min(18, 6 + margin // 8)
    effects = {}
    narration = ""
    winner = duel.get("winner")

    if winner == "player":
        if drain_key not in DRAIN_OPTIONS:
            drain_key = "降其心智"
        if drain_key == "以理服人" and pattrs.get("心计", 0) < 55:
            return None, "心计不足 55，尚不能以理服人"
        opt = DRAIN_OPTIONS[drain_key]
        if opt["self"] == "all":
            for k in ("心计", "威望", "倾向"):
                gain = max(2, steal // 2)
                pattrs[k] = min(game_state.get_attr_max(k) if hasattr(game_state, "get_attr_max") else 100, pattrs.get(k, 30) + gain)
                nattrs[k] = max(0, nattrs.get(k, 40) - gain)
                effects[k] = gain
        else:
            k = opt["self"]
            cap = game_state.get_attr_max(k) if hasattr(game_state, "get_attr_max") else 100
            pattrs[k] = min(cap, pattrs.get(k, 30) + steal)
            nattrs[k] = max(0, nattrs.get(k, 40) - steal)
            effects[k] = steal
        npc["压力"] = min(120, npc.get("压力", 20) + 8 + steal // 2)
        if target in game_state.relationships:
            game_state.relationships[target]["好感"] = max(-100, game_state.relationships[target].get("好感", 0) + opt["favor"])
        game_state.rivalries[target] = game_state.rivalries.get(target, 0) + 8
        narration = f"你胜了{target}，择「{drain_key}」。{opt['desc']}。对方压力攀升。"
    elif winner == "npc":
        steal = max(4, steal // 2)
        for k in ("心计", "倾向"):
            pattrs[k] = max(0, pattrs.get(k, 30) - steal)
            nattrs[k] = min(100, nattrs.get(k, 40) + steal // 2)
            effects[k] = -steal
        pattrs["威望"] = max(0, pattrs.get("威望", 20) - 3)
        effects["威望"] = effects.get("威望", 0) - 3
        if target in game_state.relationships:
            game_state.relationships[target]["好感"] = max(-100, game_state.relationships[target].get("好感", 0) - 10)
        narration = f"你败于{target}。颜面受损，心计与倾向皆挫。"
    else:
        narration = f"与{target}争锋未分胜负，各自收场。"

    game_state.last_duel_period = period_key(game_state)
    game_state._active_duel = None
    game_state.add_memory(narration)
    game_state.add_attr_change(effects, f"争锋：{target}")
    return {
        "narration": narration,
        "effects": effects,
        "log": duel["log"],
        "winner": winner,
        "player_score": duel["player_score"],
        "npc_score": duel["npc_score"],
        "pressure": npc.get("压力", 0),
    }, None


def chat_probe(game_state, npc_name):
    npc = game_state.npcs.get(npc_name)
    if not npc:
        return None, "妃嫔不在"
    p_wit = game_state.attributes.get("心计", 40)
    n_wit = npc.get("attributes", {}).get("心计", 50)
    revealed = []
    if p_wit + random.randint(0, 20) >= n_wit:
        revealed.append(f"性格：{npc.get('personality', '难测')}（{npc.get('personality_desc', '')}）")
        revealed.append(f"心计约 {n_wit}")
        revealed.append(f"倾向 {npc.get('attributes', {}).get('倾向', '?')}，压力 {npc.get('压力', 0)}")
        hint = "闲聊间，她心思已被你摸清几分。"
    else:
        hint = "闲聊数句，她笑意浅淡，什么也没透。聊不出性格与心计，说明暂且惹不起。"
        revealed.append("未探明")
    if npc_name in game_state.relationships:
        game_state.relationships[npc_name]["好感"] = min(100, game_state.relationships[npc_name].get("好感", 0) + random.randint(0, 3))
        game_state.relationships[npc_name]["互动次数"] = game_state.relationships[npc_name].get("互动次数", 0) + 1
    narration = hint + " " + "；".join(revealed)
    return {"narration": narration, "revealed": revealed, "safe_to_duel": p_wit + 10 >= n_wit}, None


def pray_or_curse(game_state, mode, target=None):
    """mode: bless / curse"""
    if mode == "bless":
        cost = 15
        if game_state.silver < cost:
            return None, "银两不足，香火钱要十五两"
        game_state.silver -= cost
        luck = random.randint(4, 9)
        tend = random.randint(1, 4)
        game_state.attributes["福运"] = min(100, game_state.attributes.get("福运", 30) + luck)
        game_state.attributes["倾向"] = min(100, game_state.attributes.get("倾向", 30) + tend)
        # 福运高时小概率圣眷
        extra = ""
        if random.random() < 0.18:
            fav = random.randint(2, 6)
            game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + fav)
            extra = f" 签上显「宠」字，宠爱+{fav}。"
        narration = f"你至奉天楼焚香祈福。福运+{luck}，倾向+{tend}。{extra}"
        effects = {"福运": luck, "倾向": tend, "银两": -cost}
        game_state.add_memory(narration)
        game_state.add_attr_change(effects, "奉天楼祈福")
        return {"narration": narration, "effects": effects}, None

    if mode == "curse":
        cost = 40
        if game_state.silver < cost:
            return None, "掌祀需四十两香火与纸钱"
        if not target or target not in game_state.npcs:
            return None, "请选定要克的妃嫔"
        if game_state.attributes.get("心计", 0) < 25:
            return None, "心计太浅，掌祀只恐反噬"
        game_state.silver -= cost
        npc = game_state.npcs[target]
        press = random.randint(12, 22)
        luck_cut = random.randint(3, 8)
        npc["压力"] = min(120, npc.get("压力", 20) + press)
        nattrs = npc.setdefault("attributes", {})
        nattrs["福运"] = max(0, nattrs.get("福运", 40) - luck_cut)
        # 反噬
        backfire = ""
        if random.random() < 0.22:
            self_cut = random.randint(2, 6)
            game_state.attributes["福运"] = max(0, game_state.attributes.get("福运", 30) - self_cut)
            backfire = f" 香灰骤灭，自身福运-{self_cut}。"
        if target in game_state.relationships:
            game_state.relationships[target]["好感"] = max(-100, game_state.relationships[target].get("好感", 0) - 6)
        game_state.rivalries[target] = game_state.rivalries.get(target, 0) + 5
        narration = f"你在奉天楼暗行掌祀，克向{target}。对方压力+{press}，福运-{luck_cut}。{backfire}"
        effects = {"银两": -cost}
        game_state.add_memory(narration)
        return {"narration": narration, "effects": effects, "pressure": npc["压力"]}, None

    return None, "无效仪式"


def process_pressure(game_state):
    events = []
    for name, npc in game_state.npcs.items():
        if name in ("太后",) or not npc.get("alive", True):
            continue
        press = npc.get("压力", 20)
        # 自然回落一点
        if press > 15:
            npc["压力"] = max(0, press - random.randint(1, 4))
        press = npc.get("压力", 0)
        if press >= 100:
            nattrs = npc.setdefault("attributes", {})
            loss = random.randint(8, 16)
            nattrs["心计"] = max(5, nattrs.get("心计", 40) - loss)
            nattrs["倾向"] = max(0, nattrs.get("倾向", 40) - loss)
            nattrs["健康"] = max(10, nattrs.get("健康", 60) - 6)
            npc["压力"] = random.randint(35, 55)
            npc["personality"] = "心神不宁"
            events.append(f"💔 {name} 压力难承，竟至疯癫边缘，心计与斗志大损。")
        elif press >= 70 and random.random() < 0.35:
            events.append(f"😟 {name} 近日神思恍惚，宫人说她夜里常惊坐。")
    # 玩家倾向自然微变
    if game_state.attributes.get("倾向", 30) < 20 and random.random() < 0.2:
        events.append("你自觉气势不足，行走宫道都要让人三分。")
    return events
