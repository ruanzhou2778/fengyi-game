# family_backgrounds.py — 官家出身：与本人同姓的父亲官员 + 嫡庶养私生
import random
from names import (
    EMPEROR_GIVEN,
    NPC_SURNAMES,
    extract_surname,
    generate_female_name_for_surname,
    random_given,
    random_surname,
)

MINISTRIES = ["吏部", "户部", "礼部", "兵部", "刑部", "工部"]

DAUGHTER_STATUSES = [
    {"key": "嫡", "weight": 32, "rank_offset": 0, "score_mod": 12, "attr": {"威望": 2, "魅力": 2}},
    {"key": "庶", "weight": 38, "rank_offset": 1, "score_mod": 0, "attr": {"心计": 2}},
    {"key": "养", "weight": 18, "rank_offset": 2, "score_mod": -10, "attr": {"福运": 1, "心计": 1}},
    {"key": "私生", "weight": 12, "rank_offset": 2, "score_mod": -20, "attr": {"心计": 3, "容貌": -1}},
]

PLAYER_START_RANKS = ["秀女", "答应", "常在", "贵人", "嫔"]

# 官阶 → 初始位份索引（0=秀女 … 4=嫔）
GRADE_BASE_RANK_INDEX = {1: 4, 2: 4, 3: 3, 4: 3, 5: 2, 6: 2, 7: 1, 8: 1, 9: 0}

GRADE_BASE_SCORE = {1: 88, 2: 78, 3: 70, 4: 62, 5: 55, 6: 48, 7: 42, 8: 36, 9: 30}

GRADE_WEIGHTS = [1, 2, 3, 4, 5, 6, 7, 8, 9]
GRADE_WEIGHT_VALUES = [2, 3, 6, 10, 14, 18, 16, 12, 6]
# 玩家选秀：略向中高门第倾斜，避免人人秀女/答应
PLAYER_GRADE_WEIGHT_VALUES = [3, 5, 8, 12, 16, 14, 10, 6, 4]

GRADE_ATTR_BONUS = {
    1: {"威望": 5, "才情": 3, "魅力": 3},
    2: {"威望": 4, "才情": 2, "魅力": 2},
    3: {"威望": 3, "才情": 2, "魅力": 1},
    4: {"威望": 2, "才情": 1},
    5: {"威望": 1, "才情": 1},
    6: {"心计": 1},
    7: {"心计": 1, "福运": 1},
    8: {"福运": 1},
    9: {"福运": 1},
}


def _pick_official_title(grade):
    if grade == 1:
        return random.choice(["太师", "太傅", "太保", "内阁首辅", "文华殿大学士"])
    if grade == 2:
        m = random.choice(MINISTRIES)
        return random.choice([f"{m}尚书", "都察院左都御史", "两江总督", "湖广总督", "闽浙总督"])
    if grade == 3:
        m = random.choice(MINISTRIES)
        return random.choice([f"{m}侍郎", "顺天巡抚", "山东巡抚", "河南巡抚", "四川巡抚"])
    if grade == 4:
        m = random.choice(MINISTRIES)
        return random.choice([f"{m}郎中", "参将", "按察使", "盐运使"])
    if grade == 5:
        return random.choice(["知府", "同知", "通判", "参将", "副将"])
    if grade == 6:
        return random.choice(["知州", "同知", "通判", "州判", "都事"])
    if grade == 7:
        return random.choice(["知县", "县丞", "主簿", "经历", "巡检"])
    if grade == 8:
        return random.choice(["县丞", "主簿", "典史", "吏目", "巡检"])
    return random.choice(["典史", "吏目", "未入流训导", "巡检"])


def _pick_daughter_status():
    keys = [s["key"] for s in DAUGHTER_STATUSES]
    weights = [s["weight"] for s in DAUGHTER_STATUSES]
    key = random.choices(keys, weights=weights)[0]
    return next(s for s in DAUGHTER_STATUSES if s["key"] == key)


def _official_given_name():
    return random_given(EMPEROR_GIVEN, 0.55)


def rank_to_index(rank_name):
    try:
        return PLAYER_START_RANKS.index(rank_name)
    except ValueError:
        return 1


def index_to_rank(idx):
    idx = max(0, min(len(PLAYER_START_RANKS) - 1, idx))
    return PLAYER_START_RANKS[idx]


