# royal_clan.py — 宗室系统引擎（设计稿 v2.0）
# 宗室男性（亲王/郡王/国公/宗室男/老王爷）+ 宗室女性（长公主/大长公主/郡主/县主/宗室女）
# + 宗人府（大宗正/削爵/除名/袭爵）+ 两翼联动 + 玩法接口
import random

from names import random_given, EMPEROR_GIVEN

# ===== 常量（§2.1 / §3.1） =====
PRINCE_COUNT = (3, 4)          # 亲王
JUNWANG_COUNT = (6, 8)         # 郡王
GUOGONG_COUNT = (4, 6)         # 国公
ELDER_COUNT = (1, 2)           # 宗室长辈（老王爷）
ZHANG_GONGZHU = (1, 2)         # 长公主
ROYAL_FEMALE_EXTRA = (2, 3)    # 旁系宗室女（可入宫候选）
ROYAL_CLAN_LOG_MAX = 20

WANG_TITLES = ["雍", "晋", "楚", "齐", "燕", "赵", "魏", "韩", "秦", "蜀", "吴", "越", "郑", "卫"]

FEMALE_TITLES = ["景阳", "华阳", "清宁", "永宁", "安平", "乐平", "长宁", "兴平", "定安", "宣宁"]

MALE_GIVEN_POOL = ["承", "弘", "煜", "珩", "琛", "翊", "勋", "煦", "晟", "澜", "澈", "恒"]

ACTIONS_MALE = {
    "ally": {"name": "结盟", "min_rel": 30, "cost": {}, "desc": "关系≥30：结成宗室-外戚联合体"},
    "advise": {"name": "献计", "min_rel": 20, "cost": {"actions": 1}, "desc": "关系≥20：借其口向圣上传话"},
    "aid": {"name": "求援", "min_rel": 50, "cost": {}, "desc": "关系≥50：获宗室接济银两（每旬一次）"},
    "report": {"name": "举报", "min_rel": -100, "cost": {}, "desc": "掌握谋逆迹象可揭发，换皇帝信任"},
    "marry_off": {"name": "联姻", "min_rel": 30, "cost": {}, "desc": "将己出公主嫁入宗室，结永久之盟"},
}
ACTIONS_FEMALE = {
    "befriend": {"name": "结交", "min_rel": 0, "cost": {"silver": 20}, "desc": "赠礼结交，增进情分"},
    "pull": {"name": "拉拢", "min_rel": 20, "cost": {"silver": 50}, "desc": "借郡主影响其父系（郡主/县主专属）"},
    "intel": {"name": "获取情报", "min_rel": 20, "cost": {"actions": 1}, "desc": "听见宗室内部谈话，化作流言"},
    "recommend": {"name": "推荐入宫", "min_rel": 30, "cost": {"actions": 1}, "desc": "宗室女进入下届选秀名册"},
    "match": {"name": "促成联姻", "min_rel": 20, "cost": {"silver": 100}, "desc": "嫁入外戚世家，两族结好"},
    "bond": {"name": "结为手帕交", "min_rel": 30, "cost": {}, "desc": "与宗室女义结金兰（长公主需威望≥60）"},
}


def default_royal_clan():
    return {
        "dazongzheng": "",
        "males": {},        # 名字 -> 成员
        "females": {},      # 名字 -> 成员
        "allies": [],       # 玩家结盟的宗室男
        "handkerchief": [], # 手帕交宗室女
        "aid_used_period": "",
        "pending": [],      # 待办事件（玩家可响应）
        "log": [],
        "seeded": False,
    }


def get_royal_clan(game_state):
    rc = getattr(game_state, "royal_clan", None)
    if not isinstance(rc, dict):
        rc = default_royal_clan()
        game_state.royal_clan = rc
    for k, v in default_royal_clan().items():
        rc.setdefault(k, v)
    return rc


def _royal_surname(game_state):
    emp = game_state.emperor or {}
    return str(emp.get("name", "萧"))[:1] or "萧"


