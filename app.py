# app.py
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import uuid
import json
import os
import random
from datetime import datetime

load_dotenv()
from models import GameState, Rank, Storyline, Servant
from scenarios import START_SCENARIOS, apply_scenario
from events import get_daily_actions, apply_daily_action
from names import (
    generate_female_name, generate_emperor_name_local, generate_child_name,
    generate_servant_name, extract_surname, NPC_SURNAMES,
    CHILD_GIVEN_NAME_CATEGORIES, CHILD_GIVEN_CHARS, is_valid_given_char,
)
from family_backgrounds import (
    generate_background_story,
    generate_concubine_identity,
    generate_official_background,
    generate_official_background_for_name,
)
from player_traits import apply_trait_bonuses, get_trait_catalog, suggest_traits
from palace_extra import (
    start_duel, play_duel_skill, resolve_duel, chat_probe, pray_or_curse,
    process_pressure, available_skills, DUEL_SKILLS, DRAIN_OPTIONS,
)
from openai import OpenAI
import httpx
from ai_service import generate_period_events

app = Flask(__name__)

CORS(app, resources={r"/api/*": {
    "origins": ["http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:5000", "http://127.0.0.1:5000", "null", "*"],
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization", "X-API-Base", "X-API-Key", "X-API-Model"],
    "supports_credentials": True
}})

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Base,X-API-Key,X-API-Model')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "接口不存在，请确认游戏后端已启动"}), 404
    return e

@app.errorhandler(405)
def handle_405(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "请求方法不允许"}), 405
    return e

sessions = {}
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = os.path.join(BASE_DIR, "saves")
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

EVENT_FILE = os.path.join(BASE_DIR, "events.json")
EVENT_POOL = []

def load_events():
    global EVENT_POOL
    if os.path.exists(EVENT_FILE):
        try:
            with open(EVENT_FILE, 'r', encoding='utf-8') as f:
                EVENT_POOL = json.load(f)
            print(f"[ok] loaded {len(EVENT_POOL)} events")
        except Exception as e:
            print(f"[warn] load events failed: {e}")
            EVENT_POOL = []
    else:
        print(f"[warn] events file not found: {EVENT_FILE}")
        EVENT_POOL = []
load_events()

user_configs = {}

