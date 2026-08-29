# affair_system.py — 出轨/私通 + 揭发利用 + 狸猫换皇子 引擎（设计稿 v2.0）
# 私通六类对象五阶段 · 风险累积与阈值事件 · 消解五式 · NPC 私通发现与四处置 · 狸猫六阶段事件链
import random

from names import random_given, EMPEROR_GIVEN

STAGES = ["偶遇", "熟识", "私交", "深交", "情缘"]
STAGE_GATE = [0, 25, 50, 70]           # 情感值达到阈值升阶

TARGET_TYPES = {
    "侍卫": {"身份": "禁军侍卫", "风险": "高", "能力": "禁军情报", "姓氏池": ["张", "李", "赵", "周"]},
    "太医": {"身份": "太医院院判", "风险": "中", "能力": "伪造脉案", "姓氏池": ["张", "钱", "孙", "吴"]},
    "外臣": {"身份": "翰林院编修", "风险": "极高", "能力": "朝堂情报", "姓氏池": ["陈", "沈", "裴", "薛"]},
    "宗室": {"身份": "宗室子", "风险": "高", "能力": "宗室奥援", "姓氏池": ["萧", "宇文", "慕容"]},
    "宫人": {"身份": "贴身内侍", "风险": "低", "能力": "跑腿传递", "姓氏池": ["小", "阿"]},
    "妃嫔": {"身份": "后宫姐妹", "风险": "中", "能力": "情感支撑", "姓氏池": ["柳", "苏", "杜"]},
}

DEVELOP_WAYS = {
    "summon": {"name": "借故召见", "cost": {"actions": 1}, "base": 60, "bonus": "心计", "div": 5},
    "message": {"name": "托人传话", "cost": {"silver": 50}, "base": 30, "bonus": "威望", "div": 10},
    "encounter": {"name": "制造偶遇", "cost": {"actions": 1}, "base": 50, "bonus": "容貌", "div": 8},
    "gift": {"name": "赠礼拉近", "cost": {"silver": 30}, "base": 70, "bonus": "好感", "div": 10},
}

MITIGATIONS = {
    "cut": {"name": "主动断绝", "risk": -30},
    "bribe_knower": {"name": "收买知情者", "risk": -20, "silver": 100},
    "silence": {"name": "灭口", "risk": -100, "min_scheme": 70},
    "divert": {"name": "制造假象", "risk": -15, "actions": 2},
    "confess_dowager": {"name": "向太后坦白", "risk": -40, "min_dowager": 50},
}

EXPOSE_OPS = {"expose": "向皇帝揭发", "blackmail": "秘密勒索", "control": "利用控制", "keep": "保存备用"}

SWAP_MIN_RANK = "嫔"
SWAP_MIN_SCHEME = 60
SWAP_COST = 200
SWAP_PREGNANCY_PERIODS = 6     # 伪造怀孕的旬数
SWAP_CASE_RISK = 80


def default_secret_relationships():
    return {
        "player": [],       # 玩家的私通关系列表
        "npc": {},          # 玩家发现的 NPC 私通 {妃嫔名: {..., 掌握证据: []}}
        "hidden_npc": {},   # NPC 自己的私通（未被发现，tick 生成）
        "swap": {"phase": None, "内应": "", "孕旬": 0, "child_uid": "", "真实父母": {},
                 "知情者": [], "风险值": 0, "案发": False, "揭穿": False},
        "risk_log": [],
    }


def get_affairs(game_state):
    sr = getattr(game_state, "secret_relationships", None)
    if not isinstance(sr, dict):
        sr = default_secret_relationships()
        game_state.secret_relationships = sr
    for k, v in default_secret_relationships().items():
        sr.setdefault(k, v)
    sw = sr["swap"]
    for k, v in default_secret_relationships()["swap"].items():
        sw.setdefault(k, v)
    return sr