def resolve_start_rank(*rank_names):
    """取多个位份候选中的最高者（用于家世 + 场景卡合并）。"""
    best = 0
    for name in rank_names:
        if name:
            best = max(best, rank_to_index(name))
    return index_to_rank(best)


def _pick_player_grade():
    return random.choices(GRADE_WEIGHTS, weights=PLAYER_GRADE_WEIGHT_VALUES)[0]


def _rank_bonus_for(grade, status):
    base_idx = GRADE_BASE_RANK_INDEX.get(grade, 0)
    idx = max(0, min(len(PLAYER_START_RANKS) - 1, base_idx - status["rank_offset"]))
    return PLAYER_START_RANKS[idx]


def _attr_bonus_for(grade, status):
    bonus = dict(GRADE_ATTR_BONUS.get(grade, {}))
    for k, v in status.get("attr", {}).items():
        bonus[k] = bonus.get(k, 0) + v
    return bonus


def _score_for(grade, status):
    return max(20, min(95, GRADE_BASE_SCORE.get(grade, 40) + status["score_mod"]))


def generate_official_background(surname, for_player=False):
    """根据女儿姓氏生成同姓父亲官家背景。显示：礼部尚书林子敬（嫡）女"""
    surname = (surname or "").strip() or random_surname(NPC_SURNAMES)

    grade = _pick_player_grade() if for_player else random.choices(GRADE_WEIGHTS, weights=GRADE_WEIGHT_VALUES)[0]
    title = _pick_official_title(grade)
    status = _pick_daughter_status()
    given = _official_given_name()
    official_name = f"{surname}{given}"
    label = f"{title}{official_name}（{status['key']}）女"

    status_desc = {
        "嫡": "嫡出千金，族中寄予厚望",
        "庶": "庶出之女，自幼谨小慎微",
        "养": "养女之身，寄人篱下却得栽培",
        "私生": "私生之女，名分尴尬却不得不选秀",
    }
    desc = f"父{official_name}，现任{title}，{status_desc[status['key']]}"

    score = _score_for(grade, status)
    meta = {
        "surname": surname,
        "official_title": title,
        "official_name": official_name,
        "official_grade": grade,
        "daughter_status": status["key"],
        "score": score,
    }

    result = {
        "id": label,
        "label": label,
        "desc": desc,
        "meta": meta,
        "score": score,
    }

    if for_player:
        result["rankBonus"] = _rank_bonus_for(grade, status)
        result["attrBonus"] = _attr_bonus_for(grade, status)

    return result


def generate_official_background_for_name(full_name, for_player=False):
    return generate_official_background(extract_surname(full_name), for_player=for_player)


def generate_concubine_identity(surnames=None):
    """先定姓氏，再生成妃嫔姓名与同姓官员家世，保证姓氏一致。"""
    surname = random_surname(surnames or NPC_SURNAMES)
    name = generate_female_name_for_surname(surname)
    bg = generate_official_background(surname)
    return name, bg


STORY_OPENERS = {
    "嫡": [
        "身为{official_name}嫡女，自幼受教于庭训，族中对我寄予厚望。",
        "我是{official_name}的嫡出女儿，门楣虽高，选秀入宫后每一步都关乎家族荣辱。",
        "家父{official_name}膝下嫡女，自幼习礼明义。选秀诏下，我便知此生再难只做闺阁中人。",
    ],
    "庶": [
        "我是{official_name}的庶出女儿，自幼谨小慎微，却也不得不被推上选秀之路。",
        "庶出之身让我比旁人更早学会察言观色。家父{official_name}说，入宫或是我最好的出路。",
        "同为{official_name}之女，我却只是庶出。选秀入选后，我更知唯有自强方能立足。",
    ],
    "养": [
        "我本是养女，由{official_name}抚养成人。虽非亲生，却也承蒙栽培，选秀入宫是我报答恩情的方式。",
        "寄养在{official_name}门下多年，外人只当我也是府中千金。入宫之后，这身份反倒成了我的枷锁。",
        "养女之身，名分尴尬。{official_name}将我送入宫中，说是为我寻一条生路。",
    ],
    "私生": [
        "私生女的身份，我从未对人言明。家父{official_name}将我送入宫中，或许只是想抹去这段不堪。",
        "我出身隐秘，是{official_name}不愿承认的女儿。选秀入选，是我为自己挣下的唯一名分。",
        "名分不正，自幼受尽冷眼。{official_name}将我送进深宫，说是成全，更像是安置。",
    ],
}

