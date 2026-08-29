# ai_service.py
import os
import json
import random
import re
import httpx
from openai import OpenAI
from dotenv import load_dotenv
from names import generate_emperor_name_local

load_dotenv()


def get_openai_client(api_key=None, base_url=None):
    """全项目唯一的 OpenAI 客户端工厂（原 app.py 同名函数的语义）。

    未配置或配置为空时返回 None（调用方自行走本地兜底）；带 15s 请求超时。
    """
    if not (api_key and base_url and str(api_key).strip() and str(base_url).strip()):
        return None
    http_client = httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0))
    return OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)


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
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    base_url = base_url or os.getenv("OPENAI_BASE_URL")
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
        if client is None:
            raise RuntimeError("no_api_config")
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
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    base_url = base_url or os.getenv("OPENAI_BASE_URL")
    try:
        prompt = """请生成一个古代中国风格的天子名字，风格类似"萧景琰"、"慕容九"、"李承乾"。
要求：
1. 姓氏可以是单姓或复姓（如：萧、李、慕容、宇文、上官、司马等）
2. 名字为2个字
3. 要有帝王气派
4. 返回JSON格式：{"surname": "姓氏", "given": "名", "full_name": "全名"}

返回纯JSON，不要其他文字。"""
        client = get_openai_client(api_key, base_url)
        if client is None:
            raise RuntimeError("no_api_config")
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


def generate_period_events(game_state, npc_names=None, api_key=None, api_base=None, api_model=None):
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

    if not (api_key and api_base and api_model and str(api_key).strip() and str(api_base).strip() and str(api_model).strip()):
        print("⚠️ generate_period_events: 未配置 API Key 或模型，使用本地情报")
        events = _period_events_local_fallback(game_state, target_count)
        return {"events": events, "ai_used": False, "reason": "no_api_config", "fallback": True}

    ai_events = []
    ai_parsed_count = 0
    ai_called = False
    client = get_openai_client(api_key, api_base)

    for attempt, use_json in enumerate((True,)):
        try:
            print(f"📌 generate_period_events: 调用 AI model={api_model}, base={api_base}, json={use_json}, attempt={attempt + 1}")
            parsed, _raw_text = _call_period_events_ai(
                client, api_model, npc_list, children_hint, pregnant_hint, json_mode=use_json
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