def _contact_name(target_type, used):
    pool = TARGET_TYPES[target_type]["姓氏池"]
    for _ in range(200):
        name = random.choice(pool) + random_given(EMPEROR_GIVEN, 0.4)
        if name not in used:
            used.add(name)
            return name
    return random.choice(pool) + "·" + str(random.randint(2, 99))


def _stage_of(affection):
    idx = 0
    for i, gate in enumerate(STAGE_GATE):
        if affection >= gate:
            idx = i
    return STAGES[idx]


def _log(sr, text):
    sr["risk_log"].insert(0, text)
    del sr["risk_log"][30:]


def _rel_snapshot(rel):
    return {k: rel.get(k) for k in ("对象", "对象身份", "对象类型", "关系阶段", "风险值", "情感值", "忠诚度", "特殊能力")}

def affair_overview_payload(game_state):
    sr = get_affairs(game_state)
    return {
        "player": [_rel_snapshot(r) for r in sr["player"]],
        "npc": [{**_rel_snapshot(v), "妃嫔": k, "掌握证据": v.get("掌握证据", [])}
                for k, v in sr["npc"].items()],
        "swap": {k: sr["swap"].get(k) for k in ("phase", "内应", "孕旬", "风险值", "案发",
                                                "知情者", "child_uid")},
        "risk_log": list(sr["risk_log"])[:8],
        "can_swap": swap_eligibility(game_state),
    }


# ===== 私通：发展（§2.4） =====
def develop_affair(game_state, target_type, way, name=None):
    """玩家主动发展/推进一段私通关系。target_type ∈ TARGET_TYPES。"""
    from app import guard_action, check_and_consume_action
    sr = get_affairs(game_state)
    if not TARGET_TYPES.get(target_type) and name:
        existing_rel = next((r for r in sr["player"] if r["对象"] == name), None)
        if existing_rel:
            target_type = existing_rel["对象类型"]  # 旧前端漏传类型时按对象名自愈
    spec = TARGET_TYPES.get(target_type)
    if not spec:
        return None, "无效的对象类型"
    way_spec = DEVELOP_WAYS.get(way)
    if not way_spec:
        return None, "无效的发展方式"
    rel = next((r for r in sr["player"] if r["对象类型"] == target_type and (not name or r["对象"] == name)), None)
    if "actions" in way_spec["cost"]:
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
    if "silver" in way_spec["cost"]:
        if game_state.silver < way_spec["cost"]["silver"]:
            return False, f"银两不足（需{way_spec['cost']['silver']}两）"
        game_state.silver -= way_spec["cost"]["silver"]
    if not rel:
        used = {r["对象"] for r in sr["player"]}
        name = _contact_name(target_type, used)
        rel = {
            "对象": name, "对象身份": spec["身份"], "对象类型": target_type,
            "关系阶段": "偶遇", "开始旬": f"{game_state.year}-{game_state.month}",
            "最近互动旬": f"{game_state.year}-{game_state.month}",
            "风险值": 0, "秘密": [], "情感值": random.randint(10, 25),
            "忠诚度": random.randint(45, 80), "特殊能力": spec["能力"],
            "可用作把柄": True,
        }
        sr["player"].append(rel)
        msg = f"🌑 {spec['身份']}{name}进入了你的视线。一段不能见光的关系，就此开始。"
    else:
        bonus_val = 0
        if way_spec["bonus"] == "心计":
            bonus_val = game_state.attributes.get("心计", 40) / way_spec["div"]
        elif way_spec["bonus"] == "威望":
            bonus_val = game_state.attributes.get("威望", 40) / way_spec["div"]
        elif way_spec["bonus"] == "容貌":
            bonus_val = game_state.attributes.get("容貌", 50) / way_spec["div"]
        else:
            bonus_val = rel["情感值"] / way_spec["div"]
        if random.randint(1, 100) > way_spec["base"] + bonus_val:
            rel["风险值"] = min(100, rel["风险值"] + 3)
            return True, f"🌫️ {way_spec['name']}落了空——{rel['对象']}只当是寻常照面。小心，多一次接触就多一分耳目。"
        rel["情感值"] = min(100, rel["情感值"] + random.randint(8, 15))
        rel["风险值"] = min(100, rel["风险值"] + random.randint(5, 10))
        rel["最近互动旬"] = f"{game_state.year}-{game_state.month}"
        rel["秘密"].append(random.choice(["曾深夜独处一室", "互赠信物", "密信往来", "被人撞见过一次眼神"]))
        old_stage = rel["关系阶段"]
        rel["关系阶段"] = _stage_of(rel["情感值"])
        if rel["关系阶段"] != old_stage:
            rel["风险值"] = min(100, rel["风险值"] + 10)
            msg = f"🌘 你与{rel['对象']}的情意已至「{rel['关系阶段']}」。他承诺：{spec['能力']}，随时为你所用。（风险+10）"
        else:
            msg = f"🌒 你与{rel['对象']}又见了一面，情意更笃（情感+，风险+）"
    _log(sr, f"私通推进：{rel['对象']}（{rel['关系阶段']}·风险{rel['风险值']}）")
    game_state.add_memory(f"私会：{rel['对象']}（{rel['关系阶段']}）")
    return True, msg


