# scenarios.py
from models import Rank

START_SCENARIOS = {
    "世家贵女": {
        "description": "你是当朝重臣之女，家族势力庞大，入宫便是贵人。",
        "attributes_bonus": {"容貌": 10, "威望": 30, "才情": 5},
        "relationships_bonus": {"太后": 20, "皇后": 10},
        "initial_flag": "世家背景",
        "starting_history": "你父亲是当朝丞相，入宫前太后便对你青睐有加。"
    },
    "才女入宫": {
        "description": "你以才情闻名天下，是选秀中的佼佼者。",
        "attributes_bonus": {"才情": 30, "容貌": 10, "心计": 5},
        "relationships_bonus": {"皇帝": 20},
        "initial_flag": "才女之名",
        "starting_history": "你的一首《咏梅》传遍京城，皇帝特意钦点你入宫。"
    },
    "宫女逆袭": {
        "description": "你本是御前奉茶宫女，因机缘巧合被皇帝注意。",
        "attributes_bonus": {"心计": 20, "容貌": 5, "威望": 5},
        "relationships_bonus": {"皇帝": 15},
        "initial_flag": "宫女出身",
        "starting_history": "你在御前奉茶三年，深知宫中险恶，也练就了一身察言观色的本领。"
    },
    "和亲公主": {
        "description": "你是边陲小国的公主，为两国和平入宫和亲。",
        "attributes_bonus": {"容貌": 20, "心计": 10, "才情": 5},
        "relationships_bonus": {"太后": -10, "皇后": -20},
        "initial_flag": "和亲公主",
        "starting_history": "你来自异域，虽然被封为嫔，但宫中上下对你都心存戒备。"
    }
}

def apply_scenario(base_state, scenario_key):
    """应用场景卡（只加属性，不改变位份）"""
    scenario = START_SCENARIOS[scenario_key]
    # 属性加成
    for attr, bonus in scenario.get("attributes_bonus", {}).items():
        if attr in base_state.attributes:
            base_state.attributes[attr] = min(100, base_state.attributes[attr] + bonus)
    # 关系加成
    for person, bonus in scenario.get("relationships_bonus", {}).items():
        if person in base_state.relationships:
            base_state.relationships[person] = min(100, base_state.relationships[person] + bonus)
    # 剧情标志
    base_state.story_flags.append(scenario.get("initial_flag", ""))
    base_state.history.append(scenario.get("starting_history", ""))
    return base_state