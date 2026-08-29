# dowager_system.py — 太后垂帘听政线（新帝登基后的续章）
# 上朝奏事裁决 · 摄政权威/朝堂控制 · 新帝成长与母子博弈 · 归政/称制/失势三条出路
import random

COURT_LOG_MAX = 20
EMPEROR_ADULT_AGE = 16          # 新帝请求亲政的年龄
RETURN_POWER_GRACE = 3          # 亲政请求后可周旋的旬数
REGENCY_CRISIS_AUTH = 25        # 摄政权威跌破此值触发失势危机
EMPRESS_REGNANT_AUTH = 90       # 临朝称制（女帝）所需权威
EMPRESS_REGNANT_COURT = 85      # 临朝称制所需朝堂控制力

# 后宫治理模式（太后如何对待新帝的后宫）
HAREM_MODES = {
    "亲掌": {"name": "太后亲掌", "desc": "六宫事无大小皆决于慈宁宫；权威+，帝心-，新后怨望",
              "authority": 2, "emperor_affection": -2, "queen_favor": -3},
    "共治": {"name": "与后共治", "desc": "大事由你，细务归新后；平稳持中",
              "authority": 1, "emperor_affection": 0, "queen_favor": 1},
    "放权": {"name": "全付新后", "desc": "撤手不问，颐养天年；帝心+，新后感念，权威-",
              "authority": -2, "emperor_affection": 3, "queen_favor": 4},
}
HAREM_MODE_DEFAULT = "共治"