STORY_MIDDLES_HIGH = [
    "父亲现任{title}，朝堂上颇有声名，京中无人不知{family_label}。",
    "父亲官至{title}，府中门客往来不绝，我耳濡目染，也略懂朝局利害。",
    "家父{official_name}如今是{title}，族中荣耀皆系于他一身，我亦不敢辜负。",
]

STORY_MIDDLES_MID = [
    "父亲任{title}，虽非权倾朝野，却也足以在地方称一方人物。",
    "家父{official_name}现为{title}，门第清贵，却也算不得京城顶流。",
    "父亲在任{title}，家教谨严，我入宫前便被告知，谨言慎行方能保全。",
]

STORY_MIDDLES_LOW = [
    "父亲只是{title}，品秩不高，家族指望我入宫谋个出身。",
    "家父{official_name}官居{title}，门楣平常，选秀于我而言，几乎是唯一的出路。",
    "父亲任{title}，俸禄微薄，送我入宫选秀，不过是想为家族博一线机会。",
]

STORY_CLOSERS = {
    "琴艺": "我自幼习琴，指下清音曾慰父亲心绪，入宫后亦想以才艺自保。",
    "棋艺": "我善弈棋，棋盘上的进退取舍，与这后宫生存之道竟有几分相似。",
    "书法": "我苦练书法，一笔一画皆求端正，入宫后更知行事亦需如此。",
    "绘画": "我嗜丹青，画中山水虽静，却难比这深宫波澜。",
    "诗词": "我略通诗词，曾以一首咏梅诗得父亲夸赞，入宫后亦不敢荒废笔墨。",
    "舞蹈": "我善舞，曾在家宴上献舞娱亲，如今这舞技或许也是我的倚仗。",
    "歌喉": "我歌喉清越，闺中时常练唱，入宫后或能以声动人。",
    "刺绣": "我精于刺绣，针黹之间见心性，这手艺或许能让我在宫中立足。",
    "医术": "我随府医略通药理，入宫后见惯了人情冷暖，更觉医术可贵。",
    "茶道": "我善茶道，烹茶如待人，水温火候皆不可差。",
    "花艺": "我喜莳花弄草，闺中庭院四季有香，入宫后最念那抹清幽。",
    "香道": "我习香道，识得诸般香料，这嗅觉或许能助我避开宫中险恶。",
    "骑射": "我自幼习骑射，不似寻常闺秀娇弱，入宫后也不愿轻易示弱。",
    "烹饪": "我厨艺尚可，曾亲手为父亲备膳，入宫后这手艺倒成了慰藉。",
    "音律": "我通晓音律，丝竹之声曾是我闺中时光最好的陪伴。",
    "兵法": "我读过兵书，虽为女子，却也知进退攻守之理。",
    "占卜": "我略通占卜，冥冥之中或有天意，入宫前曾卜过一卦，结果吉凶难辨。",
    "酿酒": "我善酿酒，府中家宴上的佳酿多出自我的手，入宫后这技艺怕是难再施展。",
}

PERSONALITY_CLOSERS = {
    "温婉贤淑": "性情温婉，我只盼在深宫中守住本心，不争不抢。",
    "端庄大方": "我行事向来端庄，入宫后更须步步谨慎，不负家教。",
    "活泼开朗": "我生性开朗，纵使深宫幽深，也不愿失了生气。",
    "冷傲孤高": "我性情孤高，不屑逢迎，可这宫里由不得人清高。",
    "聪慧机敏": "我心思灵敏，入宫前便知这后宫从无净土。",
    "心机深沉": "我惯于谋算，入宫不过是另一盘棋局的开端。",
    "温柔可人": "我待人温柔，只愿以真心换真心，却不知这宫中真心几何。",
    "刚烈果断": "我性情刚烈，宁折不弯，入宫后也不会轻易低头。",
    "娴静淡雅": "我性情淡雅，不爱争宠，却也不信淡泊便能自保。",
    "娇俏灵动": "我娇俏灵动，或能以几分鲜活在这沉闷宫墙内博得一线生机。",
    "沉稳内敛": "我沉稳内敛，遇事不慌，入宫后更须藏锋守拙。",
    "明媚张扬": "我明媚张扬，不愿做个默默无闻的妃嫔。",
    "潇洒不羁": "我潇洒不羁，深宫规矩繁多，与我本性多有相悖。",
    "纯真无邪": "我心思单纯，入宫前对后宫险恶只有模糊想象。",
    "坚韧隐忍": "我惯于隐忍，再大的委屈也能咽下，只等一个时机。",
}