def use_affair_perk(game_state, name):
    """动用私通对象的特殊能力（§2.6）。"""
    sr = get_affairs(game_state)
    rel = next((r for r in sr["player"] if r["对象"] == name), None)
    if not rel:
        return None, "查无此段关系"
    if rel["关系阶段"] not in ("私交", "深交", "情缘"):
        return False, "交情尚浅（需私交及以上），人家未必肯冒险"
    ability = rel["特殊能力"]
    if ability == "伪造脉案":
        rel["风险值"] = max(0, rel["风险值"] - 10)
        return True, f"💊 {name}为你伪造了一份脉案，旧疾有了新的说法（风险-10）"
    if ability == "禁军情报":
        from app import _append_intrigue_rumor
        _append_intrigue_rumor(game_state, {"target": "后宫", "type": "npc", "severity": 1,
                                            "turns_left": 3,
                                            "text": f"🌕 {name}递来的话：近日宫门岗哨换防有异动",
                                            "source": "affair"})
        return True, f"🌕 {name}抄了份禁军换防的路程图给你（得情报一条）"
    if ability == "朝堂情报":
        faction = random.choice(["文官党", "武官党"])
        from app import normalize_court_faction_favor
        favor = normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None))
        favor[faction] = min(100, favor.get(faction, 50) + 3)
        game_state.court_faction_favor = favor
        return True, f"🏛️ {name}为你递了句朝堂的话，{faction}对你观感好了些（{faction}+3）"
    if ability == "宗室奥援":
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"),
                                            game_state.attributes.get("威望", 0) + 3)
        return True, f"🏵️ {name}在宗宴上替你说了话，宗室间都知你有个靠山（威望+3）"
    if ability == "跑腿传递":
        rel["风险值"] = max(0, rel["风险值"] - 5)
        return True, f"🤫 {name}替你把一桩隐患抹平了（风险-5）"
    if ability == "情感支撑":
        game_state.attributes["健康"] = min(game_state.get_attr_max("健康"),
                                            game_state.attributes.get("健康", 60) + 4)
        return True, f"🌸 与{name}说话的半个时辰，是你近来唯一能喘息的时刻（健康+4）"
    return False, "此人帮不上什么忙"


