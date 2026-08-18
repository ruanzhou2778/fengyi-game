# npcs.py
import random
from names import generate_female_name, NPC_SURNAMES, FEMALE_GIVEN

SURNAMES = NPC_SURNAMES
GIVEN_NAMES = FEMALE_GIVEN

PERSONALITIES = [
    {"name": "端庄大方", "desc": "举止得体，深得人心", "traits": ["宽容", "城府深"]},
    {"name": "妖艳张扬", "desc": "美貌绝伦，恃宠而骄", "traits": ["骄傲", "狠辣"]},
    {"name": "温婉贤淑", "desc": "与世无争，善解人意", "traits": ["善良", "懦弱"]},
    {"name": "聪明机敏", "desc": "心思玲珑，善于谋划", "traits": ["机智", "圆滑"]},
    {"name": "高傲冷艳", "desc": "孤芳自赏，不屑争宠", "traits": ["清高", "孤僻"]},
    {"name": "活泼开朗", "desc": "天真烂漫，人缘极好", "traits": ["乐观", "单纯"]},
    {"name": "阴险毒辣", "desc": "笑里藏刀，心狠手辣", "traits": ["狠毒", "多疑"]},
    {"name": "懦弱胆小", "desc": "胆小怕事，随波逐流", "traits": ["懦弱", "依赖"]},
    {"name": "野心勃勃", "desc": "不甘人下，志在皇后", "traits": ["野心", "隐忍"]},
    {"name": "清冷孤傲", "desc": "不爱热闹，独居一隅", "traits": ["清冷", "孤傲"]}
]

NPC_RANKS = ["答应", "常在", "贵人", "才人", "美人", "婕妤", "嫔", "妃", "淑妃", "德妃", "贤妃", "宸妃", "贵妃", "皇贵妃", "皇后"]

def generate_npc_rank():
    """生成普通妃嫔位份（排除皇后）"""
    weights = [22, 18, 15, 12, 10, 8, 6, 4, 2, 2, 2, 2, 1, 1, 0]
    return random.choices(NPC_RANKS, weights=weights)[0]

def generate_queen():
    """专门生成皇后"""
    return "皇后"

def generate_npc_name():
    return generate_female_name()

def generate_npc_personality():
    return random.choice(PERSONALITIES)

def generate_npc_attributes():
    return {
        "容貌": random.randint(40, 95),
        "才情": random.randint(30, 90),
        "心计": random.randint(30, 95),
        "宠爱": random.randint(10, 80),
        "威望": random.randint(10, 70),
        "健康": random.randint(50, 95),
        "福运": random.randint(30, 70),
        "倾向": random.randint(20, 70),
    }

def generate_npc(is_queen=False):
    """生成NPC，包含完整的怀孕状态字段"""
    if is_queen:
        rank = "皇后"
        personality = PERSONALITIES[0]
        attrs = {
            "容貌": random.randint(70, 95),
            "才情": random.randint(70, 95),
            "心计": random.randint(70, 95),
            "宠爱": random.randint(60, 90),
            "威望": random.randint(80, 100),
            "健康": random.randint(70, 95),
            "福运": random.randint(50, 80),
            "倾向": random.randint(70, 95),
        }
    else:
        rank = generate_npc_rank()
        personality = generate_npc_personality()
        attrs = generate_npc_attributes()
        rank_bonus = {
            "答应": {"容貌": 5, "才情": 5, "心计": 0},
            "常在": {"容貌": 10, "才情": 10, "心计": 5},
            "贵人": {"容貌": 15, "才情": 15, "心计": 10},
            "嫔": {"容貌": 20, "才情": 20, "心计": 15},
            "妃": {"容貌": 24, "才情": 24, "心计": 18},
            "淑妃": {"容貌": 25, "才情": 25, "心计": 20},
            "德妃": {"容貌": 26, "才情": 26, "心计": 21},
            "贤妃": {"容貌": 27, "才情": 27, "心计": 22},
            "宸妃": {"容貌": 28, "才情": 28, "心计": 23},
            "贵妃": {"容貌": 30, "才情": 30, "心计": 25},
            "皇贵妃": {"容貌": 35, "才情": 35, "心计": 30}
        }
        bonus = rank_bonus.get(rank, {})
        for key, val in bonus.items():
            attrs[key] = min(100, attrs[key] + val)
    
    icons = ["🌸", "🌺", "🌷", "💐", "🌹", "🌻", "🌿", "🍃", "🪷", "🌙"]
    
    return {
        "name": generate_npc_name(),
        "rank": rank,
        "personality": personality["name"],
        "personality_desc": personality["desc"],
        "traits": personality["traits"],
        "attributes": attrs,
        "relationship": {
            "好感": random.randint(-20, 50) if not is_queen else random.randint(10, 40),
            "印象": random.choice(["友善", "疏离", "敌视", "崇拜", "嫉妒", "畏惧", "信任"]) if not is_queen else "威严尊贵",
            "互动次数": 0
        },
        "icon": random.choice(icons),
        "is_active": True,
        "alive": True,
        # ===== 完整怀孕状态字段 =====
        "is_pregnant": False,
        "pregnancy_month": 0,
        "children": [],
        "pregnancy_history": [],
        "last_conception_day": 0,
        "fertility": random.randint(20, 80),
        "miscarriage_risk": random.randint(5, 30),
        "pregnancy_bonus": {"宠爱": 0, "威望": 0, "健康": 0},
        "压力": random.randint(8, 28) if not is_queen else random.randint(5, 18),
    }

