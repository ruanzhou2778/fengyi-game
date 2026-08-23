# ai_service.py
import os
import json
import random
import re
from openai import OpenAI
from dotenv import load_dotenv
from names import generate_emperor_name_local

load_dotenv()

# 从环境变量或前端配置读取
def get_openai_client(api_key=None, base_url=None):
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY", "sk-xxx")
    if base_url is None:
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.siliconflow.cn/v1")
    return OpenAI(api_key=api_key, base_url=base_url)

NARRATIONS = [
    "你在御花园中漫步，花香袭人。",
    "宫中一片宁静，你独自走在长廊上。",
    "阳光正好，你遇到了几位妃嫔。",
]

def build_prompt(game_state, player_action, npc_names, event=None):
    rank = game_state.rank.name
    time = game_state.current_time
    attrs = game_state.attributes
    relationships = game_state.relationships
    memories = game_state.get_recent_memories(3)
    emperor = game_state.emperor
    storyline = game_state.storyline.value
    emperor_personality = emperor["personality"]
    emperor_name = emperor["name"]
    romance_mode = getattr(game_state, "romance_mode", False)
    custom_prompt = getattr(game_state, "custom_prompt", "")
    rel_desc = "\n".join([f"- {name}：好感度{info['好感']}，印象：{info['印象']}" for name, info in relationships.items() if info["好感"] != 0]) if relationships else "暂无特别关系"
    mem_desc = "\n".join([f"- {m}" for m in memories]) if memories else "暂无重要记忆"
    attr_desc = "、".join([f"{k}{v}" for k, v in attrs.items()])
    time_atmospheres = {"卯时": "清晨的露水还未干透，宫人们已经开始忙碌", "辰时": "晨光熹微，后宫正是请安的时辰", "巳时": "日头渐高，御花园里正是好风光", "午时": "正午时分，宫中一片寂静", "未时": "午后时光，慵懒而闲适", "申时": "夕阳西斜，宫中开始掌灯", "酉时": "暮色渐沉，晚膳时分", "戌时": "夜色渐浓，宫门紧闭", "亥时": "夜深人静，只有虫鸣"}
    atmosphere = time_atmospheres.get(time, "宫中一片宁静")
    npc_list_str = "、".join(npc_names) if npc_names else "暂无其他妃嫔"
    romance_instruction = ""
    if not romance_mode:
        romance_instruction = """【重要：感情线模式已关闭】\n- 故事中**不要**出现与皇帝的暧昧、宠幸、情爱相关情节\n- **不要**描写争风吃醋、为爱争宠的内容\n- 专注于：权谋、晋升、宫斗策略、人际博弈、个人成长、事业线\n- 皇帝只是你事业路上的一个权力符号，不是感情对象\n- 如果提到皇帝，仅限于公务、朝政、权力关系层面\n- 故事基调偏向女强人奋斗史，而非后宫言情"""
    else:
        romance_instruction = """【感情线模式已开启】\n- 可以描写与皇帝的感情发展、暧昧、宠幸\n- 可以有后宫争宠、为爱争斗的情节\n- 保持宫斗小说的戏剧性"""
    custom_instruction = f"\n【用户自定义提示词】\n{custom_prompt}\n" if custom_prompt else ""
    prompt = f"""你是一个顶尖的宫斗题材小说作家，风格细腻典雅，类似《甄嬛传》和《如懿传》。

【重要规则】
后宫妃嫔名单（你只能提及以下人物，绝对不能编造新的人物）：
{npc_list_str}

{romance_instruction}
{custom_instruction}

【世界观设定】
- 朝代：架空大周王朝
- 皇帝：{emperor_name}（性格：{emperor_personality}）
- 你的位份：{rank}
- 当前时辰：{time}（{atmosphere}）
- 当前剧情线：{storyline}

【你的状态】
- 属性：{attr_desc}
- 人际关系：
{rel_desc}

【重要记忆】
{mem_desc}

【玩家行动】
{player_action}

【创作要求】
1. 根据时辰和皇帝性格调整故事氛围
2. 文笔要古风雅致，但不要晦涩难懂
3. 要有细腻的心理描写和对话
4. 故事要有戏剧性和张力
5. 根据当前剧情线发展故事
6. 提及的妃嫔必须来自上方名单，不得编造新人物
7. 如果情节需要反派，从名单中选择
8. {"注重事业线发展，减少感情描写" if not romance_mode else "可以适当发展感情线"}

请生成一段精彩的故事（80-120字），直接输出故事内容，不要加任何格式标记。"""
    return prompt