def _male_name(game_state, used):
    for _ in range(300):
        name = _royal_surname(game_state) + random.choice(MALE_GIVEN_POOL) + random_given(EMPEROR_GIVEN, 0.6)
        if name not in used:
            used.add(name)
            return name
    while True:
        name = f"{_royal_surname(game_state)}{random.choice(MALE_GIVEN_POOL)}·{random.randint(2, 99)}"
        if name not in used:
            used.add(name)
            return name


def _female_name(used):
    for _ in range(300):
        name = random.choice(FEMALE_TITLES)
        if name not in used:
            used.add(name)
            return name
    # 封号池不足（宗室繁衍后名册庞大）时加排行后缀保证唯一
    while True:
        name = f"{random.choice(FEMALE_TITLES)}·{random.randint(2, 99)}"
        if name not in used:
            used.add(name)
            return name


def _derive_stance(m):
    """立场由帝眷与野心共同推导（§2.5）。"""
    score = int(m["帝眷"]) - int(m["野心"]) * 0.5
    if score > 40:
        return "拥皇"
    if score < -10:
        return "反皇"
    return "中立"


def _make_male(game_state, used, title, *, fief=None, generation="同辈", age=None, father=""):
    dijuan = random.randint(15, 85) if generation != "长辈" else random.randint(40, 80)
    m = {
        "name": _male_name(game_state, used),
        "爵位": title,
        "封地": fief or "",
        "generation": generation,          # 长辈/同辈/子侄
        "father": father,
        "年龄": age or (random.randint(55, 75) if generation == "长辈" else
                    random.randint(22, 45) if generation == "同辈" else random.randint(14, 30)),
        "帝眷": dijuan,
        "野心": random.randint(5, 90),
        "实力": random.randint(20, 80) if title in ("亲王", "郡王") else random.randint(10, 45),
        "立场": "中立",
        "关系": random.randint(-10, 20),
        "妻妾": [],
        "子女": 0,
        "alive": True,
        "标记": [],
    }
    if title == "亲王" and not m["封地"]:
        m["封地"] = f"{m['name'][1:]}州"
    m["立场"] = _derive_stance(m)
    return m


def _make_female(game_state, used, title, *, father="", 身份="", age=None):
    influence = 80 if title in ("大长公主", "长公主") else random.randint(15, 60)
    f = {
        "name": _female_name(used),
        "称号": title,
        "身份": 身份 or (f"{father}之女" if father else "宗室女"),
        "父系": father,
        "年龄": age if age is not None else random.randint(8, 22) if title in ("郡主", "县主", "宗室女") else random.randint(45, 62),
        "影响力": influence,
        "与太后关系": random.randint(-10, 40),
        "与皇帝关系": random.randint(-10, 50) if title in ("大长公主", "长公主") else random.randint(0, 40),
        "与玩家关系": random.randint(-5, 15),
        "婚配状态": "待字闺中" if title in ("郡主", "县主", "宗室女") else random.choice(["守寡", "已嫁"]),
        "联姻潜力": random.randint(30, 90) if title in ("郡主", "县主", "宗室女") else 0,
        "标记": (["宗室长辈", "可入宫"] if title in ("大长公主", "长公主") else
             (["可入宫候选"] if title == "宗室女" else ["可入宫"])),
        "alive": True,
    }
    return f


