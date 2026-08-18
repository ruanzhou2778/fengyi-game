# events.py
import random

# ============================================================
#  本地事件模板库（根据本局妃子具体化）
# ============================================================
LOCAL_EVENT_TEMPLATES = [
    {"desc": "{npc1}与{npc2}在御花园相遇，因言语不合起了冲突。", "effects": {"宠爱": (2, 6), "威望": (-3, 3), "心计": (1, 4)}},
    {"desc": "{npc1}在皇帝面前献舞，博得龙颜大悦。", "effects": {"宠爱": (5, 12), "威望": (2, 5)}},
    {"desc": "{npc1}深夜在御书房外弹琴，皇帝召其入内伴驾。", "effects": {"宠爱": (8, 15), "威望": (3, 6)}},
    {"desc": "{npc1}得知皇帝喜爱梅花，连夜在御花园种下十株红梅。", "effects": {"宠爱": (6, 10), "威望": (4, 8)}},
    {"desc": "{npc1}在宫宴上即兴赋诗，满座皆惊。", "effects": {"宠爱": (4, 9), "才情": (3, 7), "威望": (3, 6)}},
    {"desc": "{npc1}与{npc2}同时向皇帝献上寿礼，暗中较劲。", "effects": {"宠爱": (3, 8), "威望": (-2, 4), "心计": (2, 5)}},
    {"desc": "{npc1}在{npc2}的茶中下药，幸好被宫女发现。", "effects": {"心计": (5, 10), "宠爱": (-3, 3), "威望": (-5, 0)}},
    {"desc": "{npc1}散布谣言说{npc2}私通外臣。", "effects": {"心计": (4, 8), "威望": (-6, 2), "宠爱": (-3, 3)}},
    {"desc": "{npc1}在{npc2}的寝殿里放了一双绣花鞋，意图栽赃。", "effects": {"心计": (6, 12), "威望": (-5, 3), "宠爱": (-2, 4)}},
    {"desc": "{npc1}买通太医，让{npc2}的安胎药变成了毒药。", "effects": {"心计": (8, 15), "宠爱": (-8, 0), "威望": (-10, -3)}},
    {"desc": "{npc1}在太后面前告发{npc2}不敬之罪。", "effects": {"心计": (5, 10), "威望": (3, 8), "宠爱": (-3, 2)}},
    {"desc": "宫中传言{npc1}曾与一名侍卫有染。", "effects": {"心计": (3, 6), "威望": (-8, -2), "宠爱": (-5, 0)}},
    {"desc": "有人散播消息说{npc1}是灾星转世。", "effects": {"威望": (-10, -3), "宠爱": (-6, -1), "心计": (2, 5)}},
    {"desc": "后宫传闻{npc1}暗中诅咒皇帝。", "effects": {"威望": (-12, -4), "宠爱": (-8, -2), "心计": (4, 8)}},
    {"desc": "有流言说{npc1}与{npc2}结党营私。", "effects": {"威望": (-6, 2), "心计": (3, 6), "宠爱": (-3, 3)}},
    {"desc": "{npc1}向{npc2}赠送了稀世珍宝，表达结盟之意。", "effects": {"心计": (2, 5), "威望": (2, 4), "宠爱": (0, 2)}},
    {"desc": "{npc1}在{npc2}失宠时伸出援手，赢得了信任。", "effects": {"心计": (3, 6), "威望": (4, 8), "宠爱": (1, 3)}},
    {"desc": "{npc1}与{npc2}在佛堂偶遇，相约一同吃斋念佛。", "effects": {"心计": (2, 4), "威望": (3, 6), "福运": (2, 4)}},
    {"desc": "{npc1}在御花园赏花时被蜜蜂蜇伤，皇帝亲自探望。", "effects": {"宠爱": (3, 8), "健康": (-3, 0), "威望": (2, 4)}},
    {"desc": "{npc1}不慎摔碎了一尊玉佛，被罚禁足三日。", "effects": {"威望": (-5, -1), "宠爱": (-3, 0), "心计": (1, 3)}},
    {"desc": "{npc1}的寝殿夜间失火，幸好扑救及时。", "effects": {"健康": (-5, -1), "威望": (2, 5), "宠爱": (2, 4)}},
    {"desc": "{npc1}在御膳房尝了一道新菜，赞不绝口，传为美谈。", "effects": {"威望": (2, 4), "宠爱": (1, 3)}},
    {"desc": "{npc1}在湖边散步时不慎落水，被一名侍卫救起。", "effects": {"健康": (-4, -1), "威望": (-2, 2), "宠爱": (1, 4)}},
    {"desc": "{npc1}因才情出众，被皇帝钦点主持中秋诗会。", "effects": {"宠爱": (4, 9), "威望": (5, 10), "才情": (3, 6)}},
    {"desc": "{npc1}在太后寿宴上献上自绣的百寿图，太后大喜。", "effects": {"威望": (8, 15), "宠爱": (5, 10), "才艺": (3, 6)}},
    {"desc": "{npc1}因抚育皇子有功，皇帝有意晋封。", "effects": {"威望": (10, 18), "宠爱": (6, 12)}},
    {"desc": "{npc1}在御前失仪，被罚抄写宫规一百遍。", "effects": {"威望": (-6, -2), "宠爱": (-3, 0), "心计": (1, 3)}},
    {"desc": "{npc1}与{npc2}在宫道上狭路相逢，互不相让。", "effects": {"威望": (-3, 3), "心计": (2, 5), "宠爱": (-2, 2)}},
    {"desc": "{npc1}的宫女偷窃被捉，牵连主仆失和。", "effects": {"威望": (-4, 0), "心计": (1, 4), "宠爱": (-2, 1)}},
    {"desc": "{npc1}在佛前许愿，祈求皇帝龙体安康。", "effects": {"威望": (3, 6), "福运": (2, 5)}},
    {"desc": "{npc1}与{npc2}相约一同赏雪，关系亲近了几分。", "effects": {"心计": (1, 3), "威望": (2, 4)}},
    {"desc": "{npc1}精心培育的一株牡丹开出了并蒂花，被视为祥瑞。", "effects": {"威望": (4, 8), "宠爱": (3, 6), "福运": (3, 6)}},
]