def generate_background_story(bg, player_name=None, talent=None, personality=None):
    """根据官家出身生成匹配的背景故事。"""
    meta = (bg or {}).get("meta") or {}
    status = meta.get("daughter_status", "庶")
    title = meta.get("official_title", "官员")
    official_name = meta.get("official_name", "某人")
    grade = meta.get("official_grade", 5)
    family_label = (bg or {}).get("label") or f"{title}{official_name}（{status}）女"

    opener = random.choice(STORY_OPENERS.get(status, STORY_OPENERS["庶"]))
    if grade <= 3:
        middle_pool = STORY_MIDDLES_HIGH
    elif grade <= 6:
        middle_pool = STORY_MIDDLES_MID
    else:
        middle_pool = STORY_MIDDLES_LOW
    middle = random.choice(middle_pool)

    fmt = {
        "official_name": official_name,
        "title": title,
        "family_label": family_label,
        "status": status,
        "player_name": player_name or "我",
    }
    parts = [opener.format(**fmt), middle.format(**fmt)]

    if talent and talent in STORY_CLOSERS:
        parts.append(STORY_CLOSERS[talent])
    if personality and personality in PERSONALITY_CLOSERS:
        parts.append(PERSONALITY_CLOSERS[personality])

    return "".join(parts)


def get_family_score(family, family_meta=None):
    if family_meta and isinstance(family_meta, dict):
        return family_meta.get("score", 45)
    if not family:
        return 40
    if family == "皇室宗亲":
        return 95
    text = str(family)
    if "（私生）" in text:
        return 35
    if "（养）" in text:
        return 42
    if "（庶）" in text:
        return 52
    if "（嫡）" in text:
        base = 68
        if any(t in text for t in ("太师", "太傅", "太保", "首辅", "大学士")):
            return min(95, base + 18)
        if "尚书" in text or "总督" in text:
            return min(90, base + 12)
        if "侍郎" in text or "巡抚" in text:
            return min(82, base + 6)
        return base
    high_titles = ("太师", "太傅", "太保", "首辅", "大学士", "尚书", "总督")
    mid_titles = ("侍郎", "巡抚", "郎中", "按察使")
    low_titles = ("知府", "知州", "知县", "县丞", "典史", "吏目")
    if any(t in text for t in high_titles):
        return 72
    if any(t in text for t in mid_titles):
        return 58
    if any(t in text for t in low_titles):
        return 42
    return 45


# ============================================================
#  前朝关联系统 · 家族生成引擎（v2.0）
# ============================================================
CLAN_FACTIONS = ["文官党", "武官党", "宗室党"]

# 官职类型 → 派系（兵部/武职 → 武官党，余多为文官党）
MILITARY_TITLE_KEYWORDS = ("兵", "参将", "副将", "将军", "巡抚", "总督", "按察")
MILITARY_KEYWORDS = ("参将", "副将", "将军")


def _faction_for_title(title):
    t = str(title or "")
    if any(k in t for k in MILITARY_KEYWORDS) or "兵部" in t:
        return "武官党"
    return random.choices(CLAN_FACTIONS, weights=[55, 25, 20])[0] if random.random() < 0.85 else "宗室党"


def _clan_tags(faction, grade, daughter_status=None):
    tags = []
    if faction == "文官党":
        tags.append("清流世家" if grade <= 3 else "书香门第")
    elif faction == "武官党":
        tags.append("将门之后" if grade <= 4 else "边军之后")
    else:
        tags.append("宗室远亲")
    if grade <= 2:
        tags.append("簪缨世族")
    if daughter_status == "庶":
        tags.append("庶出旁支")
    return tags


def _clan_member_name(surname):
    return f"{surname}{random_given(EMPEROR_GIVEN, 0.55)}"