# 上朝奏事模板：每条三选，效果键 权威/朝堂/国库/帝心/民心/派系_x
COURT_AFFAIRS = [
    {
        "id": "border_raid", "type": "军情", "icon": "⚔️",
        "title": "北境告急",
        "desc": "北境边镇急报：胡骑犯边，掠去牛马千头。兵部请旨发兵，户部却道国库支绌。",
        "choices": [
            {"text": "发禁军三万北征", "icon": "⚔️", "effects": {"权威": 6, "国库": -300, "派系_武官党": 6, "民心": -3}},
            {"text": "遣使议和，岁赐安边", "icon": "🕊️", "effects": {"权威": -3, "国库": -120, "派系_文官党": 5, "民心": 4}},
            {"text": "命边将自守，不予增援", "icon": "🛡️", "effects": {"权威": -5, "派系_武官党": -8, "民心": -5}},
        ],
    },
    {
        "id": "tax_flood", "type": "赋税", "icon": "🌊",
        "title": "江南水患",
        "desc": "江南三州大水，田庐尽没。地方请免赋三年，户部言若允，国库将亏空过半。",
        "choices": [
            {"text": "免赋三年，开仓赈济", "icon": "🌾", "effects": {"国库": -400, "民心": 12, "权威": 4, "派系_文官党": 4}},
            {"text": "免赋一年，余者缓征", "icon": "⚖️", "effects": {"国库": -150, "民心": 5, "权威": 2}},
            {"text": "照例征收，不可开例", "icon": "📜", "effects": {"国库": 120, "民心": -12, "权威": -4}},
        ],
    },
    {
        "id": "corrupt_case", "type": "吏治", "icon": "⚖️",
        "title": "封疆大吏贪墨案",
        "desc": "御史弹劾两江总督贪墨河工银二十万两。此人是先帝旧臣，门生故吏遍布朝野。",
        "choices": [
            {"text": "下诏严办，抄没家产", "icon": "🗡️", "effects": {"权威": 8, "国库": 250, "朝堂": -6, "民心": 8}},
            {"text": "夺官留命，令其还银", "icon": "⚖️", "effects": {"权威": 3, "国库": 120, "朝堂": 2}},
            {"text": "留中不发，暗示其自请致仕", "icon": "🤫", "effects": {"权威": -4, "朝堂": 6, "民心": -6}},
        ],
    },
    {
        "id": "exam_reform", "type": "科举", "icon": "📚",
        "title": "科场舞弊",
        "desc": "本届春闱有权贵子弟夹带,已成众矢之的。士林哗然，宗室却为其请托。",
        "choices": [
            {"text": "彻查重考，褫夺功名", "icon": "📚", "effects": {"权威": 6, "派系_文官党": 8, "派系_宗室党": -8, "民心": 8}},
            {"text": "只黜首恶，余者不问", "icon": "⚖️", "effects": {"权威": 2, "派系_文官党": 3, "朝堂": 2}},
            {"text": "压下此事，安抚宗室", "icon": "🏵️", "effects": {"权威": -5, "派系_宗室党": 8, "派系_文官党": -8, "民心": -8}},
        ],
    },
    {
        "id": "clan_title", "type": "宗室", "icon": "🏵️",
        "title": "宗室请封",
        "desc": "数位宗室联名上表，请为新帝叔伯加封亲王、增食邑，言此乃「皇室体面」。",
        "choices": [
            {"text": "择贤者一人加封", "icon": "🏵️", "effects": {"权威": 3, "国库": -100, "派系_宗室党": 6, "朝堂": 3}},
            {"text": "一概驳回，宗室不可骄纵", "icon": "🚫", "effects": {"权威": 5, "派系_宗室党": -10, "朝堂": -4}},
            {"text": "尽数准奏，广施恩泽", "icon": "🎁", "effects": {"权威": -4, "国库": -350, "派系_宗室党": 12}},
        ],
    },
    {
        "id": "emperor_study", "type": "帝学", "icon": "📖",
        "title": "新帝课业",
        "desc": "太傅奏称新帝近来懈于经史，常以「母后自会料理」为辞推诿。",
        "choices": [
            {"text": "严词训诲，加课加责", "icon": "📖", "effects": {"帝心": -6, "帝威": 6, "权威": 3}},
            {"text": "温言劝勉，寓教于游", "icon": "🌿", "effects": {"帝心": 8, "帝威": 2}},
            {"text": "由他去罢，朝政有我", "icon": "🫱", "effects": {"帝心": 3, "帝威": -8, "权威": 5}},
        ],
    },
    {
        "id": "eunuch_power", "type": "内廷", "icon": "🕯️",
        "title": "内侍干政",
        "desc": "司礼监掌印以传旨为名擅改票拟，外朝已有怨言，然此人是你垂帘之初的心腹。",
        "choices": [
            {"text": "杖毙以正朝纲", "icon": "🗡️", "effects": {"权威": 4, "朝堂": 8, "民心": 4}},
            {"text": "调外任职，体面收权", "icon": "📜", "effects": {"权威": 2, "朝堂": 4}},
            {"text": "留用如故，正需其耳目", "icon": "🕯️", "effects": {"权威": 3, "朝堂": -8, "民心": -5}},
        ],
    },
    {
        "id": "return_power_hint", "type": "朝议", "icon": "👑",
        "title": "还政之议",
        "desc": "有大臣于朝会试探：「陛下渐长，太后垂帘辛劳，可否择日还政？」满殿寂然，都在看你脸色。",
        "choices": [
            {"text": "允议，着礼部拟还政仪注", "icon": "👑", "effects": {"权威": -8, "帝心": 12, "朝堂": 6, "民心": 6}},
            {"text": "斥其妄言，帘幕不动", "icon": "🚫", "effects": {"权威": 6, "帝心": -8, "朝堂": -6}},
            {"text": "含糊其辞，容后再议", "icon": "🤫", "effects": {"权威": 1, "帝心": -2}},
        ],
    },
]

# 太后可主动施为（每旬各一次）
DOWAGER_ACTIONS = {
    "instruct": {"name": "亲授帝学", "cost": {"actions": 1}, "desc": "亲课新帝经史，帝心与帝威俱进"},
    "grant": {"name": "赏赐朝臣", "cost": {"silver": 150}, "desc": "以私帑赏赐重臣，朝堂控制+"},
    "purge": {"name": "整肃朝纲", "cost": {"actions": 2}, "desc": "罢黜异己，权威+但朝堂震动"},
    "almsgiving": {"name": "施粥赈灾", "cost": {"silver": 200}, "desc": "以国库行仁政，民心+"},
    "audience": {"name": "召见宗亲", "cost": {"actions": 1}, "desc": "抚循宗室，宗室党好感+"},
}