def seed_royal_clan(game_state):
    """开局世系生成（§2.1/§3.1/大宗正遴选）。旧档缺省时自动补种。"""
    rc = get_royal_clan(game_state)
    if rc.get("seeded"):
        return rc
    used = set()
    # 老王爷（宗室长辈）
    for _ in range(random.randint(*ELDER_COUNT)):
        m = _make_male(game_state, used, random.choice(["亲王", "郡王"]), generation="长辈")
        m["标记"].append("三朝元老")
        rc["males"][m["name"]] = m
    # 亲王：皇帝兄弟（同辈）
    princes = []
    for _ in range(random.randint(*PRINCE_COUNT)):
        m = _make_male(game_state, used, "亲王", generation="同辈")
        princes.append(m)
        rc["males"][m["name"]] = m
    # 郡王：亲王之子（子侄辈）+ 近支
    for _ in range(random.randint(*JUNWANG_COUNT)):
        father = random.choice(princes)["name"] if random.random() < 0.5 else ""
        m = _make_male(game_state, used, "郡王", generation="子侄" if father else "同辈", father=father)
        rc["males"][m["name"]] = m
    # 国公：远支
    for _ in range(random.randint(*GUOGONG_COUNT)):
        m = _make_male(game_state, used, "国公", generation="子侄")
        rc["males"][m["name"]] = m
    # 长公主 / 大长公主
    for _ in range(random.randint(*ZHANG_GONGZHU)):
        f = _make_female(game_state, used, "长公主", 身份="先帝之妹", age=random.randint(45, 60))
        rc["females"][f["name"]] = f
    if random.random() < 0.35:
        f = _make_female(game_state, used, "大长公主", 身份="皇帝之姑祖母", age=random.randint(62, 74))
        rc["females"][f["name"]] = f
    # 郡主（亲王之女）/ 县主（郡王之女）
    for m in rc["males"].values():
        if m["爵位"] not in ("亲王", "郡王"):
            continue
        for _ in range(random.choice([0, 0, 1, 1, 2])):
            title = "郡主" if m["爵位"] == "亲王" else "县主"
            f = _make_female(game_state, used, title, father=m["name"], 身份=f"{m['name']}之女")
            rc["females"][f["name"]] = f
    # 旁系宗室女（可入宫候选）
    for _ in range(random.randint(*ROYAL_FEMALE_EXTRA)):
        f = _make_female(game_state, used, "宗室女", 身份="宗室旁系之女", age=random.randint(15, 19))
        rc["females"][f["name"]] = f
    # 大宗正：优先老王爷，否则帝眷最高的亲王
    elders = [m for m in rc["males"].values() if m["generation"] == "长辈" and m["alive"]]
    if elders:
        rc["dazongzheng"] = elders[0]["name"]
    else:
        pr = sorted((m for m in rc["males"].values() if m["爵位"] == "亲王" and m["alive"]),
                    key=lambda x: -x["帝眷"])
        rc["dazongzheng"] = pr[0]["name"] if pr else ""
    rc["seeded"] = True
    _log(rc, "宗人府呈上玉牒，宗室名册归档")
    return rc


def _log(rc, text):
    rc["log"].insert(0, f"[{text}]")
    del rc["log"][ROYAL_CLAN_LOG_MAX:]


def _add_pending(rc, kind, title, desc, payload=None):
    rc["pending"].append({"id": f"rp{len(rc['pending']) + 1}_{random.randint(100, 999)}",
                          "kind": kind, "title": title, "desc": desc, "payload": payload or {}})
    del rc["pending"][6:]


def alive_males(rc):
    return [m for m in rc["males"].values() if m.get("alive")]


def alive_females(rc):
    return [f for f in rc["females"].values() if f.get("alive")]


def royal_overview(game_state):
    rc = seed_royal_clan(game_state)
    males = sorted(alive_males(rc), key=lambda m: (-{"亲王": 0, "郡王": 1, "国公": 2}.get(m["爵位"], 3), -m["帝眷"]))
    females = sorted(alive_females(rc), key=lambda f: (-{"大长公主": 0, "长公主": 1, "郡主": 2, "县主": 3}.get(f["称号"], 4), -f["影响力"]))
    return rc, males, females


def _faction_favor(game_state, faction, delta):
    favor = {"文官党": 50, "武官党": 50, "宗室党": 50}
    favor.update(getattr(game_state, "court_faction_favor", None) or {})
    if faction in favor:
        favor[faction] = max(0, min(100, int(favor[faction] or 0) + delta))
    game_state.court_faction_favor = favor


