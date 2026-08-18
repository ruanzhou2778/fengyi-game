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
    {"key": "私生", "weight": 12, "rank_offset": 3, "score_mod": -20, "attr": {"心计": 3, "容貌": -1}},
]

PLAYER_START_RANKS = ["秀女", "答应", "常在", "贵人", "嫔"]

GRADE_BASE_RANK_INDEX = {1: 3, 2: 2, 3: 2, 4: 1, 5: 1, 6: 0, 7: 0, 8: 0, 9: 0}

GRADE_BASE_SCORE = {1: 88, 2: 78, 3: 70, 4: 62, 5: 55, 6: 48, 7: 42, 8: 36, 9: 30}

GRADE_WEIGHTS = [1, 2, 3, 4, 5, 6, 7, 8, 9]
GRADE_WEIGHT_VALUES = [2, 3, 6, 10, 14, 18, 16, 12, 6]

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

    grade = random.choices(GRADE_WEIGHTS, weights=GRADE_WEIGHT_VALUES)[0]
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


# 兼容旧版 app.py 导入（世家名录已改为官家出身）
def random_family_clan(surname=None):
    bg = generate_official_background(surname or random_surname())
    return bg["label"]


PLAYER_FAMILY_OPTIONS = []