def default_dowager():
    return {
        "active": False,
        "authority": 60,        # 摄政权威
        "court": 50,            # 朝堂控制力
        "treasury": 2000,       # 国库
        "people": 60,           # 民心
        "emperor": {"name": "", "age": 6, "affection": 60, "majesty": 30, "alive": True},
        "periods": 0,
        "pending": [],          # 待裁奏事
        "history": [],
        "log": [],
        "return_requested": 0,  # 亲政请求后已过旬数（0=未请求）
        "used_period": "",      # 本旬已施为记录
        "used_actions": [],
        # ---- 新帝后宫（太后仍可插手的那一半） ----
        "harem_mode": HAREM_MODE_DEFAULT,   # 亲掌 / 共治 / 放权
        "new_queen": "",                    # 新后名（新帝的皇后）
        "queen_favor": 50,                  # 新后对你的敬顺度 0-100
        "harem_log": [],
    }


def get_dowager(game_state):
    d = getattr(game_state, "dowager_state", None)
    if not isinstance(d, dict):
        d = default_dowager()
        game_state.dowager_state = d
    for k, v in default_dowager().items():
        d.setdefault(k, v)
    for k, v in default_dowager()["emperor"].items():
        d["emperor"].setdefault(k, v)
    return d


def is_dowager_active(game_state):
    d = getattr(game_state, "dowager_state", None)
    return isinstance(d, dict) and bool(d.get("active"))


def _log(d, text):
    d["log"].insert(0, text)
    del d["log"][COURT_LOG_MAX:]


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, int(v)))


def enter_dowager_mode(game_state, heir_child):
    """新帝登基：由「母仪天下」转入垂帘听政续章，而非直接终局。"""
    d = get_dowager(game_state)
    if d.get("active"):
        return False, "你已在垂帘听政"
    d["active"] = True
    prestige = int(game_state.attributes.get("威望", 0) or 0)
    d["authority"] = _clamp(45 + prestige // 20)
    d["court"] = _clamp(40 + int(game_state.attributes.get("心计", 40) or 0) // 4)
    d["treasury"] = 2000
    d["people"] = 60
    d["emperor"] = {
        "name": (heir_child or {}).get("name", "新帝"),
        "age": int(float((heir_child or {}).get("age", 8) or 8)),
        "affection": int((heir_child or {}).get("affection", 60) or 60),
        "majesty": _clamp(20 + int((heir_child or {}).get("emperor_favor", 30) or 30) // 3),
        "alive": True,
    }
    d["periods"] = 0
    game_state.dowager_mode = True
    game_state.regency_authority = d["authority"]
    game_state.court_power = d["court"]
    game_state.ending = None          # 续章：清掉「母仪天下」的终局落定
    game_state.game_over = False
    _log(d, f"{d['emperor']['name']}登基，你于养心殿后垂帘听政")
    game_state.add_memory(f"👑 你以太后之尊垂帘听政，辅幼帝{d['emperor']['name']}")
    return True, (f"👑 新帝{d['emperor']['name']}年方{d['emperor']['age']}，冲龄践祚。"
                  f"珠帘之后，你第一次听见满殿朝臣向帘幕行礼。\n"
                  f"摄政权威{d['authority']} · 朝堂控制{d['court']} · 国库{d['treasury']}万 · 民心{d['people']}")


def _apply_effects(game_state, d, effects):
    applied = {}
    for k, v in (effects or {}).items():
        v = int(v)
        if k == "权威":
            d["authority"] = _clamp(d["authority"] + v)
            applied["摄政权威"] = v
        elif k == "朝堂":
            d["court"] = _clamp(d["court"] + v)
            applied["朝堂控制"] = v
        elif k == "国库":
            d["treasury"] = max(0, int(d["treasury"]) + v)
            applied["国库"] = v
        elif k == "民心":
            d["people"] = _clamp(d["people"] + v)
            applied["民心"] = v
        elif k == "帝心":
            d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] + v)
            applied["帝心"] = v
        elif k == "帝威":
            d["emperor"]["majesty"] = _clamp(d["emperor"]["majesty"] + v)
            applied["新帝威仪"] = v
        elif k.startswith("派系_"):
            faction = k.split("_", 1)[1]
            favor = {"文官党": 50, "武官党": 50, "宗室党": 50}
            favor.update(getattr(game_state, "court_faction_favor", None) or {})
            if faction in favor:
                favor[faction] = _clamp(int(favor[faction] or 0) + v)
                game_state.court_faction_favor = favor
                applied[faction] = v
    game_state.regency_authority = d["authority"]
    game_state.court_power = d["court"]
    return applied


def generate_court_affairs(game_state):
    """转旬：生成 1~2 件待裁奏事（队列上限 3）。"""
    d = get_dowager(game_state)
    if not d.get("active"):
        return []
    msgs = []
    if len(d["pending"]) >= 3:
        return ["📜 通政司积压的奏本已堆到三件，朝臣都在等太后裁断"]
    for _ in range(random.choice([1, 1, 2])):
        if len(d["pending"]) >= 3:
            break
        tpl = random.choice(COURT_AFFAIRS)
        if tpl["id"] == "return_power_hint" and d["emperor"]["age"] < EMPEROR_ADULT_AGE - 2:
            continue
        if any(p.get("tpl") == tpl["id"] for p in d["pending"]):
            continue
        d["pending"].append({
            "id": f"ca{len(d['history']) + len(d['pending']) + 1}_{random.randint(100, 999)}",
            "tpl": tpl["id"], "type": tpl["type"], "icon": tpl["icon"],
            "title": tpl["title"], "desc": tpl["desc"],
            "choices": [{"text": c["text"], "icon": c.get("icon", ""), "effects": c["effects"]}
                        for c in tpl["choices"]],
            "period": f"{game_state.year}年{game_state.month}月",
        })
        msgs.append(f"{tpl['icon']} 朝会奏事：{tpl['title']}——满殿都在等帘后一言")
    return msgs


def respond_court_affair(game_state, affair_id, choice_index):
    """裁决一件奏事。"""
    d = get_dowager(game_state)
    if not d.get("active"):
        return None, "你不在垂帘听政"
    ev = next((p for p in d["pending"] if p.get("id") == affair_id), None)
    if not ev:
        return None, "此奏本已批过或不存在"
    choices = ev.get("choices") or []
    idx = int(choice_index or 0)
    if not (0 <= idx < len(choices)):
        return False, "无此选项"
    choice = choices[idx]
    applied = _apply_effects(game_state, d, choice.get("effects"))
    d["pending"] = [p for p in d["pending"] if p.get("id") != affair_id]
    d["history"].insert(0, {"title": ev["title"], "choice": choice["text"], "period": ev.get("period")})
    del d["history"][30:]
    # 还政之议特判
    if ev.get("tpl") == "return_power_hint" and idx == 0:
        d["return_requested"] = max(1, d["return_requested"])
    parts = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in applied.items() if v]
    narr = f"「{ev['title']}」你于帘后裁断：{choice['text']}。"
    if parts:
        narr += "（" + "、".join(parts) + "）"
    _log(d, f"{ev['title']}：{choice['text']}")
    game_state.add_memory(f"垂帘裁断：{ev['title']}—{choice['text']}")
    return True, narr