# ===== 转旬引擎（§2.5 / §5 / §6 / §7） =====
def process_royal_clan_period(game_state):
    """转旬：立场演化 + 世系繁衍 + 专属事件 + 谋逆链 + 爵位流转。返回情报消息列表。"""
    rc = seed_royal_clan(game_state)
    msgs = []
    # --- 宫中宗室女反馈（§6.2：受宠/失宠 → 父系帝眷/立场） ---
    for npc in (game_state.npcs or {}).values():
        if not isinstance(npc, dict) or not npc.get("alive", True) or not npc.get("royal_father"):
            continue
        m = rc["males"].get(npc["royal_father"])
        if not m or not m.get("alive"):
            continue
        favor = int((npc.get("attributes") or {}).get("宠爱", 30) or 0)
        if favor >= 70 and m["帝眷"] < 100:
            m["帝眷"] += 1
        elif favor <= 20 and m["帝眷"] > 0:
            m["帝眷"] -= 1
        m["立场"] = _derive_stance(m)
    # --- 立场自动演化（§2.5） ---
    for m in alive_males(rc):
        if m["帝眷"] > 70 and m["立场"] != "拥皇" and random.random() < 0.3:
            m["立场"] = "拥皇"
        elif m["帝眷"] < 30 and m["立场"] != "反皇" and random.random() < 0.3:
            m["立场"] = "反皇"
        elif 30 <= m["帝眷"] <= 70 and random.random() < 0.1:
            m["立场"] = _derive_stance(m)
    # --- 谋逆链（§2.4：野心≥70 且 帝眷≤30） ---
    for m in alive_males(rc):
        if m["野心"] >= 70 and m["帝眷"] <= 30 and m["爵位"] in ("亲王", "郡王") and random.random() < 0.08:
            msgs.extend(_rebellion_chain(game_state, rc, m))
            break  # 一旬至多一案
    # --- 世系繁衍（§5.1：每年1月 20%） ---
    if game_state.month == 1 and game_state.day <= 10:
        for m in alive_males(rc):
            if m["爵位"] in ("亲王", "郡王") and m["年龄"] < 55 and random.random() < 0.20:
                m["子女"] += 1
                if random.random() < 0.5:
                    used = set(rc["females"].keys())
                    title = "郡主" if m["爵位"] == "亲王" else "县主"
                    f = _make_female(game_state, used, title, father=m["name"],
                                     身份=f"{m['name']}之女", age=0)
                    f["标记"] = []
                    rc["females"][f["name"]] = f
                    _log(rc, f"{m['name']}喜得千金，襁褓之中已受封{title}")
                else:
                    _log(rc, f"{m['name']}府中添丁")
    # --- 爵位流转与寿终（§5.2） ---
    for name, m in list(rc["males"].items()):
        if not m.get("alive"):
            continue
        death_chance = 0.10 if (m["generation"] == "长辈" and m["年龄"] >= 68) else 0.004
        if random.random() < death_chance:
            msgs.extend(_succeed_title(game_state, rc, m))
    # --- 专属事件（男8/女10 中取代表事件，概率触发至多1件） ---
    if random.random() < 0.35:
        msgs.append(_royal_random_event(game_state, rc))
    return msgs


def _rebellion_chain(game_state, rc, m):
    """宗室谋逆：宗人府与皇帝合力镇压；其女受牵连降等；举报者得赏。"""
    msgs = []
    reported = m.get("reported", False)
    m["alive"] = False
    m["标记"].append("谋逆伏诛")
    loss = max(10, int(m["实力"]) // 3)
    _faction_favor(game_state, "宗室党", -8)
    game_state.attributes["威望"] = min(game_state.get_attr_max("威望"),
                                       game_state.attributes.get("威望", 0) + 3)
    msgs.append(f"⚔️ {m['name']}私藏甲胄、勾结边将，事败伏诛！宗人府除其宗籍（{m['爵位']}除爵，宗室党声势-{8}）")
    game_state.add_memory(f"{m['name']}谋逆伏诛，朝野震动")
    # 其女牵连降等（§6.2）
    for f in alive_females(rc):
        if f.get("父系") == m["name"] and f["称号"] == "郡主":
            f["称号"] = "县主"
            f["身份"] = f"罪宗{m['name']}之女"
            msgs.append(f"🍂 其女{f['name']}由郡主降为县主，迁出王府")
    if reported:
        gain = random.randint(8, 15)
        game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"),
                                            game_state.attributes.get("宠爱", 0) + gain)
        msgs.append(f"👑 因你先期密告，皇帝嘉你忠慎，宠爱+{gain}")
    _log(rc, f"{m['name']}谋逆伏诛")
    return msgs