def _strip_reasoning(text):
    """清洗推理模型（DeepSeek-R1/QwQ 类）泄漏到正文里的思考过程。

    - 剥离 <think>...</think> / <thinking>...</thinking> 等标签块（含未闭合的残留）；
    - 去除以「思考：」「分析：」等前缀独占一行的引导段；
    - 返回清洗后的正文。
    """
    if not text:
        return text
    # 去掉成对的思维标签块
    text = re.sub(r"<\s*(think|thinking|reasoning|thought)\s*>.*?<\s*/\s*\1\s*>",
                  "", text, flags=re.DOTALL | re.IGNORECASE)
    # 去掉未闭合的起始标签及其之前的内容（模型只输出了 </think> 收尾的情况）
    m = re.search(r"<\s*/\s*(think|thinking|reasoning|thought)\s*>", text, flags=re.IGNORECASE)
    if m:
        text = text[m.end():]
    # 去掉残留的孤立标签
    text = re.sub(r"<\s*/?\s*(think|thinking|reasoning|thought)\s*>", "", text, flags=re.IGNORECASE)
    return text.strip()


def _extract_story_content(message):
    """从模型返回的 message 中提取「故事正文」。

    推理模型常把思考写进 reasoning_content，正文写进 content；
    这里只取 content，并清洗其中可能混入的 <think> 块。
    """
    content = getattr(message, "content", None) or ""
    return _strip_reasoning(content)


def generate_story(game_state, player_action, npc_names=None, api_key=None, base_url=None, model=None):
    if npc_names is None:
        npc_names = list(game_state.npcs.keys())
    from events import check_event
    event = check_event(game_state)
    prompt = build_prompt(game_state, player_action, npc_names, event)
    
    try:
        client = get_openai_client(api_key, base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是才华横溢的宫斗小说作家，擅长写细腻深刻的宫廷故事。故事要引人入胜，人物要有血有肉。你只输出故事正文本身，绝对不要输出任何思考过程、分析、评价、解释或 <think> 之类的标记；不要写「思考：」「分析：」「我认为」这类内容。注意：绝对不能编造后宫妃嫔名单之外的人物。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.85,
            max_tokens=500,
            top_p=0.95
        )
        narration = _extract_story_content(response.choices[0].message)
        if len(narration) < 20:
            narration = random.choice(NARRATIONS)
        base_changes = {"宠爱": random.randint(-2, 4), "威望": random.randint(-1, 3), "心计": random.randint(-1, 3), "健康": random.randint(-2, 2)}
        if event:
            for attr, change in event.get("effects", {}).items():
                if attr in base_changes:
                    base_changes[attr] += change
                else:
                    base_changes[attr] = change
            game_state.add_memory(f"{event['name']}")
        for attr, change in base_changes.items():
            if attr in game_state.attributes:
                max_val = game_state.get_attr_max(attr)
                game_state.attributes[attr] = max(0, min(max_val, game_state.attributes[attr] + change))
        for name in game_state.relationships:
            if random.random() < 0.3:
                change = random.randint(-2, 3)
                game_state.relationships[name]["好感"] = max(-100, min(100, game_state.relationships[name]["好感"] + change))
        game_state.history.append(f"行动：{player_action}")
        game_state.history.append(f"结果：{narration[:30]}...")
        return {"narration": narration, "choices": ["继续", "查看状态", "保存游戏"], "effects": base_changes, "event_triggered": event["name"] if event else None}
    except Exception as e:
        print(f"AI调用失败: {e}")
        return {"narration": random.choice(NARRATIONS), "choices": ["继续", "查看状态", "保存游戏"], "effects": {"宠爱": 0, "威望": 0, "心计": 0, "健康": 0}}