def dowager_action(game_state, action):
    """太后主动施为（每旬每项一次）。"""
    from app import guard_action, check_and_consume_action
    d = get_dowager(game_state)
    if not d.get("active"):
        return None, "你不在垂帘听政"
    spec = DOWAGER_ACTIONS.get(action)
    if not spec:
        return None, "无此举措"
    period_key = f"{game_state.year}-{game_state.month}-{game_state.day}"
    if d.get("used_period") != period_key:
        d["used_period"] = period_key
        d["used_actions"] = []
    if action in d["used_actions"]:
        return False, f"本旬已{spec['name']}，不宜再行"
    if "silver" in spec["cost"]:
        need = spec["cost"]["silver"]
        if action == "almsgiving":
            if d["treasury"] < need:
                return False, f"国库不足（需{need}万）"
            d["treasury"] -= need
        else:
            if game_state.silver < need:
                return False, f"私帑不足（需{need}两）"
            game_state.silver -= need
    if "actions" in spec["cost"]:
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
        for _ in range(spec["cost"]["actions"] - 1):
            check_and_consume_action(game_state)
    d["used_actions"].append(action)
    if action == "instruct":
        eff = {"帝心": random.randint(3, 7), "帝威": random.randint(2, 5), "权威": 1}
        applied = _apply_effects(game_state, d, eff)
        msg = f"📖 你亲执朱笔为{d['emperor']['name']}讲《贞观政要》，他听得入神"
    elif action == "grant":
        applied = _apply_effects(game_state, d, {"朝堂": random.randint(5, 9), "权威": 1})
        msg = "🎁 你以私帑厚赏几位老臣，朝上的风向和缓了些"
    elif action == "purge":
        applied = _apply_effects(game_state, d, {"权威": random.randint(6, 10),
                                                 "朝堂": -random.randint(3, 6),
                                                 "民心": -random.randint(0, 3)})
        msg = "🗡️ 你借考功之名罢黜数名异议之臣，朝堂一时噤声"
    elif action == "almsgiving":
        applied = _apply_effects(game_state, d, {"民心": random.randint(6, 11), "权威": 2})
        msg = "🌾 京畿设粥棚三十处，百姓称颂太后仁德"
    else:  # audience
        applied = _apply_effects(game_state, d, {"派系_宗室党": random.randint(4, 8), "朝堂": 2})
        msg = "🏵️ 你于慈宁宫召见宗亲，赐茶叙话，宗室感念"
    parts = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in applied.items() if v]
    if parts:
        msg += "（" + "、".join(parts) + "）"
    _log(d, spec["name"])
    return True, msg