def _succeed_title(game_state, rc, m):
    """宗室男身故：嫡子袭爵 → 庶子降等 → 除爵（§5.2）。老王爷告老与辞世共用。"""
    msgs = []
    m["alive"] = False
    heir = None
    for cand in alive_males(rc):
        if cand.get("father") == m["name"] and cand["年龄"] >= 12:
            heir = cand
            break
    if heir and m["爵位"] in ("亲王", "郡王"):
        old = heir["爵位"]
        heir["爵位"] = m["爵位"]
        heir["封地"] = m["封地"] or heir["封地"]
        if old != heir["爵位"]:
            msgs.append(f"📜 {heir['name']}袭{heir['爵位']}爵，承{m['name']}香火")
    elif m["爵位"] in ("亲王", "郡王"):
        msgs.append(f"🍂 {m['name']}薨逝无嗣，除爵，封地归朝廷")
    else:
        msgs.append(f"🕯️ {m['name']}薨逝")
    if rc["dazongzheng"] == m["name"]:
        cand = sorted(alive_males(rc), key=lambda x: -x["帝眷"])
        rc["dazongzheng"] = cand[0]["name"] if cand else ""
        msgs.append(f"🏛️ 宗人府大宗正之位由{rc['dazongzheng']}接任")
    if m["name"] in rc["allies"]:
        rc["allies"].remove(m["name"])
    _log(rc, f"{m['name']}薨逝")
    return msgs


def _royal_random_event(game_state, rc):
    """宗室专属随机事件（§2.4/§3.4/§7 代表事件）。"""
    m_pool = [m for m in alive_males(rc) if m["爵位"] in ("亲王", "郡王")]
    f_pool = alive_females(rc)
    roll = random.random()
    if roll < 0.2 and m_pool:
        m = random.choice(m_pool)
        m["帝眷"] = min(100, m["帝眷"] + 3)
        _log(rc, f"{m['name']}入宫朝见，皇帝赐金")
        return f"🏛️ {m['name']}入宫朝见，皇帝赐金千两，宗室与有荣焉"
    if roll < 0.35 and f_pool:
        f = random.choice([f for f in f_pool if f["称号"] in ("长公主", "大长公主")] or f_pool)
        for g in alive_females(rc):
            g["与玩家关系"] = max(-100, min(100, g["与玩家关系"] + 2))
        _log(rc, f"{f['name']}寿辰，宗室女齐聚")
        return f"🎂 {f['name']}寿辰，宗室女齐聚赴宴，是你结交的良机（宗室女好感+2）"
    if roll < 0.5 and f_pool:
        jz = [f for f in f_pool if f["称号"] in ("郡主", "县主") and f["婚配状态"] == "待字闺中"]
        if jz:
            f = random.choice(jz)
            f["与玩家关系"] = max(-100, min(100, f["与玩家关系"] + 3))
            _add_pending(rc, "jungu_visit", "郡主入宫小住",
                         f"{f['称号']}{f['name']}（{f.get('父系','')}之女）入宫小住，礼部请示由谁接待",
                         {"female": f["name"]})
            return f"🐲 {f['称号']}{f['name']}入宫小住，可主动结交"
    if roll < 0.62 and f_pool:
        elders = [f for f in f_pool if f["称号"] in ("长公主", "大长公主")]
        if elders:
            f = random.choice(elders)
            _add_pending(rc, "elder_debate", "长公主与太后争执",
                         f"{f['name']}与太后因宗室婚配事意见不合，各宫都在观望你站在哪一边",
                         {"female": f["name"]})
            return f"⚖️ {f['name']}与太后起了争执，宫中暗流涌动"
    if roll < 0.74 and m_pool:
        m = random.choice([x for x in m_pool if x["年龄"] >= 16 and x["爵位"] == "郡王"] or m_pool)
        _add_pending(rc, "junwang_marriage", "郡王议亲",
                     f"{m['name']}年已及冠，宗人府正为其议亲，各家都在递帖子",
                     {"male": m["name"]})
        return f"💒 宗人府为{m['name']}议亲，各方瞩目"
    # 宗室女与外戚议亲（§2.4）
    if roll < 0.86 and f_pool:
        f = random.choice([x for x in f_pool if x["称号"] in ("郡主", "宗室女") and x["婚配状态"] == "待字闺中"])
        faction = random.choice(["文官党", "武官党"])
        f["婚配状态"] = "已嫁"
        f["联姻潜力"] = 0
        _faction_favor(game_state, faction, 3)
        _log(rc, f"{f['name']}嫁入{faction}世家")
        return f"💒 {f['name']}嫁入{faction}世家，宗室与外戚自此多了一层姻亲"
    m_pool2 = [m for m in alive_males(rc) if m["generation"] == "长辈"]
    if m_pool2:
        m = m_pool2[0]
        msgs = _succeed_title(game_state, rc, m)
        return " ".join(msgs) if msgs else "🕯️ 宗室长辈静养"
    return "🏛️ 宗人府例行核档，波澜不惊"