def check_promotion_condition(game_state):
    if game_state._pending_promotion is not None:
        return False
    rank_order = [
        "宫女", "更衣", "官女子", "秀女", "答应", "常在", "贵人", "才人", "美人", "婕妤",
        "嫔", "妃", "贵妃", "皇贵妃", "皇后",
    ]
    current_rank_name = game_state.rank.name
    if current_rank_name == "皇后":
        return False
    rank_thresholds = {
        "宫女": {"宠爱": 50, "威望": 30, "才情": 30, "心计": 25, "健康": 50},
        "秀女": {"宠爱": 60, "威望": 40, "才情": 40, "心计": 35, "健康": 55},
        "答应": {"宠爱": 70, "威望": 50, "才情": 50, "心计": 45, "健康": 55},
        "常在": {"宠爱": 80, "威望": 60, "才情": 55, "心计": 50, "健康": 60},
        "贵人": {"宠爱": 100, "威望": 70, "才情": 60, "心计": 55, "健康": 60},
        "嫔": {"宠爱": 150, "威望": 85, "才情": 65, "心计": 60, "健康": 65},
        "妃": {"宠爱": 200, "威望": 100, "才情": 70, "心计": 65, "健康": 65},
        "贵妃": {"宠爱": 300, "威望": 120, "才情": 75, "心计": 70, "健康": 70},
        "皇贵妃": {"宠爱": 400, "威望": 140, "才情": 80, "心计": 75, "健康": 75},
    }
    if current_rank_name in rank_thresholds:
        threshold = rank_thresholds[current_rank_name]
        attrs = game_state.attributes
        for attr, value in threshold.items():
            if attrs.get(attr, 0) < value:
                return False
        if "争宠胜利" not in game_state.story_flags:
            return False
        return True
    return False

def generate_promotion_event(game_state, api_key=None, base_url=None, model=None):
    rank_order = [
        "宫女", "更衣", "官女子", "秀女", "答应", "常在", "贵人", "才人", "美人", "婕妤",
        "嫔", "妃", "贵妃", "皇贵妃", "皇后",
    ]
    current_idx = rank_order.index(game_state.rank.name)
    if current_idx >= len(rank_order) - 1:
        return None
    next_rank = rank_order[current_idx + 1]
    rank_display = game_state.get_display_rank()
    next_display = next_rank
    attrs = game_state.attributes
    rels = game_state.relationships
    emperor = game_state.emperor
    
    
    
    prompt = f"""你是一个宫斗小说作家，请根据以下信息生成一个晋升剧情事件，格式为JSON。

玩家当前位份：{rank_display}，拟晋升为：{next_display}
玩家属性：{attrs}
皇帝性格：{emperor['personality']}
后宫人际关系：{rels}

请生成一个独特的晋升剧情，包含：
- 标题（简短）
- 剧情描述（100-150字）
- 三个选项，每个选项包含：文本、影响属性变化、是否正确（只有一个是正确的，其余错误）
- 选项影响属性变化格式为 {{"属性名": 变化值}}，例如 {{"宠爱": 10, "威望": 5}}
- 正确选项的效果应导致晋升成功，错误选项应带来惩罚（如减属性或降好感）

返回JSON格式：
{{
    "title": "晋升之机",
    "description": "剧情描述...",
    "options": [
        {{"text": "选项1", "effects": {{"宠爱": 5, "威望": 3}}, "is_correct": true, "success_msg": "晋升成功！", "fail_msg": "失败..."}},
        ...
    ]
}}

注意：必须只有一个是正确的，且正确选项的剧情要合理。返回纯JSON，不要其他文字。"""
    try:
        client = get_openai_client(api_key, base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是宫斗小说专家，只输出JSON格式。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.85,
            max_tokens=800,
            response_format={"type": "json_object"}
        )
        result = json.loads(_strip_reasoning(response.choices[0].message.content))
        if "title" in result and "description" in result and "options" in result:
            return result
        else:
            raise ValueError("缺少必要字段")
    except Exception as e:
        print(f"AI生成晋升剧情失败: {e}")
        return {
            "title": f"晋升之机",
            "description": f"你听闻皇帝有意晋封后宫，你当前的位份是「{rank_display}」，若能抓住机会，便可更上一层楼。",
            "options": [
                {"text": "主动向皇帝请安，展现才情", "effects": {"宠爱": 5, "威望": 5}, "is_correct": True, "success_msg": f"皇帝对你的表现很满意，晋封你为「{next_display}」。恭喜！", "fail_msg": ""},
                {"text": "静待时机，不主动争抢", "effects": {"宠爱": -2, "威望": -2}, "is_correct": False, "success_msg": "", "fail_msg": "你太过被动，机会被其他妃嫔抢走。"},
                {"text": "向皇后献殷勤，请求推荐", "effects": {"威望": 2, "心计": 2}, "is_correct": False, "success_msg": "", "fail_msg": "皇后推荐了你，但皇帝认为你攀附权贵。"}
            ]
        }

