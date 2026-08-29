# player_traits.py — 主控特殊标签：属性加成 + 智能推荐
import random

TRAIT_DEFS = {
    "容貌倾国": {"attr": "容貌", "bonus": 2, "desc": "容貌+10"},
    "才情绝世": {"attr": "才情", "bonus": 2, "desc": "才情+10"},
    "心计过人": {"attr": "心计", "bonus": 2, "desc": "心计+10"},
    "谋略超群": {"attr": "谋略", "bonus": 2, "desc": "谋略+10"},
    "福运深厚": {"attr": "福运", "bonus": 2, "desc": "福运+10"},
    "魅力难挡": {"attr": "魅力", "bonus": 2, "desc": "魅力+10"},
    "健康强健": {"attr": "健康", "bonus": 2, "desc": "健康+10"},
    "才艺双绝": {"attr": "才艺", "bonus": 2, "desc": "才艺+10"},
    "勇敢无畏": {"attr": "倾向", "bonus": 2, "desc": "倾向+10"},
    "温柔似水": {"attr": "魅力", "bonus": 1, "desc": "魅力+5"},
    "冰雪聪明": {"attr": "才情", "bonus": 1, "desc": "才情+5"},
    "善解人意": {"attr": "威望", "bonus": 1, "desc": "威望+5"},
    "刚正不阿": {"attr": "威望", "bonus": 2, "desc": "威望+10"},
    "八面玲珑": {"attr": "心计", "bonus": 1, "desc": "心计+5"},
    "通透豁达": {"attr": "福运", "bonus": 1, "desc": "福运+5"},
    "执拗倔强": {"attr": "倾向", "bonus": 1, "desc": "倾向+5"},
    # ===== 心腹相关特质 =====
    "忠心耿耿": {"attr": "威望", "bonus": 2, "desc": "威望+10，立心腹时忠诚额外+5"},
    "知人善任": {"attr": "心计", "bonus": 2, "desc": "心计+10，心腹协助宫斗加成+5"},
    "恩威并施": {"attr": "威望", "bonus": 1, "desc": "威望+5，心腹背叛风险-20%"},
}

PERSONALITY_TRAITS = {
    "温婉贤淑": ["温柔似水", "善解人意"],
    "端庄大方": ["刚正不阿", "善解人意"],
    "活泼开朗": ["魅力难挡", "福运深厚"],
    "冷傲孤高": ["执拗倔强", "冰雪聪明"],
    "聪慧机敏": ["冰雪聪明", "心计过人"],
    "心机深沉": ["心计过人", "八面玲珑"],
    "温柔可人": ["温柔似水", "魅力难挡"],
    "刚烈果断": ["勇敢无畏", "执拗倔强"],
    "娴静淡雅": ["通透豁达", "冰雪聪明"],
    "娇俏灵动": ["魅力难挡", "福运深厚"],
    "沉稳内敛": ["谋略超群", "通透豁达"],
    "明媚张扬": ["容貌倾国", "魅力难挡"],
    "潇洒不羁": ["勇敢无畏", "通透豁达"],
    "纯真无邪": ["福运深厚", "温柔似水"],
    "坚韧隐忍": ["健康强健", "执拗倔强"],
}

TRAIT_OPTIONS = list(TRAIT_DEFS.keys())


def get_trait_catalog():
    return [
        {"name": name, "attr": info["attr"], "bonus": info["bonus"], "desc": info["desc"]}
        for name, info in TRAIT_DEFS.items()
    ]


def suggest_traits(attrs=None, personality=None, count=3, max_total=3):
    """根据属性分配与性格，推荐特殊标签。"""
    attrs = attrs or {}
    count = max(1, min(max_total, count))
    scores = {}

    for trait, info in TRAIT_DEFS.items():
        attr_key = info["attr"]
        scores[trait] = attrs.get(attr_key, 0) * 2

    for trait in PERSONALITY_TRAITS.get(personality or "", []):
        scores[trait] = scores.get(trait, 0) + 12

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    chosen = []
    used_attrs = set()

    for trait, _ in ranked:
        if len(chosen) >= count:
            break
        attr_key = TRAIT_DEFS[trait]["attr"]
        if attr_key in used_attrs and scores[trait] < 10:
            continue
        chosen.append(trait)
        used_attrs.add(attr_key)

    if len(chosen) < count:
        pool = [t for t in TRAIT_OPTIONS if t not in chosen]
        random.shuffle(pool)
        for trait in pool:
            if len(chosen) >= count:
                break
            chosen.append(trait)

    return chosen[:count]


def apply_trait_bonuses(game_state, traits):
    """将标签加成写入角色属性（bonus * 5）。"""
    applied = []
    for trait in traits or []:
        info = TRAIT_DEFS.get(trait)
        if not info:
            continue
        attr = info["attr"]
        if attr not in game_state.attributes:
            continue
        gain = info.get("bonus", 1) * 5
        max_attr = game_state.get_attr_max(attr)
        game_state.attributes[attr] = max(0, min(max_attr, game_state.attributes[attr] + gain))
        applied.append({"trait": trait, "attr": attr, "gain": gain})
    return applied