def mitigate_risk(game_state, name, way):
    """消解风险五式（§2.5）。"""
    from app import guard_action, check_and_consume_action
    sr = get_affairs(game_state)
    rel = next((r for r in sr["player"] if r["对象"] == name), None)
    if not rel:
        return None, "查无此段关系"
    spec = MITIGATIONS.get(way)
    if not spec:
        return None, "无效的消解方式"
    if way == "cut":
        rel["风险值"] = max(0, rel["风险值"] + spec["risk"])
        rel["情感值"] = 0
        rel["关系阶段"] = "偶遇"
        rel["忠诚度"] = max(0, rel["忠诚度"] - 30)
        return True, f"✂️ 你与{name}断了。他转身时眼里的东西，你不敢细看（风险{spec['risk']}，恐生怨）"
    if way == "bribe_knower":
        if game_state.silver < spec["silver"]:
            return False, f"银两不足（需{spec['silver']}两）"
        game_state.silver -= spec["silver"]
        rel["风险值"] = max(0, rel["风险值"] + spec["risk"])
        return True, f"🪙 那张多嘴的嘴被银子缝上了（风险{spec['risk']}）"
    if way == "silence":
        if game_state.attributes.get("心计", 0) < spec["min_scheme"]:
            return False, f"心计不足{spec['min_scheme']}，灭口不成反受其乱"
        rel["风险值"] = 0
        rel["秘密"] = []
        rel["忠诚度"] = 100
        game_state.attributes["威望"] = max(0, game_state.attributes.get("威望", 0) - 15)
        game_state.add_memory(f"灭口：与{name}相关的隐患")
        return True, f"🌑 深宫又少了一个知道秘密的人。你的手很稳，只是夜里偶尔会醒（风险清零，威望-15）"
    if way == "divert":
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
        for _ in range(spec["actions"] - 1):
            check_and_consume_action(game_state)
        rel["风险值"] = max(0, rel["风险值"] + spec["risk"])
        return True, f"🎭 一场恰到好处的戏，把众人目光引去了别处（风险{spec['risk']}）"
    if way == "confess_dowager":
        tai = game_state.relationships.get("太后", {})
        if tai.get("好感", 0) < spec["min_dowager"]:
            return False, f"太后好感不足{spec['min_dowager']}"
        rel["风险值"] = max(0, rel["风险值"] + spec["risk"])
        rel["情感值"] = max(0, rel["情感值"] - 30)
        return True, f"👵 你跪在太后膝前陈情。太后叹了口气替你压下此事——但{name}被调出了宫（风险{spec['risk']}）"
    return None, "无效的消解方式"


# ===== NPC 私通：发现与处置（§四） =====
def probe_npc_affair(game_state):
    """刺探宫闱：1行动点+20两，可能发现某 NPC 的私通。"""
    from app import guard_action
    ok, err = guard_action(game_state)
    if not ok:
        return False, err
    if game_state.silver < 20:
        return False, "银两不足（需20两）"
    game_state.silver -= 20
    sr = get_affairs(game_state)
    candidates = [n for n, c in (game_state.npcs or {}).items()
                  if isinstance(c, dict) and c.get("alive", True) and n != game_state.name
                  and n not in sr["npc"]]
    hidden = [n for n in sr["hidden_npc"] if n in candidates]
    if hidden and random.random() < 0.6:
        name = random.choice(hidden)
        sr["npc"][name] = dict(sr["hidden_npc"].pop(name))
        sr["npc"][name]["掌握证据"] = [f"{sr['npc'][name]['对象']}的密信抄本"]
        return True, (f"🕸️ 你拿到了实证——{name}与{sr['npc'][name]['对象']}（{sr['npc'][name]['对象身份']}）"
                      f"往来已非一日（关系阶段：{sr['npc'][name]['关系阶段']}）。证据在手，去留随你。")
    if candidates and random.random() < 0.25:
        name = random.choice(candidates)
        affair = {
            "对象": _contact_name(random.choice(list(TARGET_TYPES)), set()),
            "对象身份": random.choice([v["身份"] for v in TARGET_TYPES.values()]),
            "关系阶段": random.choice(["偶遇", "熟识", "私交"]),
            "风险值": random.randint(20, 50),
            "秘密": ["往来书信"],
            "情感值": random.randint(20, 60),
            "掌握证据": ["宫人转述的私会"],
        }
        sr["npc"][name] = affair
        return True, f"🕸️ 意外之获——{name}与{affair['对象']}（{affair['对象身份']}）似乎有私情。真伪尚需斟酌。"
    return True, "🕸️ 你竖着耳朵听了半日，后宫表面风平浪静。"