# ===== 玩法接口（§2.3 / §3.3） =====
def _rel_key(member):
    """男性成员用「关系」，女性成员用「与玩家关系」（前端/概览沿用此键）。"""
    return "与玩家关系" if "与玩家关系" in member else "关系"


def _rel_get(member):
    return int(member.get(_rel_key(member), 0) or 0)


def _rel_change(member, delta):
    k = _rel_key(member)
    member[k] = max(-100, min(100, int(member.get(k, 0) or 0) + delta))


def royal_male_action(game_state, rc, member, action):
    """宗室男玩法接口（§2.3）。返回 (ok, msg)。"""
    from app import guard_action, check_and_consume_action
    spec = ACTIONS_MALE.get(action)
    if not spec:
        return False, "无效的宗室动作"
    if _rel_get(member) < spec["min_rel"]:
        return False, f"{spec['name']}需关系≥{spec['min_rel']}（当前{_rel_get(member)}）"
    if action == "ally":
        if member["name"] in rc["allies"]:
            return False, "你与她家已有盟约"
        rc["allies"].append(member["name"])
        _rel_change(member, 5)
        _faction_favor(game_state, "宗室党", 3)
        game_state.add_memory(f"与{member['name']}结为盟友")
        return True, f"🤝 你与{member['爵位']}{member['name']}歃血为盟，宗室-外戚联合体自此成形（宗室党+3）"
    if action == "advise":
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
        gain = 2 if member["帝眷"] > 50 else (1 if random.random() < 0.5 else -1)
        emp_rel = game_state.relationships.setdefault("皇帝", {"好感": 10})
        emp_rel["好感"] = max(0, min(100, emp_rel.get("好感", 10) + gain))
        _rel_change(member, 2)
        return True, f"📜 你托{member['name']}向圣上转陈一言，{'圣意颇纳' if gain > 0 else '圣意未察'}（皇帝好感{'+' if gain > 0 else ''}{gain}）"
    if action == "aid":
        period_key = f"{game_state.year}-{game_state.month}-{game_state.day}"
        if rc.get("aid_used_period") == period_key:
            return False, "本旬已得过接济，再求惹人嫌"
        if member["实力"] < 30:
            return False, f"{member['name']}自身难保，无力接济"
        rc["aid_used_period"] = period_key
        silver = 80 + int(member["实力"]) * 2
        game_state.silver += silver
        _rel_change(member, -5)
        game_state.add_memory(f"{member['name']}接济白银{silver}两")
        return True, f"💰 {member['name']}遣人送来白银{silver}两，解你燃眉之急（关系-5，人情要还）"
    if action == "report":
        if member["野心"] < 60 or member["立场"] != "反皇":
            return False, "此人并无谋逆迹象，妄告宗室反遭其祸"
        member["reported"] = True
        member["帝眷"] = max(0, member["帝眷"] - 15)
        gain = random.randint(4, 8)
        game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"),
                                            game_state.attributes.get("宠爱", 0) + gain)
        _rel_change(member, -30)
        game_state.add_memory(f"密告{member['name']}不法")
        return True, f"⚠️ 你密奏{member['name']}私蓄异志。皇帝览奏沉吟，宠爱+{gain}；宗人府已暗中盯紧此人"
    if action == "marry_off":
        if member["爵位"] not in ("亲王", "郡王") or member["妻妾"]:
            return False, "此王已有正妃，或爵位不足以尚主"
        girls = [c for c in (getattr(game_state, "children", []) or [])
                 if c.get("gender") == "公主" and c.get("alive", True)
                 and c.get("marriage_status") in ("未议", "议婚中") and float(c.get("age", 0) or 0) >= 15]
        if not girls:
            return False, "你膝下暂无适龄待嫁的公主"
        girl = girls[0]
        girl["marriage_status"] = "已嫁"
        girl["consort"] = {"name": member["name"], "faction": "宗室党",
                           "family_score": 60 + int(member["实力"]) // 4}
        girl["mansion"] = {"name": f"{member['name'][1:]}王府", "level": 2, "income": 15, "reputation": 60}
        _rel_change(member, 40)
        if member["name"] not in rc["allies"]:
            rc["allies"].append(member["name"])
        _faction_favor(game_state, "宗室党", 5)
        game_state.add_memory(f"公主{girl.get('name')}嫁入{member['name']}府")
        return True, f"💒 公主{girl.get('name')}与{member['name']}结缡，宗室-外戚永结同好（关系+40，宗室党+5）"
    return False, "无效的宗室动作"


def royal_female_action(game_state, rc, member, action):
    """宗室女玩法接口（§3.3）。返回 (ok, msg)。"""
    from app import guard_action
    spec = ACTIONS_FEMALE.get(action)
    if not spec:
        return False, "无效的宗室女动作"
    if _rel_get(member) < spec["min_rel"]:
        return False, f"{spec['name']}需关系≥{spec['min_rel']}（当前{_rel_get(member)}）"
    if action == "befriend":
        if game_state.silver < 20:
            return False, "银两不足，结交需20两"
        game_state.silver -= 20
        gain = random.randint(6, 12)
        _rel_change(member, gain)
        return True, f"🎁 你备了一份心意送进{member['称号']}府，{member['name']}回赠了亲手做的香囊（关系+{gain}）"
    if action == "pull":
        if member["称号"] not in ("郡主", "县主"):
            return False, "只有郡主/县主能直接影响其父系"
        father = rc["males"].get(member.get("父系"))
        if game_state.silver < 50:
            return False, "银两不足，拉拢需50两"
        game_state.silver -= 50
        _rel_change(member, 3)
        if father:
            father["帝眷"] = max(0, min(100, father["帝眷"] + 2))
            father["立场"] = _derive_stance(father)
            return True, f"🤲 你借{member['name']}向{father['name']}递了句话，王府承你的情（其父帝眷+2）"
        return True, f"🤲 {member['name']}应下你的请托，愿在宗室间为你美言"
    if action == "intel":
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
        text = random.choice([
            f"{member['name']}无意间提起：宗室近来为爵位承袭的事颇有争执",
            f"{member['name']}压低声音：有位王爷近来频繁接见边将",
            f"{member['name']}说：宗人府里有人为了玉牒上的名字在打点上下",
            f"{member['name']}提道：太后宫里的赏赐，近来频频流向某王府",
        ])
        from app import _append_intrigue_rumor
        _append_intrigue_rumor(game_state, {"target": "后宫", "type": "npc", "severity": 1,
                                            "turns_left": 3, "text": f"🏛️ {text}", "source": "royal_clan"})
        return True, f"🕵️ {text}"
    if action == "recommend":
        if member["称号"] != "宗室女" or "可入宫候选" not in member.get("标记", []):
            return False, "只有待选的宗室女可荐入宫闱"
        if member.get("recommended"):
            return False, "此女已应选，容宗人府备办"
        member["recommended"] = True
        member["婚配状态"] = "待字闺中"
        rc.setdefault("draft_inject", []).append(member["name"])
        game_state.add_memory(f"荐宗室女{member['name']}入宫候选")
        return True, f"📜 你为{member['name']}在宗人府挂了号，下届选秀名册上会多出一个名字"
    if action == "match":
        if member["婚配状态"] != "待字闺中":
            return False, "此女已字人家"
        if game_state.silver < 100:
            return False, "银两不足，促成联姻需100两"
        game_state.silver -= 100
        member["婚配状态"] = "已嫁"
        member["联姻潜力"] = 0
        faction = random.choice(["文官党", "武官党"])
        _faction_favor(game_state, faction, 5)
        father = rc["males"].get(member.get("父系"))
        if father:
            father["实力"] = min(100, father["实力"] + 3)
        _rel_change(member, 10)
        _log(rc, f"{member['name']}经你撮合嫁入{faction}世家")
        return True, f"💒 经你撮合，{member['name']}嫁入{faction}世家，两族承你的情（{faction}+5）"
    if action == "bond":
        if member["称号"] in ("长公主", "大长公主") and game_state.attributes.get("威望", 0) < 60:
            return False, "与长公主义结金兰，需威望≥60"
        if member["name"] in rc["handkerchief"]:
            return False, "你们已是手帕交"
        rc["handkerchief"].append(member["name"])
        _rel_change(member, 15)
        emp_rel = game_state.relationships.setdefault("皇帝", {"好感": 10})
        emp_rel["好感"] = min(100, emp_rel.get("好感", 10) + 3)
        return True, f"🌸 你与{member['name']}互换信物，义结金兰（关系+15，皇帝好感+3）"
    return False, "无效的宗室女动作"


def respond_royal_pending(game_state, rc, event_id, choice_index):
    """宗室待办事件响应（郡主入宫/长辈争执/郡王议亲）。"""
    ev = next((e for e in rc.get("pending", []) if e.get("id") == event_id), None)
    if not ev:
        return None, "事件不存在或已了结"
    kind = ev["kind"]
    idx = int(choice_index or 0)
    if kind == "jungu_visit":
        f = rc["females"].get((ev.get("payload") or {}).get("female", ""))
        if idx == 0:  # 热情接待
            if f:
                _rel_change(f, 10)
            game_state.attributes["威望"] = min(game_state.get_attr_max("威望"),
                                               game_state.attributes.get("威望", 0) + 2)
            msg = f"你亲自设宴款待{f['name'] if f else '郡主'}，宾主尽欢（关系+10，威望+2）"
        else:  # 婉拒
            if f:
                _rel_change(f, -5)
            msg = "你称病未出，郡主悻悻回府（关系-5）"
    elif kind == "elder_debate":
        f = rc["females"].get((ev.get("payload") or {}).get("female", ""))
        if idx == 0:  # 站太后
            tai = game_state.relationships.setdefault("太后", {"好感": 25, "印象": "和善", "互动次数": 0})
            tai["好感"] = min(100, tai.get("好感", 25) + 6)
            if f:
                _rel_change(f, -8)
            msg = "你站在了太后一边，太后欣慰，长公主冷淡（太后+6，长公主-8）"
        else:  # 站长公主
            if f:
                _rel_change(f, 12)
                f["影响力"] = min(100, f["影响力"] + 3)
            tai = game_state.relationships.setdefault("太后", {"好感": 25, "印象": "和善", "互动次数": 0})
            tai["好感"] = max(0, tai.get("好感", 25) - 4)
            msg = f"你在宴上附和了{f['name'] if f else '长公主'}，宗室称你有主见（长公主+12，太后-4）"
    elif kind == "junwang_marriage":
        m = rc["males"].get((ev.get("payload") or {}).get("male", ""))
        if idx == 0:  # 助其美言
            if m:
                m["帝眷"] = min(100, m["帝眷"] + 3)
                _rel_change(m, 8)
            msg = f"你在御前为{m['name'] if m else '郡王'}美言了几句，王府感激（关系+8）"
        else:  # 不掺和
            msg = "你笑而不语，只当没听见"
    else:
        return None, "未知的事件类型"
    rc["pending"] = [e for e in rc["pending"] if e.get("id") != event_id]
    game_state.add_memory(f"宗室待办：{ev['title']}")
    return True, msg


def royal_overview_payload(game_state):
    rc, males, females = royal_overview(game_state)
    return {
        "dazongzheng": rc.get("dazongzheng", ""),
        "males": [{k: m.get(k) for k in ("name", "爵位", "封地", "generation", "年龄", "帝眷",
                                         "野心", "实力", "立场", "关系")} for m in males],
        "females": [{k: f.get(k) for k in ("name", "称号", "身份", "父系", "年龄", "影响力",
                                           "与玩家关系", "婚配状态", "联姻潜力", "标记")} for f in females],
        "allies": list(rc.get("allies", [])),
        "handkerchief": list(rc.get("handkerchief", [])),
        "pending": list(rc.get("pending", [])),
        "log": list(rc.get("log", []))[:8],
    }