def _clan_brother(surname, father_grade):
    """父亲官阶越高，兄弟起点越高（恩荫）。"""
    grade = max(4, min(9, father_grade + random.randint(2, 5)))
    title = _pick_official_title(grade)
    return {
        "name": _clan_member_name(surname),
        "官职": title,
        "grade": grade,
        "age": random.randint(18, 45),
        "健康": random.randint(60, 95),
        "alive": True,
        "派系": None,  # 与父亲同派系（外层填充）
        "政绩": random.randint(40, 75),
        "忠诚": random.randint(60, 90),
    }


def build_clan(surname, official_name, official_title, official_grade,
               faction=None, is_player=False, daughter_status=None):
    """构建一个前朝家族的完整结构。位份/官阶决定家族量级。"""
    surname = (surname or "沈").strip() or "沈"
    faction = faction or _faction_for_title(official_title)
    grade = int(official_grade or 5)
    prestige = max(10, min(95, get_family_score("", {"score": GRADE_BASE_SCORE.get(grade, 40)})))
    brothers = []
    n_bro = random.choices([0, 1, 2, 3], weights=[25, 40, 25, 10])[0]
    for _ in range(n_bro):
        brothers.append(_clan_brother(surname, grade))
    for b in brothers:
        b["派系"] = faction
    return {
        "surname": surname,
        "father": {
            "name": official_name,
            "官职": official_title,
            "grade": grade,
            "age": random.randint(42, 62),
            "健康": random.randint(55, 90),
            "alive": True,
            "派系": faction,
            "政绩": random.randint(45, 85),
            "忠诚": random.randint(50, 90),
        },
        "brothers": brothers,
        "家族威望": prestige,
        "家族银两": random.randint(300, 900) + (10 - grade) * 60,
        "政治倾向": faction,
        "恩荫次数": 0,
        "风险值": random.randint(0, 15),
        "标记": _clan_tags(faction, grade, daughter_status),
        "历史事件": [f"家族于{official_title}门下立身，世代{('清誉' if faction == '文官党' else '武名' if faction == '武官党' else '显贵')}"],
        "last_rank": None,  # NPC 家族：上次结算时的位份（用于检测晋升/降位）
        "与玩家家族关系": None,  # {好感, 关系, 历史}
        "is_player": bool(is_player),
    }


def generate_player_clan(surname, family_meta):
    """由开局家世（family_meta）生成玩家家族，保证与父亲官职/姓名一致。"""
    meta = family_meta or {}
    title = meta.get("official_title") or _pick_official_title(meta.get("official_grade", 5))
    return build_clan(
        meta.get("surname") or surname,
        meta.get("official_name") or (str(surname) + _clan_member_name("")),
        title,
        meta.get("official_grade", 5),
        daughter_status=meta.get("daughter_status"),
        is_player=True,
    )


# NPC 位份 → 父亲官阶区间（设计 3.3）
NPC_RANK_GRADE = {
    "皇后": (1, 2), "皇贵妃": (1, 2), "贵妃": (2, 3), "妃": (2, 3),
    "嫔": (3, 4), "婕妤": (3, 4), "美人": (3, 5), "才人": (4, 6),
    "贵人": (4, 6), "常在": (4, 7), "答应": (6, 9), "官女子": (6, 9), "秀女": (6, 9),
}


def generate_npc_clan(npc_name, npc_rank, family_meta=None):
    """为 NPC 生成家族；若已有同姓家世 meta 则以其为准（保证姓氏/官职一致）。"""
    meta = family_meta or {}
    surname = meta.get("surname") or str(npc_name)[:1]
    grade = int(meta.get("official_grade") or random.randint(*NPC_RANK_GRADE.get(npc_rank, (4, 7))))
    title = meta.get("official_title") or _pick_official_title(grade)
    father_name = meta.get("official_name") or (surname + random_given(EMPEROR_GIVEN, 0.55))
    return build_clan(surname, father_name, title, grade, daughter_status=meta.get("daughter_status"))