def return_power(game_state, mode):
    """还政抉择：yield=归政新帝（结局）；refuse=继续垂帘（权威消耗）。"""
    from app import trigger_ending
    d = get_dowager(game_state)
    if not d.get("active"):
        return None, "你不在垂帘听政"
    if d["emperor"]["age"] < EMPEROR_ADULT_AGE and mode == "yield":
        return False, f"新帝尚未及{EMPEROR_ADULT_AGE}岁，此时归政恐社稷动摇"
    if mode == "yield":
        d["active"] = False
        game_state.dowager_mode = False
        affection = d["emperor"]["affection"]
        if affection >= 60 and d["people"] >= 50:
            trigger_ending(game_state, "还政归养",
                           f"{d['emperor']['name']}既冠,你撤帘还政，母慈子孝")
            return True, ("🌤️ 撤帘那日，新帝亲扶你出殿。你把批红的朱笔交回他手里，"
                          "从此只在慈宁宫看花——这江山，你替他守住了。（终局：还政归养）")
        trigger_ending(game_state, "还政归养",
                       f"{d['emperor']['name']}亲政，你交还权柄，母子间终究隔了一层")
        return True, ("🍂 你撤了帘。新帝受玺时没有看你。此后慈宁宫的门槛，他一年也难得踏过一次。"
                      "（终局：还政归养）")
    if mode == "refuse":
        d["return_requested"] = 0
        applied = _apply_effects(game_state, d, {"权威": -6, "帝心": -10, "朝堂": -4})
        _log(d, "拒还政")
        return True, ("🚫 你只说了一句「皇帝还小」。帘外一片沉默，新帝的手在袖中攥紧了。"
                      f"（{'、'.join(f'{k}{v}' for k, v in applied.items())}）")
    if mode == "regnant":
        if d["authority"] < EMPRESS_REGNANT_AUTH or d["court"] < EMPRESS_REGNANT_COURT:
            return False, (f"临朝称制需摄政权威≥{EMPRESS_REGNANT_AUTH}、朝堂控制≥{EMPRESS_REGNANT_COURT}"
                           f"（现{d['authority']}/{d['court']}）")
        d["active"] = False
        game_state.dowager_mode = False
        trigger_ending(game_state, "临朝称制", "你受群臣之请，去帘临朝，改元称制")
        return True, ("👑 那道珠帘被撤了下来——不是还政，是不必再隔着帘子。"
                      "你着帝服受百官朝贺，改元称制。史笔如何写你，你已不在意。（终局：临朝称制）")
    return None, "无效的抉择"


# ===== 新帝后宫：太后仍可插手的那一半 =====
HAREM_ACTIONS = {
    "select_draft": {"name": "为帝选秀", "cost": {"actions": 1}, "min_mode": ("亲掌", "共治"),
                     "desc": "为新帝钦定秀女入宫，充实子嗣（新后敬顺-）"},
    "instruct_queen": {"name": "训诫新后", "cost": {"actions": 1}, "min_mode": ("亲掌", "共治"),
                       "desc": "以太后之尊教诲新后宫务（权威+，敬顺-）"},
    "bless_consort": {"name": "抚循妃嫔", "cost": {"silver": 100}, "min_mode": ("亲掌", "共治", "放权"),
                      "desc": "赏赐新帝妃嫔，广植恩德（民心+，敬顺+）"},
    "urge_heir": {"name": "催促皇嗣", "cost": {"actions": 1}, "min_mode": ("亲掌", "共治"),
                  "desc": "催新帝早绵子嗣（帝心-，皇孙有望）"},
    "arbitrate": {"name": "裁断宫争", "cost": {"actions": 1}, "min_mode": ("亲掌", "共治"),
                  "desc": "亲裁新帝后宫的争端（权威+，或招怨）"},
}