def get_flip_candidates(game_state):
    candidates = []
    player_name = game_state.name
    player_favor = game_state.attributes.get("宠爱", 0)
    player_appearance = game_state.attributes.get("容貌", 50)
    player_talent = game_state.attributes.get("才艺", 50)
    rank_score = {
        "更衣": 0, "官女子": 1, "答应": 2, "常在": 3, "贵人": 4,
        "才人": 5, "美人": 6, "婕妤": 7, "嫔": 8,
        "妃": 9,
        "贵妃": 10, "皇贵妃": 11, "皇后": 12
    }.get(game_state.rank.name, 0)
    player_weight = player_favor * 3 + player_appearance * 2 + player_talent * 1 + rank_score * 5
    
    # ===== 核心修改：玩家怀孕时权重大幅降低（但保留探望可能） =====
    if game_state.is_pregnant:
        player_weight = max(0, player_weight // 5)  # 降低到原来的1/5
        player_weight += 10  # 加一点点探望基础分
    
    if game_state.rank.name == "皇后":
        player_weight += 20
    candidates.append({"name": player_name, "weight": player_weight, "is_player": True})
    
    for name, npc in game_state.npcs.items():
        if name == "太后":
            continue
        favor = game_state.relationships.get(name, {}).get("好感", 0)
        appearance = npc.get("attributes", {}).get("容貌", 50)
        talent = npc.get("attributes", {}).get("才艺", 50)
        rank_score = {
            "更衣": 0, "官女子": 1, "答应": 2, "常在": 3, "贵人": 4,
            "才人": 5, "美人": 6, "婕妤": 7, "嫔": 8,
            "妃": 9,
            "贵妃": 10, "皇贵妃": 11, "皇后": 12
        }.get(npc.get("rank"), 0)
        weight = favor * 3 + appearance * 2 + talent * 1 + rank_score * 5
        
        # ===== NPC怀孕时权重降低 =====
        if npc.get("is_pregnant", False):
            weight = max(0, weight // 4) + 8  # 降低但保留探望可能
        
        if npc.get("rank") == "皇后":
            weight += 20
        candidates.append({"name": name, "weight": weight, "is_player": False})
    
    candidates.sort(key=lambda x: x["weight"], reverse=True)
    return candidates

# ============================================================
#  宫斗事件生成（AI版本）
# ============================================================

CONFLICT_TYPES = {
    "争宠": {"desc": "争夺皇帝的宠爱", "effects": {"宠爱": (5, 15), "威望": (-5, 5), "心计": (3, 8)}},
    "陷害": {"desc": "设计陷害对手", "effects": {"心计": (5, 12), "威望": (-8, 5), "宠爱": (-5, 5)}},
    "谣言": {"desc": "散布流言蜚语", "effects": {"心计": (3, 8), "威望": (-10, 3), "宠爱": (-3, 3)}},
    "拉拢": {"desc": "拉拢盟友共同对抗", "effects": {"心计": (3, 6), "威望": (2, 6), "宠爱": (0, 3)}},
    "告发": {"desc": "告发对手的不轨行为", "effects": {"威望": (5, 15), "心计": (5, 10), "宠爱": (-5, 5)}},
    "争辩": {"desc": "当面与对手争辩", "effects": {"威望": (-5, 8), "心计": (3, 8), "宠爱": (-3, 5)}},
}

def generate_palace_conflict(game_state, initiator=None, target=None, api_key=None, base_url=None, model=None):
    """生成宫斗事件（优先AI，失败则降级到规则生成）"""
    if initiator is None:
        all_names = [game_state.name] + list(game_state.npcs.keys())
        all_names = [n for n in all_names if n != "太后"]
        if not all_names:
            return None
        initiator = random.choice(all_names)
    all_names = [game_state.name] + list(game_state.npcs.keys())
    all_names = [n for n in all_names if n != "太后" and n != initiator]
    if not all_names:
        return None
    target = random.choice(all_names) if target is None else target
    conflict_type = random.choice(list(CONFLICT_TYPES.keys()))
    conflict_info = CONFLICT_TYPES[conflict_type]
    
    initiator_rank = game_state.rank.name if initiator == game_state.name else game_state.npcs.get(initiator, {}).get("rank", "妃嫔")
    target_rank = game_state.rank.name if target == game_state.name else game_state.npcs.get(target, {}).get("rank", "妃嫔")
    initiator_attrs = game_state.attributes if initiator == game_state.name else game_state.npcs.get(initiator, {}).get("attributes", {})
    target_attrs = game_state.attributes if target == game_state.name else game_state.npcs.get(target, {}).get("attributes", {})
    
    initiator_score = initiator_attrs.get("心计", 50) * 0.5 + initiator_attrs.get("宠爱", 30) * 0.3 + initiator_attrs.get("威望", 20) * 0.2
    target_score = target_attrs.get("心计", 50) * 0.5 + target_attrs.get("宠爱", 30) * 0.3 + target_attrs.get("威望", 20) * 0.2
    initiator_win = initiator_score > target_score
    if random.random() < 0.3:
        initiator_win = not initiator_win
    
    # 尝试AI生成故事
    narration = None
    
    try:
        prompt = f"""你是一个宫斗小说作家，请生成一段精彩的宫斗情节（80-120字）。

事件类型：{conflict_type}（{conflict_info['desc']}）
发起者：{initiator}（{initiator_rank}）
目标：{target}（{target_rank}）
胜负：{'发起者胜利' if initiator_win else '目标胜利'}

要求：
1. 描写要生动具体，有画面感
2. 包含人物对话和心理活动
3. 风格类似《甄嬛传》《如懿传》
4. 直接输出故事内容，不要加任何格式标记

直接输出故事："""
        client = get_openai_client(api_key, base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是宫斗小说作家，只输出故事内容，不要任何格式标记。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.9,
            max_tokens=300
        )
        narration = _strip_reasoning(response.choices[0].message.content)
        if len(narration) < 20:
            narration = f"{initiator}与{target}在御花园相遇，因言语不合起了冲突。"
    except Exception as e:
        print(f"AI生成宫斗事件失败: {e}")
        narrations = [
            f"{initiator}与{target}在御花园相遇，因言语不合起了冲突。",
            f"{initiator}暗中设计，在{target}的茶中动了手脚。",
            f"{initiator}在皇帝面前说{target}的坏话，意图挑拨。",
            f"宫中传言四起，说是{target}暗中勾结外臣。",
            f"{initiator}与{target}在宫宴上针锋相对，气氛紧张。"
        ]
        narration = random.choice(narrations)
    
    effects = {}
    for attr, (min_val, max_val) in conflict_info["effects"].items():
        magnitude = random.randint(
            max(1, min(abs(min_val), abs(max_val))),
            max(abs(min_val), abs(max_val), 1),
        )
        effects[attr] = magnitude if initiator_win else -magnitude
    
    if initiator == game_state.name:
        for attr, delta in effects.items():
            if attr in game_state.attributes:
                max_attr = game_state.get_attr_max(attr)
                game_state.attributes[attr] = max(0, min(max_attr, game_state.attributes[attr] + delta))
    elif target == game_state.name:
        for attr, delta in effects.items():
            if attr in game_state.attributes:
                max_attr = game_state.get_attr_max(attr)
                game_state.attributes[attr] = max(0, min(max_attr, game_state.attributes[attr] - delta))
    
    # 仇恨归属：仅玩家参与时才记入玩家仇敌表，NPC 之间的争斗记在各自 npc_rivals
    player = game_state.name
    if player in (initiator, target):
        opponent = target if initiator == player else initiator
        if opponent and opponent != player:
            game_state.rivalries[opponent] = game_state.rivalries.get(opponent, 0) + (10 if opponent in game_state.rivalries else 15)
    else:
        loser = target if initiator_win else initiator
        winner = initiator if initiator_win else target
        for owner, foe, amount in ((loser, winner, 15), (winner, loser, 8)):
            npc = game_state.npcs.get(owner)
            if not isinstance(npc, dict) or not foe or foe == owner:
                continue
            rivals = npc.setdefault("npc_rivals", {})
            rivals[foe] = min(100, rivals.get(foe, 0) + amount)
    
    return {
        "type": conflict_type,
        "initiator": initiator,
        "target": target,
        "initiator_win": initiator_win,
        "narration": narration,
        "effects": effects,
        "rivalries": game_state.rivalries
    }

def generate_emperor_name(api_key=None, base_url=None, model=None):
    """AI生成皇帝名字"""
    try:
        prompt = """请生成一个古代中国风格的天子名字，风格类似"萧景琰"、"慕容九"、"李承乾"。
要求：
1. 姓氏可以是单姓或复姓（如：萧、李、慕容、宇文、上官、司马等）
2. 名字为2个字
3. 要有帝王气派
4. 返回JSON格式：{"surname": "姓氏", "given": "名", "full_name": "全名"}

返回纯JSON，不要其他文字。"""
        client = get_openai_client(api_key, base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个古代名字生成专家，只输出JSON。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=100,
            response_format={"type": "json_object"}
        )
        result = json.loads(_strip_reasoning(response.choices[0].message.content))
        return result.get("full_name", "萧景琰")
    except Exception as e:
        print(f"AI生成皇帝名字失败: {e}")
        return generate_emperor_name_local()


def _strip_code_fence(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_period_event_lines(text):
    """解析 AI 返回的转旬情报列表，兼容多种编号格式。"""
    text = _strip_code_fence(text)
    if not text:
        return []
    # JSON 数组 / 对象
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
            if isinstance(data, dict):
                for key in ("events", "items", "data", "list", "gossip", "intel"):
                    if isinstance(data.get(key), list):
                        return [str(x).strip() for x in data[key] if str(x).strip()]
        except Exception:
            pass
    lines = re.split(r"\n\s*(?=\d+[.、)）]|[一二三四五六七八九十]+[、.．])", text)
    if len(lines) < 2:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
    events = []
    for line in lines:
        clean = re.sub(r"^[\-*•\s]+", "", line).strip()
        clean = re.sub(r"^\d+[.、)）]\s*", "", clean)
        clean = re.sub(r"^[一二三四五六七八九十]+[、.．]\s*", "", clean)
        clean = re.sub(r"^\*\*|\*\*$", "", clean).strip()
        if len(clean) >= 6:
            events.append(clean)
    if not events and text:
        events = [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= 8]
    return events


def _period_events_local_fallback(game_state, count=4):
    from events import generate_local_events
    local = generate_local_events(game_state, max_count=count)
    events = [evt["desc"] for evt in local if evt.get("desc")]
    if len(events) < count:
        npc_names = [n for n in game_state.npcs.keys() if n not in ["太后", "皇后"]]
        fillers = [
            f"{random.choice(npc_names)}在御花园偶遇太后，被夸赞举止得体。",
            f"宫人议论{random.choice(npc_names)}近日恩宠有加。",
            f"{random.choice(npc_names)}的宫女在膳房争执，惊动了总管太监。",
            f"传闻{random.choice(npc_names)}与另一名妃嫔不和，各宫都在私下议论。",
        ] if npc_names else ["后宫近日风平浪静，却暗流涌动。"]
        for line in fillers:
            if len(events) >= count:
                break
            if line not in events:
                events.append(line)
    return events[:count]


def _call_period_events_ai(client, model, npc_list, children_hint, pregnant_hint, json_mode=True):
    if json_mode:
        system = (
            "你是宫斗小说作家。只输出合法 JSON，不要 markdown，不要解释。"
            '格式固定为：{"events":["事件1","事件2","事件3","事件4"]}'
            "每条 20-40 字，必须出现妃嫔真名。"
        )
        user = (
            f"妃嫔名单（只能使用这些名字）：{npc_list}\n"
            f"请写 4 条后宫八卦/趣事。{children_hint}{pregnant_hint}"
        )
        kwargs = {"response_format": {"type": "json_object"}}
    else:
        system = "你是宫斗小说作家，只输出编号列表，不要其他文字。"
        user = (
            f"妃嫔：{npc_list}。写 4 条后宫八卦，每条一行，格式「1. …」{children_hint}{pregnant_hint}\n"
            "示例：\n1. 沈华凰在御花园赏花，被蜜蜂蜇伤。\n2. 柳如烟献上百寿图，太后大喜。"
        )
        kwargs = {}

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.75 if json_mode else 0.85,
        max_tokens=600,
        timeout=12,
        **kwargs,
    )
    text = _strip_reasoning(response.choices[0].message.content or "")
    return _parse_period_event_lines(text), text


def generate_period_events(game_state, npc_names=None, api_key=None, base_url=None, model=None):
    """转旬情报：JSON 结构化请求 + 重试 + 本地兜底，保证至少 4 条。"""
    target_count = 4
    if npc_names is None:
        npc_names = [n for n in game_state.npcs.keys() if n not in ["太后", "皇后"]]
    npc_list = "、".join(npc_names[:10]) if npc_names else "众多妃嫔"

    children_hint = ""
    if getattr(game_state, "children", None):
        names = [c.get("name", "?") for c in game_state.children[:3]]
        children_hint = f" 玩家子嗣：{'、'.join(names)}。"
    pregnant_hint = ""
    if getattr(game_state, "is_pregnant", False):
        player_name = getattr(game_state, "name", "玩家")
        pregnant_hint = f" 玩家{player_name}有孕（约{int(getattr(game_state, 'pregnancy_month', 0))}月）。"

    if not (api_key and base_url and model and str(api_key).strip() and str(base_url).strip() and str(model).strip()):
        print("⚠️ generate_period_events: 未配置 API Key 或模型，使用本地情报")
        events = _period_events_local_fallback(game_state, target_count)
        return {"events": events, "ai_used": False, "reason": "no_api_config", "fallback": True}

    ai_events = []
    ai_parsed_count = 0
    ai_called = False
    client = get_openai_client(api_key, base_url)

    for attempt, use_json in enumerate((True,)):
        try:
            print(f"📌 generate_period_events: 调用 AI model={model}, base={base_url}, json={use_json}, attempt={attempt + 1}")
            parsed, _raw_text = _call_period_events_ai(
                client, model, npc_list, children_hint, pregnant_hint, json_mode=use_json
            )
            ai_called = True
            ai_events = parsed
            ai_parsed_count = len(parsed)
            if ai_parsed_count >= 2:
                break
            print(f"⚠️ generate_period_events: 第 {attempt + 1} 次解析仅 {ai_parsed_count} 条，重试…")
        except Exception as e:
            print(f"❌ generate_period_events 第 {attempt + 1} 次失败: {e}")
            break

    used_fallback = False
    if len(ai_events) < target_count:
        need = target_count - len(ai_events)
        local_events = _period_events_local_fallback(game_state, need)
        seen = set(ai_events)
        for evt in local_events:
            if evt not in seen:
                ai_events.append(evt)
                seen.add(evt)
        used_fallback = True
        if ai_called:
            print(f"ℹ️ generate_period_events: AI 仅 {ai_parsed_count} 条，本地补足至 {len(ai_events)} 条")

    final = ai_events[:5]
    print(f"✅ generate_period_events: 最终 {len(final)} 条（AI 解析 {ai_parsed_count} 条）")
    return {
        "events": final,
        "ai_used": ai_called and ai_parsed_count > 0,
        "fallback": used_fallback,
        "ai_count": ai_parsed_count,
    }