def generate_all_npcs(count=8):
    """生成所有NPC，包含一位皇后"""
    npcs = {}
    queen = generate_npc(is_queen=True)
    npcs[queen["name"]] = queen
    for i in range(count):
        npc = generate_npc(is_queen=False)
        while npc["name"] in npcs:
            npc["name"] = generate_npc_name()
        npcs[npc["name"]] = npc
    npc_names = list(npcs.keys())
    for i, name in enumerate(npc_names):
        if i < len(npc_names) - 1:
            if random.random() > 0.6:
                target = random.choice(npc_names[:i] + npc_names[i+1:])
                if target != "皇后" and name != "皇后":
                    change = random.randint(-15, 20)
                    npcs[name]["relationship"]["好感"] = max(-100, min(100, npcs[name]["relationship"]["好感"] + change // 2))
    return npcs

def get_npc_info(name, npcs_cache=None):
    if npcs_cache and name in npcs_cache:
        return npcs_cache[name]
    return {
        "name": name,
        "rank": "妃嫔",
        "personality": "未知",
        "personality_desc": "暂无了解",
        "traits": [],
        "attributes": {},
        "relationship": {"好感": 0, "印象": "陌生", "互动次数": 0},
        "icon": "👤",
        "is_active": True,
        "alive": True,
        "is_pregnant": False,
        "pregnancy_month": 0,
        "children": [],
        "pregnancy_history": [],
        "last_conception_day": 0,
        "fertility": 50,
        "miscarriage_risk": 15,
        "pregnancy_bonus": {"宠爱": 0, "威望": 0, "健康": 0}
    }

def get_all_npcs(npcs_cache=None):
    if npcs_cache:
        return list(npcs_cache.keys())
    return []

def check_npc_pregnancy_status(npc):
    if npc.get("is_pregnant", False):
        month = npc.get("pregnancy_month", 0)
        if month < 3:
            return f"🤰 孕早期（{int(month)}月）"
        elif month < 6:
            return f"🤰 孕中期（{int(month)}月）"
        elif month < 9:
            return f"🤰 孕晚期（{int(month)}月）"
        else:
            return f"🤰 临盆在即（{int(month)}月）"
    return "未孕"

def can_npc_get_pregnant(npc):
    if not npc.get("alive", True):
        return False
    if npc.get("is_pregnant", False):
        return False
    health = npc.get("attributes", {}).get("健康", 50)
    if health < 40:
        return False
    fertility = npc.get("fertility", 50)
    base_chance = fertility / 100.0 * 0.7
    health_bonus = max(0, (health - 50) / 100.0)
    return random.random() < (base_chance + health_bonus * 0.3)

def update_npc_pregnancy(npc, game_day):
    if not npc.get("is_pregnant", False):
        return False, None
    month = npc.get("pregnancy_month", 0) + 0.5
    npc["pregnancy_month"] = month
    if random.random() * 100 < npc.get("miscarriage_risk", 15):
        npc["is_pregnant"] = False
        npc["pregnancy_month"] = 0
        npc["pregnancy_history"].append({
            "day": game_day,
            "outcome": "流产",
            "month": month
        })
        return True, "流产"
    if month >= 10:
        npc["is_pregnant"] = False
        npc["pregnancy_month"] = 0
        return True, "生产"
    return False, None