# 两家族初始关系（设计 3.4）
def initial_clan_relation(player_clan, npc_clan, player_rank_name):
    pf, nf = player_clan["政治倾向"], npc_clan["政治倾向"]
    player_high = player_rank_name in ("贵妃", "妃", "嫔", "婕妤", "皇后", "皇贵妃")
    if pf == nf and player_high:
        rel, fav = "故交", random.randint(10, 30)
    elif pf == nf:
        rel, fav = "中立", random.randint(-5, 10)
    elif player_high:
        rel, fav = "政敌", random.randint(-15, -5)
    else:
        rel, fav = "政敌", random.randint(-20, -10)
    if random.random() < 0.12:
        rel, fav = "姻亲", random.randint(15, 35)
    elif random.random() < 0.08:
        rel, fav = "世仇", random.randint(-30, -18)
    return {"好感": fav, "关系": rel, "历史": [f"两族入宫前便已{('交好' if fav >= 10 else '对立' if fav <= -10 else '平素')}于朝堂"]}


def clan_relation_label(fav):
    if fav >= 40:
        return "世交"
    if fav >= 15:
        return "故交"
    if fav >= -10:
        return "中立"
    if fav >= -25:
        return "政敌"
    return "世仇"


def default_court_state():
    return {
        "派系好感": {"文官党": 50, "武官党": 50, "宗室党": 50},
        "所有家族": {},
        "当前热点": [],
        "奏章队列": [],
        "政治局势": "平稳",
        "每旬动态": [],
    }


PLAYER_FAMILY_OPTIONS = []


# ===== 前朝关联：家族事件引擎 =====
FAMILY_EVENT_QUEUE_MAX = 2

# 选项效果键（apply_family_choice 结算）：
# 银两 / 威望（玩家）/ 家族威望 / 风险（家族风险值）/ 家族银两 / 恩荫（次数）
# 好感_{派系}（朝堂党派好感）/ 族谊_{npc名}（NPC 家族与玩家家族关系）
FAMILY_EVENT_TEMPLATES = [
    {
        "id": "clan_letter", "type": "家书问安", "icon": "✉️",
        "title": "家父来信",
        "desc": "父亲{father}遣人送来家书：\u201c为父在朝一切安好，家中诸事顺遂。听闻吾儿在宫中受用，阖家与有荣焉。\u201d",
        "choices": [
            {"text": "回信问安，附上关怀", "icon": "✉️", "effects": {"家族威望": 2}},
            {"text": "捎回五十两补贴家用", "icon": "💰", "effects": {"银两": -50, "家族威望": 4, "风险": -3}},
            {"text": "宫务繁忙，不必多礼", "icon": "🙅", "effects": {}},
        ],
    },
    {
        "id": "clan_favor", "type": "恩荫请托", "icon": "🏛️",
        "title": "族中求官",
        "desc": "族兄{brother}托人递话：愿在{faction}中谋一实缺，若得妃闱吹风，必不负家族栽培。",
        "choices": [
            {"text": "替他在御前美言几句", "icon": "🗣️", "effects": {"威望": -5, "恩荫": 1, "家族威望": 5, "好感_{faction}": 3}},
            {"text": "婉拒：宫中不便干政", "icon": "🙅", "effects": {"风险": 3}},
            {"text": "让他耐心候缺", "icon": "⏳", "effects": {}},
        ],
    },
    {
        "id": "clan_impeach", "type": "族中风波", "icon": "⚠️",
        "title": "父亲遭弹劾",
        "desc": "朝中有人弹劾父亲{father}政绩不实，御史连上两折。家族风险陡增，只怕风波会烧到宫里来。",
        "choices": [
            {"text": "花三百两打点御史", "icon": "💰", "effects": {"银两": -300, "风险": -12, "家族威望": 2}},
            {"text": "御前剖白心迹，为父辩白", "icon": "🙇", "effects": {"威望": -8, "风险": -8}},
            {"text": "静观其变，相信父亲", "icon": "⏳", "effects": {"风险": 6}},
        ],
    },
    {
        "id": "clan_alliance", "type": "联姻示好", "icon": "🤝",
        "title": "同族示好",
        "desc": "{npc}的母族遣人暗中示好：两家同朝为官，若能互为奥援，宫里宫外都好做事。",
        "choices": [
            {"text": "礼尚往来，两族修好", "icon": "🤝", "effects": {"族谊_{npc}": 15}},
            {"text": "虚与委蛇，不置可否", "icon": "🎭", "effects": {"族谊_{npc}": 3}},
            {"text": "闭门不见", "icon": "🚪", "effects": {"族谊_{npc}": -8}},
        ],
    },
    {
        "id": "clan_tribute", "type": "家族孝敬", "icon": "🧧",
        "title": "家族孝敬",
        "desc": "家族送来孝敬：白银二百两、绸缎四匹，另有父亲{father}手书一封，嘱托\u201c好生保重凤体\u201d。",
        "choices": [
            {"text": "笑纳", "icon": "🧧", "effects": {"银两": 200, "家族威望": 1}},
            {"text": "退回大半，只留心意", "icon": "🎁", "effects": {"银两": 60, "威望": 2}},
            {"text": "原封退回", "icon": "🚫", "effects": {"家族威望": -2}},
        ],
    },
]