def _harem_log(d, text):
    d.setdefault("harem_log", []).insert(0, text)
    del d["harem_log"][12:]


def ensure_new_queen(game_state, d):
    """新帝立后：从名册中挑一位（或凭空生成）作为新后。"""
    if d.get("new_queen"):
        return d["new_queen"]
    if d["emperor"]["age"] < 14:
        return ""
    from names import generate_female_name
    try:
        name = generate_female_name()
    except Exception:
        name = "新后"
    d["new_queen"] = name
    d["queen_favor"] = random.randint(40, 60)
    _harem_log(d, f"{d['emperor']['name']}册立{name}为后")
    game_state.add_memory(f"👑 新帝册立{name}为后")
    return name


def set_harem_mode(game_state, mode):
    """选择后宫治理模式：亲掌 / 共治 / 放权。"""
    d = get_dowager(game_state)
    if not d.get("active"):
        return None, "你不在垂帘听政"
    if mode not in HAREM_MODES:
        return None, "无此治理之法"
    if d.get("harem_mode") == mode:
        return False, f"你已行「{HAREM_MODES[mode]['name']}」之法"
    old = d.get("harem_mode", HAREM_MODE_DEFAULT)
    d["harem_mode"] = mode
    spec = HAREM_MODES[mode]
    # 转换代价：亲掌需权威，放权则失权威但得帝心
    if mode == "亲掌":
        d["authority"] = _clamp(d["authority"] + 3)
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) - 8)
        d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] - 4)
        narr = ("🏛️ 你传下话去：六宫事无大小，皆先报慈宁宫。"
                "新后垂手立在阶下，一句话也没有说。（权威+3，帝心-4，新后敬顺-8）")
    elif mode == "放权":
        d["authority"] = _clamp(d["authority"] - 4)
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) + 10)
        d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] + 6)
        narr = ("🌿 你把六宫的册子交回新后手里：「往后这些，你自己拿主意。」"
                "她跪下谢恩时，眼里是真的松了口气。（权威-4，帝心+6，新后敬顺+10）")
    else:
        d["authority"] = _clamp(d["authority"] + 1)
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) + 3)
        narr = ("⚖️ 你划下界线：大事你断，细务归她。"
                "这样最省心，也最容易长久。（权威+1，新后敬顺+3）")
    _harem_log(d, f"治理之法：{old}→{mode}")
    game_state.add_memory(f"后宫治理改为「{spec['name']}」")
    return True, narr