def dispose_npc_affair(game_state, name, op):
    """处置已发现的 NPC 私通（§4.2 四式）。"""
    from app import guard_action, RANK_LEVELS
    sr = get_affairs(game_state)
    affair = sr["npc"].get(name)
    if not affair:
        return None, "未掌握此人的秘密"
    if op == "keep":
        return True, f"📜 你把{name}的把柄收进了妆匣最底层——来日方长。"
    if op == "expose":
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
        gain = random.randint(10, 20)
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"),
                                            game_state.attributes.get("威望", 0) + gain)
        npc = (game_state.npcs or {}).get(name)
        faction = npc.get("clan", {}).get("政治倾向") if isinstance(npc, dict) else ""
        if faction:
            favor = {"文官党": 50, "武官党": 50, "宗室党": 50}
            favor.update(getattr(game_state, "court_faction_favor", None) or {})
            favor[faction] = max(0, favor.get(faction, 50) - 10)
            game_state.court_faction_favor = favor
        if isinstance(npc, dict) and RANK_LEVELS.get(npc.get("rank", ""), 0) < RANK_LEVELS.get("皇后", 99):
            from cold_palace import admit_npc as cp_admit
            cp_admit(game_state, name, "私通外人有据，协理裁处")
            return True, f"⚖️ 你将{name}与{affair['对象']}的私情呈上。皇帝震怒，{name}被贬入冷宫（威望+{gain}，{faction or '其族'}-10）"
        return True, f"⚖️ 你将{name}的私情密奏御前。皇帝虽未发作，{name}从此失了圣心（威望+{gain}）"
    if op == "blackmail":
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
        silver = random.randint(150, 300)
        game_state.silver += silver
        rel = game_state.relationships.setdefault(name, {"好感": 0, "印象": "陌生", "互动次数": 0})
        rel["好感"] = max(-100, rel["好感"] - 20)
        rel["印象"] = "忌惮"
        return True, f"💰 {name}奉上白银{silver}两，只求你守口如瓶。她看你的眼神，从此带了恨（关系-20）"
    if op == "control":
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
        affair["被控制"] = True
        rel = game_state.relationships.setdefault(name, {"好感": 0, "印象": "陌生", "互动次数": 0})
        rel["好感"] = min(100, rel["好感"] + 30)
        rel["印象"] = "畏服"
        return True, f"🤝 {name}成了你手里的一枚棋子——她别无选择（关系+30，畏服）"
    return None, "无效的处置方式"


# ===== 狸猫换皇子（§三） =====
def swap_eligibility(game_state):
    sr = get_affairs(game_state)
    blockers = []
    from app import RANK_LEVELS
    if RANK_LEVELS.get(game_state.rank.name, 0) < RANK_LEVELS.get(SWAP_MIN_RANK, 0):
        blockers.append(f"位份不足：需{SWAP_MIN_RANK}及以上")
    if game_state.attributes.get("心计", 0) < SWAP_MIN_SCHEME:
        blockers.append(f"心计不足{SWAP_MIN_SCHEME}，谋不成这等局")
    if game_state.silver < SWAP_COST:
        blockers.append(f"银两不足：打点需{SWAP_COST}两")
    inside = [r for r in sr["player"]
              if r["对象类型"] in ("太医", "侍卫", "宫人") and r["关系阶段"] in ("私交", "深交", "情缘")]
    if not inside:
        blockers.append("缺少可靠内应（需太医/侍卫/宫人且关系达私交）")
    return {"ok": not blockers, "blockers": blockers, "insiders": [_rel_snapshot(r) for r in inside]}