def ensure_clans(game_state):
    """补全缺失的家族结构（旧存档迁移 / NPC 新增），不产生情报。"""
    from names import extract_surname
    if not isinstance(getattr(game_state, "player_clan", None), dict):
        try:
            surname = extract_surname(game_state.name or "") or "沈"
            game_state.player_clan = generate_player_clan(surname, getattr(game_state, "family_meta", {}) or {})
        except Exception:
            game_state.player_clan = None
    clan = game_state.player_clan if isinstance(game_state.player_clan, dict) else None
    for name, npc in (game_state.npcs or {}).items():
        if not isinstance(npc, dict) or name == "太后" or not npc.get("alive", True):
            continue
        if not isinstance(npc.get("clan"), dict):
            npc["clan"] = generate_npc_clan(name, npc.get("rank", "答应"), npc.get("family_meta"))
        c = npc["clan"]
        if clan and not isinstance(c.get("与玩家家族关系"), dict):
            c["与玩家家族关系"] = initial_clan_relation(clan, c, game_state.rank.name)
    return clan


def process_clan_period(game_state):
    """每旬前朝结算：家族补全、NPC 升降位反映到家族威望、风险值回落与爆发。返回情报列表。"""
    msgs = []
    clan = ensure_clans(game_state)
    if not clan:
        return msgs
    from app import RANK_LEVELS
    for name, npc in (game_state.npcs or {}).items():
        if not isinstance(npc, dict) or name == "太后" or not npc.get("alive", True):
            continue
        c = npc.get("clan")
        if not isinstance(c, dict):
            continue
        cur = npc.get("rank", "答应")
        last = c.get("last_rank")
        if last and last != cur:
            old = RANK_LEVELS.get(last, 0)
            new = RANK_LEVELS.get(cur, 0)
            if new != old:
                c["家族威望"] = max(10, min(95, int(c.get("家族威望", 40)) + (3 if new > old else -3)))
                verb = "晋位" if new > old else "降位"
                msgs.append(f"🏛️ {name}{verb}（{last}→{cur}），{c.get('surname', '')}家在朝中声势随之{'水涨船高' if new > old else '有所回落'}")
        c["last_rank"] = cur
    # 玩家家族风险：自然回落，积重则爆发
    risk = int(clan.get("风险值", 0) or 0)
    risk = max(0, risk - 1)
    if risk >= 80 and random.random() < 0.5:
        loss = random.randint(8, 15)
        game_state.attributes["威望"] = max(0, game_state.attributes.get("威望", 0) - loss)
        clan["风险值"] = max(0, risk - 30)
        msgs.append(f"⚠️ 家族积弊发作，御史弹劾牵连于你，威望-{loss}")
        game_state.add_memory(f"家族风险爆发，威望-{loss}")
    else:
        clan["风险值"] = risk
    return msgs


def _alive_npc_with_clan(game_state):
    names = [n for n, c in (game_state.npcs or {}).items()
             if isinstance(c, dict) and c.get("alive", True) and n != game_state.name
             and isinstance(c.get("clan"), dict)]
    return random.choice(names) if names else None