def harem_action(game_state, action):
    """太后对新帝后宫的施为（受治理模式限制）。"""
    from app import guard_action
    d = get_dowager(game_state)
    if not d.get("active"):
        return None, "你不在垂帘听政"
    spec = HAREM_ACTIONS.get(action)
    if not spec:
        return None, "无此举措"
    mode = d.get("harem_mode", HAREM_MODE_DEFAULT)
    if mode not in spec["min_mode"]:
        return False, f"你已行「{HAREM_MODES[mode]['name']}」，此事不宜再由慈宁宫过问"
    period_key = f"{game_state.year}-{game_state.month}-{game_state.day}"
    key = "harem_" + action
    if d.get("used_period") != period_key:
        d["used_period"] = period_key
        d["used_actions"] = []
    if key in d["used_actions"]:
        return False, f"本旬已{spec['name']}"
    if "silver" in spec["cost"]:
        if game_state.silver < spec["cost"]["silver"]:
            return False, f"私帑不足（需{spec['cost']['silver']}两）"
        game_state.silver -= spec["cost"]["silver"]
    if "actions" in spec["cost"]:
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
    d["used_actions"].append(key)
    queen = ensure_new_queen(game_state, d)

    if action == "select_draft":
        applied = _apply_effects(game_state, d, {"权威": 2, "帝心": -2})
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) - 5)
        d.setdefault("grandchild_chance", 0)
        d["grandchild_chance"] = min(60, int(d.get("grandchild_chance", 0)) + 15)
        msg = (f"📜 你为{d['emperor']['name']}钦定了两名秀女入宫。"
               f"{'新后' + queen + '闻讯，指尖掐进了掌心。' if queen else ''}"
               f"（权威+2，帝心-2，新后敬顺-5，皇孙可期）")
    elif action == "instruct_queen":
        if not queen:
            return False, "新帝尚未立后，无人可训"
        applied = _apply_effects(game_state, d, {"权威": 3})
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) - 6)
        msg = (f"📖 你召{queen}至慈宁宫，从晨昏定省讲到内帑出入，讲了一个时辰。"
               f"她跪谢受教，膝下的砖被跪出了印子。（权威+3，新后敬顺-6）")
    elif action == "bless_consort":
        applied = _apply_effects(game_state, d, {"民心": 3, "朝堂": 2})
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) + 6)
        msg = ("🎁 你以私帑赏赐新帝的妃嫔，人人有份，厚薄得宜。"
               "宫里都说太后慈厚。（民心+3，朝堂+2，新后敬顺+6）")
    elif action == "urge_heir":
        applied = _apply_effects(game_state, d, {"帝心": -3, "权威": 1})
        d["grandchild_chance"] = min(70, int(d.get("grandchild_chance", 0)) + 20)
        msg = (f"🍼 你当着朝臣的面问{d['emperor']['name']}：「皇嗣之事，可有消息了？」"
               f"他脸上一红，答不上话。（帝心-3，权威+1，皇孙可期）")
    else:  # arbitrate
        good = random.random() < 0.6
        if good:
            applied = _apply_effects(game_state, d, {"权威": 4, "朝堂": 2})
            d["queen_favor"] = _clamp(d.get("queen_favor", 50) + 2)
            msg = ("⚖️ 新帝后宫两位娘娘争一处宫室，闹到慈宁宫来。"
                   "你三言两语断得公道，两边都谢了恩。（权威+4，朝堂+2）")
        else:
            applied = _apply_effects(game_state, d, {"权威": 1, "民心": -2})
            d["queen_favor"] = _clamp(d.get("queen_favor", 50) - 5)
            msg = ("⚖️ 你裁断了那桩争执，可落败的那位是新后的亲表妹。"
                   "从此新后见你，礼数越发周全了。（权威+1，民心-2，新后敬顺-5）")
    parts = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in (applied or {}).items() if v]
    _harem_log(d, spec["name"])
    return True, msg