def swap_start_plan(game_state, insider_name):
    """阶段一：密谋——接受计划。"""
    sr = get_affairs(game_state)
    sw = sr["swap"]
    if sw["phase"]:
        return False, "狸猫之局已在进行中"
    el = swap_eligibility(game_state)
    if not el["ok"]:
        return False, el["blockers"][0]
    insider = next((r for r in sr["player"] if r["对象"] == insider_name), None)
    if not insider or insider["对象类型"] not in ("太医", "侍卫", "宫人") \
            or insider["关系阶段"] not in ("私交", "深交", "情缘"):
        return False, "所选内应不可托付此等大事"
    if game_state.silver < SWAP_COST:
        return False, f"银两不足（需{SWAP_COST}两）"
    game_state.silver -= SWAP_COST
    sw["phase"] = "plan"
    sw["内应"] = insider_name
    sw["孕旬"] = 0
    game_state.add_memory(f"💀 密谋：狸猫换子（内应{insider_name}）")
    return True, (f"🕯️ {insider_name}叩首领命。自今日起，你「有孕在身」——宫外那位临盆的妇人、"
                  f"接生的稳婆、打点的银钱，都已铺好。约需{SWAP_PREGNANCY_PERIODS}旬，"
                  f"届时便是「生产之日」。（已支{SWAP_COST}两）")


def swap_execute(game_state):
    """阶段二：执行——生产之日。"""
    sr = get_affairs(game_state)
    sw = sr["swap"]
    if sw["phase"] != "ready":
        return None, "时机未到"
    insider = next((r for r in sr["player"] if r["对象"] == sw["内应"]), None)
    loyalty = int(insider["忠诚度"]) if insider else 50
    rate = int(60 + game_state.attributes.get("心计", 40) / 10 + loyalty / 5)
    roll = random.randint(1, 100)
    if roll > rate:
        if roll > 85:  # 重度失败：被察觉 → 直接案发
            sw["phase"] = "executed"
            sw["风险值"] = 85
            sw["案发"] = True
            return True, ("💔 产房里多了一双不该有的眼睛。事情瞒不住了吗……你听见外面传旨的脚步声。"
                          "（执行败露，狸猫案发！）")
        sw["phase"] = "ready"
        sw["风险值"] = min(100, sw["风险值"] + 15)
        game_state.silver -= 100
        return True, ("⚠️ 接生婆的手抖了一下，她看见了。你按住她的手——灭口或收买，须得选一样。"
                      "（轻险过关，风险+15，建议即刻善后）")
    # 成功：孩子入宫
    gender = "皇子" if random.random() < 0.6 else "公主"
    name = _new_child_name(game_state, gender)
    child = _create_newborn(game_state, gender, name)
    from app import ensure_child_uid, set_player_rank, get_next_rank_name
    ensure_child_uid(game_state, child)
    child["血统"] = "换入"       # 隐藏血统标记（前端不展示）
    game_state.children.append(child)
    game_state.has_children = True
    sw["phase"] = "executed"
    sw["child_uid"] = child["uid"]
    sw["真实父母"] = {"父亲": "宫外", "母亲": "宫外妇人"}
    sw["知情者"] = [sw["内应"], "接生稳婆"]
    sw["风险值"] = 25
    new_rank = get_next_rank_name(game_state.rank.name)
    if new_rank:
        set_player_rank(game_state, new_rank)
    game_state.attributes["威望"] = min(game_state.get_attr_max("威望"),
                                        game_state.attributes.get("威望", 0) + 20)
    game_state.add_memory(f"🕯️ 「诞下」{gender}{name}——狸猫已入巢")
    return True, (f"👶 你听到了孩子的哭声。\n「恭喜娘娘，是位{gender}。」\n"
                  f"你抱着他，心中百感交集——这孩子是你的，你选择他是你的，他就是你的。"
                  f"皇帝闻讯龙颜大悦，你晋封{game_state.rank.name}，威望+20。\n"
                  f"⚠️ 秘密已埋下（风险25）：知情者{sw['知情者']}，善后宜早。")