def generate_local_events(game_state, max_count=2):
    """生成最多 max_count 条本地事件，并尽量使用不同妃子名，避免重复"""
    if not game_state.npcs:
        return []
    npc_names = [name for name in game_state.npcs.keys() if name not in ["太后", "皇后"]]
    if not npc_names:
        return []
    num_events = min(max_count, len(LOCAL_EVENT_TEMPLATES), len(npc_names))
    selected_templates = random.sample(LOCAL_EVENT_TEMPLATES, min(num_events, len(LOCAL_EVENT_TEMPLATES)))
    events = []
    used_names = set()
    for template in selected_templates:
        desc_template = template["desc"]
        needs_two = "{npc2}" in desc_template
        available = [n for n in npc_names if n not in used_names]
        if not available:
            break
        if needs_two:
            pool = available if len(available) >= 2 else npc_names
            if len(pool) < 2:
                continue
            npc1, npc2 = random.sample(pool, 2)
            desc = desc_template.replace("{npc1}", npc1).replace("{npc2}", npc2)
        else:
            npc1 = random.choice(available)
            npc2 = None
            desc = desc_template.replace("{npc1}", npc1)
        effects = {}
        for attr, (min_val, max_val) in template["effects"].items():
            effects[attr] = random.randint(min_val, max_val)
        events.append({"desc": desc, "effects": effects})
        used_names.add(npc1)
        if npc2:
            used_names.add(npc2)
    return events

# ============================================================
#  特殊事件（仅用于实时行动，转旬不用）
# ============================================================
SPECIAL_EVENTS = [
    {"name": "御花园偶遇", "trigger": {"宠爱": 40}, "description": "你在御花园赏花时，偶遇皇帝微服游园。", "effects": {"宠爱": 10, "威望": 5}, "choices": ["上前请安", "假装没看见", "故意展示才艺"], "story_hint": "皇帝正在游园"},
    {"name": "太后召见", "trigger": {"威望": 30}, "description": "太后突然召你前往慈宁宫，不知所谓何事。", "effects": {"威望": 10, "心计": 5}, "choices": ["恭敬前往", "称病不去", "找人打听"], "story_hint": "太后有要事相商"},
    {"name": "皇帝赏赐", "trigger": {"宠爱": 60}, "description": "皇帝今日心情大好，赏赐了众多珍宝给后宫。", "effects": {"宠爱": 5, "威望": 10}, "choices": ["欣然接受", "推辞谦让", "请求赏赐他人"], "story_hint": "龙颜大悦"},
]

def check_event(game_state):
    # 降低实时行动的随机事件触发概率，避免频繁弹出
    if random.random() > 0.1:  # 原来0.3，改为0.1
        return None
    attrs = game_state.attributes
    available = []
    for event in SPECIAL_EVENTS:
        trigger = event.get("trigger", {})
        meets = True
        for attr, threshold in trigger.items():
            if attrs.get(attr, 0) < threshold:
                meets = False
                break
        if meets:
            available.append(event)
    if available:
        available.sort(key=lambda e: sum(e.get("trigger", {}).values()), reverse=True)
        return random.choice(available[:3])
    return None

def get_daily_actions():
    return {
        "晨起请安": {"宠爱": 2, "威望": 3, "健康": -1, "desc": "向皇后和太后请安"},
        "练习才艺": {"才情": 5, "健康": -2, "desc": "练习琴棋书画"},
        "结交妃嫔": {"心计": 3, "威望": 2, "desc": "与其他妃嫔走动"},
        "侍奉皇帝": {"宠爱": 8, "健康": -3, "desc": "去御书房侍奉皇帝"},
        "宫中散步": {"健康": 3, "容貌": 1, "desc": "在宫中散步赏景"},
        "打听消息": {"心计": 5, "威望": 1, "desc": "打探宫中消息"},
    }

def apply_daily_action(game_state, action_key):
    actions = get_daily_actions()
    if action_key not in actions:
        return None
    action = actions[action_key]
    effects = {}
    for attr, change in action.items():
        if attr != "desc" and attr in game_state.attributes:
            old_value = game_state.attributes[attr]
            game_state.attributes[attr] = max(0, min(100, old_value + change))
            effects[attr] = change
    game_state.add_memory(f"进行了每日行动：{action['desc']}")
    return effects