def generate_family_events(game_state):
    """转旬时按概率生成 0~1 件家族事件（队列上限 2）。"""
    if not isinstance(getattr(game_state, "family_event_queue", None), list):
        game_state.family_event_queue = []
    if not isinstance(getattr(game_state, "family_event_history", None), list):
        game_state.family_event_history = []
    if len(game_state.family_event_queue) >= FAMILY_EVENT_QUEUE_MAX:
        return
    if random.random() >= 0.4:
        return
    clan = game_state.player_clan if isinstance(game_state.player_clan, dict) else None
    if not clan or not clan.get("father", {}).get("alive", True):
        return
    father = clan["father"]
    brother = next((b["name"] for b in clan.get("brothers", []) if b.get("alive", True)), father["name"])
    faction = clan.get("政治倾向") or "文官党"
    npc = _alive_npc_with_clan(game_state)
    if npc is None:
        npc = "宫中同僚"
    for tpl in random.sample(FAMILY_EVENT_TEMPLATES, len(FAMILY_EVENT_TEMPLATES)):
        if "npc" in tpl["desc"] and npc == "宫中同僚" and tpl["id"] == "clan_alliance":
            continue
        game_state.family_event_queue.append({
            "id": f"fam_{tpl['id']}_{game_state.year}_{game_state.month}_{len(game_state.family_event_queue)}",
            "type": tpl["type"], "icon": tpl["icon"],
            "title": tpl["title"].format(father=father["name"], brother=brother, faction=faction, npc=npc),
            "desc": tpl["desc"].format(father=father["name"], brother=brother, faction=faction, npc=npc),
            "choices": [{"text": ch["text"].format(faction=faction, npc=npc), "icon": ch.get("icon", ""),
                         "effects": {k.format(faction=faction, npc=npc): v for k, v in (ch.get("effects") or {}).items()}}
                        for ch in tpl["choices"]],
            "period": f"{game_state.year}年{game_state.month}月",
        })
        return


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def apply_family_choice(game_state, ev, choice):
    """结算家族事件选项。返回 {narration, effects}。"""
    effects = {}
    clan = game_state.player_clan if isinstance(game_state.player_clan, dict) else {}
    favor = {"文官党": 50, "武官党": 50, "宗室党": 50}
    favor.update(getattr(game_state, "court_faction_favor", None) or {})
    for k, v in (choice.get("effects") or {}).items():
        v = int(v)
        if k == "银两":
            game_state.silver = max(0, game_state.silver + v)
            effects["银两"] = v
        elif k == "威望":
            old = int(game_state.attributes.get("威望", 0) or 0)
            game_state.attributes["威望"] = int(_clamp(old + v, 0, game_state.get_attr_max("威望")))
            effects["威望"] = v
        elif k == "家族威望":
            clan["家族威望"] = _clamp(int(clan.get("家族威望", 40) or 0) + v, 10, 95)
            effects["家族威望"] = v
        elif k == "风险":
            clan["风险值"] = _clamp(int(clan.get("风险值", 0) or 0) + v, 0, 100)
            effects["家族风险"] = v
        elif k == "家族银两":
            clan["家族银两"] = max(0, int(clan.get("家族银两", 0) or 0) + v)
            effects["家族银两"] = v
        elif k == "恩荫":
            clan["恩荫次数"] = max(0, int(clan.get("恩荫次数", 0) or 0) + v)
            effects["恩荫"] = v
        elif k.startswith("好感_"):
            faction = k.split("_", 1)[1]
            if faction in favor:
                favor[faction] = _clamp(int(favor[faction] or 0) + v, 0, 100)
                effects[f"{faction}好感"] = v
        elif k.startswith("族谊_"):
            npc_name = k.split("_", 1)[1]
            npc = (game_state.npcs or {}).get(npc_name)
            rel = npc.get("clan", {}).get("与玩家家族关系") if isinstance(npc, dict) else None
            if isinstance(rel, dict):
                rel["好感"] = _clamp(int(rel.get("好感", 0) or 0) + v, -100, 100)
                rel["关系"] = clan_relation_label(rel["好感"])
                rel.setdefault("历史", []).append(f"[{ev.get('period', '')}] {ev.get('title', '')}：{choice.get('text', '')}")
                effects[f"与{npc_name}母族"] = v
    game_state.court_faction_favor = favor
    narr = f"「{ev.get('title', '')}」你处置：{choice.get('text', '')}。"
    parts = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in effects.items() if v != 0]
    if parts:
        narr += "（" + "、".join(parts) + "）"
    hist = getattr(game_state, "family_event_history", None)
    if not isinstance(hist, list):
        hist = []
    hist.insert(0, {"id": ev.get("id"), "title": ev.get("title"), "type": ev.get("type"),
                    "choice": choice.get("text"), "period": ev.get("period")})
    game_state.family_event_history = hist[:20]
    return {"narration": narr, "effects": effects}