def swap_aftercare(game_state, way):
    """阶段三：善后四选。"""
    sr = get_affairs(game_state)
    sw = sr["swap"]
    if sw["phase"] != "executed":
        return None, "无局可善后"
    if way == "silence_witness":
        if game_state.silver < 100:
            return False, "银两不足（需100两）"
        game_state.silver -= 100
        sw["知情者"] = [w for w in sw["知情者"] if w != "接生稳婆"]
        sw["风险值"] = max(0, sw["风险值"] - 30)
        return True, "🌑 接生婆一家连夜「迁居」出京。世上少了一个知情人（风险-30）"
    if way == "retire_medic":
        if game_state.silver < 50:
            return False, "银两不足（需50两）"
        game_state.silver -= 50
        sw["知情者"] = [w for w in sw["知情者"] if w != sw["内应"]]
        insider = next((r for r in sr["player"] if r["对象"] == sw["内应"]), None)
        if insider:
            sr["player"].remove(insider)
        sw["内应"] = ""
        sw["风险值"] = max(0, sw["风险值"] - 20)
        return True, "📜 内应告老还乡的文书批了下来。少了个内应，也少了个把柄（风险-20）"
    if way == "bribe_maids":
        if game_state.silver < 80:
            return False, "银两不足（需80两）"
        game_state.silver -= 80
        sw["风险值"] = max(0, sw["风险值"] - 15)
        return True, "🪙 产房上下都领了赏，人人都是「什么也没看见」（风险-15）"
    if way == "nothing":
        sw["风险值"] = min(100, sw["风险值"] + 20)
        return True, "🌫️ 你选择静观其变。可纸包不住火（风险+20）"
    return None, "无效的善后方式"


def swap_case_respond(game_state, choice):
    """阶段五：案发三选。"""
    from app import trigger_ending
    sr = get_affairs(game_state)
    sw = sr["swap"]
    if not sw.get("案发"):
        return None, "尚无事发"
    if choice == "deny":
        rate = int(20 + game_state.attributes.get("心计", 40) / 10)
        if random.randint(1, 100) <= rate:
            sw["风险值"] = 50
            sw["案发"] = False
            flags = getattr(game_state, "story_flags", [])
            if isinstance(flags, list) and "皇帝疑心" not in flags:
                flags.append("皇帝疑心")
            return True, "🗡️ 你跪得笔直，字字咬得清楚。皇帝盯着你良久，挥手退朝——半信半疑（风险50，皇帝疑心）"
        trigger_ending(game_state, "狸猫之祸", "抵死不认，却人证物证俱全")
        return True, "⚖️ 你抵死不认。可铁证如山……旨意落下时，殿外正打雷。（终局：狸猫之祸）"
    if choice == "confess":
        trigger_ending(game_state, "废为庶人", "全盘托出，坦白从宽")
        return True, "📜 你把一切原原本本说了。皇帝闭目良久：「废为庶人，逐出宫外。」（终局：废为庶人）"
    if choice == "frame":
        insider = next((r for r in sr["player"] if r["对象"] == sw["内应"]), None)
        if not insider or insider["情感值"] < 40:
            return False, "嫁祸需知情且情深的内应顶罪——此人如今靠不住"
        ok_case = random.random() < 0.5 + insider["情感值"] / 200
        if ok_case:
            sr["player"].remove(insider)
            sw["知情者"] = []
            sw["风险值"] = 10
            sw["案发"] = False
            game_state.attributes["威望"] = max(0, game_state.attributes.get("威望", 0) - 5)
            return True, "🎭 内应叩首领罪，一口咬定此事与你无关。你脱了身——从此你欠他一命，他已不在人世（风险10）"
        trigger_ending(game_state, "狸猫之祸", "嫁祸败露，罪加一等")
        return True, "⚖️ 嫁祸的事被当场戳穿，皇帝的刀比你想的快。（终局：狸猫之祸）"
    return None, "无效的应对"


def _new_child_name(game_state, gender):
    from app import new_child_name
    return new_child_name(gender, game_state)


def _create_newborn(game_state, gender, name):
    from app import create_newborn_child
    return create_newborn_child(gender, name, game_state, mother_name=game_state.name)