def dowager_period_tick(game_state):
    """转旬：奏事生成、国库民心自然变动、新帝成长、亲政请求与失势危机。"""
    d = get_dowager(game_state)
    if not d.get("active"):
        return []
    msgs = []
    d["periods"] += 1
    # 财政与民心
    income = 120 + d["people"] // 2 + d["court"] // 3
    d["treasury"] = max(0, d["treasury"] + income - 100)
    if d["treasury"] <= 0:
        d["people"] = _clamp(d["people"] - 5)
        msgs.append("💸 国库空虚，京畿米价飞涨，民怨渐起（民心-5）")
    # 积压奏本消磨权威
    if len(d["pending"]) >= 3:
        d["authority"] = _clamp(d["authority"] - 3)
        msgs.append("📜 奏本积压不批，朝臣私议太后倦政（摄政权威-3）")
    # 后宫治理模式的每旬效应
    mode = d.get("harem_mode", HAREM_MODE_DEFAULT)
    spec = HAREM_MODES.get(mode) or {}
    d["authority"] = _clamp(d["authority"] + int(spec.get("authority", 0)))
    d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] + int(spec.get("emperor_affection", 0)))
    d["queen_favor"] = _clamp(d.get("queen_favor", 50) + int(spec.get("queen_favor", 0)))
    # 新帝立后
    if not d.get("new_queen") and d["emperor"]["age"] >= 14:
        q = ensure_new_queen(game_state, d)
        if q:
            msgs.append(f"👑 {d['emperor']['name']}册立{q}为后，六宫有主")
    # 新后敬顺过低 → 联手新帝抗命
    if d.get("new_queen") and d.get("queen_favor", 50) <= 20 and random.random() < 0.3:
        d["authority"] = _clamp(d["authority"] - 4)
        d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] - 3)
        msgs.append(f"🕸️ {d['new_queen']}在御前哭诉太后严苛，新帝默然听了很久（权威-4，帝心-3）")
    # 皇孙诞生
    gc = int(d.get("grandchild_chance", 0) or 0)
    if gc > 0 and random.random() < gc / 100.0:
        d["grandchild_chance"] = 0
        d["authority"] = _clamp(d["authority"] + 3)
        d["people"] = _clamp(d["people"] + 4)
        d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] + 5)
        msgs.append(f"👶 {d['emperor']['name']}得了皇长子，宗庙有继——你成了太皇太后的辈分（权威+3，民心+4，帝心+5）")
        game_state.add_memory("👶 皇孙诞生，宗庙有继")
    # 新帝成长
    if d["periods"] % 3 == 0:
        d["emperor"]["age"] += 1
        d["emperor"]["majesty"] = _clamp(d["emperor"]["majesty"] + random.randint(0, 2))
        if d["emperor"]["age"] == EMPEROR_ADULT_AGE:
            d["return_requested"] = 1
            msgs.append(f"👑 {d['emperor']['name']}已及{EMPEROR_ADULT_AGE}岁，行冠礼，朝野皆言当亲政（可归政或拒还）")
        else:
            msgs.append(f"👦 {d['emperor']['name']}又长一岁（{d['emperor']['age']}岁，威仪{d['emperor']['majesty']}）")
    # 亲政请求逾期未决
    if d["return_requested"]:
        d["return_requested"] += 1
        if d["return_requested"] > RETURN_POWER_GRACE:
            from app import trigger_ending
            if d["emperor"]["majesty"] >= 60 and d["emperor"]["affection"] < 40:
                d["active"] = False
                game_state.dowager_mode = False
                trigger_ending(game_state, "幽居慈宁",
                               f"{d['emperor']['name']}羽翼已成，恨你久握权柄，奉你于慈宁宫「养尊」")
                msgs.append("⛓️ 新帝终究动了手——慈宁宫的门从外面锁上了。（终局：幽居慈宁）")
                return msgs
            d["authority"] = _clamp(d["authority"] - 5)
            d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] - 5)
            msgs.append("⏳ 还政之事悬而未决，朝野议论纷纷（摄政权威-5，帝心-5）")
    # 失势危机
    if d["authority"] <= REGENCY_CRISIS_AUTH:
        from app import trigger_ending
        if random.random() < 0.4:
            d["active"] = False
            game_state.dowager_mode = False
            trigger_ending(game_state, "幽居慈宁", "摄政权威扫地，为群臣所弃")
            msgs.append("⛓️ 朝臣联名请太后「颐养天年」。这一次，没有人再向帘幕行礼。（终局：幽居慈宁）")
            return msgs
        msgs.append("⚠️ 帘外的礼数越来越薄了——摄政权威已危（<25）")
    # 生成新奏事
    msgs.extend(generate_court_affairs(game_state))
    return msgs


def dowager_payload(game_state):
    d = get_dowager(game_state)
    from app import normalize_court_faction_favor
    return {
        "active": bool(d.get("active")),
        "authority": d["authority"], "court": d["court"],
        "treasury": d["treasury"], "people": d["people"],
        "emperor": dict(d["emperor"]),
        "periods": d["periods"],
        "pending": list(d["pending"]),
        "history": list(d["history"])[:6],
        "log": list(d["log"])[:8],
        "return_requested": d["return_requested"],
        "adult_age": EMPEROR_ADULT_AGE,
        "regnant_req": {"authority": EMPRESS_REGNANT_AUTH, "court": EMPRESS_REGNANT_COURT},
        "factions": normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None)),
        "actions": [{"key": k, "name": v["name"], "desc": v["desc"],
                     "used": k in (d.get("used_actions") or [])}
                    for k, v in DOWAGER_ACTIONS.items()],
        "harem_mode": d.get("harem_mode", HAREM_MODE_DEFAULT),
        "harem_modes": [{"key": k, "name": v["name"], "desc": v["desc"]} for k, v in HAREM_MODES.items()],
        "new_queen": d.get("new_queen", ""),
        "queen_favor": d.get("queen_favor", 50),
        "grandchild_chance": int(d.get("grandchild_chance", 0) or 0),
        "harem_actions": [{"key": k, "name": v["name"], "desc": v["desc"],
                           "allowed": d.get("harem_mode", HAREM_MODE_DEFAULT) in v["min_mode"],
                           "used": ("harem_" + k) in (d.get("used_actions") or [])}
                          for k, v in HAREM_ACTIONS.items()],
        "harem_log": list(d.get("harem_log") or [])[:5],
    }