# ============================================================
#  会话持久化：从存档恢复 + 自动存档
# ============================================================
def find_best_save_path(player_id, slot_name='default'):
    default_path = os.path.join(SAVE_DIR, f"{player_id}_{slot_name}.json")
    if os.path.exists(default_path):
        return default_path
    if not os.path.exists(SAVE_DIR):
        return None
    pattern_prefix = f"{player_id}_"
    best_path = None
    best_time = ''
    for filename in os.listdir(SAVE_DIR):
        if filename.startswith(pattern_prefix) and filename.endswith('.json'):
            filepath = os.path.join(SAVE_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                st = data.get('save_time', '')
                if st >= best_time:
                    best_time = st
                    best_path = filepath
            except Exception:
                continue
    return best_path


def restore_session_from_file(player_id, slot_name='default'):
    filepath = find_best_save_path(player_id, slot_name)
    if not filepath:
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            save_data = json.load(f)
        if "game_state" not in save_data:
            return None
        game_state = GameState.from_save_data(save_data)
        if not hasattr(game_state, 'npcs') or not game_state.npcs:
            game_state.npcs = generate_all_npcs(10)
            for name, npc in game_state.npcs.items():
                if name not in game_state.relationships:
                    game_state.relationships[name] = npc.get("relationship", {"好感": 0, "印象": "陌生", "互动次数": 0})
        if not hasattr(game_state, '_pending_promotion'):
            game_state._pending_promotion = None
        game_state._promotion_done = False
        sessions[player_id] = game_state
        return game_state
    except Exception as e:
        print(f"[warn] restore session {player_id} failed: {e}")
        return None


def get_or_restore_session(player_id, slot_name='default'):
    if not player_id:
        return None
    if player_id in sessions:
        return sessions[player_id]
    return restore_session_from_file(player_id, slot_name)


def session_or_404(player_id, error_msg="会话无效"):
    if not player_id:
        return None, (jsonify({"error": error_msg}), 404)
    game_state = get_or_restore_session(player_id)
    if not game_state:
        return None, (jsonify({"error": error_msg}), 404)
    return game_state, None


def autosave_session(player_id, slot_name='default'):
    if not player_id or player_id not in sessions:
        return
    try:
        game_state = sessions[player_id]
        save_data = game_state.to_save_data()
        filename = os.path.join(SAVE_DIR, f"{player_id}_{slot_name}.json")
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[warn] autosave {player_id} failed: {e}")


def restore_sessions_on_startup():
    if not os.path.exists(SAVE_DIR):
        return
    player_ids = set()
    for filename in os.listdir(SAVE_DIR):
        if not filename.endswith('.json'):
            continue
        base = filename[:-5]
        parts = base.split('_', 1)
        if len(parts) == 2:
            player_ids.add(parts[0])
    restored = 0
    for pid in player_ids:
        if pid not in sessions and restore_session_from_file(pid):
            restored += 1
    if restored:
        print(f"[ok] restored {restored} sessions from saves")

RANK_ORDER = ["更衣", "官女子", "答应", "常在", "贵人", "才人", "美人", "婕妤", "嫔", "妃", "贵妃", "皇贵妃", "皇后"]
RANK_LEVELS = {name: i for i, name in enumerate(RANK_ORDER)}

RANK_BONUS = {
    "更衣": {"容貌": 0, "才情": 0, "心计": 0, "威望": 0},
    "官女子": {"容貌": 2, "才情": 2, "心计": 2, "威望": 0},
    "答应": {"容貌": 5, "才情": 5, "心计": 3, "威望": 2},
    "常在": {"容貌": 8, "才情": 8, "心计": 5, "威望": 5},
    "贵人": {"容貌": 12, "才情": 12, "心计": 8, "威望": 8},
    "才人": {"容貌": 15, "才情": 15, "心计": 10, "威望": 10},
    "美人": {"容貌": 18, "才情": 18, "心计": 12, "威望": 12},
    "婕妤": {"容貌": 22, "才情": 22, "心计": 15, "威望": 15},
    "嫔": {"容貌": 26, "才情": 26, "心计": 18, "威望": 18},
    "妃": {"容貌": 30, "才情": 30, "心计": 22, "威望": 22},
    "贵妃": {"容貌": 35, "才情": 35, "心计": 26, "威望": 26},
    "皇贵妃": {"容貌": 40, "才情": 40, "心计": 30, "威望": 30},
    "皇后": {"容貌": 45, "才情": 45, "心计": 35, "威望": 35}
}

RANK_LIMITS = {
    "皇后": 1, "皇贵妃": 1, "贵妃": 2, "妃": 4, "嫔": 6,
    "婕妤": 6, "美人": 8, "才人": 8, "贵人": 10, "常在": 12,
    "答应": 15, "官女子": 20, "更衣": 30
}

def get_rank_bonus(rank_name):
    return RANK_BONUS.get(rank_name, {"容貌": 0, "才情": 0, "心计": 0, "威望": 0})

def can_promote_to_rank(game_state, target_rank_name):
    if target_rank_name not in RANK_LIMITS:
        return True
    limit = RANK_LIMITS[target_rank_name]
    count = 0
    for name, npc in game_state.npcs.items():
        if npc.get("rank") == target_rank_name:
            count += 1
    if game_state.rank.name == target_rank_name:
        count += 1
    return count < limit

def get_pai_name(game_state, name):
    surname = extract_surname(name)
    if name == game_state.name:
        rank = game_state.rank.name
        nobletitle = game_state.nobletitle
        return f"{nobletitle}{rank}" if nobletitle else f"{surname}{rank}"
    else:
        npc = game_state.npcs.get(name, {})
        rank = npc.get("rank", "妃嫔")
        nobletitle = npc.get("nobletitle", None)
        return f"{nobletitle}{rank}" if nobletitle else f"{surname}{rank}"

# ============================================================
#  赏赐系统
# ============================================================
TREASURES = [
    "翡翠镯子", "玛瑙项链", "金镶玉簪", "珊瑚摆件", "珍珠冠",
    "白玉如意", "碧玉屏风", "金丝绣衣", "鎏金香炉", "翡翠如意",
    "点翠凤钗", "东珠耳坠", "羊脂玉佩", "红珊瑚珠", "百花锦缎",
    "夜明珠", "和田玉璧", "金漆妆奁", "银鎏金钗", "青玉笔洗"
]

def generate_reward(game_state, source="emperor"):
    if source == "emperor":
        reward_types = ["银两", "珍宝", "珍宝", "珍宝", "位份", "封号", "恩典"]
        weights = [40, 30, 20, 10, 5, 3, 2]
    elif source == "dowager":
        reward_types = ["银两", "珍宝", "珍宝", "恩典"]
        weights = [40, 30, 20, 10]
    else:
        reward_types = ["银两", "珍宝", "珍宝"]
        weights = [45, 35, 20]
    reward_type = random.choices(reward_types, weights=weights)[0]
    
    if reward_type == "银两":
        amount = random.randint(20, 100) if source == "emperor" else random.randint(10, 50)
        return {"type": "银两", "name": f"白银{amount}两", "desc": f"赏赐白银{amount}两", "silver": amount, "effects": {}}
    elif reward_type == "珍宝":
        treasure = random.choice(TREASURES)
        favor_gain = random.randint(2, 8)
        return {"type": "珍宝", "name": treasure, "desc": f"赏赐「{treasure}」一件", "silver": 0, "effects": {"宠爱": favor_gain}}
    elif reward_type == "位份":
        current_rank_name = game_state.rank.name
        if current_rank_name in RANK_LEVELS:
            idx = RANK_LEVELS[current_rank_name]
            if idx < len(RANK_ORDER) - 1:
                next_rank = RANK_ORDER[idx + 1]
                if can_promote_to_rank(game_state, next_rank):
                    for rank_enum in Rank:
                        if rank_enum.name == next_rank:
                            game_state.rank = rank_enum
                            break
                    return {"type": "位份", "name": game_state.get_display_rank(), "desc": f"晋封为「{game_state.get_display_rank()}」！", "silver": 0, "effects": {"宠爱": 10, "威望": 10}, "is_promotion": True}
        amount = random.randint(30, 80)
        return {"type": "银两", "name": f"白银{amount}两", "desc": f"赏赐白银{amount}两（暂未能晋封）", "silver": amount, "effects": {}}
    elif reward_type == "封号":
        from models import NOBLETITLES
        new_title = random.choice(NOBLETITLES)
        game_state.nobletitle = new_title
        return {"type": "封号", "name": new_title, "desc": f"赐封号『{new_title}』", "silver": 0, "effects": {"宠爱": 8, "威望": 12}}
    else:
        attrs = ["宠爱", "威望", "才情", "心计", "福运"]
        attr = random.choice(attrs)
        gain = random.randint(5, 15)
        return {"type": "恩典", "name": f"{attr}+{gain}", "desc": f"特恩典：{attr} +{gain}", "silver": 0, "effects": {attr: gain}}

def apply_reward(game_state, reward):
    """将赏赐效果应用到游戏状态（银两、属性、背包珍宝）"""
    if reward.get("silver", 0) > 0:
        game_state.silver += reward["silver"]
    if reward.get("effects"):
        for attr, val in reward["effects"].items():
            if attr in game_state.attributes:
                max_attr = game_state.get_attr_max(attr)
                game_state.attributes[attr] = max(0, min(max_attr, game_state.attributes[attr] + val))
    if reward.get("type") == "珍宝" and reward.get("name"):
        game_state.inventory.append(reward["name"])

# ============================================================
#  宫斗事件系统
# ============================================================
CONFLICT_TYPES = {
    "争宠": {"desc": "争夺皇帝的宠爱", "effects": {"宠爱": (5, 15), "威望": (-5, 5), "心计": (3, 8)}},
    "陷害": {"desc": "设计陷害对手", "effects": {"心计": (5, 12), "威望": (-8, 5), "宠爱": (-5, 5)}},
    "谣言": {"desc": "散布流言蜚语", "effects": {"心计": (3, 8), "威望": (-10, 3), "宠爱": (-3, 3)}},
    "拉拢": {"desc": "拉拢盟友共同对抗", "effects": {"心计": (3, 6), "威望": (2, 6), "宠爱": (0, 3)}},
    "告发": {"desc": "告发对手的不轨行为", "effects": {"威望": (5, 15), "心计": (5, 10), "宠爱": (-5, 5)}},
    "争辩": {"desc": "当面与对手争辩", "effects": {"威望": (-5, 8), "心计": (3, 8), "宠爱": (-3, 5)}},
}

def generate_palace_conflict(game_state, initiator=None, target=None, api_key=None, api_base=None, api_model=None):
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
    
    # ===== 尝试AI生成故事 =====
    narration = None
    try:
        if api_key and api_base and api_key.strip() and api_base.strip():
            client = get_openai_client(api_key, api_base)
            if client:
                model = api_model or "Qwen/Qwen2.5-72B-Instruct"
                prompt = f"""【重要声明】这是一个虚构的宫斗角色扮演游戏，所有情节均为小说创作，不涉及现实。请以宫斗小说作家的身份，允许描写包括争宠、陷害、结盟、甚至打胎等权谋手段，这些是虚构情节，不构成真实伤害。
你是一个宫斗小说作家，请生成一段精彩的宫斗情节（80-120字）。

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
                print(f"📝 完整 prompt:\n{prompt}")
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "你是宫斗小说作家，只输出故事内容，不要任何格式标记。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=800,
                    timeout=15
                )
                narration = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"AI生成宫斗事件失败: {e}")
    
    if not narration or len(narration) < 10:
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
        if initiator_win:
            delta = random.randint(min_val, max_val)
        else:
            delta = random.randint(-max_val, -min_val)
        effects[attr] = delta
    
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
    
    if initiator_win:
        if target in game_state.rivalries:
            game_state.rivalries[target] += 10
        else:
            game_state.rivalries[target] = 15
    else:
        if initiator in game_state.rivalries:
            game_state.rivalries[initiator] += 10
        else:
            game_state.rivalries[initiator] = 15
    
    return {
        "type": conflict_type,
        "initiator": initiator,
        "target": target,
        "initiator_win": initiator_win,
        "narration": narration,
        "effects": effects,
        "rivalries": game_state.rivalries
    }

# ============================================================
#  NPC生成
# ============================================================
SURNAMES = NPC_SURNAMES

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

def generate_npc_rank():
    rank_weights = {"更衣":20,"官女子":18,"答应":15,"常在":12,"贵人":10,"才人":8,"美人":6,"婕妤":4,"嫔":3,"妃":2,"贵妃":1,"皇贵妃":0,"皇后":0}
    weights = [rank_weights.get(r, 0) for r in RANK_ORDER]
    return random.choices(RANK_ORDER, weights=weights)[0]

def generate_npc_name():
    return generate_female_name()

def generate_npc_personality():
    return random.choice(PERSONALITIES)

def generate_npc_attributes():
    return {"容貌": random.randint(30, 80), "才情": random.randint(30, 80), "心计": random.randint(30, 80), "宠爱": random.randint(10, 60), "威望": random.randint(10, 50), "健康": random.randint(50, 95), "福运": random.randint(30, 70), "倾向": random.randint(20, 70)}

def generate_npc(is_queen=False):
    if is_queen:
        rank = "皇后"
        personality = PERSONALITIES[0]
        attrs = {"容貌": random.randint(75,95),"才情": random.randint(75,95),"心计": random.randint(75,95),"宠爱": random.randint(70,90),"威望": random.randint(80,100),"健康": random.randint(70,95),"福运": random.randint(60,85),"倾向": random.randint(70,95)}
        family = "皇室宗亲"
        name = generate_npc_name()
        family_meta = {"score": 95, "daughter_status": "嫡", "official_title": "皇室宗亲"}
    else:
        rank = generate_npc_rank()
        personality = generate_npc_personality()
        attrs = generate_npc_attributes()
        name, bg = generate_concubine_identity()
        family = bg["label"]
        family_meta = bg["meta"]
        bonus = get_rank_bonus(rank)
        for key, val in bonus.items():
            if key in attrs:
                attrs[key] = min(100, attrs[key] + val)
    icons = ["🌸", "🌺", "🌷", "💐", "🌹", "🌻", "🌿", "🍃", "🪷", "🌙"]
    return {
        "name": name,
        "rank": rank,
        "personality": personality["name"],
        "personality_desc": personality["desc"],
        "traits": personality["traits"],
        "attributes": attrs,
        "relationship": {"好感": random.randint(-20, 50) if not is_queen else random.randint(10, 40), "印象": random.choice(["友善","疏离","敌视","崇拜","嫉妒","畏惧","信任"]) if not is_queen else "威严尊贵", "互动次数": 0},
        "icon": random.choice(icons),
        "is_active": True,
        "alive": True,
        "is_pregnant": False,
        "pregnancy_month": 0,
        "children": [],
        "pregnancy_history": [],
        "last_conception_day": 0,
        "fertility": random.randint(40, 85),
        "miscarriage_risk": random.randint(3, 12),
        "pregnancy_bonus": {"宠爱": 0, "威望": 0, "健康": 0},
        "family_background": family,
        "family_meta": family_meta,
        "nobletitle": None,
        "压力": random.randint(8, 28) if not is_queen else random.randint(5, 18),
    }

def generate_all_npcs(count=10):
    npcs = {}
    queen = generate_npc(is_queen=True)
    npcs[queen["name"]] = queen
    for i in range(count):
        npc = generate_npc(is_queen=False)
        while npc["name"] in npcs:
            npc = generate_npc(is_queen=False)
        npcs[npc["name"]] = npc
        if random.random() < 0.15 and npc.get("rank") not in ["皇后", "皇贵妃"]:
            child_count = random.randint(1, 2)
            for _ in range(child_count):
                gender = random.choice(["皇子", "公主"])
                child_name = generate_child_name(gender)
                age = round(random.randint(0, 36) / 12, 1)
                if "children" not in npc:
                    npc["children"] = []
                npc["children"].append({"name": child_name, "gender": gender, "age": age, "birth_day": random.randint(1,30), "birth_month": random.randint(1,12), "birth_year": random.randint(1,3), "trait": "🎀 襁褓" if age < 0.5 else ("🎂 周岁" if age < 1.5 else ("👶 幼童" if age < 3 else "🎓 启蒙"))})
    npc_names = list(npcs.keys())
    for i, name in enumerate(npc_names):
        if i < len(npc_names) - 1:
            if random.random() > 0.6:
                target = random.choice(npc_names[:i] + npc_names[i+1:])
                if target != "皇后" and name != "皇后":
                    change = random.randint(-15, 20)
                    npcs[name]["relationship"]["好感"] = max(-100, min(100, npcs[name]["relationship"]["好感"] + change // 2))
    return npcs

PREGNANCY_STEP = 10 / 30
CHILD_AGE_STEP = 1 / 12
EDUCATION_TRAITS = ["文才出众", "武艺超群", "聪慧过人", "品行端正", "琴棋书画"]

def newborn_trait(gender):
    return "🍼 襁褓" if gender == "皇子" else "🎀 襁褓"

def create_newborn_child(gender, name, game_state):
    return {
        "name": name,
        "gender": gender,
        "age": 0,
        "birth_day": game_state.day,
        "birth_month": game_state.month,
        "birth_year": game_state.year,
        "trait": newborn_trait(gender),
    }

def process_child_milestones(child, prefix, game_state=None):
    """处理子嗣成长节点，返回事件消息列表。game_state 不为 None 时为玩家子嗣，会发放属性奖励。"""
    events = []
    age_years = int(child.get("age", 0))
    child_name = child.get("name", "未命名")
    gender = child.get("gender", "")
    if age_years == 1 and not child.get("first_birthday", False):
        child["first_birthday"] = True
        child["trait"] = "🎂 周岁"
        events.append(f"🎂 {prefix}{gender} {child_name} 满周岁！")
    elif age_years == 3 and not child.get("three_years", False):
        child["three_years"] = True
        if gender == "皇子":
            child["title"] = random.choice(["郡王", "亲王"])
        else:
            child["title"] = random.choice(["郡主", "公主"])
        child["trait"] = "👑 册封"
        events.append(f"👑 {prefix}{gender} {child_name} 满3岁，获封 {child['title']}！")
        if game_state:
            if gender == "皇子":
                game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes["威望"] + 10)
            else:
                game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes["宠爱"] + 5)
    elif age_years == 6 and not child.get("six_years", False):
        child["six_years"] = True
        child["education"] = random.choice(EDUCATION_TRAITS)
        child["trait"] = f"📚 {child['education']}"
        events.append(f"📚 {prefix}{gender} {child_name} 开始启蒙，{child['education']}！")
    return events

def serialize_npcs_for_client(game_state):
    result = {}
    for name, npc in game_state.npcs.items():
        if name == "太后":
            continue
        result[name] = {
            "name": name,
            "rank": npc.get("rank", "妃嫔"),
            "personality": npc.get("personality", "未知"),
            "icon": npc.get("icon", "🌸"),
            "children": npc.get("children", []),
            "is_pregnant": npc.get("is_pregnant", False),
            "pregnancy_month": npc.get("pregnancy_month", 0),
            "attributes": npc.get("attributes", {}),
            "family_background": npc.get("family_background", ""),
            "nobletitle": npc.get("nobletitle", None),
            "压力": npc.get("压力", 0),
        }
    return result

def can_npc_get_pregnant(npc):
    if not npc.get("alive", True):
        return False
    if npc.get("is_pregnant", False):
        return False
    health = npc.get("attributes", {}).get("健康", 50)
    if health < 35:
        return False
    return True

def npc_conception_chance(npc):
    """NPC 每月受孕概率（仅在月初统一检测）。"""
    fertility = npc.get("fertility", 50)
    health = npc.get("attributes", {}).get("健康", 50)
    return fertility / 100.0 * 0.035 + max(0, (health - 50) / 1200.0)

def monthly_player_conception_chance(game_state):
    """玩家每月受孕概率，取决于当月承宠次数与属性。"""
    if not game_state or game_state.is_pregnant:
        return 0
    intimacy = getattr(game_state, "monthly_intimacy", 0)
    if intimacy <= 0:
        return 0
    favor = game_state.attributes.get("宠爱", 30)
    health = game_state.attributes.get("健康", 50)
    chance = 0.025 + intimacy * 0.006 + favor / 1500 + max(0, (health - 50) / 1500)
    return min(0.08, chance)

def record_player_intimacy(game_state, weight=1):
    if game_state.is_pregnant:
        return
    game_state.monthly_intimacy = min(6, getattr(game_state, "monthly_intimacy", 0) + weight)

def apply_player_pregnancy(game_state, source="月末诊脉"):
    game_state.is_pregnant = True
    game_state.pregnancy_month = 0
    game_state.monthly_intimacy = 0
    game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + 20)
    game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 10)
    game_state.add_memory(f"被诊断出怀孕（{source}）")
    return f"🤰 太医请脉，你有喜了！（{source}）皇帝龙颜大悦，宠爱+20，威望+10"

def run_monthly_conception_checks(game_state):
    """每月初统一检测玩家与 NPC 是否受孕。"""
    player_msg = None
    npc_events = []
    if not game_state.is_pregnant:
        chance = monthly_player_conception_chance(game_state)
        if chance > 0 and random.random() < chance:
            player_msg = apply_player_pregnancy(game_state, "月末诊脉")
        game_state.monthly_intimacy = 0
    else:
        game_state.monthly_intimacy = 0
    for name, npc in game_state.npcs.items():
        if name == game_state.name or name == "太后" or npc.get("rank") == "皇后":
            continue
        if npc.get("is_pregnant", False):
            continue
        if can_npc_get_pregnant(npc) and random.random() < npc_conception_chance(npc):
            npc["is_pregnant"] = True
            npc["pregnancy_month"] = 0
            npc_events.append(f"{name} 被诊出有喜！")
            npc["pregnancy_bonus"] = {"宠爱": random.randint(5, 12), "威望": random.randint(3, 8), "健康": random.randint(-3, 3)}
            for attr, bonus in npc["pregnancy_bonus"].items():
                if attr in npc["attributes"]:
                    npc["attributes"][attr] = max(0, min(100, npc["attributes"][attr] + bonus))
    return player_msg, npc_events

def check_player_miscarriage(game_state):
    """孕期 3/6/9 月检查小产，返回消息或 None。"""
    month = int(game_state.pregnancy_month)
    if month not in [3, 6, 9]:
        return None
    health = game_state.attributes.get("健康", 50)
    risk = 5 * (1 - health / 200)
    if random.random() * 100 >= risk:
        return None
    game_state.is_pregnant = False
    game_state.pregnancy_month = 0
    game_state.attributes["健康"] = max(0, health - 15)
    msg = "🌧️ 你不幸小产，健康-15，需好生休养"
    game_state.add_memory(msg)
    return msg

def update_npc_pregnancy(npc, game_day):
    if not npc.get("is_pregnant", False): return False, None
    month = npc.get("pregnancy_month", 0) + PREGNANCY_STEP
    npc["pregnancy_month"] = month
    if int(month) in [3, 6, 9]:
        risk = npc.get("miscarriage_risk", 8) / 2 * (1 - npc.get("attributes", {}).get("健康", 50) / 200)
        if random.random() * 100 < risk:
            npc["is_pregnant"] = False
            npc["pregnancy_month"] = 0
            npc["pregnancy_history"].append({"day": game_day, "outcome": "流产", "month": month})
            return True, "流产"
    if month >= 10:
        npc["is_pregnant"] = False
        npc["pregnancy_month"] = 0
        return True, "生产"
    return False, None

def process_npc_pregnancy(game_state):
    pregnancy_events, birth_events = [], []
    for name, npc in game_state.npcs.items():
        if name == game_state.name or name == "太后" or npc.get("rank") == "皇后": continue
        if npc.get("is_pregnant", False):
            event_happened, event_type = update_npc_pregnancy(npc, game_state.day)
            if event_happened:
                if event_type == "流产":
                    pregnancy_events.append(f"🌧️ {name} 不幸小产...")
                    if name in game_state.relationships:
                        game_state.relationships[name]["好感"] = max(-100, game_state.relationships[name]["好感"] - 8)
                    npc["attributes"]["健康"] = max(0, npc["attributes"]["健康"] - 10)
                elif event_type == "生产":
                    gender = random.choice(["皇子", "公主"])
                    child_name = generate_child_name(gender)
                    if "children" not in npc: npc["children"] = []
                    npc["children"].append(create_newborn_child(gender, child_name, game_state))
                    birth_events.append(f"👶 {name} 诞下{gender}，取名{child_name}！")
                    current_rank = npc.get("rank", "答应")
                    if current_rank in RANK_LEVELS:
                        idx = RANK_LEVELS[current_rank]
                        if idx < len(RANK_ORDER) - 2 and random.random() < 0.5:
                            next_rank = RANK_ORDER[idx + 1]
                            if can_promote_to_rank(game_state, next_rank):
                                npc["rank"] = next_rank
                                birth_events.append(f"  {name} 母凭子贵，晋升为 {next_rank}！")
                    npc["attributes"]["宠爱"] = min(100, npc["attributes"].get("宠爱", 0) + 12)
                    npc["attributes"]["威望"] = min(100, npc["attributes"].get("威望", 0) + 8)
    return pregnancy_events, birth_events

def update_npc_children_growth(game_state):
    growth_events = []
    for name, npc in game_state.npcs.items():
        if "children" not in npc or not npc["children"]:
            continue
        for child in npc["children"]:
            child["age"] = child.get("age", 0) + CHILD_AGE_STEP
            growth_events.extend(process_child_milestones(child, f"{name}的"))
    return growth_events

def check_and_consume_action(game_state):
    if not game_state.can_act():
        return False, game_state.remaining_actions
    game_state.consume_action()
    return True, game_state.remaining_actions

# ============================================================
#  AI服务
# ============================================================
def get_openai_client(api_key=None, api_base=None):
    if api_key and api_base and api_key.strip() and api_base.strip():
        http_client = httpx.Client(
            timeout=httpx.Timeout(15.0, connect=5.0)
        )
        return OpenAI(api_key=api_key, base_url=api_base, http_client=http_client)
    return None

def generate_emperor_name(api_key=None, api_base=None, api_model=None):
    return generate_emperor_name_local()

def build_prompt(game_state, player_action, npc_names, event=None):
    rank = game_state.rank.name
    time = game_state.current_time
    attrs = game_state.attributes
    relationships = game_state.relationships
    memories = game_state.get_recent_memories(3)
    emperor = game_state.emperor
    storyline = game_state.storyline.value
    emperor_personality = emperor.get("personality", "明君")
    emperor_name = emperor.get("name", "皇帝")
    romance_mode = getattr(game_state, "romance_mode", False)
    custom_prompt = getattr(game_state, "custom_prompt", "")
    player_traits = getattr(game_state, "traits", []) or []
    player_personality = getattr(game_state, "personality", "")
    player_talent = getattr(game_state, "talent", "")
    player_appearance = getattr(game_state, "appearance", "")
    player_story = getattr(game_state, "custom_story", "")
    family_bg = getattr(game_state, "family_background", "未知")
    
    character_desc_parts = []
    if family_bg and family_bg != "未知":
        character_desc_parts.append(f"家世：{family_bg}")
    if player_personality:
        character_desc_parts.append(f"性格：{player_personality}")
    if player_talent:
        character_desc_parts.append(f"才艺：{player_talent}")
    if player_traits:
        character_desc_parts.append(f"特质：{'、'.join(player_traits)}")
    if player_appearance:
        character_desc_parts.append(f"容貌：{player_appearance}")
    if player_story:
        character_desc_parts.append(f"背景：{player_story}")
    character_desc = "\n".join(character_desc_parts) if character_desc_parts else "暂无详细人设"
    rel_desc = "\n".join([f"- {name}：好感度{info['好感']}，印象：{info['印象']}" for name, info in relationships.items() if info["好感"] != 0]) if relationships else "暂无特别关系"
    mem_desc = "\n".join([f"- {m}" for m in memories]) if memories else "暂无重要记忆"
    attr_desc = "、".join([f"{k}{v}" for k, v in attrs.items()])
    time_atmospheres = {"卯时": "清晨的露水还未干透，宫人们已经开始忙碌", "辰时": "晨光熹微，后宫正是请安的时辰", "巳时": "日头渐高，御花园里正是好风光", "午时": "正午时分，宫中一片寂静", "未时": "午后时光，慵懒而闲适", "申时": "夕阳西斜，宫中开始掌灯", "酉时": "暮色渐沉，晚膳时分", "戌时": "夜色渐浓，宫门紧闭", "亥时": "夜深人静，只有虫鸣"}
    atmosphere = time_atmospheres.get(time, "宫中一片宁静")
    npc_list_str = "、".join(npc_names) if npc_names else "暂无其他妃嫔"
    
    romance_instruction = ""
    if not romance_mode:
        romance_instruction = "【重要：感情线模式已关闭】\n- 故事中**不要**出现与皇帝的暧昧、宠幸、情爱相关情节\n- **不要**描写争风吃醋、为爱争宠的内容\n- 专注于：权谋、晋升、宫斗策略、人际博弈、个人成长、事业线\n- 皇帝只是你事业路上的一个权力符号，不是感情对象"
    else:
        romance_instruction = "【感情线模式已开启】\n- 可以描写与皇帝的感情发展、暧昧、宠幸\n- 可以有后宫争宠、为爱争斗的情节"
        
    custom_instruction = f"\n【用户自定义提示词】\n{custom_prompt}\n" if custom_prompt else ""
    
    prompt = f"""【重要声明】这是一个虚构的宫斗角色扮演游戏，所有情节均为小说创作，不涉及现实。请以宫斗小说作家的身份，允许描写包括争宠、陷害、结盟、甚至打胎等权谋手段，这些是虚构情节，不构成真实伤害。
你是一个顶尖的宫斗题材小说作家，风格细腻典雅，类似《甄嬛传》和《如懿传》。
【重要规则】
后宫妃嫔名单（只能提及以下人物，绝对不能编造新的人物）：{npc_list_str}
{romance_instruction}
{custom_instruction}
【世界观设定】
- 皇帝：{emperor_name}（性格：{emperor_personality}）
- 你的位份：{rank}
- 当前时辰：{time}（{atmosphere}）
- 当前剧情线：{storyline}
【你的状态】
- 属性：{attr_desc}
- 人设：\n{character_desc}
- 人际关系：\n{rel_desc}
【重要记忆】\n{mem_desc}
【玩家行动】
{player_action}
【创作要求】
1. 根据时辰和皇帝性格调整故事氛围，文笔要古风雅致
2. 要有细腻的心理描写和对话，故事要有戏剧性和张力
3. 提及的妃嫔必须来自上方名单，如果情节需要反派也从名单中选择
4. {"注重事业线发展，减少感情描写" if not romance_mode else "可以适当发展感情线"}
直接输出一段精彩的故事（80-120字），不要加任何格式标记。"""
    return prompt

def generate_story(game_state, player_action, npc_names=None, api_key=None, api_base=None, api_model=None):
    if npc_names is None:
        npc_names = list(game_state.npcs.keys())
    from events import check_event, generate_local_events
    event = check_event(game_state)
    prompt = build_prompt(game_state, player_action, npc_names, event)
    
    print(f"📌 generate_story 收到 api_key: {api_key}, api_base: {api_base}")
    print(f"📝 完整 prompt:\n{prompt}\n---")
    
    narration = None
    if api_key is not None and api_base is not None and api_key.strip() and api_base.strip():
        try:
            client = get_openai_client(api_key, api_base)
            if client:
                model = api_model or "Qwen/Qwen2.5-72B-Instruct"
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "你是才华横溢的宫斗小说作家，只输出故事内容，不要任何格式标记。尽量使用名单中的人物。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.8,
                    max_tokens=800,
                    top_p=0.95,
                    timeout=15
                )
                narration = response.choices[0].message.content.strip()
                print(f"✅ AI 返回原始内容长度: {len(narration)}")
        except Exception as e:
            print(f"❌ AI调用失败: {e}")
            narration = None
    else:
        print("⚠️ 未提供有效的 API Key，跳过 AI")

    # ===== 处理 AI 返回内容 =====
    if narration is not None:
        if narration.strip() == "":
            narration = "（AI 本次未生成内容，这是一段默认的故事。）"
            print("⚠️ AI 返回空内容，已使用占位")
        else:
            print(f"✅ 使用 AI 生成内容，完整内容: {narration}")

        base_changes = {"宠爱": random.randint(-1, 3), "威望": random.randint(-1, 2), "心计": random.randint(-1, 2), "健康": random.randint(-1, 2)}
        if event:
            for attr, change in event.get("effects", {}).items():
                base_changes[attr] = base_changes.get(attr, 0) + change
            game_state.add_memory(f"{event['name']}")
        for attr, change in base_changes.items():
            if attr in game_state.attributes:
                game_state.attributes[attr] = max(0, min(game_state.get_attr_max(attr), game_state.attributes[attr] + change))
        return {"narration": narration, "choices": ["继续", "查看状态", "保存游戏"], "effects": base_changes, "event_triggered": event["name"] if event else None}

    # ===== AI 未返回任何内容（None），使用本地事件 =====
    print("⚠️ AI 未返回有效内容，使用本地事件")
    local_events = generate_local_events(game_state, max_count=1)
    if local_events:
        evt = local_events[0]
        narration = evt["desc"]
        for attr, delta in evt["effects"].items():
            if attr in game_state.attributes:
                game_state.attributes[attr] = max(0, min(game_state.get_attr_max(attr), game_state.attributes[attr] + delta))
    else:
        fallback_narrations = [
            "你正在宫中散步，恰巧遇到了几位妃嫔在亭中品茶闲聊。",
            "御花园里花开正好，你独自赏花时，听见远处传来阵阵琴声。",
            "今日天气晴朗，你正在读书时，宫女来报说太后召见。",
            "你刚用完午膳，便听说了皇帝最近常去皇后宫中用膳的消息。",
            "宫中来了一位新的乐师，琴艺高超，引得各宫妃嫔纷纷前往聆听。"
        ]
        narration = random.choice(fallback_narrations)

    base_changes = {"宠爱": random.randint(-1, 3), "威望": random.randint(-1, 2), "心计": random.randint(-1, 2), "健康": random.randint(-1, 2)}
    if event:
        for attr, change in event.get("effects", {}).items():
            base_changes[attr] = base_changes.get(attr, 0) + change
        game_state.add_memory(f"{event['name']}")
    for attr, change in base_changes.items():
        if attr in game_state.attributes:
            game_state.attributes[attr] = max(0, min(game_state.get_attr_max(attr), game_state.attributes[attr] + change))
    return {"narration": narration, "choices": ["继续", "查看状态", "保存游戏"], "effects": base_changes, "event_triggered": event["name"] if event else None}

# ============================================================
#  晋升条件（真实属性阈值 + 防重复）
# ============================================================
def check_promotion_condition(game_state):
    # 防止本次周期内重复晋升
    if getattr(game_state, "_promotion_done", False):
        return False
    if getattr(game_state, "_pending_promotion", None) is not None:
        return False
    current_rank_name = game_state.rank.name
    if current_rank_name == "皇后":
        return False
    rank_thresholds = {
        "更衣": {"宠爱": 10, "威望": 10},
        "官女子": {"宠爱": 20, "威望": 20},
        "答应": {"宠爱": 40, "威望": 30, "才情": 30, "心计": 25},
        "常在": {"宠爱": 60, "威望": 40, "才情": 40, "心计": 35},
        "贵人": {"宠爱": 80, "威望": 50, "才情": 50, "心计": 45},
        "才人": {"宠爱": 100, "威望": 60, "才情": 55, "心计": 50},
        "美人": {"宠爱": 120, "威望": 70, "才情": 60, "心计": 55},
        "婕妤": {"宠爱": 150, "威望": 85, "才情": 65, "心计": 60},
        "嫔": {"宠爱": 200, "威望": 100, "才情": 70, "心计": 65},
        "妃": {"宠爱": 250, "威望": 120, "才情": 75, "心计": 70},
        "贵妃": {"宠爱": 300, "威望": 140, "才情": 80, "心计": 75},
        "皇贵妃": {"宠爱": 400, "威望": 160, "才情": 85, "心计": 80},
    }
    if current_rank_name in rank_thresholds:
        threshold = rank_thresholds[current_rank_name]
        attrs = game_state.attributes
        for attr, value in threshold.items():
            if attrs.get(attr, 0) < value:
                return False
        return True
    return False

# ============================================================
#  晋升事件（废弃，保留占位）
# ============================================================
def generate_promotion_event(game_state, api_key=None, api_base=None, api_model=None):
    # 已废弃，但保留以防调用
    return None

def get_flip_candidates(game_state):
    candidates = []
    player_name = game_state.name
    player_favor = game_state.attributes.get("宠爱", 0)
    player_app = game_state.attributes.get("容貌", 50)
    player_tal = game_state.attributes.get("才情", game_state.attributes.get("才艺", 50))
    
    player_weight = player_favor * 3 + player_app * 2 + player_tal * 1 + RANK_LEVELS.get(game_state.rank.name, 0) * 5
    if getattr(game_state, "is_pregnant", False):
        player_weight = max(0, player_weight // 5) + 10
    if game_state.rank.name == "皇后":
        player_weight += 20
    candidates.append({"name": player_name, "weight": player_weight, "is_player": True})
    
    for name, npc in game_state.npcs.items():
        if name == "太后":
            continue
        favor = game_state.relationships.get(name, {}).get("好感", 0)
        appearance = npc.get("attributes", {}).get("容貌", 50)
        talent = npc.get("attributes", {}).get("才艺", 50)
        weight = favor * 3 + appearance * 2 + talent * 1 + RANK_LEVELS.get(npc.get("rank"), 0) * 5
        if npc.get("is_pregnant", False):
            weight = max(0, weight // 4) + 8
        if npc.get("rank") == "皇后":
            weight += 20
        candidates.append({"name": name, "weight": weight, "is_player": False})
    
    candidates.sort(key=lambda x: x["weight"], reverse=True)
    return candidates
# ============================================================
#  Flask 路由
# ============================================================

def get_user_api_config(request, player_id=None):
    config = {}
    config['api_key'] = request.headers.get('X-API-Key') or request.headers.get('Authorization', '').replace('Bearer ', '')
    config['api_base'] = request.headers.get('X-API-Base') or 'https://cn.jixiangai.xyz/v1'
    config['api_model'] = request.headers.get('X-API-Model') or 'Qwen/Qwen2.5-72B-Instruct'
    if request.is_json:
        data = request.get_json(silent=True) or {}
        config['api_key'] = config['api_key'] or data.get('api_key', '')
        config['api_base'] = config['api_base'] or data.get('api_base', 'https://cn.jixiangai.xyz/v1')
        config['api_model'] = config['api_model'] or data.get('api_model', 'Qwen/Qwen2.5-72B-Instruct')
    if player_id and player_id in user_configs:
        stored = user_configs[player_id]
        config['api_key'] = config['api_key'] or stored.get('api_key', '')
        config['api_base'] = config['api_base'] or stored.get('api_base', 'https://cn.jixiangai.xyz/v1')
        config['api_model'] = config['api_model'] or stored.get('api_model', 'Qwen/Qwen2.5-72B-Instruct')
    if not config['api_key']:
        config['api_key'] = os.getenv('OPENAI_API_KEY', '')
    if not config['api_base']:
        config['api_base'] = os.getenv('OPENAI_BASE_URL', 'https://cn.jixiangai.xyz/v1')
    return config

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "version": "1.4.0",
        "events_loaded": len(EVENT_POOL),
    })


@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    data = request.get_json() or {}
    player_id = data.get('player_id') or request.args.get('player_id')
    if not player_id:
        return jsonify({"error": "缺少player_id"}), 400
    if request.method == 'GET':
        config = user_configs.get(player_id, {"custom_prompt": "", "romance_mode": False, "api_base": "https://cn.jixiangai.xyz/v1", "api_key": "", "api_model": "Qwen/Qwen2.5-72B-Instruct"})
        return jsonify(config)
    data = request.get_json()
    user_configs[player_id] = {
        "custom_prompt": data.get('custom_prompt', ''),
        "romance_mode": data.get('romance_mode', False),
        "api_base": data.get('api_base', 'https://cn.jixiangai.xyz/v1'),
        "api_key": data.get('api_key', ''),
        "api_model": data.get('api_model', 'Qwen/Qwen2.5-72B-Instruct')
    }
    if player_id in sessions:
        game_state = sessions[player_id]
        game_state.romance_mode = user_configs[player_id]["romance_mode"]
        game_state.custom_prompt = user_configs[player_id]["custom_prompt"]
    return jsonify({"success": True})

@app.route('/api/servants', methods=['GET'])
def get_servants():
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    return jsonify({"servants": [s.to_dict() for s in game_state.get_active_servants()], "max": game_state.max_servants, "count": len(game_state.get_active_servants())})

@app.route('/api/servant/hire', methods=['POST'])
def hire_servant():
    data = request.get_json()
    player_id = data.get('player_id')
    servant_type = data.get('type', '宫女')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    cost = 30 if servant_type == '宫女' else 20
    if game_state.silver < cost:
        return jsonify({"error": f"银两不足，需要{cost}两"}), 400
    name = generate_servant_name(servant_type)
    existing_names = [s.name for s in game_state.get_active_servants()]
    if name in existing_names:
        name = "新" + name
    servant = Servant(name, servant_type, random.randint(40,70), random.randint(30,60))
    success, msg = game_state.add_servant(servant)
    if not success:
        return jsonify({"error": msg}), 400
    game_state.silver -= cost
    game_state.add_memory(f"招募了{name}（{servant_type}）")
    return jsonify({"success": True, "message": msg, "servant": servant.to_dict(), "silver": game_state.silver, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})

@app.route('/api/servant/dismiss', methods=['POST'])
def dismiss_servant():
    data = request.get_json()
    player_id = data.get('player_id')
    name = data.get('name')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    success, msg = game_state.remove_servant(name)
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"success": True, "message": msg})

@app.route('/api/servant/train', methods=['POST'])
def train_servant():
    data = request.get_json()
    player_id = data.get('player_id')
    name = data.get('name')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    for s in game_state.servants:
        if s.name == name and s.is_active:
            if game_state.silver < 15:
                return jsonify({"error": "银两不足，需要15两"}), 400
            game_state.silver -= 15
            s.skill = min(100, s.skill + random.randint(3, 10))
            s.loyalty = min(100, s.loyalty + random.randint(2, 6))
            return jsonify({"success": True, "message": f"{name}训练成功！", "servant": s.to_dict(), "silver": game_state.silver, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})
    return jsonify({"error": "未找到该仆人"}), 404

@app.route('/api/scenarios', methods=['GET'])
def get_scenarios():
    return jsonify({"scenarios": [{"key": k, "name": k, "description": v["description"]} for k, v in START_SCENARIOS.items()]})

@app.route('/api/npcs', methods=['GET'])
def get_npcs():
    player_id = request.args.get('player_id')
    if player_id and player_id in sessions:
        game_state = sessions[player_id]
        return jsonify({"npcs": {name: {"name": name, "rank": npc.get("rank","妃嫔"), "personality": npc.get("personality","未知"), "icon": npc.get("icon","🌸"), "relationship": game_state.relationships.get(name, {"好感":0,"印象":"陌生"}), "children": npc.get("children",[]), "is_pregnant": npc.get("is_pregnant",False), "pregnancy_month": npc.get("pregnancy_month",0), "attributes": npc.get("attributes",{}), "family_background": npc.get("family_background",""), "nobletitle": npc.get("nobletitle",None), "压力": npc.get("压力", 0)} for name, npc in game_state.npcs.items() if name != "太后"}})
    return jsonify({"npcs": {}})

@app.route('/api/npc/<name>', methods=['GET'])
def get_npc_detail(name):
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if name not in game_state.npcs:
        return jsonify({"error": "NPC不存在"}), 404
    npc = game_state.npcs[name]
    return jsonify({
        "name": name, "rank": npc.get("rank","妃嫔"), "personality": npc.get("personality","未知"),
        "personality_desc": npc.get("personality_desc",""), "icon": npc.get("icon","🌸"),
        "attributes": npc.get("attributes",{}), "relationship": game_state.relationships.get(name, {"好感":0,"印象":"陌生","互动次数":0}),
        "rivalry": game_state.rivalries.get(name, 0), "alliance": game_state.alliances.get(name, 0),
        "is_active": npc.get("is_active", True), "alive": npc.get("alive", True),
        "children": npc.get("children", []), "is_pregnant": npc.get("is_pregnant", False),
        "pregnancy_month": npc.get("pregnancy_month", 0), "family_background": npc.get("family_background", ""),
        "nobletitle": npc.get("nobletitle", None),
        "压力": npc.get("压力", 0),
        "duel_skills": available_skills(npc.get("rank", "答应")),
    })

@app.route('/api/interact', methods=['POST'])
def interact_npc():
    data = request.get_json()
    player_id = data.get('player_id')
    npc_name = data.get('npc_name')
    action = data.get('action')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    if npc_name not in game_state.npcs:
        return jsonify({"error": "NPC不存在"}), 404
    result = {"narration": "", "effects": {}, "silver_change": 0}

    if action == 'clear_rival':
        if npc_name in game_state.rivalries:
            del game_state.rivalries[npc_name]
        result["narration"] = f"已清除与{npc_name}的仇敌关系"
        return jsonify({**result, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})
    elif action == 'clear_ally':
        if npc_name in game_state.alliances:
            del game_state.alliances[npc_name]
        result["narration"] = f"已清除与{npc_name}的盟友关系"
        return jsonify({**result, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})

    if action == 'gift':
        if game_state.silver < 20:
            return jsonify({"error": "银两不足"}), 400
        game_state.silver -= 20
        gain = random.randint(5, 15)
        game_state.relationships[npc_name]["好感"] = min(100, game_state.relationships[npc_name]["好感"] + gain)
        result["silver_change"] = -20
        result["effects"]["好感"] = gain
        result["narration"] = f"你向{npc_name}赠送了礼物，好感度 +{gain}。"
        game_state.add_memory(f"向{npc_name}送礼，好感+{gain}")
    elif action == 'ally':
        if game_state.relationships[npc_name]["好感"] < 30:
            return jsonify({"error": "好感度不足，无法结盟"}), 400
        if npc_name in game_state.alliances:
            return jsonify({"error": "已经是盟友"}), 400
        if npc_name in game_state.rivalries:
            del game_state.rivalries[npc_name]
        game_state.alliances[npc_name] = 30
        game_state.relationships[npc_name]["好感"] += 10
        result["narration"] = f"你与{npc_name}结为盟友！"
        game_state.add_memory(f"与{npc_name}结盟")
    elif action == 'rival':
        if game_state.attributes["心计"] < 30:
            return jsonify({"error": "心计不足，无法陷害"}), 400
        game_state.attributes["心计"] = max(0, game_state.attributes["心计"] - 10)
        if npc_name in game_state.alliances:
            del game_state.alliances[npc_name]
        game_state.rivalries[npc_name] = game_state.rivalries.get(npc_name, 0) + 20
        game_state.relationships[npc_name]["好感"] -= 15
        result["effects"]["心计"] = -10
        result["narration"] = f"你设计陷害了{npc_name}，与{npc_name}结仇！"
        game_state.add_memory(f"陷害{npc_name}")
    elif action == 'chat':
        probed, err = chat_probe(game_state, npc_name)
        if err:
            return jsonify({"error": err}), 400
        result["narration"] = probed["narration"]
        result["revealed"] = probed.get("revealed", [])
        result["safe_to_duel"] = probed.get("safe_to_duel")
        game_state.add_memory(f"闲聊试探{npc_name}")
    else:
        return jsonify({"error": "无效操作"}), 400

    game_state.add_attr_change(result.get("effects", {}), f"与{npc_name}交互：{action}")
    return jsonify({**result, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})

@app.route('/api/emperor/interact', methods=['POST'])
def emperor_interact():
    data = request.get_json()
    player_id = data.get('player_id')
    action = data.get('action')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    if "皇帝" not in game_state.relationships:
        game_state.relationships["皇帝"] = {"好感": 10, "印象": "初识", "互动次数": 0}
    action_map = {'serve_tea': {'desc': '献茶', 'effects': {'宠爱': (1,5), '威望': (0,2)}, 'cost': 10}, 'discuss': {'desc': '奏对', 'effects': {'宠爱': (2,6), '威望': (2,5), '谋略': (1,4)}, 'cost': 0}, 'recite_poem': {'desc': '献诗', 'effects': {'宠爱': (3,8), '才情': (2,5)}, 'cost': 0}, 'ask_reward': {'desc': '求赏赐', 'effects': {'宠爱': (0,3), '威望': (0,2)}, 'cost': 0}}
    if action not in action_map:
        return jsonify({"error": "无效行为"}), 400
    act = action_map[action]
    if act.get('cost', 0) > 0 and game_state.silver < act['cost']:
        return jsonify({"error": f"银两不足，需要{act['cost']}两"}), 400
    changes = {}
    for attr, (min_val, max_val) in act['effects'].items():
        delta = random.randint(min_val, max_val)
        if attr in game_state.attributes:
            old = game_state.attributes[attr]
            max_attr = game_state.get_attr_max(attr)
            game_state.attributes[attr] = max(0, min(max_attr, old + delta))
            changes[attr] = delta
    if act.get('cost', 0) > 0:
        game_state.silver -= act['cost']
        changes['银两'] = -act['cost']
    favor_delta = random.randint(2, 8)
    game_state.relationships["皇帝"]["好感"] = min(100, game_state.relationships["皇帝"]["好感"] + favor_delta)
    game_state.relationships["皇帝"]["互动次数"] += 1
    reward_info = None
    if action == 'ask_reward':
        if random.random() < 0.5:
            reward = generate_reward(game_state, "emperor")
            apply_reward(game_state, reward)
            reward_info = {"type": reward["type"], "name": reward["name"], "desc": reward["desc"], "silver": reward["silver"], "effects": reward["effects"], "is_promotion": reward.get("is_promotion", False)}
            game_state.add_memory(f"求赏赐获得：{reward['desc']}")
            narration = f"你向皇帝求赏赐，皇帝龙颜大悦，赏赐了你{reward['desc']}！"
        else:
            narration = "你向皇帝求赏赐，皇帝今日兴致不高，未予赏赐。"
    else:
        narration = f"你向皇帝{act['desc']}，皇帝龙颜大悦，好感度+{favor_delta}，"
        if changes:
            change_str = "、".join([f"{k}{'+' if v>0 else ''}{v}" for k, v in changes.items() if k != '银两' or v != 0])
            narration += f"属性变化：{change_str}"
        else:
            narration += "一切如常。"
    game_state.add_memory(f"皇帝{act['desc']}，{narration}")
    game_state.add_attr_change(changes, f"皇帝{act['desc']}")
    intimacy_weights = {'serve_tea': 1, 'discuss': 1, 'recite_poem': 2, 'ask_reward': 1}
    if action in intimacy_weights:
        record_player_intimacy(game_state, intimacy_weights[action])
    return jsonify({"success": True, "narration": narration, "effects": changes, "reward": reward_info, "pregnancy": None, "is_pregnant": game_state.is_pregnant, "pregnancy_month": game_state.pregnancy_month, "attributes": game_state.attributes, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})

@app.route('/api/dowager/interact', methods=['POST'])
def dowager_interact():
    data = request.get_json()
    player_id = data.get('player_id')
    action = data.get('action')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    if "太后" not in game_state.relationships:
        game_state.relationships["太后"] = {"好感": 20, "印象": "和善", "互动次数": 0}
    action_map = {'pay_respects': {'desc': '请安', 'effects': {'威望': (1,4), '宠爱': (1,3)}, 'cost': 0}, 'present_gift': {'desc': '献礼', 'effects': {'威望': (3,6), '宠爱': (2,5)}, 'cost': 25}, 'chat': {'desc': '陪聊', 'effects': {'威望': (2,5), '心计': (1,3), '魅力': (1,2)}, 'cost': 0}, 'ask_favor': {'desc': '求恩典', 'effects': {'威望': (5,10), '宠爱': (3,7)}, 'cost': 0}}
    if action not in action_map:
        return jsonify({"error": "无效行为"}), 400
    act = action_map[action]
    if act.get('cost', 0) > 0 and game_state.silver < act['cost']:
        return jsonify({"error": f"银两不足，需要{act['cost']}两"}), 400
    changes = {}
    for attr, (min_val, max_val) in act['effects'].items():
        delta = random.randint(min_val, max_val)
        if attr in game_state.attributes:
            old = game_state.attributes[attr]
            max_attr = game_state.get_attr_max(attr)
            game_state.attributes[attr] = max(0, min(max_attr, old + delta))
            changes[attr] = delta
    if act.get('cost', 0) > 0:
        game_state.silver -= act['cost']
        changes['银两'] = -act['cost']
    favor_delta = random.randint(3, 8)
    game_state.relationships["太后"]["好感"] = min(100, game_state.relationships["太后"]["好感"] + favor_delta)
    game_state.relationships["太后"]["互动次数"] += 1
    reward_info = None
    if action == 'ask_favor':
        if random.random() < 0.6:
            reward = generate_reward(game_state, "dowager")
            apply_reward(game_state, reward)
            reward_info = {"type": reward["type"], "name": reward["name"], "desc": reward["desc"], "silver": reward["silver"], "effects": reward["effects"]}
            game_state.add_memory(f"太后恩典：{reward['desc']}")
            narration = f"你向太后求恩典，太后恩准，赐予你{reward['desc']}！"
        else:
            narration = "你向太后求恩典，太后未予回应。"
    else:
        narration = f"你向太后{act['desc']}，太后颇为满意，好感度+{favor_delta}，"
        if changes:
            change_str = "、".join([f"{k}{'+' if v>0 else ''}{v}" for k, v in changes.items() if k != '银两' or v != 0])
            narration += f"属性变化：{change_str}"
        else:
            narration += "一切如常。"
    game_state.add_memory(f"太后{act['desc']}，{narration}")
    game_state.add_attr_change(changes, f"太后{act['desc']}")
    return jsonify({"success": True, "narration": narration, "effects": changes, "reward": reward_info, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})

@app.route('/api/promotion/choose', methods=['POST'])
def promotion_choose():
    # 已废弃，返回错误
    return jsonify({"error": "晋升现在为自动触发，无需选择"}), 400

@app.route('/api/emperor/flip', methods=['POST'])
def emperor_flip():
    data = request.get_json()
    player_id = data.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    
    candidates = get_flip_candidates(game_state)
    if not candidates:
        return jsonify({"error": "没有合适的妃嫔"}), 400
    total_weight = sum(c["weight"] for c in candidates)
    if total_weight <= 0:
        return jsonify({"error": "权重无效"}), 400
    r = random.random() * total_weight
    chosen = None
    for c in candidates:
        r -= c["weight"]
        if r <= 0:
            chosen = c["name"]
            break
    if not chosen:
        chosen = candidates[0]["name"]
    
    pai_name = get_pai_name(game_state, chosen)
    pregnancy_msg = None
    favor_gain = random.randint(10, 25)
    prestige_gain = random.randint(5, 15)
    
    is_pregnant = False
    pregnant_month = 0
    if chosen == game_state.name:
        is_pregnant = game_state.is_pregnant
        pregnant_month = game_state.pregnancy_month
    else:
        npc = game_state.npcs.get(chosen, {})
        is_pregnant = npc.get("is_pregnant", False)
        pregnant_month = npc.get("pregnancy_month", 0)
    
    visit_mode = False
    if is_pregnant:
        visit_mode = True
        favor_gain = random.randint(5, 12)
        health_gain = random.randint(3, 8)
        prestige_gain = 0
        visit_msg = f"🤰 皇帝前来探望孕中的{chosen}，宠爱+{favor_gain}，健康+{health_gain}"
        if chosen == game_state.name:
            game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes["宠爱"] + favor_gain)
            game_state.attributes["健康"] = min(game_state.get_attr_max("健康"), game_state.attributes["健康"] + health_gain)
            game_state.add_memory(f"皇帝前来探望孕中的你，宠爱+{favor_gain}，健康+{health_gain}")
            pregnancy_msg = visit_msg
        else:
            if chosen in game_state.npcs:
                npc = game_state.npcs[chosen]
                npc["attributes"]["宠爱"] = min(100, npc["attributes"].get("宠爱", 50) + favor_gain)
                npc["attributes"]["健康"] = min(100, npc["attributes"].get("健康", 50) + health_gain)
                if chosen in game_state.relationships:
                    game_state.relationships[chosen]["好感"] = min(100, game_state.relationships[chosen]["好感"] + random.randint(3, 8))
                game_state.add_memory(f"皇帝探望了孕中的{chosen}，宠爱+{favor_gain}，健康+{health_gain}")
                pregnancy_msg = visit_msg
    else:
        game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes["宠爱"] + favor_gain)
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes["威望"] + prestige_gain)
        if chosen in game_state.relationships:
            game_state.relationships[chosen]["好感"] = min(100, game_state.relationships[chosen]["好感"] + random.randint(5, 15))
        if chosen == game_state.name and not game_state.is_pregnant:
            record_player_intimacy(game_state, 3)
            pregnancy_msg = "翻牌承宠，月末太医请脉方知有无身孕"
    
    reward_info = None
    if random.random() < 0.30:
        reward = generate_reward(game_state, "emperor")
        apply_reward(game_state, reward)
        reward_info = {
            "type": reward["type"],
            "name": reward["name"],
            "desc": reward["desc"],
            "silver": reward["silver"],
            "effects": reward["effects"],
            "is_promotion": reward.get("is_promotion", False)
        }
        game_state.add_memory(f"皇帝赏赐：{reward['desc']}")
    
    game_state.add_memory(f"皇帝{'探望' if visit_mode else '翻了'}{pai_name}的牌子")
    return jsonify({
        "success": True,
        "chosen": chosen,
        "pai_name": pai_name,
        "favor_gain": favor_gain,
        "prestige_gain": prestige_gain,
        "visit_mode": visit_mode,
        "is_pregnant_target": is_pregnant,
        "pregnant_month": pregnant_month,
        "attributes": game_state.attributes,
        "relationships": game_state.relationships,
        "message": f"皇帝{'前来探望' if visit_mode else '翻了'}{pai_name}的牌子！{'宠爱+'+str(favor_gain) if favor_gain>0 else ''}{'健康+'+str(health_gain) if visit_mode else ''}{'威望+'+str(prestige_gain) if prestige_gain>0 else ''}",
        "pregnancy": pregnancy_msg,
        "reward": reward_info
    })

@app.route('/api/next_period', methods=['POST'])
def next_period():
    data = request.get_json()
    player_id = data.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    api_config = get_user_api_config(request, player_id)

    # ---- 时间推进 ----
    old_month, old_year = game_state.month, game_state.year
    game_state.advance_calendar()
    month_changed = game_state.month != old_month or game_state.year != old_year
    game_state.reset_actions()
    game_state.current_time = "卯时"

    intelligence = []

    # ---- 宫女情报 ----
    servants = game_state.get_active_servants()
    if servants:
        for servant in servants:
            if random.random() < (0.5 + servant.loyalty / 200):
                topics = [
                    f"{servant.name}打听到：皇帝最近常去 {random.choice(['御书房','皇后宫中','贵妃宫中','御花园'])}。",
                    f"{servant.name}报告：后宫传闻 {random.choice(['某妃嫔失宠','某妃嫔怀孕','太后身体欠安','皇帝心情不佳'])}。",
                    f"{servant.name}发现：{random.choice(['御膳房新进了许多珍稀食材','宫外有商队进贡','边疆有捷报传来'])}。",
                    f"{servant.name}听到：{random.choice(['皇帝打算选秀','皇后准备举办宫宴','太后想修佛堂'])}。"
                ]
                intelligence.append(random.choice(topics))
            else:
                intelligence.append(f"{servant.name}今日没有打探到有用消息。")
    else:
        intelligence.append("你身边没有宫女太监，未能获得任何情报。")

    if random.random() < 0.3:
        intelligence.append(f"宫中谣言：{random.choice(['某妃嫔暗中诅咒皇帝','有人私通外臣','御花园发现可疑物品'])}。")

    # ===== AI 生成 4~5 条后宫事件 =====
    npc_names = [n for n in list(game_state.npcs.keys()) if n not in ["太后", "皇后"]]
    period_result = generate_period_events(
        game_state,
        npc_names,
        api_config.get('api_key'),
        api_config.get('api_base'),
        api_config.get('api_model'),
    )
    ai_events = period_result.get("events", [])
    ai_events_used = period_result.get("ai_used", False)
    ai_fallback = period_result.get("fallback", False)

    seen = set()
    final_events = []
    for evt in ai_events:
        if evt not in seen and evt.strip():
            seen.add(evt)
            final_events.append(evt)
    final_events = final_events[:5]
    for evt in final_events:
        intelligence.append(f"📜 {evt}")

    # ---- 俸禄 ----
    game_state.attributes["健康"] = max(0, game_state.attributes["健康"] - random.randint(0, 2))
    salary = max(1, (20 + game_state.rank.value * 5) // 3)
    game_state.silver += salary
    game_state.add_memory(f"领取俸禄{salary}银两")

    # ---- 玩家怀孕进展 ----
    pregnancy_update = None
    if game_state.is_pregnant:
        game_state.pregnancy_month += PREGNANCY_STEP
        miscarriage_msg = check_player_miscarriage(game_state)
        if miscarriage_msg:
            pregnancy_update = miscarriage_msg
        elif game_state.pregnancy_month >= 10:
            game_state.is_pregnant = False
            game_state.pregnancy_month = 0
            if random.random() < 0.15:
                game_state.attributes["健康"] = max(0, game_state.attributes["健康"] - 25)
                pregnancy_update = f"⚠️ 你难产了！健康-25，请好好休养。"
                game_state.add_memory(f"难产，健康-25")
            else:
                gender = random.choice(["皇子", "公主"])
                child_name = generate_child_name(gender)
                game_state.children.append(create_newborn_child(gender, child_name, game_state))
                game_state.has_children = True
                game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes["宠爱"] + 20)
                game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes["威望"] + 15)
                pregnancy_update = f"👶 你诞下{gender}，取名{child_name}！宠爱+20，威望+15"
                game_state.add_memory(f"诞下{gender}，取名{child_name}")
                current_rank_name = game_state.rank.name
                if current_rank_name in RANK_LEVELS:
                    idx = RANK_LEVELS[current_rank_name]
                    if idx < len(RANK_ORDER) - 2 and random.random() < 0.5:
                        next_rank_name = RANK_ORDER[idx + 1]
                        if can_promote_to_rank(game_state, next_rank_name):
                            for rank_enum in Rank:
                                if rank_enum.name == next_rank_name:
                                    game_state.rank = rank_enum
                                    pregnancy_update += f" 母凭子贵，晋升为「{game_state.get_display_rank()}」！"
                                    break
        elif game_state.is_pregnant:
            month = int(game_state.pregnancy_month)
            if month == 2:
                pregnancy_update = "🤰 你开始害喜，胃口不佳，健康-2"
                game_state.attributes["健康"] = max(0, game_state.attributes["健康"] - 2)
            elif month == 5:
                pregnancy_update = "🤰 你感受到胎动，心中欢喜，福运+3"
                game_state.attributes["福运"] = min(100, game_state.attributes["福运"] + 3)
            elif month == 8:
                pregnancy_update = "🤰 你行动日益不便，但皇上时常来看望，宠爱+5"
                game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes["宠爱"] + 5)
            if pregnancy_update:
                game_state.add_memory(pregnancy_update)
            if random.random() < 0.25:
                favor_gain = random.randint(3, 10)
                health_gain = random.randint(1, 5)
                game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes["宠爱"] + favor_gain)
                game_state.attributes["健康"] = min(game_state.get_attr_max("健康"), game_state.attributes["健康"] + health_gain)
                intelligence.append(f"👑 皇帝前来探望孕中的你，宠爱+{favor_gain}，健康+{health_gain}")
                game_state.add_memory(f"皇帝探望，宠爱+{favor_gain}，健康+{health_gain}")

    # ---- 每月初统一检测受孕 ----
    monthly_npc_conceptions = []
    if month_changed:
        monthly_player_msg, monthly_npc_conceptions = run_monthly_conception_checks(game_state)
        if monthly_player_msg:
            pregnancy_update = monthly_player_msg

    # ---- NPC怀孕进展、子嗣成长 ----
    pregnancy_events = list(monthly_npc_conceptions)
    pregnancy_progress, birth_events = process_npc_pregnancy(game_state)
    pregnancy_events.extend(pregnancy_progress)
    if pregnancy_events:
        for msg in pregnancy_events:
            game_state.add_memory(msg)
    if birth_events:
        for msg in birth_events:
            game_state.add_memory(msg)

    growth_events = update_npc_children_growth(game_state)
    if growth_events:
        for msg in growth_events:
            game_state.add_memory(msg)

    pressure_events = process_pressure(game_state)
    if pressure_events:
        for msg in pressure_events:
            intelligence.append(msg)
            game_state.add_memory(msg)

    prince_events = []
    for child in game_state.children:
        child["age"] = child.get("age", 0) + CHILD_AGE_STEP
        prince_events.extend(process_child_milestones(child, "你的", game_state))
    if prince_events:
        for evt in prince_events:
            game_state.add_memory(evt)

    # ===== 晋升触发（直接晋升，防重复） =====
    promotion_message = None
    if check_promotion_condition(game_state):
        current_rank_name = game_state.rank.name
        if current_rank_name in RANK_LEVELS:
            idx = RANK_LEVELS[current_rank_name]
            if idx < len(RANK_ORDER) - 1:
                next_rank_name = RANK_ORDER[idx + 1]
                if can_promote_to_rank(game_state, next_rank_name):
                    # 直接通过枚举名赋值
                    game_state.rank = Rank[next_rank_name]
                    title_msg = game_state.grant_nobletitle()
                    promotion_msg = f"📜 圣旨到！恭喜晋升为「{game_state.get_display_rank()}」！"
                    if title_msg:
                        promotion_msg += f"\n{title_msg}"
                    promotion_message = promotion_msg
                    game_state.add_memory(f"晋升为{game_state.get_display_rank()}")
                    game_state.story_flags.append("晋升成功")
                    game_state._promotion_done = True
                else:
                    promotion_message = f"⚠️ {next_rank_name} 人数已满，暂无法晋升。"
            else:
                promotion_message = "你已位极人臣，无法再晋升。"

    # ---- NPC晋升 ----
    other_promotions = []
    if game_state.month % 3 == 0:
        for name, npc in game_state.npcs.items():
            if name == "太后" or npc.get("rank") == "皇后" or name == game_state.name:
                continue
            attrs = npc.get("attributes", {})
            favor = attrs.get("宠爱", 0)
            prestige = attrs.get("威望", 0)
            current_rank = npc.get("rank", "答应")
            if current_rank in RANK_LEVELS:
                idx = RANK_LEVELS[current_rank]
                if idx < len(RANK_ORDER) - 1 and favor > 50 + idx * 10 and prestige > 40 + idx * 8:
                    next_rank = RANK_ORDER[idx + 1]
                    if can_promote_to_rank(game_state, next_rank) and random.random() < 0.25:
                        npc["rank"] = next_rank
                        npc["attributes"]["宠爱"] = min(100, favor + random.randint(5, 12))
                        npc["attributes"]["威望"] = min(100, prestige + random.randint(5, 10))
                        other_promotions.append(f"✨ {name} 晋升为 {next_rank}！")
        if other_promotions:
            game_state.add_memory(f"其他妃嫔晋升：{', '.join(other_promotions)}")

    # ---- 纳新人 ----
    new_concubine = None
    if game_state.year % 3 == 0 and game_state.month == 1 and game_state.day <= 10:
        if random.random() < 0.8:
            count = random.randint(3, 5)
            new_names = []
            for _ in range(count):
                new_npc = generate_npc(is_queen=False)
                while new_npc["name"] in game_state.npcs:
                    new_npc = generate_npc(is_queen=False)
                game_state.npcs[new_npc["name"]] = new_npc
                game_state.relationships[new_npc["name"]] = {"好感": random.randint(-10, 30), "印象": "陌生", "互动次数": 0}
                new_names.append(f"{new_npc['icon']}{new_npc['name']}（{new_npc['rank']}）")
            new_concubine = {"names": new_names, "is_daxuan": True}
            game_state.add_memory(f"三年一大选，{len(new_names)}位新人入宫")
    elif game_state.month % 6 == 0 and game_state.day <= 10 and random.random() < 0.3:
        count = random.randint(1, 2)
        new_names = []
        for _ in range(count):
            new_npc = generate_npc(is_queen=False)
            while new_npc["name"] in game_state.npcs:
                new_npc = generate_npc(is_queen=False)
            game_state.npcs[new_npc["name"]] = new_npc
            game_state.relationships[new_npc["name"]] = {"好感": random.randint(-10, 30), "印象": "陌生", "互动次数": 0}
            new_names.append(f"{new_npc['icon']}{new_npc['name']}（{new_npc['rank']}）")
        if new_names:
            new_concubine = {"names": new_names, "is_daxuan": False}
            game_state.add_memory(f"{len(new_names)}位新人入宫")

    npcs_with_children = serialize_npcs_for_client(game_state)

    autosave_session(player_id)
    return jsonify({
        "success": True,
        "day": game_state.day,
        "month": game_state.month,
        "year": game_state.year,
        "calendar_str": game_state.get_calendar_str(),
        "time": game_state.current_time,
        "narration": f"📅 {game_state.get_calendar_str()}，转旬完成。",
        "intelligence": "\n".join(intelligence),
        "intelligence_list": intelligence,
        "attributes": game_state.attributes,
        "attr_max": game_state.ATTR_MAX,
        "silver": game_state.silver,
        "is_pregnant": game_state.is_pregnant,
        "pregnancy_month": game_state.pregnancy_month,
        "children": game_state.children,
        "has_children": game_state.has_children,
        "rivalries": game_state.rivalries,
        "alliances": game_state.alliances,
        "npcs": npcs_with_children,
        "emperor": game_state.emperor,
        "memories": game_state.get_recent_memories(5),
        "attr_change_log": game_state.attr_change_log[-5:],
        "player_name": game_state.name,
        "display_rank": game_state.get_display_rank(),
        "remaining_actions": game_state.remaining_actions,
        "max_actions": game_state.max_actions,
        "promotion_message": promotion_message,
        "other_promotions": other_promotions,
        "new_concubine": new_concubine,
        "pregnancy_update": pregnancy_update,
        "other_pregnancy_msgs": pregnancy_events,
        "other_birth_msgs": birth_events,
        "prince_events": prince_events,
        "growth_events": growth_events,
        "ai_events_used": ai_events_used,
        "ai_events_fallback": ai_fallback,
    })

@app.route('/api/scheme', methods=['POST'])
def scheme_action():
    data = request.get_json()
    player_id = data.get('player_id')
    target = data.get('target')
    action = data.get('action')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    if target not in game_state.npcs:
        return jsonify({"error": "目标不存在"}), 404
    result = {"narration": "", "effects": {}}
    if action == 'compete':
        if game_state.attributes["宠爱"] < 30:
            return jsonify({"error": "宠爱不足，不敢争宠"}), 400
        if random.random() < 0.6:
            game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes["宠爱"] + 10)
            game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes["威望"] + 5)
            game_state.rivalries[target] = game_state.rivalries.get(target, 0) + 10
            result["effects"] = {"宠爱": 10, "威望": 5}
            result["narration"] = f"你在争宠中胜过了{target}！宠爱+10，威望+5"
            game_state.story_flags.append("争宠胜利")
        else:
            game_state.attributes["宠爱"] = max(0, game_state.attributes["宠爱"] - 8)
            game_state.attributes["威望"] = max(0, game_state.attributes["威望"] - 3)
            result["effects"] = {"宠爱": -8, "威望": -3}
            result["narration"] = f"你在争宠中输给了{target}，宠爱-8，威望-3"
        game_state.add_memory(result["narration"])
    elif action == 'rumor':
        if game_state.attributes["谋略"] < 20:
            return jsonify({"error": "谋略不足"}), 400
        if random.random() < 0.5:
            game_state.attributes["谋略"] = max(0, game_state.attributes["谋略"] - 5)
            game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes["威望"] + 5)
            game_state.rivalries[target] = game_state.rivalries.get(target, 0) + 15
            result["effects"] = {"谋略": -5, "威望": 5}
            result["narration"] = f"你散布了关于{target}的谣言，威望+5"
        else:
            game_state.attributes["谋略"] = max(0, game_state.attributes["谋略"] - 5)
            game_state.attributes["威望"] = max(0, game_state.attributes["威望"] - 5)
            result["effects"] = {"谋略": -5, "威望": -5}
            result["narration"] = f"你散布谣言被揭穿，威望-5"
        game_state.add_memory(result["narration"])
    elif action == 'bribe':
        if game_state.silver < 30:
            return jsonify({"error": "银两不足"}), 400
        game_state.silver -= 30
        game_state.relationships[target]["好感"] = min(100, game_state.relationships[target]["好感"] + 15)
        if target in game_state.rivalries:
            game_state.rivalries[target] = max(0, game_state.rivalries[target] - 10)
        result["silver_change"] = -30
        result["effects"] = {"好感": 15}
        result["narration"] = f"你花费银两拉拢{target}，好感+15"
        game_state.add_memory(result["narration"])
    else:
        return jsonify({"error": "无效行动"}), 400
    game_state.add_attr_change(result.get("effects", {}), f"主动宫斗：{action} against {target}")
    return jsonify({**result, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})

@app.route('/api/daily_actions', methods=['GET'])
def get_actions():
    return jsonify({"actions": get_daily_actions()})

@app.route('/api/action', methods=['POST'])
def perform_action():
    data = request.get_json()
    player_id = data.get('player_id')
    action = data.get('action')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    action_names = {'embroidery': '绣花', 'calligraphy': '练字', 'greet': '请安', 'study': '读书', 'rest': '休养', 'walk': '散步'}
    effects = {'embroidery': {'才艺': 3, '银两': 5, '健康': -1}, 'calligraphy': {'才情': 4, '威望': 2, '健康': -1}, 'greet': {'威望': 3, '宠爱': 1, '心计': 1}, 'study': {'谋略': 4, '才情': 2, '健康': -2}, 'rest': {'健康': 5, '福运': 2}, 'walk': {'健康': 2, '容貌': 1, '福运': 1}}
    if action not in effects:
        return jsonify({"error": "无效行为"}), 400
    changes = effects[action]
    for attr, delta in changes.items():
        if attr == '银两':
            game_state.silver = max(0, game_state.silver + delta)
        elif attr in game_state.attributes:
            max_attr = game_state.get_attr_max(attr)
            game_state.attributes[attr] = max(0, min(max_attr, game_state.attributes[attr] + delta))
    change_desc = "，".join([f"{k}+{v}" if v > 0 else f"{k}{v}" for k, v in changes.items() if k != '银两' or v != 0])
    if '银两' in changes and changes['银两'] != 0:
        change_desc += f"，银两{'+' if changes['银两']>0 else ''}{changes['银两']}"
    action_name = action_names.get(action, action)
    game_state.add_attr_change(changes, f"行为：{action_name}")
    game_state.add_memory(f"进行了{action_name}，{change_desc}")
    autosave_session(player_id)
    return jsonify({"success": True, "effects": changes, "attributes": game_state.attributes, "silver": game_state.silver, "message": f"你完成了{action_name}，{change_desc}", "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})

@app.route('/api/event/random', methods=['POST'])
def get_random_event():
    player_id = request.get_json().get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    attrs = game_state.attributes
    if not EVENT_POOL:
        return jsonify({"event": None, "message": "暂无事件库"})
    available = []
    for event in EVENT_POOL:
        condition = event.get('trigger', '')
        if not condition:
            available.append(event)
            continue
        try:
            if '>' in condition:
                key, val = condition.split('>')
                if attrs.get(key.strip(), 0) > float(val.strip()):
                    available.append(event)
            elif '<' in condition:
                key, val = condition.split('<')
                if attrs.get(key.strip(), 0) < float(val.strip()):
                    available.append(event)
            else:
                available.append(event)
        except:
            continue
    if not available:
        return jsonify({"event": None, "message": "今日无事发生"})
    return jsonify({"event": random.choice(available)})

@app.route('/api/start', methods=['POST'])
def start_game():
    data = request.get_json()
    scenario_key = data.get('scenario', '世家贵女')
    player_name = data.get('name', '未命名')
    storyline = data.get('storyline', '主线')
    background_data = data.get('background_data', None)
    player_attributes = data.get('attributes', None)
    emperor_data = data.get('emperor', None)
    character = data.get('character', {})
    api_config = get_user_api_config(request)
    player_id = str(uuid.uuid4())
    game_state = GameState(player_id, Rank.答应)
    game_state.name = player_name
    game_state.appearance = character.get('appearance', '')
    game_state.talent = character.get('talent', '')
    game_state.personality = character.get('personality', '')
    game_state.background_desc = character.get('background_desc', '')
    game_state.traits = character.get('traits', [])
    game_state.custom_story = character.get('custom_story', '')
    
    if background_data:
        game_state.family_background = background_data.get('label', '未知')
        game_state.family_meta = background_data.get('meta') or {}
        rank_name = background_data.get('rankBonus', '答应')
        for rank_enum in Rank:
            if rank_enum.name == rank_name:
                game_state.rank = rank_enum
                break
        if 'attrBonus' in background_data:
            for attr, bonus in background_data['attrBonus'].items():
                if attr in game_state.attributes:
                    max_attr = game_state.get_attr_max(attr)
                    game_state.attributes[attr] = max(0, min(max_attr, game_state.attributes[attr] + bonus * 5))
        game_state.history.append(f"出身：{background_data.get('label', '未知')}（{background_data.get('desc', '')}）")
    
    for sl in Storyline:
        if sl.value == storyline:
            game_state.storyline = sl
            break
    
    game_state = apply_scenario(game_state, scenario_key)
    
    if player_attributes:
        for attr, value in player_attributes.items():
            if attr in game_state.attributes:
                max_attr = game_state.get_attr_max(attr)
                game_state.attributes[attr] = max(0, min(max_attr, value * 5))

    trait_applied = apply_trait_bonuses(game_state, game_state.traits)
    if trait_applied:
        game_state.history.append(f"特质加成：{', '.join(t['trait'] for t in trait_applied)}")
    
    if emperor_data:
        game_state.emperor = emperor_data
    else:
        emp_name = generate_emperor_name(api_config.get('api_key'), api_config.get('api_base'), api_config.get('api_model'))
        from models import EmperorPersonality
        game_state.emperor = {"name": emp_name, "age": random.randint(25,55), "personality": random.choice([p.value for p in EmperorPersonality]), "stats": {"威严": random.randint(40,90), "仁德": random.randint(30,85), "勤政": random.randint(30,85), "好色": random.randint(10,80)}, "favor_factors": {"明君": {"容貌":0.2,"才情":0.5,"心计":0.3}, "昏君": {"容貌":0.8,"才情":0.1,"心计":0.1}, "痴情": {"容貌":0.3,"才情":0.3,"心计":0.4}, "多疑": {"容貌":0.2,"才情":0.2,"心计":0.6}}}
    
    game_state.npcs = generate_all_npcs(10)
    if "太后" not in game_state.npcs:
        game_state.npcs["太后"] = {"name": "太后", "rank": "太后", "personality": "威严慈祥", "personality_desc": "历经三朝，深谙宫闱之道", "icon": "👑", "attributes": {"威望":90,"心计":80,"健康":60,"宠爱":0,"容貌":70}, "relationship": {"好感":25,"印象":"和善","互动次数":0}, "is_active": True, "alive": True}
        game_state.relationships["太后"] = {"好感": 25, "印象": "和善", "互动次数": 0}
    
    for name, npc in game_state.npcs.items():
        if name not in game_state.relationships:
            game_state.relationships[name] = npc.get("relationship", {"好感":0,"印象":"陌生","互动次数":0})
        if npc.get("rank") == "皇后":
            continue
        rand_val = random.random()
        if rand_val < 0.15:
            game_state.rivalries[name] = random.randint(10, 40)
        elif rand_val < 0.30:
            game_state.alliances[name] = random.randint(10, 30)
    
    if "皇帝" not in game_state.relationships:
        game_state.relationships["皇帝"] = {"好感": 10, "印象": "初识", "互动次数": 0}
    
    game_state.romance_mode = False
    game_state.custom_prompt = ""
    game_state._pending_promotion = None
    game_state._promotion_done = False
    sessions[player_id] = game_state
    user_configs[player_id] = {"custom_prompt": "", "romance_mode": False, "api_base": api_config.get('api_base', 'https://cn.jixiangai.xyz/v1'), "api_key": api_config.get('api_key', ''), "api_model": api_config.get('api_model', 'Qwen/Qwen2.5-72B-Instruct')}
    npc_names = list(game_state.npcs.keys())
    story = generate_story(game_state, "入宫选秀，开启了后宫生涯", npc_names, api_config.get('api_key'), api_config.get('api_base'), api_config.get('api_model'))
    
    npcs_with_children = serialize_npcs_for_client(game_state)
    autosave_session(player_id)
    return jsonify({"player_id": player_id, "player_name": player_name, "family_background": game_state.family_background, "rank": game_state.rank.name, "nobletitle": game_state.nobletitle, "display_rank": game_state.get_display_rank(), "attributes": game_state.attributes, "attr_max": game_state.ATTR_MAX, "relationships": game_state.relationships, "emperor": game_state.emperor, "storyline": game_state.storyline.value, "silver": game_state.silver, "npcs": npcs_with_children, "narration": story.get("narration","欢迎来到后宫。"), "choices": story.get("choices",["四处看看","去请安","回宫休息"]), "effects": story.get("effects",{}), "is_pregnant": game_state.is_pregnant, "children": game_state.children, "has_children": game_state.has_children, "rivalries": game_state.rivalries, "alliances": game_state.alliances, "servants": [], "romance_mode": game_state.romance_mode, "year": game_state.year, "month": game_state.month, "day": game_state.day, "calendar_str": game_state.get_calendar_str(), "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions, "appearance": game_state.appearance, "talent": game_state.talent, "personality": game_state.personality, "traits": game_state.traits, "custom_story": game_state.custom_story})

@app.route('/api/act', methods=['POST'])
def player_action():
    data = request.get_json()
    player_id = data.get('player_id')
    choice = data.get('choice')
    new_time = data.get('current_time')
    action_type = data.get('action_type', 'story')
    api_config = get_user_api_config(request, player_id)
    
    game_state, err = session_or_404(player_id, "会话已过期")
    if err:
        return err
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    if new_time:
        game_state.current_time = new_time
        if new_time == "卯时":
            game_state.advance_calendar()
    if action_type == 'daily' and choice in get_daily_actions():
        effects = apply_daily_action(game_state, choice)
        daily_actions = get_daily_actions()
        story = {"narration": f"第{game_state.day}天，你选择了『{daily_actions[choice]['desc']}』", "choices": list(daily_actions.keys())[:4], "effects": effects}
    else:
        npc_names = list(game_state.npcs.keys())
        story = generate_story(game_state, choice, npc_names, api_config.get('api_key'), api_config.get('api_base'), api_config.get('api_model'))
    
    # 晋升不再是选择事件，故移除 promotion_event
    rivalry_event = None
    if random.random() < 0.15 and game_state.npcs:
        npc_names = list(game_state.npcs.keys())
        if npc_names:
            rival = random.choice(npc_names)
            if random.random() < 0.5:
                game_state.attributes["宠爱"] = max(0, game_state.attributes["宠爱"] - 5)
                rivalry_event = f"⚠️ {rival}在背后说了你的坏话，宠爱-5"
            else:
                game_state.attributes["心计"] = min(100, game_state.attributes["心计"] + 3)
                rivalry_event = f"✅ 你察觉到了{rival}的敌意，心计+3"
            if rivalry_event:
                game_state.add_memory(rivalry_event)
    if game_state.day % 3 == 0:
        salary = (20 + game_state.rank.value * 5) // 3
        game_state.silver += max(1, salary)
        game_state.add_memory(f"领取俸禄{salary}银两")
    for name in game_state.npcs:
        if random.random() < 0.2:
            change = random.randint(-2, 4)
            if name in game_state.relationships:
                game_state.relationships[name]["好感"] = max(-100, min(100, game_state.relationships[name]["好感"] + change))
    if story.get("effects"):
        game_state.add_attr_change(story["effects"], choice)
    npcs_with_children = serialize_npcs_for_client(game_state)
    autosave_session(player_id)
    return jsonify({"player_id": player_id, "rank": game_state.rank.name, "nobletitle": game_state.nobletitle, "display_rank": game_state.get_display_rank(), "attributes": game_state.attributes, "attr_max": game_state.ATTR_MAX, "relationships": game_state.relationships, "story_flags": game_state.story_flags, "storyline": game_state.storyline.value, "emperor": game_state.emperor, "day": game_state.day, "month": game_state.month, "year": game_state.year, "calendar_str": game_state.get_calendar_str(), "silver": game_state.silver, "family_background": game_state.family_background, "npcs": npcs_with_children, "narration": story.get("narration","宫中岁月静好。"), "choices": story.get("choices",["继续","查看状态","保存游戏"]), "effects": story.get("effects",{}), "rivalry_event": rivalry_event, "event_triggered": story.get("event_triggered"), "memories": game_state.get_recent_memories(3), "is_pregnant": game_state.is_pregnant, "pregnancy_month": game_state.pregnancy_month, "children": game_state.children, "has_children": game_state.has_children, "rivalries": game_state.rivalries, "alliances": game_state.alliances, "attr_change_log": game_state.attr_change_log[-5:], "servants": [s.to_dict() for s in game_state.get_active_servants()], "romance_mode": game_state.romance_mode, "player_name": game_state.name, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})

@app.route('/api/state/<player_id>', methods=['GET'])
def get_state(player_id):
    try:
        need_restore = player_id not in sessions
        game_state = get_or_restore_session(player_id)
        if not game_state:
            return jsonify({"error": "会话不存在"}), 404
        if not hasattr(game_state, 'npcs') or game_state.npcs is None:
            game_state.npcs = {}
        if not hasattr(game_state, 'servants') or game_state.servants is None:
            game_state.servants = []
        if not hasattr(game_state, 'attr_change_log') or game_state.attr_change_log is None:
            game_state.attr_change_log = []
        if not hasattr(game_state, 'relationships') or game_state.relationships is None:
            game_state.relationships = {}
        if not hasattr(game_state, 'rivalries') or game_state.rivalries is None:
            game_state.rivalries = {}
        if not hasattr(game_state, 'alliances') or game_state.alliances is None:
            game_state.alliances = {}
        if not hasattr(game_state, 'children') or game_state.children is None:
            game_state.children = []
        npcs_with_children = serialize_npcs_for_client(game_state)
        return jsonify({"rank": game_state.rank.name, "nobletitle": game_state.nobletitle, "display_rank": game_state.get_display_rank(), "name": game_state.name, "family_background": game_state.family_background, "attributes": game_state.attributes, "attr_max": game_state.ATTR_MAX, "relationships": game_state.relationships, "current_time": game_state.current_time, "day": game_state.day, "month": game_state.month, "year": game_state.year, "calendar_str": game_state.get_calendar_str(), "silver": game_state.silver, "story_flags": game_state.story_flags, "storyline": game_state.storyline.value, "emperor": game_state.emperor, "memories": game_state.get_recent_memories(5), "inventory": game_state.inventory, "npcs": npcs_with_children, "is_pregnant": game_state.is_pregnant, "pregnancy_month": game_state.pregnancy_month, "children": game_state.children, "has_children": game_state.has_children, "rivalries": game_state.rivalries, "alliances": game_state.alliances, "attr_change_log": game_state.attr_change_log[-10:], "servants": [s.to_dict() for s in game_state.get_active_servants()], "romance_mode": game_state.romance_mode, "player_name": game_state.name, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions, "appearance": getattr(game_state,'appearance',''), "talent": getattr(game_state,'talent',''), "personality": getattr(game_state,'personality',''), "traits": getattr(game_state,'traits',[]), "custom_story": getattr(game_state,'custom_story',''), "restored_from_save": need_restore})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"服务器内部错误: {str(e)}"}), 500

@app.route('/api/times', methods=['GET'])
def get_times():
    return jsonify({"times": ["卯时","辰时","巳时","午时","未时","申时","酉时","戌时","亥时"]})

@app.route('/api/storylines', methods=['GET'])
def get_storylines():
    return jsonify({"storylines": [{"key":"主线","name":"📜 主线剧情","desc":"在后宫中生存发展"}, {"key":"爱情线","name":"❤️ 爱情线","desc":"专注与皇帝的感情"}, {"key":"权谋线","name":"⚔️ 权谋线","desc":"争夺权势，成为后宫之主"}, {"key":"自由线","name":"🕊️ 自由线","desc":"寻找机会逃离深宫"}]})

@app.route('/api/all_saves', methods=['GET'])
def all_saves():
    saves = []
    if not os.path.exists(SAVE_DIR):
        return jsonify({"saves": []})
    for filename in os.listdir(SAVE_DIR):
        if filename.endswith('.json'):
            try:
                with open(os.path.join(SAVE_DIR, filename), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    game_data = data.get("game_state", {})
                    base = filename[:-5]
                    parts = base.split('_', 1)
                    if len(parts) == 2:
                        saves.append({"player_id": parts[0], "slot": parts[1], "save_time": data.get("save_time","未知"), "player_name": game_data.get("name","未知"), "rank": game_data.get("display_rank", game_data.get("rank","未知")), "day": game_data.get("day",1)})
            except:
                continue
    saves.sort(key=lambda x: x.get("save_time",""), reverse=True)
    return jsonify({"saves": saves})

@app.route('/api/save', methods=['POST'])
def save_game():
    data = request.get_json()
    player_id = data.get('player_id')
    slot_name = data.get('slot_name', 'default')
    if not player_id:
        return jsonify({"error": "缺少玩家ID"}), 400
    game_state, err = session_or_404(player_id, "会话不存在")
    if err:
        return err
    save_data = game_state.to_save_data()
    filename = os.path.join(SAVE_DIR, f"{player_id}_{slot_name}.json")
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        return jsonify({"success": True, "message": f"游戏已保存 ({slot_name})", "slot": slot_name, "save_time": save_data.get("save_time", datetime.now().isoformat())})
    except Exception as e:
        return jsonify({"error": f"保存失败: {str(e)}"}), 500

@app.route('/api/load', methods=['POST'])
def load_game():
    data = request.get_json()
    player_id = data.get('player_id')
    slot_name = data.get('slot_name', 'default')
    if not player_id:
        return jsonify({"error": "缺少玩家ID"}), 400
    filename = os.path.join(SAVE_DIR, f"{player_id}_{slot_name}.json")
    if not os.path.exists(filename):
        return jsonify({"error": f"存档不存在: {slot_name}"}), 404
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            save_data = json.load(f)
        if "game_state" not in save_data:
            return jsonify({"error": "存档数据损坏"}), 500
        game_state = GameState.from_save_data(save_data)
        if not hasattr(game_state, 'npcs') or not game_state.npcs:
            game_state.npcs = generate_all_npcs(10)
            for name, npc in game_state.npcs.items():
                if name not in game_state.relationships:
                    game_state.relationships[name] = npc.get("relationship", {"好感":0,"印象":"陌生","互动次数":0})
        if not hasattr(game_state, '_pending_promotion'):
            game_state._pending_promotion = None
        game_state._promotion_done = False
        sessions[player_id] = game_state
        api_config = get_user_api_config(request, player_id)
        existing = user_configs.get(player_id, {})
        user_configs[player_id] = {
            "custom_prompt": getattr(game_state, "custom_prompt", "") or existing.get("custom_prompt", ""),
            "romance_mode": getattr(game_state, "romance_mode", False) if hasattr(game_state, "romance_mode") else existing.get("romance_mode", False),
            "api_base": api_config.get("api_base") or existing.get("api_base", "https://cn.jixiangai.xyz/v1"),
            "api_key": api_config.get("api_key") or existing.get("api_key", ""),
            "api_model": api_config.get("api_model") or existing.get("api_model", "Qwen/Qwen2.5-72B-Instruct"),
        }
        return jsonify({"success": True, "message": f"读取存档成功 ({slot_name})", "game_state": game_state.to_dict()})
    except Exception as e:
        return jsonify({"error": f"读取存档失败: {str(e)}"}), 500

@app.route('/api/saves/<player_id>', methods=['GET'])
def list_saves(player_id):
    saves = []
    pattern = f"{player_id}_"
    if not os.path.exists(SAVE_DIR):
        return jsonify({"saves": []})
    for filename in os.listdir(SAVE_DIR):
        if filename.startswith(pattern) and filename.endswith('.json'):
            try:
                with open(os.path.join(SAVE_DIR, filename), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    game_data = data.get("game_state", {})
                    slot_name = filename[len(pattern):-5]
                    saves.append({"slot": slot_name, "save_time": data.get("save_time","未知"), "player_name": game_data.get("name","未知"), "rank": game_data.get("display_rank", game_data.get("rank","未知"))})
            except:
                continue
    saves.sort(key=lambda x: x.get("save_time",""), reverse=True)
    return jsonify({"saves": saves})

@app.route('/api/save/delete', methods=['POST'])
def delete_save():
    data = request.get_json()
    player_id = data.get('player_id')
    slot_name = data.get('slot_name', 'default')
    if not player_id:
        return jsonify({"error": "缺少玩家ID"}), 400
    filename = os.path.join(SAVE_DIR, f"{player_id}_{slot_name}.json")
    if os.path.exists(filename):
        os.remove(filename)
        return jsonify({"success": True, "message": f"已删除存档 ({slot_name})"})
    return jsonify({"error": "存档不存在"}), 404

@app.route('/api/duel/start', methods=['POST'])
def api_duel_start():
    data = request.get_json() or {}
    player_id = data.get('player_id')
    target = data.get('target')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    existing = getattr(game_state, "_active_duel", None)
    resuming = bool(existing and not existing.get("finished"))
    if not resuming:
        can_act, remaining = check_and_consume_action(game_state)
        if not can_act:
            return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    duel, err = start_duel(game_state, target)
    if err:
        game_state.remaining_actions += 1
        return jsonify({"error": err}), 400
    skills = [{"key": k, "name": k, "desc": DUEL_SKILLS[k]["desc"]} for k in duel["player_left"]]
    return jsonify({
        "success": True, "duel": duel, "skills": skills,
        "drain_options": [{"key": k, "desc": v["desc"]} for k, v in DRAIN_OPTIONS.items()],
        "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions,
    })

@app.route('/api/duel/skill', methods=['POST'])
def api_duel_skill():
    data = request.get_json() or {}
    player_id = data.get('player_id')
    skill = data.get('skill')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    duel, duel_err = play_duel_skill(game_state, skill)
    if duel_err:
        return jsonify({"error": duel_err}), 400
    left = [{"key": k, "name": k, "desc": DUEL_SKILLS[k]["desc"]} for k in duel["player_left"]]
    return jsonify({"success": True, "duel": duel, "skills": left})

@app.route('/api/duel/resolve', methods=['POST'])
def api_duel_resolve():
    data = request.get_json() or {}
    player_id = data.get('player_id')
    drain = data.get('drain')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    result, err = resolve_duel(game_state, drain)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({
        "success": True, **result,
        "attributes": game_state.attributes,
        "remaining_actions": game_state.remaining_actions,
        "max_actions": game_state.max_actions,
    })

@app.route('/api/pray', methods=['POST'])
def api_pray():
    data = request.get_json() or {}
    player_id = data.get('player_id')
    mode = data.get('mode', 'bless')
    target = data.get('target')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    result, err = pray_or_curse(game_state, mode, target)
    if err:
        game_state.remaining_actions += 1
        return jsonify({"error": err}), 400
    return jsonify({
        "success": True, **result,
        "attributes": game_state.attributes, "silver": game_state.silver,
        "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions,
    })

@app.route('/api/conflict/random', methods=['POST'])
def random_conflict():
    data = request.get_json()
    player_id = data.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    api_config = get_user_api_config(request, player_id)
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    event = generate_palace_conflict(game_state, None, None, api_config.get('api_key'), api_config.get('api_base'), api_config.get('api_model'))
    if not event:
        return jsonify({"error": "没有合适的宫斗对象"}), 400
    game_state.add_memory(f"宫斗事件：{event['narration'][:30]}...")
    return jsonify({"success": True, "event": event, "attributes": game_state.attributes, "relationships": game_state.relationships, "rivalries": game_state.rivalries, "alliances": game_state.alliances, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})

@app.route('/api/conflict/initiate', methods=['POST'])
def initiate_conflict():
    data = request.get_json()
    player_id = data.get('player_id')
    target = data.get('target')
    conflict_type = data.get('type', '争宠')
    api_config = get_user_api_config(request, player_id)
    game_state, err = session_or_404(player_id)
    if err:
        return err
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    if target not in game_state.npcs and target != game_state.name:
        return jsonify({"error": "目标不存在"}), 404
    if target == game_state.name:
        return jsonify({"error": "不能对自己发起宫斗"}), 400
    event = generate_palace_conflict(game_state, game_state.name, target, api_config.get('api_key'), api_config.get('api_base'), api_config.get('api_model'))
    if not event:
        return jsonify({"error": "宫斗事件生成失败"}), 400
    event["type"] = conflict_type
    game_state.add_memory(f"主动宫斗：{event['narration'][:30]}...")
    return jsonify({"success": True, "event": event, "attributes": game_state.attributes, "relationships": game_state.relationships, "rivalries": game_state.rivalries, "alliances": game_state.alliances, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})

@app.route('/api/conflict/types', methods=['GET'])
def get_conflict_types():
    return jsonify({"types": [{"key": k, "name": k, "desc": v["desc"]} for k, v in CONFLICT_TYPES.items()]})

@app.route('/api/conflict/targets', methods=['GET'])
def get_conflict_targets():
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    targets = [{"name": name, "rank": npc.get("rank","妃嫔"), "personality": npc.get("personality","未知"), "icon": npc.get("icon","🌸")} for name, npc in game_state.npcs.items() if name != "太后"]
    return jsonify({"targets": targets})

@app.route('/api/npc/pregnancy/status', methods=['GET'])
def get_npc_pregnancy_status():
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    pregnancy_status = {}
    for name, npc in game_state.npcs.items():
        if name == "太后" or npc.get("rank") == "皇后" or name == game_state.name:
            continue
        if npc.get("is_pregnant", False):
            month = npc.get("pregnancy_month", 0)
            pregnancy_status[name] = {"is_pregnant": True, "month": month, "stage": "早期" if month < 3 else "中期" if month < 6 else "晚期" if month < 9 else "临盆", "children_count": len(npc.get("children", [])), "fertility": npc.get("fertility", 50)}
        else:
            pregnancy_status[name] = {"is_pregnant": False, "month": 0, "stage": "未孕", "children_count": len(npc.get("children", [])), "fertility": npc.get("fertility", 50)}
    return jsonify({"success": True, "pregnancy_status": pregnancy_status, "total_pregnant": len([s for s in pregnancy_status.values() if s["is_pregnant"]]), "total_children": sum([s["children_count"] for s in pregnancy_status.values()])})

@app.route('/api/family_background/generate', methods=['POST'])
def generate_family_background_api():
    data = request.get_json() or {}
    name = data.get('name', '')
    surname = data.get('surname') or extract_surname(name)
    if not surname:
        return jsonify({"error": "需要姓名或姓氏"}), 400
    bg = generate_official_background(surname, for_player=True)
    talent = data.get('talent')
    personality = data.get('personality')
    attrs = data.get('attributes')
    story = generate_background_story(bg, player_name=name, talent=talent, personality=personality)
    suggested_traits = suggest_traits(attrs=attrs, personality=personality)
    return jsonify({
        "success": True,
        "background": bg,
        "story": story,
        "suggested_traits": suggested_traits,
    })


@app.route('/api/traits/catalog', methods=['GET'])
def list_trait_catalog():
    return jsonify({"traits": get_trait_catalog()})


@app.route('/api/traits/suggest', methods=['POST'])
def suggest_traits_api():
    data = request.get_json() or {}
    traits = suggest_traits(
        attrs=data.get('attributes'),
        personality=data.get('personality'),
        count=data.get('count', 3),
    )
    return jsonify({"success": True, "suggested_traits": traits})


@app.route('/api/background_story/generate', methods=['POST'])
def generate_background_story_api():
    data = request.get_json() or {}
    bg = data.get('background') or {}
    if not bg:
        surname = data.get('surname') or extract_surname(data.get('name', ''))
        if not surname:
            return jsonify({"error": "需要家世或姓名"}), 400
        bg = generate_official_background(surname, for_player=True)
    story = generate_background_story(
        bg,
        player_name=data.get('name'),
        talent=data.get('talent'),
        personality=data.get('personality'),
    )
    return jsonify({"success": True, "story": story, "background": bg})

@app.route('/api/child/given_chars', methods=['GET'])
def list_child_given_chars():
    return jsonify({"categories": CHILD_GIVEN_NAME_CATEGORIES, "chars": CHILD_GIVEN_CHARS})

@app.route('/api/child/interact', methods=['POST'])
def child_interact():
    data = request.get_json()
    player_id = data.get('player_id')
    action = data.get('action')
    child_index = data.get('child_index', 0)
    mother_name = data.get('mother_name')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429

    if mother_name and mother_name != game_state.name:
        if mother_name not in game_state.npcs:
            return jsonify({"error": "目标不存在"}), 404
        children = game_state.npcs[mother_name].get("children", [])
    else:
        children = game_state.children

    if child_index < 0 or child_index >= len(children):
        return jsonify({"error": "子嗣不存在"}), 404
    child = children[child_index]
    child_name = child.get("name", "未命名")
    narration = ""
    effects = {}

    if action == "赐字":
        if child.get("given_name"):
            return jsonify({"error": f"{child_name}已有赐字「{child['given_name']}」", "success": False}), 400
        char = (data.get("given_char") or data.get("char") or "").strip()
        if char and not is_valid_given_char(char):
            return jsonify({"error": "所选字号不在可选范围内", "success": False}), 400
        if not char:
            char = random.choice(CHILD_GIVEN_CHARS)
        child["given_name"] = char
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 3)
        effects = {"威望": 3}
        narration = f"你为{child_name}赐字「{char}」，威望+3"
    elif action == "延师":
        if game_state.silver < 10:
            return jsonify({"error": "银两不足，延师需10两", "success": False}), 400
        child["tutor_level"] = child.get("tutor_level", 0) + 1
        if not child.get("education"):
            child["education"] = random.choice(EDUCATION_TRAITS)
            child["trait"] = f"📚 {child['education']}"
        elif child.get("tutor_level", 0) >= 2:
            pool = [e for e in EDUCATION_TRAITS if e != child.get("education")]
            if pool:
                child["education"] = random.choice(pool)
                child["trait"] = f"📚 {child['education']}"
        game_state.silver = max(0, game_state.silver - 10)
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 2)
        effects = {"威望": 2, "silver": -10}
        lvl = child.get("tutor_level", 1)
        narration = f"你为{child_name}延请名师（第{lvl}次），耗费10银两，威望+2"
    elif action == "赏赐":
        if game_state.silver < 5:
            return jsonify({"error": "银两不足，赏赐需5两", "success": False}), 400
        affection_gain = random.randint(5, 12)
        child["affection"] = child.get("affection", 0) + affection_gain
        game_state.silver = max(0, game_state.silver - 5)
        game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + 3)
        effects = {"宠爱": 3, "silver": -5}
        narration = f"你赏赐{child_name}珍宝，耗费5银两，宠爱+3，亲密度+{affection_gain}"
    else:
        return jsonify({"error": "未知互动"}), 400

    game_state.add_memory(narration)
    return jsonify({
        "success": True,
        "narration": narration,
        "effects": effects,
        "child": child,
        "children": game_state.children,
        "attributes": game_state.attributes,
        "silver": game_state.silver,
        "remaining_actions": game_state.remaining_actions,
        "max_actions": game_state.max_actions,
    })

@app.route('/api/abort', methods=['POST'])
def abort_pregnancy():
    data = request.get_json()
    player_id = data.get('player_id')
    target = data.get('target')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429
    if target not in game_state.npcs:
        return jsonify({"error": "目标不存在"}), 404
    npc = game_state.npcs[target]
    if not npc.get("is_pregnant", False):
        return jsonify({"error": "目标并未怀孕", "success": False}), 400
    abort_month = npc.get("pregnancy_month", 0)
    npc["is_pregnant"] = False
    npc["pregnancy_month"] = 0
    npc["pregnancy_history"].append({"day": game_state.day, "outcome": "被打胎", "month": abort_month})
    game_state.attributes["心计"] = min(100, game_state.attributes.get("心计", 50) + 5)
    game_state.attributes["宠爱"] = max(0, game_state.attributes.get("宠爱", 30) - 5)
    game_state.attributes["威望"] = max(0, game_state.attributes.get("威望", 20) - 3)
    if target in game_state.relationships:
        game_state.relationships[target]["好感"] = max(-100, game_state.relationships[target]["好感"] - 20)
    game_state.rivalries[target] = game_state.rivalries.get(target, 0) + 30
    return jsonify({
        "success": True,
        "narration": f"你成功打掉了{target}的孩子！",
        "effects": {"心计": 5, "宠爱": -5, "威望": -3},
        "attributes": game_state.attributes,
        "remaining_actions": game_state.remaining_actions,
        "max_actions": game_state.max_actions
    })

@app.route('/')
def serve_index():
    return send_file('index.html')

@app.route('/<path:filename>', methods=['GET'])
def serve_static(filename):
    if filename.startswith('api/'):
        return jsonify({"error": "接口不存在，请确认游戏后端已启动"}), 404
    return send_from_directory('.', filename)

restore_sessions_on_startup()

if __name__ == '__main__':
    load_events()
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    print("=" * 60)
    print("🌸 凤仪天下 - 宫斗游戏后端 v1.4.0 ")
    print("=" * 60)
    print(f"🚀 访问: http://0.0.0.0:{port}")
    print("📱 前端与 API 同域部署，分享链接即可游玩")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=debug)