# ===== 转旬引擎（§2.4/§2.5/§3.4 阶段四/五） =====
def process_affair_period(game_state):
    """转旬：风险累积 + 阈值事件 + NPC 私通暗流 + 狸猫孕程/案发。返回消息列表。"""
    sr = get_affairs(game_state)
    msgs = []
    # 玩家私通：持续存在风险 + 阈值事件
    for rel in sr["player"]:
        rel["风险值"] = min(100, rel["风险值"] + random.randint(1, 2))
        r = rel["风险值"]
        if r >= 85 and not rel.get("_case"):
            rel["_case"] = True
            from app import trigger_ending
            trigger_ending(game_state, "废为庶人", f"与{rel['对象']}私通事败，圣意难回")
            msgs.append(f"⚖️ 你与{rel['对象']}的私情传到了御前……（终局：废为庶人）")
            break
        if r >= 70 and not rel.get("_warn70"):
            rel["_warn70"] = True
            msgs.append(f"⚠️ 有妃嫔似已察觉你与{rel['对象']}的私情——灭口、收买、断绝，宜早做决断")
        elif r >= 50 and not rel.get("_warn50"):
            rel["_warn50"] = True
            msgs.append(f"🌙 宫里开始有人对你与{rel['对象']}的往来嚼舌根了（风险{r}）")
        elif r >= 30 and not rel.get("_warn30"):
            rel["_warn30"] = True
            msgs.append(f"🤫 隐约有人觉得你最近「不大对劲」（风险{r}）")
    # 情感支撑（§2.6）：有深交及以上关系，每旬恢复
    if any(r["关系阶段"] in ("深交", "情缘") for r in sr["player"]):
        game_state.attributes["健康"] = min(game_state.get_attr_max("健康"),
                                            game_state.attributes.get("健康", 60) + 2)
    # NPC 私通暗流
    if random.random() < 0.06:
        alive = [n for n, c in (game_state.npcs or {}).items()
                 if isinstance(c, dict) and c.get("alive", True) and n != game_state.name
                 and n not in sr["hidden_npc"] and n not in sr["npc"]]
        if alive:
            name = random.choice(alive)
            sr["hidden_npc"][name] = {
                "对象": _contact_name(random.choice(list(TARGET_TYPES)), set()),
                "对象身份": random.choice([v["身份"] for v in TARGET_TYPES.values()]),
                "关系阶段": random.choice(["偶遇", "熟识", "私交"]),
                "风险值": random.randint(20, 60),
                "秘密": ["私会目击"],
                "情感值": random.randint(20, 60),
            }
    # 狸猫孕程
    sw = sr["swap"]
    if sw["phase"] == "plan":
        sw["孕旬"] += 1
        if sw["孕旬"] >= SWAP_PREGNANCY_PERIODS:
            sw["phase"] = "ready"
            msgs.append("🕯️ 产期将至。稳婆都已备好，「生产之日」到了——去狸猫局中执行吧")
        elif sw["孕旬"] == 2:
            msgs.append("🤰 你「害喜」的模样做足了，皇帝闻讯颇为欣喜")
    elif sw["phase"] == "executed" and not sw["案发"]:
        insider_alive = sw["内应"] == "" or any(r["对象"] == sw["内应"] for r in sr["player"])
        drift = random.randint(1, 2) + (3 if sw["知情者"] and not insider_alive else 0) \
            + (3 if sw["知情者"] else 0)
        sw["风险值"] = min(100, sw["风险值"] + drift)
        if random.random() < 0.1:
            sw["风险值"] = min(100, sw["风险值"] + 10)
            msgs.append("👶 宫人私下议论：小皇子长得……似乎不大像陛下（身世疑云，风险+10）")
        if sw["风险值"] >= SWAP_CASE_RISK and not sw["案发"]:
            sw["案发"] = True
            msgs.append("⚖️ 事发——太医署的旧档被人翻了出来。皇帝已知一切，只差你一个交代！（狸猫案发：抵死不认/全盘托出/嫁祸于人）")
    return msgs
