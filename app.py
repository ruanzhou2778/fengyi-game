# app.py
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import uuid
import json
import os
import random
import re
import sys
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

load_dotenv()
from models import GameState, Rank, Storyline, Servant, FOUR_CONSORTS, NOBLETITLES, normalize_rank_name, get_rank_power, is_titled_consort, default_heir_status
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
    get_family_score,
)
from player_traits import apply_trait_bonuses, get_trait_catalog, suggest_traits
from palace_extra import (
    start_duel, play_duel_skill, resolve_duel, chat_probe, pray_or_curse,
    process_pressure, available_skills, DUEL_SKILLS, DRAIN_OPTIONS,
    process_consort_deaths, try_childbirth_death, try_conflict_death,
    kill_consort, period_key, npc_display_rank,
)
from endings import (
    ENDINGS, ensure_ending_fields, is_game_over, ending_payload,
    evaluate_period_endings, check_player_childbirth_death,
    check_player_poison_death, build_life_summary, trigger_ending,
)
from openai import OpenAI
import httpx
from urllib.parse import urlparse
from ai_service import generate_period_events

app = Flask(__name__)

CORS(app, resources={r"/api/*": {
    "origins": ["http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:5000", "http://127.0.0.1:5000", "null", "*"],
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization", "X-API-Base", "X-API-Key", "X-API-Model"],
    "supports_credentials": False
}})

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Base,X-API-Key,X-API-Model,X-Client-Id')
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

def extract_client_id(request=None, data=None):
    if data and data.get("client_id"):
        return str(data["client_id"]).strip()
    if request:
        header = request.headers.get("X-Client-Id")
        if header:
            return str(header).strip()
        arg = request.args.get("client_id")
        if arg:
            return str(arg).strip()
    return None


def save_belongs_to_client(save_data, client_id, known_player_ids=None):
    if not client_id:
        return False
    gs = save_data.get("game_state", save_data)
    owner = gs.get("client_id") or save_data.get("client_id")
    if owner:
        return owner == client_id
    pid = gs.get("player_id")
    if known_player_ids and pid in known_player_ids:
        return True
    return False


def ensure_game_state_client_id(game_state, client_id):
    if client_id and not getattr(game_state, "client_id", None):
        game_state.client_id = client_id
    return game_state.client_id


def parse_known_player_ids(raw):
    if raw is None:
        return set()
    if isinstance(raw, list):
        return {str(x).strip() for x in raw if str(x).strip()}
    if isinstance(raw, str):
        return {x.strip() for x in raw.split(",") if x.strip()}
    return set()

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
            game_state.npcs = generate_all_npcs(10, surname=royal_surname(game_state))
            for name, npc in game_state.npcs.items():
                if name not in game_state.relationships:
                    game_state.relationships[name] = npc.get("relationship", {"好感": 0, "印象": "陌生", "互动次数": 0})
        for npc in game_state.npcs.values():
            if "rank" in npc:
                npc["rank"] = normalize_rank_name(npc["rank"])
        if not hasattr(game_state, '_pending_promotion'):
            game_state._pending_promotion = None
        game_state._promotion_done = False
        if not hasattr(game_state, 'scandal_strikes'):
            game_state.scandal_strikes = 0
        if not hasattr(game_state, 'rank_periods'):
            game_state.rank_periods = 0
        ensure_ending_fields(game_state)
        ensure_character_ages(game_state)
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

RANK_ORDER = [
    "宫女", "更衣", "官女子", "秀女", "答应", "常在", "贵人", "才人", "美人", "婕妤",
    "嫔", "妃", "淑妃", "德妃", "贤妃", "宸妃", "贵妃", "皇贵妃", "皇后",
]
RANK_LEVELS = {name: i for i, name in enumerate(RANK_ORDER)}

RANK_BONUS = {
    "宫女": {"容貌": 0, "才情": 0, "心计": 0, "威望": 0},
    "更衣": {"容貌": 1, "才情": 1, "心计": 1, "威望": 0},
    "官女子": {"容貌": 2, "才情": 2, "心计": 2, "威望": 0},
    "秀女": {"容貌": 3, "才情": 3, "心计": 2, "威望": 1},
    "答应": {"容貌": 5, "才情": 5, "心计": 3, "威望": 2},
    "常在": {"容貌": 7, "才情": 7, "心计": 5, "威望": 4},
    "贵人": {"容貌": 10, "才情": 10, "心计": 7, "威望": 6},
    "才人": {"容貌": 13, "才情": 13, "心计": 9, "威望": 8},
    "美人": {"容貌": 16, "才情": 16, "心计": 11, "威望": 10},
    "婕妤": {"容貌": 18, "才情": 18, "心计": 12, "威望": 11},
    "嫔": {"容貌": 21, "才情": 21, "心计": 14, "威望": 13},
    "妃": {"容貌": 25, "才情": 25, "心计": 17, "威望": 16},
    "淑妃": {"容貌": 28, "才情": 28, "心计": 20, "威望": 19},
    "德妃": {"容貌": 26, "才情": 26, "心计": 18, "威望": 17},
    "贤妃": {"容貌": 27, "才情": 27, "心计": 19, "威望": 18},
    "宸妃": {"容貌": 28, "才情": 28, "心计": 20, "威望": 19},
    "贵妃": {"容貌": 30, "才情": 30, "心计": 20, "威望": 20},
    "皇贵妃": {"容貌": 36, "才情": 36, "心计": 24, "威望": 24},
    "皇后": {"容貌": 42, "才情": 42, "心计": 28, "威望": 28},
}

RANK_LIMITS = {
    "皇后": 1, "皇贵妃": 1, "贵妃": 2,
    "淑妃": 1, "德妃": 1, "贤妃": 1, "宸妃": 1,
    "妃": 5, "嫔": 6,
    "婕妤": 8, "美人": 8, "才人": 10, "贵人": 12, "常在": 15,
    "答应": 18, "秀女": 22, "官女子": 28, "更衣": 32, "宫女": 40,
}

PROMOTION_THRESHOLDS = {
    "宫女": {"宠爱": 20, "威望": 15},
    "更衣": {"宠爱": 32, "威望": 25, "才情": 18},
    "官女子": {"宠爱": 48, "威望": 38, "才情": 28},
    "秀女": {"宠爱": 65, "威望": 50, "才情": 38, "心计": 28},
    "答应": {"宠爱": 85, "威望": 65, "才情": 48, "心计": 38},
    "常在": {"宠爱": 108, "威望": 82, "才情": 58, "心计": 48},
    "贵人": {"宠爱": 135, "威望": 100, "才情": 68, "心计": 58},
    "才人": {"宠爱": 168, "威望": 120, "才情": 72, "心计": 62},
    "美人": {"宠爱": 205, "威望": 142, "才情": 76, "心计": 66},
    "婕妤": {"宠爱": 245, "威望": 168, "才情": 78, "心计": 70},
    "嫔": {"宠爱": 290, "威望": 195, "才情": 80, "心计": 74},
    "妃": {"宠爱": 340, "威望": 225, "才情": 82, "心计": 78},
    "淑妃": {"宠爱": 400, "威望": 268, "才情": 85, "心计": 81},
    "德妃": {"宠爱": 360, "威望": 240, "才情": 83, "心计": 79},
    "贤妃": {"宠爱": 380, "威望": 255, "才情": 84, "心计": 80},
    "宸妃": {"宠爱": 400, "威望": 268, "才情": 85, "心计": 81},
    "贵妃": {"宠爱": 420, "威望": 275, "才情": 85, "心计": 80},
    "皇贵妃": {"宠爱": 540, "威望": 350, "才情": 88, "心计": 82},
}

MIN_RANK_TENURE = {
    "宫女": 2, "更衣": 2, "官女子": 3, "秀女": 3, "答应": 5,
    "常在": 5, "贵人": 6, "才人": 6, "美人": 7, "婕妤": 7,
    "嫔": 8, "妃": 10,
    "淑妃": 12, "德妃": 12, "贤妃": 12, "宸妃": 12,
    "贵妃": 14, "皇贵妃": 16,
}

SPECIAL_FAVOR_RATIO = 1.70   # 宠爱达门槛 170% → 可破格跳过资历（专宠）
SUPER_FAVOR_RATIO = 2.05     # 宠爱达门槛 205% → 属性要求略降
SPECIAL_FAVOR_ABSOLUTE_MIN = 95  # 低位份门槛过低时，专宠至少须达此宠爱

DEMOTION_SEVERE_CONFLICTS = {"陷害", "告发"}
DEMOTION_MODERATE_CONFLICTS = {"谣言", "争辩", "争宠"}

PROMOTION_EXTRA_REQUIREMENTS = {
    "淑妃": {"min_children": 1, "hint": "晋封淑妃须至少诞下一名皇嗣（母凭子贵）"},
    "贵妃": {"min_children": 1, "hint": "晋封贵妃须至少诞下一名皇嗣"},
    "皇贵妃": {"min_children": 2, "hint": "晋封皇贵妃须至少诞下两名皇嗣"},
    "皇后": {"hint": "册立皇后除圣宠外，还需母家势力与朝臣请立中宫的时机"},
}

EMPRESS_SUPPORT_FLAG = "朝臣请立中宫"
EMPRESS_SUPPORT_CLUE_FLAGS = {
    "heir": "立后风向:皇子储位",
    "palace": "立后风向:协理六宫",
    "vacancy": "立后风向:废后朝局",
}
EMPRESS_SUPPORT_SOURCE_FLAGS = {
    "heir": "朝议缘由:皇子储位",
    "palace": "朝议缘由:协理六宫",
    "vacancy": "朝议缘由:废后朝局",
}
EMPRESS_SUPPORT_SOURCE_LABELS = {
    "heir": "皇子储位",
    "palace": "协理六宫",
    "vacancy": "废后朝局",
    "legacy": "旧有朝议",
}
EMPRESS_SUPPORT_VACANCY_FLAG = "中宫悬空:废后"
EMPRESS_MIN_FAMILY_POWER = 62
EMPRESS_EVENT_MIN_FAMILY_POWER = 56
EMPRESS_EVENT_MIN_PRESTIGE = 320
EMPRESS_EVENT_MIN_FAVOR = 460
EMPRESS_EVENT_MIN_EMPEROR_REL = 45

DEPOSE_QUEEN_MIN_RANK = "贵妃"

def get_prev_rank(rank_name):
    if rank_name not in RANK_LEVELS:
        return None
    idx = RANK_LEVELS[rank_name]
    if idx <= 0:
        return None
    return RANK_ORDER[idx - 1]

def pick_available_four_consort(game_state):
    for name in FOUR_CONSORTS:
        if can_promote_to_rank(game_state, name):
            return name
    return None

def grant_consort_nobletitle(game_state):
    """妃位赐封号 → 带封号的妃（位份仍为妃）。"""
    if game_state.rank.name != "妃" or game_state.nobletitle:
        return None
    four_chars = {c.replace("妃", "") for c in FOUR_CONSORTS}
    candidates = [t for t in NOBLETITLES if t not in four_chars]
    if not candidates:
        candidates = list(NOBLETITLES)
    game_state.nobletitle = random.choice(candidates)
    return f"皇帝赐封号：『{game_state.nobletitle}』，册为「{game_state.get_display_rank()}」"

def get_promotion_step(game_state):
    rank = game_state.rank.name
    if rank == "妃" and not game_state.nobletitle:
        return {"type": "赐封号"}
    if rank == "妃" and game_state.nobletitle:
        target = pick_available_four_consort(game_state) or FOUR_CONSORTS[0]
        return {"type": "位份", "target": target}
    next_rank = get_next_rank_name(rank)
    if next_rank:
        return {"type": "位份", "target": next_rank}
    return None


def get_empress_family_power(game_state):
    base = get_family_score(getattr(game_state, "family_background", ""), getattr(game_state, "family_meta", {}))
    prestige = game_state.attributes.get("威望", 0)
    princes = len([c for c in game_state.children if c.get("alive", True) and c.get("gender") == "皇子"])
    prestige_bonus = min(20, prestige // 50)
    prince_bonus = min(12, princes * 6)
    return min(100, base + prestige_bonus + prince_bonus)


def _story_flags(game_state):
    flags = getattr(game_state, "story_flags", None)
    if not isinstance(flags, list):
        flags = list(flags) if flags else []
        game_state.story_flags = flags
    return flags


def _has_story_flag(game_state, flag):
    return flag in _story_flags(game_state)


def _add_story_flag(game_state, flag):
    flags = _story_flags(game_state)
    if flag not in flags:
        flags.append(flag)
        return True
    return False


def _resolve_empress_source_from_flags(game_state, mapping):
    for flag in reversed(_story_flags(game_state)):
        for key, mapped_flag in mapping.items():
            if flag == mapped_flag:
                return key
    return None


def get_empress_support_clues(game_state):
    return [key for key, flag in EMPRESS_SUPPORT_CLUE_FLAGS.items() if _has_story_flag(game_state, flag)]


def get_empress_support_source(game_state):
    source = _resolve_empress_source_from_flags(game_state, EMPRESS_SUPPORT_SOURCE_FLAGS)
    if source:
        return source
    source = _resolve_empress_source_from_flags(game_state, EMPRESS_SUPPORT_CLUE_FLAGS)
    if source:
        return source
    if _has_story_flag(game_state, EMPRESS_SUPPORT_FLAG):
        return "legacy"
    return None


def get_empress_requirement_status(game_state):
    step = get_promotion_step(game_state) or {}
    target = step.get("target")
    living_children = [c for c in game_state.children if c.get("alive", True)]
    princes = [c for c in living_children if c.get("gender") == "皇子"]
    clues = get_empress_support_clues(game_state)
    source = get_empress_support_source(game_state)
    support_ready = _has_story_flag(game_state, EMPRESS_SUPPORT_FLAG)
    return {
        "is_candidate": target == "皇后",
        "family_power": get_empress_family_power(game_state),
        "family_power_required": EMPRESS_MIN_FAMILY_POWER,
        "support_ready": support_ready,
        "support_flag": EMPRESS_SUPPORT_FLAG,
        "support_stage": "ready" if support_ready else ("rumor" if clues else "waiting"),
        "support_source": source,
        "support_source_label": EMPRESS_SUPPORT_SOURCE_LABELS.get(source, ""),
        "support_clues": clues,
        "support_clue_labels": [EMPRESS_SUPPORT_SOURCE_LABELS.get(key, key) for key in clues],
        "support_clue_count": len(clues),
        "children": len(living_children),
        "princes": len(princes),
        "queen_vacant": get_queen_name(game_state) is None,
    }


def _empress_support_source_candidates(game_state, status):
    attrs = game_state.attributes
    emperor_rel = _get_relation_favor(game_state, "皇帝")
    has_queen = bool(get_queen_name(game_state))
    candidates = []
    if status["princes"] >= 1 and status["family_power"] >= 52 and attrs.get("威望", 0) >= 260:
        score = 1.20 + min(1.00, status["princes"] * 0.45)
        score += min(0.80, max(0, status["family_power"] - 52) / 18.0)
        score += min(0.70, max(0, attrs.get("威望", 0) - 260) / 220.0)
        candidates.append({
            "key": "heir",
            "score": score,
            "rumor_text": "📜 皇子渐长，宗室与礼臣已在私下议论：若要早定储位，宜先立中宫。",
            "petition_text": "📜 皇子储位牵动朝局，朝臣请立中宫，礼臣联名上奏，请皇帝早定中宫，以正皇嗣名分。",
        })
    palace_ready = (
        getattr(game_state, "queen_assistance_count", 0) >= 1 or
        _get_six_palace_assistant(game_state) == game_state.name or
        (not has_queen and game_state.rank.name == "皇贵妃" and
         attrs.get("威望", 0) >= 360 and emperor_rel >= 45)
    )
    if palace_ready and status["family_power"] >= 54 and attrs.get("威望", 0) >= 300:
        score = 1.10 + min(0.90, max(0, attrs.get("威望", 0) - 300) / 180.0)
        score += min(0.55, max(0, emperor_rel - 45) / 90.0)
        candidates.append({
            "key": "palace",
            "score": score,
            "rumor_text": "📜 中宫暂缺，皇帝命你协理六宫，六宫多称秩序井然，朝野已有人议及你的中宫之望。",
            "petition_text": "📜 你代掌宫务已久，内外称贤，朝臣请立中宫，联名上奏愿由你名正言顺统摄六宫。",
        })
    if (not has_queen and _has_story_flag(game_state, EMPRESS_SUPPORT_VACANCY_FLAG) and
            status["family_power"] >= 54 and attrs.get("威望", 0) >= 300):
        score = 1.35 + min(0.75, max(0, status["family_power"] - 54) / 18.0)
        score += min(0.70, max(0, attrs.get("威望", 0) - 300) / 180.0)
        score += min(0.35, max(0, emperor_rel - 40) / 70.0)
        candidates.append({
            "key": "vacancy",
            "score": score,
            "rumor_text": "📜 废后风波未平，中宫悬空，前朝议论纷纷，已有大臣私下提起应尽快再定国母。",
            "petition_text": "📜 废后之后朝局未稳，朝臣请立中宫，前朝为安六宫与宗庙名分，联名请皇帝尽快册立中宫。",
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates


def _maybe_open_empress_support_clue(game_state, status):
    candidates = [
        item for item in _empress_support_source_candidates(game_state, status)
        if not _has_story_flag(game_state, EMPRESS_SUPPORT_CLUE_FLAGS[item["key"]])
    ]
    if not candidates:
        return None
    candidate = candidates[0]
    chance = min(0.72, 0.18 + candidate["score"] * 0.16)
    if random.random() >= chance:
        return None
    _add_story_flag(game_state, EMPRESS_SUPPORT_CLUE_FLAGS[candidate["key"]])
    if candidate["key"] == "palace" and not get_queen_name(game_state):
        game_state.six_palace_assistant = game_state.name
    game_state.add_memory(candidate["rumor_text"])
    return candidate["rumor_text"]


def _maybe_raise_empress_petition(game_state, status):
    attrs = game_state.attributes
    emperor_rel = _get_relation_favor(game_state, "皇帝")
    if status["family_power"] < EMPRESS_EVENT_MIN_FAMILY_POWER:
        return None
    if attrs.get("威望", 0) < EMPRESS_EVENT_MIN_PRESTIGE:
        return None
    if attrs.get("宠爱", 0) < EMPRESS_EVENT_MIN_FAVOR:
        return None
    if emperor_rel < EMPRESS_EVENT_MIN_EMPEROR_REL and not is_special_favor(game_state):
        return None
    active_clues = set(get_empress_support_clues(game_state))
    if not active_clues:
        return None
    candidates = [
        item for item in _empress_support_source_candidates(game_state, status)
        if item["key"] in active_clues
    ]
    if not candidates:
        return None
    candidate = candidates[0]
    chance = 0.12
    chance += min(0.18, max(0, status["family_power"] - EMPRESS_EVENT_MIN_FAMILY_POWER) / 100.0)
    chance += min(0.16, max(0, attrs.get("威望", 0) - EMPRESS_EVENT_MIN_PRESTIGE) / 240.0)
    chance += min(0.12, max(0, attrs.get("宠爱", 0) - EMPRESS_EVENT_MIN_FAVOR) / 320.0)
    chance += min(0.12, max(0, emperor_rel - EMPRESS_EVENT_MIN_EMPEROR_REL) / 180.0)
    chance += min(0.08, candidate["score"] / 12.0)
    chance += min(0.06, max(0, len(active_clues) - 1) * 0.03)
    if candidate["key"] == "vacancy":
        chance += 0.06
    elif candidate["key"] == "heir":
        chance += min(0.06, status["princes"] * 0.03)
    chance = min(0.82, chance)
    if random.random() >= chance:
        return None
    _add_story_flag(game_state, EMPRESS_SUPPORT_FLAG)
    _add_story_flag(game_state, EMPRESS_SUPPORT_SOURCE_FLAGS[candidate["key"]])
    game_state.add_memory(candidate["petition_text"])
    return candidate["petition_text"]


def maybe_trigger_empress_support_event(game_state):
    status = get_empress_requirement_status(game_state)
    if not status["is_candidate"] or status["support_ready"]:
        return None
    if get_queen_name(game_state):
        return None
    clue_message = _maybe_open_empress_support_clue(game_state, status)
    if clue_message:
        status = get_empress_requirement_status(game_state)
        petition_message = _maybe_raise_empress_petition(game_state, status)
        return f"{clue_message} {petition_message}" if petition_message else clue_message
    return _maybe_raise_empress_petition(game_state, status)


def apply_promotion_step(game_state, step):
    if not step:
        return None
    if step["type"] == "赐封号":
        title_msg = grant_consort_nobletitle(game_state)
        if not title_msg:
            return None
        return f"📜 圣旨到！{title_msg}"
    target = step.get("target")
    if not target:
        return None
    if target in FOUR_CONSORTS:
        if not can_promote_to_rank(game_state, target):
            return None
        old_title = game_state.nobletitle
        game_state.nobletitle = None
        if not set_player_rank(game_state, target):
            game_state.nobletitle = old_title
            return None
        return f"📜 圣旨到！恭喜晋升为「{game_state.get_display_rank()}」！"
    if not can_promote_to_rank(game_state, target):
        return None
    if set_player_rank(game_state, target):
        return f"📜 圣旨到！恭喜晋升为「{game_state.get_display_rank()}」！"
    return None

def set_player_rank(game_state, rank_name):
    try:
        rank_name = normalize_rank_name(rank_name)
        old = game_state.rank.name
        game_state.rank = Rank[rank_name]
        if old != rank_name:
            game_state.rank_periods = 0
        return True
    except KeyError:
        return False

def demote_player(game_state, reason=""):
    """降位一级，返回降位消息或 None。"""
    current = game_state.rank.name
    if current == "宫女":
        return None
    if current in FOUR_CONSORTS:
        old_display = game_state.get_display_rank()
        prefix = current.replace("妃", "")
        set_player_rank(game_state, "妃")
        game_state.nobletitle = prefix if prefix in NOBLETITLES else random.choice(NOBLETITLES)
        game_state._promotion_done = False
        game_state.rank_periods = 0
        msg = f"📉 降位旨意：由「{old_display}」降为「{game_state.get_display_rank()}」"
    elif current == "妃" and game_state.nobletitle:
        old_display = game_state.get_display_rank()
        game_state.nobletitle = None
        game_state._promotion_done = False
        game_state.rank_periods = 0
        msg = f"📉 降位旨意：由「{old_display}」降为「妃」"
    else:
        prev = get_prev_rank(current)
        if not prev or not set_player_rank(game_state, prev):
            return None
        if game_state.rank.value < Rank.妃.value and game_state.nobletitle:
            game_state.nobletitle = None
        game_state._promotion_done = False
        game_state.rank_periods = 0
        msg = f"📉 降位旨意：由「{current}」降为「{game_state.get_display_rank()}」"
    if reason:
        msg += f"。{reason}"
    game_state.add_memory(msg)
    game_state.scandal_strikes = 0
    return msg

def try_conflict_demotion(game_state, player_lost, conflict_type, opponent_name):
    """宫斗失利时按概率降位。"""
    if not player_lost:
        return None
    if game_state.rank.name == "宫女":
        return None
    favor = game_state.attributes.get("宠爱", 0)
    prestige = game_state.attributes.get("威望", 0)
    base_chance = 0.08
    if conflict_type in DEMOTION_SEVERE_CONFLICTS:
        base_chance = 0.30
    elif conflict_type in DEMOTION_MODERATE_CONFLICTS:
        base_chance = 0.16
    if favor < 30:
        base_chance += 0.12
    elif favor < 60:
        base_chance += 0.06
    if prestige < 40:
        base_chance += 0.05
    if game_state.rivalries.get(opponent_name, 0) >= 30:
        base_chance += 0.08
    strikes = getattr(game_state, "scandal_strikes", 0)
    if strikes >= 2:
        base_chance += 0.18
    if random.random() >= min(base_chance, 0.65):
        game_state.scandal_strikes = strikes + 1
        return None
    reason = f"因「{conflict_type}」失利，{opponent_name}趁机弹劾"
    return demote_player(game_state, reason)

def demote_npc(game_state, npc_name, reason=""):
    """NPC 降位一级，返回降位消息或 None。"""
    npc = game_state.npcs.get(npc_name)
    if not npc or npc_name == "太后":
        return None
    current = normalize_rank_name(npc.get("rank", "答应"))
    if current in ("宫女", "秀女"):
        return None
    if current in FOUR_CONSORTS:
        prefix = current.replace("妃", "")
        npc["rank"] = "妃"
        npc["nobletitle"] = prefix if prefix in NOBLETITLES else random.choice(NOBLETITLES)
        prev = f"{npc['nobletitle']}妃"
        msg = f"📉 {npc_name}由「{current}」降为「{prev}」"
    elif current == "妃" and npc.get("nobletitle"):
        old_display = f"{npc['nobletitle']}妃"
        npc["nobletitle"] = None
        msg = f"📉 {npc_name}由「{old_display}」降为「妃」"
    else:
        prev = get_prev_rank(current)
        if not prev:
            return None
        npc["rank"] = prev
        msg = f"📉 {npc_name}由「{current}」降为「{prev}」"
    attrs = npc.setdefault("attributes", {})
    attrs["宠爱"] = max(0, attrs.get("宠爱", 0) - random.randint(5, 15))
    attrs["威望"] = max(0, attrs.get("威望", 0) - random.randint(3, 10))
    if reason:
        msg += f"。{reason}"
    game_state.add_memory(msg)
    return msg

def try_npc_conflict_demotion(game_state, npc_name, conflict_type, player_won):
    """玩家宫斗得胜时，对手 NPC 可能被降位。"""
    if not player_won or npc_name == "太后":
        return None
    npc = game_state.npcs.get(npc_name)
    if not npc or npc.get("rank") == "皇后":
        return None
    base = 0.12
    if conflict_type in DEMOTION_SEVERE_CONFLICTS:
        base = 0.35
    elif conflict_type in DEMOTION_MODERATE_CONFLICTS:
        base = 0.20
    favor = npc.get("attributes", {}).get("宠爱", 0)
    if favor < 40:
        base += 0.10
    if random.random() >= min(base, 0.55):
        return None
    return demote_npc(game_state, npc_name, f"因「{conflict_type}」失利遭贬")

def get_queen_name(game_state):
    for name, npc in game_state.npcs.items():
        if npc.get("rank") == "皇后":
            return name
    return None

def check_depose_queen_eligible(game_state):
    """玩家是否具备图谋废后的基本资格。"""
    min_level = RANK_LEVELS.get(DEPOSE_QUEEN_MIN_RANK, 7)
    if RANK_LEVELS.get(game_state.rank.name, 0) < min_level:
        return False
    attrs = game_state.attributes
    if attrs.get("威望", 0) < 100 or attrs.get("宠爱", 0) < 80 or attrs.get("心计", 0) < 55:
        return False
    return get_queen_name(game_state) is not None

def try_depose_queen(game_state, reason=""):
    """废后：皇后降为皇贵妃。"""
    queen_name = get_queen_name(game_state)
    if not queen_name:
        return None
    queen = game_state.npcs[queen_name]
    prev = get_prev_rank("皇后") or "皇贵妃"
    queen["rank"] = prev
    attrs = queen.setdefault("attributes", {})
    attrs["宠爱"] = max(0, attrs.get("宠爱", 0) - random.randint(25, 40))
    attrs["威望"] = max(0, attrs.get("威望", 0) - random.randint(20, 35))
    msg = f"📜 凤印褫夺！{queen_name}被废去后位，降为「{prev}」"
    if reason:
        msg += f"。{reason}"
    _add_story_flag(game_state, EMPRESS_SUPPORT_VACANCY_FLAG)
    game_state.add_memory(msg)
    return msg

def try_conflict_depose_queen(game_state, target, conflict_type, player_won):
    """玩家以告发/陷害击败皇后时，有机会废后。"""
    if not player_won or target != get_queen_name(game_state):
        return None
    if conflict_type not in DEMOTION_SEVERE_CONFLICTS:
        return None
    if not check_depose_queen_eligible(game_state):
        return None
    chance = 0.25
    if game_state.attributes.get("威望", 0) >= 120:
        chance += 0.15
    if game_state.attributes.get("宠爱", 0) >= 150:
        chance += 0.10
    if random.random() >= chance:
        return None
    return try_depose_queen(game_state, f"因「{conflict_type}」一击致命，朝野再无异议")

def _calc_conflict_effects(conflict_info, initiator_win):
    """胜者得正属性、败者得负属性，避免「占了上风却显示减值」。"""
    effects = {}
    for attr, (min_val, max_val) in conflict_info["effects"].items():
        magnitude = random.randint(
            max(1, min(abs(min_val), abs(max_val))),
            max(abs(min_val), abs(max_val), 1),
        )
        effects[attr] = magnitude if initiator_win else -magnitude
    return effects

def _player_conflict_view(initiator, target, effects, initiator_win, game_state):
    """返回玩家视角的胜负与属性变化。"""
    if initiator == game_state.name:
        return initiator_win, dict(effects)
    if target == game_state.name:
        return not initiator_win, {k: -v for k, v in effects.items()}
    return None, None

def get_next_rank_name(current_rank_name):
    if current_rank_name not in RANK_LEVELS:
        return None
    if current_rank_name == "妃":
        return None
    idx = RANK_LEVELS[current_rank_name]
    if idx >= len(RANK_ORDER) - 1:
        return None
    return RANK_ORDER[idx + 1]

def get_min_tenure(rank_name):
    return MIN_RANK_TENURE.get(rank_name, 2)

def get_rank_periods(game_state):
    return getattr(game_state, "rank_periods", 0)

def check_tenure_met(game_state):
    return get_rank_periods(game_state) >= get_min_tenure(game_state.rank.name)

def get_favor_threshold(rank_name):
    return PROMOTION_THRESHOLDS.get(rank_name, {}).get("宠爱", 999)

def is_special_favor(game_state):
    """皇帝专宠：宠爱远超当阶门槛，可破格跳过资历限制。"""
    favor = game_state.attributes.get("宠爱", 0)
    required = get_favor_threshold(game_state.rank.name)
    ratio_req = int(required * SPECIAL_FAVOR_RATIO)
    return favor >= max(ratio_req, SPECIAL_FAVOR_ABSOLUTE_MIN)

def is_super_favor(game_state):
    """圣宠无极：属性要求亦略降。"""
    favor = game_state.attributes.get("宠爱", 0)
    required = get_favor_threshold(game_state.rank.name)
    ratio_req = int(required * SUPER_FAVOR_RATIO)
    return favor >= max(ratio_req, SPECIAL_FAVOR_ABSOLUTE_MIN + 40)

def get_promotion_block_reason(game_state):
    step = get_promotion_step(game_state)
    if not step:
        return None
    if step["type"] == "赐封号":
        return None
    target = step.get("target")
    if not target:
        return None
    if target == "皇后":
        status = get_empress_requirement_status(game_state)
        if status["family_power"] < status["family_power_required"]:
            return (
                f"册立皇后须有足够母家势力（需家族势力≥{status['family_power_required']}，"
                f"当前{status['family_power']}）"
            )
        if not status["support_ready"]:
            return "册立皇后尚需朝臣请立中宫、六宫归心的时机"
    req = PROMOTION_EXTRA_REQUIREMENTS.get(target)
    if not req:
        return None
    min_children = req.get("min_children", 0)
    if min_children > 0:
        living = [c for c in game_state.children if c.get("alive", True)]
        if len(living) < min_children:
            return req.get("hint", "晋升条件未满足")
    return None

def check_promotion_thresholds_met(game_state, attr_ratio=1.0):
    current_rank_name = game_state.rank.name
    if current_rank_name not in PROMOTION_THRESHOLDS:
        return False
    threshold = PROMOTION_THRESHOLDS[current_rank_name]
    attrs = game_state.attributes
    for attr, value in threshold.items():
        required = max(1, int(value * attr_ratio))
        if attrs.get(attr, 0) < required:
            return False
    return True

def npc_meets_rank_requirements(npc, target_rank):
    req = PROMOTION_EXTRA_REQUIREMENTS.get(target_rank)
    if not req:
        return True
    min_children = req.get("min_children", 0)
    if min_children > 0:
        living = [c for c in npc.get("children", []) if c.get("alive", True)]
        if len(living) < min_children:
            return False
    return True

def get_rank_bonus(rank_name):
    return RANK_BONUS.get(rank_name, {"容貌": 0, "才情": 0, "心计": 0, "威望": 0})

def can_promote_to_rank(game_state, target_rank_name):
    if target_rank_name not in RANK_LIMITS:
        return True
    target_rank_name = normalize_rank_name(target_rank_name)
    limit = RANK_LIMITS[target_rank_name]
    count = 0
    for name, npc in game_state.npcs.items():
        if normalize_rank_name(npc.get("rank")) == target_rank_name:
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
        promo_msg = try_player_promotion(game_state)
        if promo_msg:
            return {"type": "位份", "name": game_state.get_display_rank(), "desc": promo_msg.replace("📜 圣旨到！", ""), "silver": 0, "effects": {"宠爱": 10, "威望": 10}, "is_promotion": True}
        amount = random.randint(30, 80)
        return {"type": "银两", "name": f"白银{amount}两", "desc": f"赏赐白银{amount}两（暂未能晋封）", "silver": amount, "effects": {}}
    elif reward_type == "封号":
        if game_state.rank.name == "妃" and not game_state.nobletitle:
            title_msg = grant_consort_nobletitle(game_state)
            if title_msg:
                return {"type": "封号", "name": game_state.nobletitle, "desc": title_msg, "silver": 0, "effects": {"宠爱": 8, "威望": 12}}
        from models import NOBLETITLES
        if game_state.rank.name != "妃":
            new_title = random.choice(NOBLETITLES)
            game_state.nobletitle = new_title
            return {"type": "封号", "name": new_title, "desc": f"赐封号『{new_title}』", "silver": 0, "effects": {"宠爱": 8, "威望": 12}}
        amount = random.randint(30, 80)
        return {"type": "银两", "name": f"白银{amount}两", "desc": f"赏赐白银{amount}两（暂未能赐封号）", "silver": amount, "effects": {}}
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
    "下毒": {"desc": "在对手饮食中投下剧毒", "effects": {"健康": (-35, -20), "威望": (-8, 2), "宠爱": (-5, 2)}},
    "谣言": {"desc": "散布流言蜚语", "effects": {"心计": (3, 8), "威望": (-10, 3), "宠爱": (-3, 3)}},
    "拉拢": {"desc": "拉拢盟友共同对抗", "effects": {"心计": (3, 6), "威望": (2, 6), "宠爱": (0, 3)}},
    "告发": {"desc": "告发对手的不轨行为", "effects": {"威望": (5, 15), "心计": (5, 10), "宠爱": (-5, 5)}},
    "争辩": {"desc": "当面与对手争辩", "effects": {"威望": (-5, 8), "心计": (3, 8), "宠爱": (-3, 5)}},
}

SERVANT_ASSIST_MAX = 3

def resolve_servant_assist(game_state, servant_names, conflict_type=None):
    """校验并计算宫人协助加成。返回 (bonus, used_servants)。"""
    if not servant_names:
        return 0.0, []
    roster = {s.name: s for s in game_state.get_active_servants()}
    used = []
    for name in servant_names[:SERVANT_ASSIST_MAX]:
        s = roster.get(name)
        if s and s.is_active:
            used.append(s)
    if not used:
        return 0.0, []
    bonus = 0.0
    for s in used:
        type_bonus = 5.0 if s.type == "太监" else 4.0
        if conflict_type in ("陷害", "告发", "下毒") and s.type == "太监":
            type_bonus += 2.0
        elif conflict_type in ("谣言", "争宠", "造谣") and s.type == "宫女":
            type_bonus += 2.0
        bonus += type_bonus + s.skill * 0.12 + s.loyalty * 0.08
    return bonus, used

def apply_servant_assist_aftermath(used_servants, player_won):
    """宫斗结束后调整协助宫人的忠诚度。"""
    notes = []
    for s in used_servants:
        if player_won:
            s.loyalty = max(0, s.loyalty - random.randint(1, 3))
            if random.random() < 0.3:
                s.skill = min(100, s.skill + 1)
        else:
            s.loyalty = max(0, s.loyalty - random.randint(4, 8))
    if used_servants:
        names = "、".join(s.name for s in used_servants)
        if player_won:
            notes.append(f"{names}暗中协助，功不可没")
        else:
            notes.append(f"{names}协助失利，各自惶恐")
    return notes
def _apply_npc_conflict_effects(npc, effects, winner):
    """把宫斗结果真正写回 NPC，返回实际属性变化。"""
    attrs = npc.setdefault("attributes", {})
    applied = {}
    for attr, delta in effects.items():
        if attr not in attrs:
            continue
        actual = delta if winner else -delta
        old = attrs.get(attr, 0)
        attrs[attr] = max(0, min(100, old + actual))
        applied[attr] = attrs[attr] - old
    return applied


QUEEN_AUTHORITY_MAX_USES = 3
QUEEN_AUTHORITY_MIN_PRESTIGE = 80
QUEEN_MANAGEABLE_MIN_RANK = "更衣"


def _queen_authority_period_state(game_state):
    current = period_key(game_state)
    if getattr(game_state, "queen_authority_period", None) != current:
        game_state.queen_authority_period = current
        game_state.queen_authority_uses = 0
    return current, getattr(game_state, "queen_authority_uses", 0)


def _is_queen_manageable_npc(npc):
    rank = normalize_rank_name(npc.get("rank", "答应"))
    return (npc.get("alive", True) and rank in RANK_LEVELS and
            RANK_LEVELS[QUEEN_MANAGEABLE_MIN_RANK] <= RANK_LEVELS[rank] < RANK_LEVELS["妃"])


def queen_authority(game_state):
    """返回凤印持有者、协理六宫权限和本旬剩余次数。"""
    _queen_authority_period_state(game_state)
    is_player = game_state.rank.name == "皇后"
    holder = game_state.name if is_player else get_queen_name(game_state)
    queen = game_state.npcs.get(holder, {}) if holder else {}
    power = (game_state.attributes.get("威望", 0) if is_player else
             queen.get("attributes", {}).get("威望", 0))
    assistant = _get_six_palace_assistant(game_state)
    used = getattr(game_state, "queen_authority_uses", 0)
    can_use = (is_player and power >= QUEEN_AUTHORITY_MIN_PRESTIGE) or assistant == game_state.name
    return {"holder": holder, "is_player": is_player, "power": max(60, power) if holder else 0,
            "assistant": assistant,
            "can_assist_six_palaces": can_use,
            "can_manage_ranks": _can_manage_ranks(game_state),
            "uses": used, "max_uses": QUEEN_AUTHORITY_MAX_USES,
            "remaining_uses": max(0, QUEEN_AUTHORITY_MAX_USES - used),
            "period": getattr(game_state, "queen_authority_period", None)}


def _get_relation_favor(game_state, name):
    return game_state.relationships.get(name, {}).get("好感", 0)


def _target_can_be_petitioned(npc):
    if not npc or not npc.get("alive", True):
        return False
    rank = normalize_rank_name(npc.get("rank", "答应"))
    return rank in RANK_LEVELS and RANK_LEVELS[QUEEN_MANAGEABLE_MIN_RANK] <= RANK_LEVELS[rank] < RANK_LEVELS["妃"]


def _get_six_palace_assistant(game_state):
    name = getattr(game_state, "six_palace_assistant", None)
    npc = game_state.npcs.get(name) if name else None
    if npc and npc.get("alive", True):
        return name
    if name and game_state.name == name:
        return name
    game_state.six_palace_assistant = None
    return None


def _can_manage_ranks(game_state):
    if game_state.rank.name == "皇后":
        return True
    return _get_six_palace_assistant(game_state) == game_state.name


def _appoint_six_palace_assistant(game_state, candidate_name, source):
    if not candidate_name:
        return None, "请先指定协理六宫人选"
    if candidate_name == game_state.name:
        if game_state.rank.name != "皇后":
            return None, "非皇后不可自领协理六宫之权"
        game_state.six_palace_assistant = game_state.name
        text = "皇帝允准，由你暂掌协理六宫之事。"
        game_state.add_memory(text)
        return {"assistant": game_state.name, "source": source}, text
    candidate = game_state.npcs.get(candidate_name)
    if not candidate or not candidate.get("alive", True):
        return None, "所请之人已不在后宫"
    rank = normalize_rank_name(candidate.get("rank", "答应"))
    if rank not in RANK_LEVELS or RANK_LEVELS[rank] < RANK_LEVELS["嫔"]:
        return None, "协理六宫人选需为嫔位及以上妃嫔"
    if rank == "皇后":
        return None, "皇后本就执掌凤印，无需再任协理"
    game_state.six_palace_assistant = candidate_name
    candidate["assists_six_palaces"] = True
    text = f"皇帝点头，命{candidate_name}协理六宫，襄助皇后综理宫务。"
    game_state.add_memory(text)
    return {"assistant": candidate_name, "source": source, "rank": candidate.get("rank")}, text


def _promotion_roll(game_state, source_name, target_name, base_chance, title):
    target = game_state.npcs.get(target_name)
    if not _target_can_be_petitioned(target):
        return None, "只能为仍在后宫且位于妃位以下的妃嫔请晋"
    current_rank = normalize_rank_name(target.get("rank", "答应"))
    next_rank = get_next_rank_name(current_rank)
    if not next_rank or RANK_LEVELS.get(next_rank, 0) >= RANK_LEVELS["妃"]:
        return None, "该妃嫔已无法再由此途径晋位"
    if not can_promote_to_rank(game_state, next_rank):
        return None, f"{next_rank}名额已满，暂不能再晋"
    chance = base_chance
    emperor_rel = _get_relation_favor(game_state, "皇帝")
    queen_name = get_queen_name(game_state)
    queen_rel = _get_relation_favor(game_state, queen_name) if queen_name else 0
    assistant_name = _get_six_palace_assistant(game_state)
    assistant_rel = _get_relation_favor(game_state, assistant_name) if assistant_name and assistant_name != game_state.name else 0
    if emperor_rel >= 35:
        chance += 0.08
    if queen_rel >= 35:
        chance += 0.06
    if assistant_rel >= 35:
        chance += 0.06
    chance += max(0, min(18, game_state.attributes.get("威望", 0) - 60)) / 300.0
    chance = min(0.92, max(0.08, chance))
    if random.random() >= chance:
        loss = random.randint(1, 4)
        target_rel = game_state.relationships.setdefault(target_name, {"好感": 0, "印象": "陌生", "互动次数": 0})
        target_rel["好感"] = max(-100, target_rel.get("好感", 0) - loss)
        return {"success": False, "chance": round(chance, 2)}, f"你向{title}为{target_name}请晋，但{title}并未允准，{target_name}也难免失望。"
    target["rank"] = next_rank
    target["nobletitle"] = None
    attrs = target.setdefault("attributes", {})
    attrs["威望"] = min(100, attrs.get("威望", 0) + random.randint(6, 12))
    attrs["宠爱"] = min(100, attrs.get("宠爱", 0) + random.randint(3, 8))
    target_rel = game_state.relationships.setdefault(target_name, {"好感": 0, "印象": "陌生", "互动次数": 0})
    target_rel["好感"] = min(100, target_rel.get("好感", 0) + random.randint(8, 16))
    if source_name:
        src_rel = game_state.relationships.setdefault(source_name, {"好感": 0, "印象": "陌生", "互动次数": 0})
        src_rel["好感"] = min(100, src_rel.get("好感", 0) + random.randint(2, 6))
    text = f"你向{title}为{target_name}请晋，{title}终于颔首，晋{target_name}为「{next_rank}」。"
    game_state.add_memory(text)
    return {"success": True, "chance": round(chance, 2), "rank": next_rank}, text


def _consume_queen_authority(game_state):
    _queen_authority_period_state(game_state)
    if game_state.queen_authority_uses >= QUEEN_AUTHORITY_MAX_USES:
        return False
    game_state.queen_authority_uses += 1
    return True


def _player_relationship_promotion(game_state):
    if game_state.rank.name == "皇后":
        return None
    if game_state._promotion_done:
        return None
    step = get_promotion_step(game_state)
    if not step or step.get("type") != "位份":
        return None
    if get_promotion_block_reason(game_state):
        return None
    target_rank = step.get("target")
    if not target_rank or not can_promote_to_rank(game_state, target_rank):
        return None
    queen_name = get_queen_name(game_state)
    assistant_name = _get_six_palace_assistant(game_state)
    queen_rel = _get_relation_favor(game_state, queen_name) if queen_name else 0
    assistant_rel = _get_relation_favor(game_state, assistant_name) if assistant_name and assistant_name != game_state.name else 0
    emperor_rel = _get_relation_favor(game_state, "皇帝")
    chance = 0.0
    if queen_rel >= 55:
        chance += 0.18
    if assistant_rel >= 55:
        chance += 0.14
    if emperor_rel >= 45:
        chance += 0.10
    if game_state.attributes.get("宠爱", 0) >= max(40, int(get_favor_threshold(game_state.rank.name) * 0.7)):
        chance += 0.08
    if chance <= 0:
        return None
    if random.random() >= min(chance, 0.55):
        return None
    promo_msg = apply_promotion_step(game_state, step)
    if not promo_msg:
        return None
    game_state._promotion_done = True
    tag = assistant_name if assistant_rel >= queen_rel and assistant_rel >= 55 else queen_name
    if tag:
        promo_msg += f"（{tag}在内廷为你美言）"
    game_state.add_memory(f"晋升为{game_state.get_display_rank()}")
    game_state.story_flags.append("关系晋升")
    return promo_msg


def process_rank_petition(game_state, action, target_name=None, candidate_name=None):
    if action == "请示协理":
        if game_state.rank.name != "皇后":
            return None, "只有皇后可以向皇帝请示协理六宫人选"
        if game_state.attributes.get("威望", 0) < 70:
            return None, "威望不足，尚不足以向皇帝举荐协理六宫人选"
        chance = 0.42 + min(0.18, _get_relation_favor(game_state, "皇帝") / 250.0)
        if random.random() >= min(chance, 0.88):
            return {"success": False, "chance": round(chance, 2)}, "你向皇帝请示协理六宫人选，皇帝只说容后再议。"
        return _appoint_six_palace_assistant(game_state, candidate_name, "emperor-approved")
    if action == "任命协理":
        chance = 0.38 + min(0.22, _get_relation_favor(game_state, "皇帝") / 220.0)
        if random.random() >= min(chance, 0.9):
            return {"success": False, "chance": round(chance, 2)}, "皇帝听罢微微摇头，并未立刻定下协理六宫之人。"
        return _appoint_six_palace_assistant(game_state, candidate_name, "emperor-direct")
    if action == "向皇上请晋":
        return _promotion_roll(game_state, "皇帝", target_name, 0.42, "皇上")
    if action == "向皇后请晋":
        if game_state.rank.name == "皇后":
            return None, "你自己就是皇后，无法请皇后出面"
        queen_name = get_queen_name(game_state)
        if not queen_name:
            return None, "宫中尚无皇后，无法请皇后出面"
        return _promotion_roll(game_state, queen_name, target_name, 0.34 + max(0, _get_relation_favor(game_state, queen_name)) / 350.0, "皇后")
    if action == "向太后请晋":
        return _promotion_roll(game_state, "太后", target_name, 0.31 + max(0, _get_relation_favor(game_state, "太后")) / 360.0, "太后")
    return None, "无效的请示或请晋操作"




def _apply_queen_rank_adjustment(game_state, target_name, action):
    target = game_state.npcs.get(target_name)
    if not target or not _is_queen_manageable_npc(target):
        return None, "协理六宫只能调整仍在后宫的妃位以下妃嫔"
    old_rank = normalize_rank_name(target.get("rank", "答应"))
    if action == "晋位":
        new_rank = get_next_rank_name(old_rank)
        if not new_rank or RANK_LEVELS.get(new_rank, 0) >= RANK_LEVELS["妃"]:
            return None, "该妃嫔已无法再晋位"
        target["rank"] = new_rank
        target["nobletitle"] = None
        delta = {"威望": 10, "宠爱": 4}
        text = f"你以皇后名义协理六宫，晋封{target_name}为「{new_rank}」。"
    else:
        if not demote_npc(game_state, target_name, "皇后协理六宫裁定"):
            return None, "该妃嫔已无法再降位"
        delta = {"威望": -8, "宠爱": -4}
        text = f"你以皇后名义协理六宫，{target_name}由「{old_rank}」降位。"
    attrs = target.setdefault("attributes", {})
    for key, value in delta.items():
        attrs[key] = max(0, attrs.get(key, 0) + value)
    relation = game_state.relationships.setdefault(target_name, {"好感": 0, "印象": "陌生", "互动次数": 0})
    relation["好感"] = max(-100, min(100, relation.get("好感", 0) + (-8 if action == "晋位" else -18)))
    target["queen_authority_records"] = target.get("queen_authority_records", 0) + 1
    return {"rank": target.get("rank"), "display_rank": target.get("nobletitle") + "妃" if target.get("nobletitle") else target.get("rank"), **delta}, text


def apply_queen_authority(game_state, target_name, action):
    """执行凤印事务：协理六宫可调整妃位以下妃嫔。"""
    authority = queen_authority(game_state)
    target = game_state.npcs.get(target_name) if target_name else None
    if target and authority["holder"] == target_name:
        if action not in ("请安", "申诉", "求情"):
            return None, "不能对皇后执行此项处置"
        relation = game_state.relationships.setdefault(target_name, {"好感": 0, "印象": "陌生", "互动次数": 0})
        gain = 5 if action == "请安" else (3 if action == "求情" else 1)
        relation["好感"] = min(100, relation.get("好感", 0) + gain)
        return {"action": action, "target": target_name, "effects": {"好感": gain}}, f"你向{target_name}行{action}礼，皇后记下了你的态度。"
    if action == "协理六宫":
        if not authority["can_assist_six_palaces"]:
            return None, "你尚未满足协理六宫条件（需为皇后或受命协理，且皇后威望达标）"
        if not _consume_queen_authority(game_state):
            return None, "本旬协理六宫名额已用尽"
        gain = 6
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + gain)
        game_state.queen_assistance_count = getattr(game_state, "queen_assistance_count", 0) + 1
        text = "你亲理六宫事务，裁决宫规、核查份例，后宫秩序为之一肃。"
        game_state.add_memory(text)
        return {"action": action, "effects": {"威望": gain}}, text
    if action in ("晋位", "降位"):
        if not authority["can_manage_ranks"]:
            return None, "非皇后或协理六宫之人，不可直接管理妃嫔位份"
        if not authority["is_player"] and _get_six_palace_assistant(game_state) != game_state.name:
            return None, "你尚未执掌凤印，不能行使皇后处置权"
        if authority["is_player"] and authority["power"] < QUEEN_AUTHORITY_MIN_PRESTIGE:
            return None, f"威望不足，需达到{QUEEN_AUTHORITY_MIN_PRESTIGE}方可协理六宫"
        if not target_name:
            return None, "请先选择需要调整位份的妃嫔"
        if not _consume_queen_authority(game_state):
            return None, "本旬协理六宫名额已用尽"
        result, message = _apply_queen_rank_adjustment(game_state, target_name, action)
        if not result:
            game_state.queen_authority_uses = max(0, game_state.queen_authority_uses - 1)
            return None, message
        game_state.add_memory(message)
        return {"action": action, "target": target_name, "effects": result}, message
    if not authority["is_player"]:
        return None, "你尚未执掌凤印，不能行使皇后处置权"
    if action not in ("训诫", "罚俸", "禁足", "降位"):
        return None, "无效的皇后处置"
    if not target or target_name == "太后" or not target.get("alive", True):
        return None, "目标不存在或已不在后宫"
    attrs = target.setdefault("attributes", {})
    target["queen_punishments"] = target.get("queen_punishments", 0) + 1
    if action == "训诫":
        attrs["威望"] = max(0, attrs.get("威望", 0) - 8); result = {"威望": -8}; text = f"你以凤印训诫{target_name}，其威望下降。"
    elif action == "罚俸":
        attrs["宠爱"] = max(0, attrs.get("宠爱", 0) - 6); result = {"宠爱": -6}; text = f"你下令罚没{target_name}本月俸禄，圣宠也受牵连。"
    elif action == "禁足":
        target["confined_until"] = period_key(game_state); attrs["威望"] = max(0, attrs.get("威望", 0) - 12); result = {"威望": -12}; text = f"你下凤令令{target_name}禁足一旬。"
    else:
        if normalize_rank_name(target.get("rank", "答应")) == "皇后":
            return None, "皇后不可由自己降位"
        if not demote_npc(game_state, target_name, "触犯凤仪宫规"):
            return None, "该妃嫔已无法再降位"
        result = {"位份": -1}; text = f"你执掌凤印，{target_name}降位。"
    game_state.add_memory(text)
    return {"action": action, "target": target_name, "effects": result}, text



ALLIANCE_PLEDGES = [
    "他日若有一人得势，必不忘今日之约",
    "你我同舟共济，宫中风浪一并担",
    "彼此耳目相通，凡有风声先递一信",
    "若谁被人构陷，另一人必在御前分说",
    "无论谁诞下皇嗣，另一人皆护其周全",
]

ALLIANCE_SCENES = [
    "你与{name}在偏殿设一小席，屏退宫人，仅留一盏灯。她亲手为你斟茶，茶烟袅袅间彼此交换了各自的软肋",
    "夜雨敲窗，{name}执你之手立于廊下，说宫中人心难测，唯有并肩才不至于被逐一吞没",
    "你以一支旧簪相赠，{name}回你一方绣帕。物虽轻，却是彼此立信的凭据",
    "你与{name}于御花园假山后低语良久，把各自与旁人的恩怨一一摊开，反倒生出几分惺惺相惜",
    "{name}半夜遣心腹宫女送来密笺，字迹仓促，只写「愿与姐姐同进退」。你在灯下批了一个「诺」字",
]

ALLIANCE_LEVEL_BONUS = {
    "泛交": {"favor": 8, "威望": 2, "心计": 1},
    "互助": {"favor": 12, "威望": 4, "心计": 2},
    "深交": {"favor": 16, "威望": 6, "心计": 4},
    "金石之交": {"favor": 20, "威望": 9, "心计": 5},
}


def _alliance_strength(game_state, npc_name):
    """结盟牢固度：由好感、位份、威望共同决定。返回 (level, value)。"""
    favor = game_state.relationships.get(npc_name, {}).get("好感", 0)
    npc = game_state.npcs.get(npc_name, {}) or {}
    rank_power = get_rank_power(normalize_rank_name(npc.get("rank", "答应")), npc.get("nobletitle"))
    prestige = npc.get("attributes", {}).get("威望", 20)
    score = favor * 0.5 + rank_power * 2.5 + prestige * 0.25
    if score >= 85:
        return "金石之交", random.randint(55, 70)
    if score >= 60:
        return "深交", random.randint(42, 54)
    if score >= 40:
        return "互助", random.randint(32, 41)
    return "泛交", random.randint(22, 31)


def form_alliance(game_state, npc_name):
    """缔结盟约：写入盟友值，给出即时收益与一段成型剧情。"""
    level, value = _alliance_strength(game_state, npc_name)
    game_state.alliances[npc_name] = value
    bonus = ALLIANCE_LEVEL_BONUS[level]

    rel = game_state.relationships.setdefault(npc_name, {"好感": 0, "印象": "陌生", "互动次数": 0})
    favor_gain = bonus["favor"]
    rel["好感"] = min(100, rel.get("好感", 0) + favor_gain)
    rel["印象"] = "盟友"
    rel["互动次数"] = rel.get("互动次数", 0) + 1

    prestige_gain = bonus["威望"]
    wit_gain = bonus["心计"]
    game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + prestige_gain)
    game_state.attributes["心计"] = min(game_state.get_attr_max("心计"), game_state.attributes.get("心计", 0) + wit_gain)

    npc = game_state.npcs.get(npc_name, {}) or {}
    npc["压力"] = max(0, npc.get("压力", 20) - random.randint(3, 8))

    pledge = random.choice(ALLIANCE_PLEDGES)
    scene = random.choice(ALLIANCE_SCENES).format(name=npc_name)
    display = npc_display_rank(npc) if npc else "妃嫔"
    effects = {"威望": prestige_gain, "心计": wit_gain, "好感": favor_gain}
    dowry = ""
    if level in ("深交", "金石之交"):
        gift = random.randint(15, 40)
        game_state.silver += gift
        effects["银两"] = gift
        dowry = f" 临别时{npc_name}塞给你一只荷包，内有{gift}两银，说「莫要与我推让」。"

    narration = (
        f"🤝 你与{display}{npc_name}结为盟友（{level}）。{scene}。"
        f"临了她低声立誓：「{pledge}」。"
        f"好感+{favor_gain}，威望+{prestige_gain}，心计+{wit_gain}。{dowry}"
    ).strip()

    return {
        "level": level,
        "value": value,
        "pledge": pledge,
        "narration": narration,
        "effects": effects,
        "memory": f"与{npc_name}结为{level}盟友：{pledge}",
    }


def process_alliance_period(game_state):
    """每旬盟友互动：情报、援手、共谋，或因疏远而生嫌隙。返回事件文案列表。"""
    events = []
    if not getattr(game_state, "alliances", None):
        return events

    for name in list(game_state.alliances.keys()):
        npc = game_state.npcs.get(name)
        if not isinstance(npc, dict) or not npc.get("alive", True) or not npc.get("is_active", True):
            game_state.alliances.pop(name, None)
            continue

        bond = game_state.alliances.get(name, 0)
        favor = game_state.relationships.get(name, {}).get("好感", 0)

        # 好感跌破门槛：盟约松动乃至破裂
        if favor < 15:
            bond -= random.randint(5, 12)
            if bond <= 5:
                game_state.alliances.pop(name, None)
                events.append(f"💔 {name} 遣人递话，说「情分已淡，往后各安其位」，与你的盟约就此散了")
            else:
                game_state.alliances[name] = bond
                events.append(f"🍂 {name} 近来与你少了往来，盟友之谊淡了几分（盟友值{bond}）")
            continue

        if random.random() < 0.45:
            game_state.alliances[name] = min(100, bond + random.randint(1, 4))
        if random.random() > 0.55:
            continue

        events.append(_alliance_period_event(game_state, name))

    events = [e for e in events if e]
    for msg in events:
        game_state.add_memory(msg)
    return events


def _alliance_period_event(game_state, name):
    """随机抽取一条盟友互动事件并结算，返回文案。"""
    roll = random.random()
    if roll < 0.30:
        rivals = [n for n, v in game_state.rivalries.items() if v > 0 and n in game_state.npcs]
        wit = random.randint(2, 5) if rivals else random.randint(1, 3)
        game_state.attributes["心计"] = min(game_state.get_attr_max("心计"), game_state.attributes.get("心计", 0) + wit)
        if rivals:
            foe = random.choice(rivals)
            return f"📨 {name} 密报：{foe} 近日频往内务府走动，似在筹谋对你不利。你心中有了防备，心计+{wit}"
        return f"📨 {name} 将各宫近日的动静抄了一份给你，心计+{wit}"
    if roll < 0.52:
        gain = random.randint(2, 6)
        game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + gain)
        return f"🌸 御前侍膳时，{name} 有意提起你近日抄经祈福之事，皇帝颔首称贤，宠爱+{gain}"
    if roll < 0.70:
        gain = random.randint(2, 5)
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + gain)
        return f"🏮 六宫议事，{name} 处处替你说话，无人再敢轻慢，威望+{gain}"
    if roll < 0.84:
        silver = random.randint(8, 25)
        game_state.silver += silver
        return f"🎁 {name} 派人送来时令点心与{silver}两银，说是「姐妹间不必客套」"
    if roll < 0.94 and game_state.rivalries:
        foe = random.choice(list(game_state.rivalries.keys()))
        foe_npc = game_state.npcs.get(foe)
        if isinstance(foe_npc, dict) and foe_npc.get("alive", True):
            press = random.randint(5, 14)
            foe_npc["压力"] = min(120, foe_npc.get("压力", 20) + press)
            return f"⚔️ 你与{name}合谋，借宫人之口散了{foe}几句闲话，{foe}压力+{press}"
    health = random.randint(2, 6)
    game_state.attributes["健康"] = min(game_state.get_attr_max("健康"), game_state.attributes.get("健康", 0) + health)
    return f"🍲 {name} 亲手炖了补品送来，你饮后气色转好，健康+{health}"


def _record_conflict_rivalry(game_state, initiator, target, initiator_win):
    """记录一次宫斗产生的仇恨。

    只有玩家亲身参与（作为发起者或目标）时才写入 game_state.rivalries；
    NPC 与 NPC 之间的宫斗写入各自 npc["npc_rivals"]，不再污染玩家仇敌列表。
    """
    player = game_state.name
    loser = target if initiator_win else initiator
    winner = initiator if initiator_win else target

    if player in (initiator, target):
        # 玩家参与：仇恨记在对手身上（无论玩家胜负，双方都结下嫌隙）
        opponent = target if initiator == player else initiator
        if opponent and opponent != player:
            game_state.rivalries[opponent] = game_state.rivalries.get(opponent, 0) + (10 if opponent in game_state.rivalries else 15)
        return

    # NPC vs NPC：败者记恨胜者，胜者也留意败者
    for owner, foe, amount in ((loser, winner, 15), (winner, loser, 8)):
        npc = game_state.npcs.get(owner)
        if not isinstance(npc, dict) or not foe or foe == owner:
            continue
        rivals = npc.setdefault("npc_rivals", {})
        rivals[foe] = min(100, rivals.get(foe, 0) + amount)


def generate_palace_conflict(game_state, initiator=None, target=None, api_key=None, api_base=None, api_model=None, conflict_type=None, assist_servants=None):
    if initiator is None:
        all_names = [game_state.name] + [n for n in game_state.npcs.keys() if game_state.npcs[n].get("alive", True)]
        all_names = [n for n in all_names if n != "太后"]
        if not all_names:
            return None
        initiator = random.choice(all_names)
    all_names = [game_state.name] + [n for n in game_state.npcs.keys() if game_state.npcs[n].get("alive", True)]
    all_names = [n for n in all_names if n != "太后" and n != initiator]
    if not all_names:
        return None
    target = random.choice(all_names) if target is None else target
    type_aliases = {"造谣": "谣言", "掌嘴": "争辩"}
    if conflict_type:
        conflict_type = type_aliases.get(conflict_type, conflict_type)
    if conflict_type and conflict_type in CONFLICT_TYPES:
        pass
    else:
        conflict_type = random.choice(list(CONFLICT_TYPES.keys()))
    conflict_info = CONFLICT_TYPES[conflict_type]
    
    initiator_rank = game_state.rank.name if initiator == game_state.name else game_state.npcs.get(initiator, {}).get("rank", "妃嫔")
    target_rank = game_state.rank.name if target == game_state.name else game_state.npcs.get(target, {}).get("rank", "妃嫔")
    initiator_attrs = game_state.attributes if initiator == game_state.name else game_state.npcs.get(initiator, {}).get("attributes", {})
    target_attrs = game_state.attributes if target == game_state.name else game_state.npcs.get(target, {}).get("attributes", {})
    
    initiator_score = initiator_attrs.get("心计", 50) * 0.5 + initiator_attrs.get("宠爱", 30) * 0.3 + initiator_attrs.get("威望", 20) * 0.2
    target_score = target_attrs.get("心计", 50) * 0.5 + target_attrs.get("宠爱", 30) * 0.3 + target_attrs.get("威望", 20) * 0.2

    assist_bonus = 0.0
    assist_used = []
    if initiator == game_state.name and assist_servants:
        assist_bonus, assist_used = resolve_servant_assist(game_state, assist_servants, conflict_type)
        initiator_score += assist_bonus

    initiator_win = initiator_score > target_score
    flip_chance = 0.30
    if assist_bonus > 0:
        flip_chance = max(0.08, 0.30 - assist_bonus / 60.0)
    if random.random() < flip_chance:
        initiator_win = not initiator_win
    
    # ===== 尝试AI生成故事 =====
    narration = None
    try:
        if api_key and api_base and api_model and api_key.strip() and api_base.strip():
            client = get_openai_client(api_key, api_base)
            if client:
                model = api_model
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
                    timeout=10
                )
                narration = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"AI生成宫斗事件失败: {e}")
    
    if not narration or len(narration) < 10:
        from events import generate_conflict_fallback_narration
        narration = generate_conflict_fallback_narration(initiator, target)

    assist_notes = []
    if assist_used and initiator == game_state.name:
        assist_notes = apply_servant_assist_aftermath(assist_used, initiator_win)
        assist_names = "、".join(s.name for s in assist_used)
        narration = f"{narration} {assist_names}在暗中协助布置。"
    
    effects = _calc_conflict_effects(conflict_info, initiator_win)
    
    target_effects = {}
    if initiator == game_state.name:
        for attr, delta in effects.items():
            if attr in game_state.attributes:
                max_attr = game_state.get_attr_max(attr)
                game_state.attributes[attr] = max(0, min(max_attr, game_state.attributes[attr] + delta))
        if target in game_state.npcs:
            target_effects = _apply_npc_conflict_effects(game_state.npcs[target], effects, False)
    elif target == game_state.name:
        for attr, delta in effects.items():
            if attr in game_state.attributes:
                max_attr = game_state.get_attr_max(attr)
                game_state.attributes[attr] = max(0, min(max_attr, game_state.attributes[attr] - delta))
        if initiator in game_state.npcs:
            target_effects = _apply_npc_conflict_effects(game_state.npcs[initiator], effects, True)
    elif initiator in game_state.npcs and target in game_state.npcs:
        _apply_npc_conflict_effects(game_state.npcs[initiator], effects, True)
        target_effects = _apply_npc_conflict_effects(game_state.npcs[target], effects, False)

    poison_damage = 0
    if conflict_type == "下毒" and initiator_win and target in game_state.npcs:
        poison_damage = random.randint(25, 40)
        target_effects["健康"] = target_effects.get("健康", 0) - poison_damage
        target_npc = game_state.npcs[target]
        target_attrs = target_npc.setdefault("attributes", {})
        target_attrs["健康"] = max(0, target_attrs.get("健康", 60) - poison_damage)
        game_state.add_memory(f"{initiator}对{target}下毒，健康-{poison_damage}")

    # 玩家被下毒中招：与 NPC 同口径扣健康，为后续死亡判定提供依据
    player_poisoned_by = None
    if conflict_type == "下毒" and initiator_win and target == game_state.name:
        poison_damage = random.randint(25, 40)
        game_state.attributes["健康"] = max(0, game_state.attributes.get("健康", 60) - poison_damage)
        player_poisoned_by = initiator
        game_state.add_memory(f"{initiator}对你下毒，健康-{poison_damage}")

    # ---- 仇恨归属 ----
    # rivalries 是「玩家与他人」的仇恨表，只有玩家参与的宫斗才应写入；
    # NPC 之间的争斗记在双方 NPC 自己的 npc_rivals 上，避免误加到主控角色头上。
    _record_conflict_rivalry(game_state, initiator, target, initiator_win)

    demotion_message = None
    npc_demotion_message = None
    depose_queen_message = None
    death_message = None
    player_ending = None
    player_lost = (initiator == game_state.name and not initiator_win) or (target == game_state.name and initiator_win)
    player_won = not player_lost and (initiator == game_state.name or target == game_state.name)
    if player_lost:
        opponent = target if initiator == game_state.name else initiator
        demotion_message = try_conflict_demotion(game_state, True, conflict_type, opponent)
        if demotion_message:
            game_state.attributes["宠爱"] = max(0, game_state.attributes.get("宠爱", 0) - random.randint(8, 18))
            game_state.attributes["威望"] = max(0, game_state.attributes.get("威望", 0) - random.randint(5, 12))
        # 中毒濒危时可能当场毙命
        if player_poisoned_by:
            player_ending = check_player_poison_death(game_state, player_poisoned_by)
    elif player_won:
        opponent = target if initiator == game_state.name else initiator
        game_state.scandal_strikes = max(0, getattr(game_state, "scandal_strikes", 0) - 1)
        depose_queen_message = try_conflict_depose_queen(game_state, opponent, conflict_type, True)
        if not depose_queen_message:
            npc_demotion_message = try_npc_conflict_demotion(game_state, opponent, conflict_type, True)
        if conflict_type == "下毒" and opponent in game_state.npcs:
            opponent_npc = game_state.npcs[opponent]
            opponent_health = opponent_npc.get("attributes", {}).get("健康", 60)
            # 下毒成功后不再是纯随机 6%；重伤或高心计下毒会落实为死亡。
            poison_kill_chance = 1.0 if opponent_health <= 20 else 0.45 + game_state.attributes.get("心计", 40) / 250
            if random.random() < min(0.85, poison_kill_chance):
                death_message = kill_consort(game_state, opponent, "中毒", killer=game_state.name)
            else:
                death_message = None
        else:
            death_message = try_conflict_death(game_state, opponent, game_state.name, conflict_type, True)
        if death_message:
            game_state.add_memory(death_message)

    player_win, player_effects = _player_conflict_view(initiator, target, effects, initiator_win, game_state)

    return {
        "type": conflict_type,
        "initiator": initiator,
        "target": target,
        "initiator_win": initiator_win,
        "player_win": player_win,
        "narration": narration,
        "effects": effects,
        "player_effects": player_effects,
        "target_effects": target_effects,
        "poison_damage": poison_damage,
        "rivalries": game_state.rivalries,
        "demotion_message": demotion_message,
        "npc_demotion_message": npc_demotion_message,
        "depose_queen_message": depose_queen_message,
        "death_message": death_message,
        "ending": player_ending,
        "game_over": bool(player_ending),
        "assist_servants": [{"name": s.name, "type": s.type} for s in assist_used],
        "assist_bonus": round(assist_bonus, 1),
        "assist_notes": assist_notes,
        "display_rank": game_state.get_display_rank(),
        "rank": game_state.rank.name,
    }

def try_npc_birth_promotion(game_state, npc):
    rank = normalize_rank_name(npc.get("rank", "答应"))
    if rank == "妃" and not npc.get("nobletitle"):
        return promote_npc_one_step(game_state, npc)
    if rank == "妃" and npc.get("nobletitle"):
        target = pick_available_four_consort(game_state)
        if not target or not npc_meets_rank_requirements(npc, target):
            return None
        return promote_npc_one_step(game_state, npc)
    next_rank = get_next_rank_name(rank)
    if not next_rank or not can_promote_to_rank(game_state, next_rank) or not npc_meets_rank_requirements(npc, next_rank):
        return None
    npc["rank"] = next_rank
    return next_rank

def promote_npc_one_step(game_state, npc):
    rank = normalize_rank_name(npc.get("rank", "答应"))
    if rank == "妃" and not npc.get("nobletitle"):
        four_chars = {c.replace("妃", "") for c in FOUR_CONSORTS}
        candidates = [t for t in NOBLETITLES if t not in four_chars]
        npc["nobletitle"] = random.choice(candidates or NOBLETITLES)
        return f"{npc['nobletitle']}妃"
    if rank == "妃" and npc.get("nobletitle"):
        target = pick_available_four_consort(game_state)
        if not target:
            return None
        npc["nobletitle"] = None
        npc["rank"] = target
        return target
    next_rank = get_next_rank_name(rank)
    if not next_rank:
        return None
    npc["rank"] = next_rank
    return next_rank

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
    rank_weights = {
        "宫女": 14, "更衣": 12, "官女子": 11, "秀女": 10, "答应": 9, "常在": 8,
        "贵人": 7, "才人": 5, "美人": 4, "婕妤": 3, "嫔": 2,
        "嫔": 2, "妃": 1,
        "淑妃": 1, "德妃": 1, "贤妃": 1, "宸妃": 1,
        "贵妃": 0, "皇贵妃": 0, "皇后": 0,
    }
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

def generate_all_npcs(count=10, surname=None):
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
                child_name = new_child_name(gender, npcs=npcs, surname=surname or "")
                age = round(random.randint(0, 36) / 12, 1)
                if "children" not in npc:
                    npc["children"] = []
                npc["children"].append({"name": child_name, "gender": gender, "age": age, "birth_day": random.randint(1,30), "birth_month": random.randint(1,12), "birth_year": 1, "trait": "🎀 襁褓" if age < 0.5 else ("🎂 周岁" if age < 1.5 else ("👶 幼童" if age < 3 else "🎓 启蒙")), "alive": True, "adopted_count": 0, "adopted": False, "birth_mother": npc["name"], "adoptive_mother": ""})
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
CHILD_TALENT_LABELS = ["平平无奇", "伶俐可爱", "聪慧过人", "天资卓绝", "龙凤之姿"]
CHILD_PERSONALITIES = ["活泼好动", "安静乖巧", "聪慧机敏", "倔强叛逆", "温顺可人"]
CHILD_MOODS = ["开心", "平静", "思念", "兴奋", "闷闷不乐"]
CHILD_MOOD_EMOJI = {"开心": "😊", "平静": "😌", "思念": "🥺", "兴奋": "🤩", "闷闷不乐": "😔", "生病": "🤒"}
STORY_THEMES = ["嫦娥奔月", "武松打虎", "孔融让梨", "司马光砸缸", "精卫填海", "牛郎织女"]
GRAB_ITEMS = ["书卷", "金印", "弓箭", "凤钗", "算盘", "绣球"]

# —— 子嗣过继配置 ——
ADOPT_MIN_RANK = "贵人"              # 收养他人子嗣所需最低位份
ADOPT_TARGET_MIN_RANK = "嫔"         # 接受送养（被托付）所需最低位份
ADOPT_MAX_AGE = 10                   # 可过继的最大年龄
ADOPT_MAX_CHILDREN = 3               # 每位妃嫔最多养育子嗣数
ADOPT_IN_COST = 40                   # 收养公主仪式银两
ADOPT_IN_COST_PRINCE = 60            # 收养皇子仪式银两
ADOPT_OUT_COST = 30                  # 送养公主仪式银两
ADOPT_OUT_COST_PRINCE = 50           # 送养皇子仪式银两
ADOPT_RETURN_COST = 20               # 归宗（送还生母）仪式银两
ADOPT_BACK_COST = 40                 # 接回亲生子嗣仪式银两
ADOPT_PRINCE_MIN_RANK = "嫔"         # 收养皇子所需最低位份
ADOPT_MAX_TRANSFERS = 3              # 同一子嗣一生最多被过继次数（防止无限倒手）
ADOPT_PRINCE_EMPEROR_FAVOR = 40      # 收养在册皇子需皇帝宠爱门槛（低于则有几率被驳回）
ADOPT_WANT_HINT_DAYS = 30            # 「有妃嫔想收养你的子嗣」提示的有效旬数


def count_living_children(children):
    return len([c for c in children if c.get("alive", True)])


def resolve_living_child(children, index):
    """按“在世子嗣”序号解析子嗣对象。
    前端展示时已过滤夭折子嗣，后端须同样基于在世列表解析，避免序号错位。
    返回 (child, 在原列表中的位置)；找不到返回 (None, -1)。
    """
    living = [c for c in (children or []) if c.get("alive", True)]
    if not (0 <= index < len(living)):
        return None, -1
    child = living[index]
    pos = next((i for i, c in enumerate(children) if c is child), -1)
    return child, pos


def receiver_keep_willingness(game_state, npc, child, rel_favor):
    """养母是否愿意放手让亲生子嗣被接回：返回 0~100 意愿度。"""
    rank = RANK_LEVELS.get(npc.get("rank", "答应"), 0)
    my_rank = RANK_LEVELS.get(game_state.rank.name, 0)
    base = 30 + rel_favor * 0.45 + (my_rank - rank) * 4
    n_children = count_living_children(npc.get("children", []))
    if child.get("gender") == "皇子":
        base -= 15
    if n_children >= 2:
        base += 12   # 子嗣充裕，易放手
    return max(5, min(100, base))


def adoption_willingness(game_state, npc, child):
    """生母/养母是否甘愿让出子嗣：返回 0~100 意愿度。"""
    if not npc.get("alive", True):
        return 100
    rel = game_state.relationships.get(npc.get("name", ""), {"好感": 0})
    favor = rel.get("好感", 0)
    mother_rank = RANK_LEVELS.get(npc.get("rank", "答应"), 0)
    my_rank = RANK_LEVELS.get(game_state.rank.name, 0)
    n_children = count_living_children(npc.get("children", []))
    w = 38 + favor * 0.55 - mother_rank * 0.3 + my_rank * 0.45 + n_children * 12
    if child.get("gender") == "皇子":
        w -= 22
    if npc.get("压力", 0) >= 70:
        w += 10   # 压力大，自顾不暇，更愿托付
    return max(0, min(100, w))


def receiver_willingness(game_state, npc, child):
    """高位妃嫔接受托付（收养玩家子嗣）的意愿 0~100。"""
    if not npc.get("alive", True):
        return 0
    rel = game_state.relationships.get(npc.get("name", ""), {"好感": 0})
    favor = rel.get("好感", 0)
    rank = RANK_LEVELS.get(npc.get("rank", "答应"), 0)
    base = 45 + favor * 0.35 + rank * 0.5
    n_children = count_living_children(npc.get("children", []))
    if n_children == 0:
        base += 20   # 膝下无子，求子心切
    elif n_children >= ADOPT_MAX_CHILDREN:
        base -= 30
    if npc.get("压力", 0) >= 75:
        base -= 18
    if child.get("gender") == "皇子":
        base += 10   # 皇子尊贵，更愿收养
    return max(5, min(100, base))


def count_living_children(children):
    return len([c for c in children if c.get("alive", True)])


def newborn_trait(gender):
    return "🍼 襁褓" if gender == "皇子" else "🎀 襁褓"


def child_mood_emoji(mood):
    return CHILD_MOOD_EMOJI.get(mood, "😌")


def add_child_event(child, text):
    events = child.setdefault("recent_events", [])
    events.insert(0, text)
    child["recent_events"] = events[:5]


def add_adoption_history(child, action, from_name=None, to_name=None, note=None, day=None):
    history = child.setdefault("adoption_history", [])
    entry = {
        "action": action,
        "from": from_name or "",
        "to": to_name or "",
        "note": note or "",
        "day": day,
    }
    history.insert(0, entry)
    child["adoption_history"] = history[:8]


def should_use_emperor_approval(game_state, child, direction):
    """皇子归属更敏感：需要更高宠爱/威望或随机得旨。"""
    if child.get("gender") != "皇子":
        return True, ""
    favor = game_state.attributes.get("宠爱", 0)
    prestige = game_state.attributes.get("威望", 0)
    score = favor * 0.55 + prestige * 0.25 + random.randint(0, 35)
    if direction == "in":
        if score >= 55:
            return True, "皇帝允准"
        if score >= 42 and random.random() < 0.55:
            return True, "皇帝略有迟疑，仍准你收养"
        return False, "皇帝顾虑皇子去向，暂不允准"
    if score >= 48:
        return True, "皇帝首肯"
    if score >= 35 and random.random() < 0.45:
        return True, "皇帝念其前程，勉强首肯"
    return False, "皇帝不许皇子轻易归宗"


def child_adoption_pressure(child, base=0):
    age = int(child.get("age", 0) or 0)
    health = int(child.get("health", 70) or 0)
    affection = int(child.get("affection", 35) or 0)
    return base + max(0, age - 2) * 2 + max(0, 55 - health) // 4 - max(0, affection - 35) // 8


def ensure_child_fields(child):
    """补全子嗣字段（兼容旧存档）。"""
    child.setdefault("affection", random.randint(20, 50))
    child.setdefault("talent", random.randint(30, 70))
    child.setdefault("health", random.randint(65, 90))
    child.setdefault("wit", random.randint(25, 60))
    child.setdefault("emperor_favor", random.randint(15, 40))
    child.setdefault("tutor_level", 0)
    child.setdefault("personality", random.choice(CHILD_PERSONALITIES))
    child.setdefault("mood", random.choice(["平静", "开心"]))
    child.setdefault("recent_events", [])
    child.setdefault("alive", True)              # 是否在世
    child.setdefault("adopted_count", 0)          # 被过继次数
    child.setdefault("adopted", False)            # 是否为过继子嗣
    child.setdefault("birth_mother", "")          # 生母
    child.setdefault("adoptive_mother", "")       # 养母
    child.setdefault("adoption_history", [])
    child.setdefault("needs_doctor", child.get("health", 70) < 45)
    child.setdefault("want_return_home", False)
    child.setdefault("honorary_title", None)   # 徽号
    child.setdefault("palace", "")             # 所居宫殿
    child.setdefault("uid", None)              # 唯一标识
    return child

def child_talent_label(talent):
    t = int(talent or 50)
    if t >= 85:
        return CHILD_TALENT_LABELS[4]
    if t >= 70:
        return CHILD_TALENT_LABELS[3]
    if t >= 55:
        return CHILD_TALENT_LABELS[2]
    if t >= 40:
        return CHILD_TALENT_LABELS[1]
    return CHILD_TALENT_LABELS[0]

def royal_surname(game_state=None, emperor=None):
    """取国姓（皇帝姓氏）。取不到时返回空串，调用方退化为无姓。"""
    emp = emperor if isinstance(emperor, dict) else getattr(game_state, "emperor", None)
    if not isinstance(emp, dict):
        return ""
    emp_name = (emp.get("name") or "").strip()
    if not emp_name:
        return ""
    surname = extract_surname(emp_name)
    return "" if surname in ("", "某") else surname


def collect_used_child_names(game_state=None, npcs=None, extra=None):
    """汇总宫中已占用的皇嗣名（含玩家与所有妃嫔，含已故），用于避免重名。"""
    used = set()

    def _absorb(children):
        for child in children or []:
            if isinstance(child, dict):
                name = (child.get("name") or "").strip()
            else:
                name = str(child or "").strip()
            if name:
                used.add(name)

    if game_state is not None:
        _absorb(getattr(game_state, "children", None))
        for npc in (getattr(game_state, "npcs", None) or {}).values():
            if isinstance(npc, dict):
                _absorb(npc.get("children"))
    for npc in (npcs or {}).values():
        if isinstance(npc, dict):
            _absorb(npc.get("children"))
    for name in extra or []:
        if name:
            used.add(str(name).strip())
    return used


def new_child_name(gender, game_state=None, npcs=None, surname=None, extra_used=None):
    """生成不与宫中现有皇嗣重名的「国姓+名」。"""
    if surname is None:
        surname = royal_surname(game_state)
    used = collect_used_child_names(game_state, npcs, extra_used)
    return generate_child_name(gender, used=used, surname=surname)


CHILD_NAME_MAX_LEN = 6
_CHILD_NAME_RE = re.compile(r"^[\u4e00-\u9fa5]{1,%d}$" % CHILD_NAME_MAX_LEN)


def validate_child_name(raw_name, game_state, current_name=None):
    """校验并规范玩家自定义的皇嗣名。返回 (完整名, error)。

    输入允许只写名（自动补国姓）或已带国姓；长度按「去掉国姓后的名」计算。
    """
    name = (raw_name or "").strip()
    if not name:
        return None, "请输入名字"
    surname = royal_surname(game_state)
    given = name[len(surname):] if surname and name.startswith(surname) else name
    if not _CHILD_NAME_RE.match(given):
        return None, f"名字须为 1-{CHILD_NAME_MAX_LEN} 个汉字"
    full = (surname + given) if surname else given
    used = collect_used_child_names(game_state)
    if current_name:
        used.discard(current_name)
    if full in used:
        return None, f"宫中已有皇嗣名为「{full}」，请另择"
    return full, None


def create_newborn_child(gender, name, game_state, mother_name=None):
    child = {
        "name": name,
        "gender": gender,
        "age": 0,
        "birth_day": game_state.day,
        "birth_month": game_state.month,
        "birth_year": game_state.year,
        "trait": newborn_trait(gender),
        "affection": random.randint(35, 55),
        "talent": random.randint(40, 75),
        "health": random.randint(70, 95),
        "wit": random.randint(20, 50),
        "emperor_favor": random.randint(20, 45),
        "tutor_level": 0,
        "personality": random.choice(CHILD_PERSONALITIES),
        "mood": random.choice(["平静", "开心"]),
        "recent_events": [],
        "alive": True,
        "adopted_count": 0,
        "adopted": False,
        "birth_mother": mother_name or game_state.name,
        "adoptive_mother": "",
    }
    return child

def process_child_milestones(child, prefix, game_state=None):
    """处理子嗣成长节点，返回事件消息列表。game_state 不为 None 时为玩家子嗣，会发放属性奖励。"""
    events = []
    age_years = int(child.get("age", 0))
    child_name = child.get("name", "未命名")
    gender = child.get("gender", "")
    if age_years == 0 and child.get("age", 0) >= 0.25 and not child.get("full_month", False):
        child["full_month"] = True
        events.append(f"🎊 {prefix}{gender} {child_name} 满月，御赐金锁银项圈，宫中设宴庆贺！")
        child["health"] = min(100, child.get("health", 70) + 2)
        if game_state:
            game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + 2)
    elif age_years == 1 and not child.get("first_birthday", False):
        child["first_birthday"] = True
        child["trait"] = "🎂 周岁"
        grab = random.choice(GRAB_ITEMS)
        child["grab_item"] = grab
        grab_hints = {
            "书卷": "将来定是饱学之士",
            "金印": "将来贵不可言，或掌权柄",
            "弓箭": "将来将成沙场猛将",
            "凤钗": "将来姻缘尊贵，荣华加身",
            "算盘": "将来精于理财，家宅兴旺",
            "绣球": "将来姻缘美满，蕙质兰心",
        }
        hint = grab_hints.get(grab, "前途不可限量")
        events.append(f"🎂 {prefix}{gender} {child_name} 满周岁，抓周宴上竟一把抓住「{grab}」，众人皆道：{hint}！")
        if game_state:
            game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 3)
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
        child["wit"] = min(100, child.get("wit", 30) + random.randint(5, 12))
        events.append(f"📚 {prefix}{gender} {child_name} 开始启蒙，{child['education']}！")
    elif age_years == 8 and not child.get("eight_years", False):
        child["eight_years"] = True
        child["talent"] = min(100, child.get("talent", 50) + random.randint(3, 8))
        events.append(f"🎋 {prefix}{gender} {child_name} 八岁进学，{child_talent_label(child['talent'])}！")
        if game_state:
            game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes["威望"] + 3)
    elif age_years == 10 and not child.get("ten_years", False):
        child["ten_years"] = True
        if gender == "皇子":
            child["title"] = random.choice(["雍王", "晋王", "楚王", "齐王"])
            events.append(f"🏛️ {prefix}皇子 {child_name} 十岁开府，封 {child['title']}！")
            child["emperor_favor"] = min(100, child.get("emperor_favor", 30) + random.randint(5, 12))
        else:
            events.append(f"🌸 {prefix}公主 {child_name} 十岁及笄预备，宫中瞩目。")
            child["emperor_favor"] = min(100, child.get("emperor_favor", 30) + random.randint(3, 8))
        if game_state:
            game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes["宠爱"] + 5)
    elif age_years == 12 and not child.get("twelve_years", False):
        child["twelve_years"] = True
        boost = random.randint(8, 15)
        child["wit"] = min(100, child.get("wit", 40) + boost)
        if gender == "皇子" and child.get("emperor_favor", 0) >= 60:
            events.append(f"📜 朝臣奏称 {child_name} 聪慧贤德，有储君之相！")
            if game_state:
                game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes["威望"] + 12)
        else:
            events.append(f"✨ {prefix}{gender} {child_name} 十二岁才名初显，学识精进！")
    return events

def process_player_child_events(game_state):
    """转旬时玩家子嗣随机动态。"""
    events = []
    children = game_state.children
    for child in children:
        ensure_child_fields(child)
        age = int(child.get("age", 0))
        name = child.get("name", "皇嗣")
        gender = child.get("gender", "")

        # 病危夭折：健康极低且年幼时小概率夭折
        if age <= 6 and not child.get("alive", True) is False:
            hp = child.get("health", 70)
            if hp < 25 and random.random() < 0.10:
                child["alive"] = False
                child["trait"] = "🕯️ 夭折"
                child["mood"] = "平静"
                msg = f"🕯️ {name} 病势沉重，太医回天乏术，竟夭折了……"
                events.append(msg)
                add_child_event(child, msg)
                game_state.attributes["健康"] = max(0, game_state.attributes.get("健康", 80) - 10)
                game_state.attributes["宠爱"] = max(0, game_state.attributes.get("宠爱", 30) - 5)
                game_state.add_memory(msg)
                continue

        # 心情自然变化
        if random.random() < 0.15:
            if child.get("health", 70) < 50:
                child["mood"] = "生病"
            elif child.get("affection", 30) < 35:
                child["mood"] = random.choice(["思念", "闷闷不乐"])
            else:
                child["mood"] = random.choice(["开心", "平静", "兴奋"])
        if age < 1 or random.random() > 0.28:
            continue
        roll = random.random()
        is_adopted = child.get("adopted", False)
        if is_adopted and (roll < 0.15 or (child.get("adoptive_mother") == game_state.name and random.random() < 0.6)):
            # 过继子嗣特殊事件
            birth_mother = child.get("birth_mother") or "生母"
            if random.random() < 0.5:
                gain = random.randint(3, 8)
                child["affection"] = min(100, child.get("affection", 30) + gain)
                child["mood"] = "开心"
                msg = f"💕 {name} 依偎在你膝下，怯生生唤了声「母妃」，惹人怜爱，亲密度+{gain}"
            else:
                loss = random.randint(1, 4)
                child["affection"] = max(10, child.get("affection", 30) - loss)
                child["mood"] = "思念"
                msg = f"🥺 {name} 望着远处出神，低声呢喃着{birth_mother}，亲密度-{loss}"
            events.append(msg)
            add_child_event(child, msg)
        elif roll < 0.22:
            gain = random.randint(3, 8)
            child["emperor_favor"] = min(100, child.get("emperor_favor", 30) + gain)
            child["mood"] = "兴奋"
            msg = f"👑 皇帝夸赞{name}，恩宠+{gain}"
            events.append(msg)
            add_child_event(child, msg)
            game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + 2)
        elif roll < 0.38:
            loss = random.randint(2, 6)
            child["health"] = max(20, child.get("health", 70) - loss)
            child["mood"] = "生病"
            msg = f"🤒 {name} 略感不适，健康-{loss}，需多加照料"
            events.append(msg)
            add_child_event(child, msg)
        elif roll < 0.55:
            gain = random.randint(2, 5)
            child["affection"] = min(100, child.get("affection", 30) + gain)
            child["mood"] = "开心"
            msg = f"💕 {name} 近日格外依恋你，亲密度+{gain}"
            events.append(msg)
            add_child_event(child, msg)
        elif roll < 0.68 and gender == "皇子":
            gain = random.randint(2, 6)
            child["wit"] = min(100, child.get("wit", 40) + gain)
            msg = f"📖 师傅称赞{name}进学刻苦，学识+{gain}"
            events.append(msg)
            add_child_event(child, msg)
        elif roll < 0.78 and len(children) >= 2:
            sibling = random.choice([c for c in children if c is not child])
            sib_name = sibling.get("name", "手足")
            if random.random() < 0.5:
                gain = random.randint(2, 5)
                child["affection"] = min(100, child.get("affection", 30) + gain)
                sibling["affection"] = min(100, sibling.get("affection", 30) + gain)
                msg = f"👫 {name}与{sib_name}一同嬉戏，手足情深"
            else:
                loss = random.randint(1, 3)
                child["health"] = max(25, child.get("health", 70) - loss)
                child["mood"] = "闷闷不乐"
                msg = f"😤 {name}与{sib_name}争抢玩具，闹了小别扭"
            events.append(msg)
            add_child_event(child, msg)
        elif roll < 0.88 and child.get("personality") == "聪慧机敏":
            gain = random.randint(3, 7)
            child["wit"] = min(100, child.get("wit", 40) + gain)
            msg = f"💡 {name}忽发奇问，令太傅称奇，学识+{gain}"
            events.append(msg)
            add_child_event(child, msg)
        else:
            gain = random.randint(1, 4)
            child["talent"] = min(100, child.get("talent", 50) + gain)
            msg = f"🌟 {name} 展露{child_talent_label(child['talent'])}之姿"
            events.append(msg)
            add_child_event(child, msg)
    return events

def maybe_child_bonus_event(game_state, child, child_name):
    """互动时小概率触发额外事件，返回附加叙述或空串。"""
    if random.random() > 0.12:
        return ""
    roll = random.random()
    if roll < 0.35:
        gain = random.randint(4, 10)
        child["emperor_favor"] = min(100, child.get("emperor_favor", 30) + gain)
        pf = random.randint(2, 5)
        game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + pf)
        msg = f"皇帝恰好路过，见{child_name}乖巧可爱，龙颜大悦，圣宠+{gain}"
        add_child_event(child, f"👑 {msg}")
        return f"【意外之喜】{msg}，你的宠爱+{pf}"
    if roll < 0.6:
        gain = random.randint(2, 6)
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + gain)
        msg = f"太后听闻你悉心教养{child_name}，特赐褒奖"
        add_child_event(child, f"👵 {msg}")
        return f"【太后恩典】{msg}，威望+{gain}"
    gain = random.randint(3, 8)
    child["affection"] = min(100, child.get("affection", 30) + gain)
    msg = f"{child_name}扑进你怀中，一声「母妃」叫得你心都化了"
    add_child_event(child, f"💕 {msg}")
    return f"【温情时刻】{msg}，亲密度+{gain}"

PLAYER_MIN_AGE = 16
PLAYER_MAX_CREATE_AGE = 40


def clamp_age(value, default, minimum=12, maximum=80):
    try:
        age = int(value)
    except (TypeError, ValueError):
        age = default
    return max(minimum, min(maximum, age))


def ensure_character_ages(game_state):
    game_state.age = clamp_age(getattr(game_state, "age", PLAYER_MIN_AGE), PLAYER_MIN_AGE, PLAYER_MIN_AGE)
    if not isinstance(getattr(game_state, "emperor", None), dict):
        game_state.emperor = {}
    game_state.emperor["age"] = clamp_age(game_state.emperor.get("age"), random.randint(25, 55), 18, 80)
    for name, npc in game_state.npcs.items():
        rank = npc.get("rank", "")
        if name == "太后" or rank == "太后":
            npc["age"] = clamp_age(npc.get("age"), random.randint(45, 65), 35, 90)
        else:
            npc["age"] = clamp_age(npc.get("age"), random.randint(PLAYER_MIN_AGE, 32), PLAYER_MIN_AGE, 80)


# ---- 立储/继承/宫殿/徽号 辅助函数 ----

PALACE_LIST = ["长春宫", "钟粹宫", "承乾宫", "翊坤宫", "永寿宫", "储秀宫", "咸福宫", "景仁宫", "永和宫", "景阳宫"]

def is_child_heir(game_state, child_name_or_mother_name):
    """判断某妃嫔的子嗣是否被立为储君；若传入妃嫔名，检查其子嗣。"""
    heir_id = (game_state.heir_status or {}).get("heir_id")
    if not heir_id:
        return False
    # 检查玩家子嗣中是否有储君
    for c in game_state.children:
        if c.get("uid") == heir_id or c.get("name") == heir_id:
            return True
    # 检查 NPC 子嗣中是否有储君
    npc = game_state.npcs.get(child_name_or_mother_name)
    if npc:
        for c in npc.get("children", []):
            if c.get("uid") == heir_id or c.get("name") == heir_id:
                return True
    return False

def get_heir_child(game_state):
    """返回储君子嗣对象（dict）或 None。"""
    heir_id = (game_state.heir_status or {}).get("heir_id")
    if not heir_id:
        return None
    for c in game_state.children:
        if c.get("uid") == heir_id or c.get("name") == heir_id:
            return c
    for name, npc in game_state.npcs.items():
        for c in npc.get("children", []):
            if c.get("uid") == heir_id or c.get("name") == heir_id:
                return c
    return None

def get_heir_mother_name(game_state):
    """返回储君生母/养母的名称。"""
    child = get_heir_child(game_state)
    if not child:
        return ""
    return child.get("adoptive_mother") or child.get("birth_mother") or ""

def find_child_by_uid(game_state, uid):
    """在所有子嗣中按 uid 查找。"""
    for c in game_state.children:
        if c.get("uid") == uid:
            return c, "player", len(game_state.children)
    for name, npc in game_state.npcs.items():
        for i, c in enumerate(npc.get("children", [])):
            if c.get("uid") == uid:
                return c, name, i
    return None, None, None

def serialize_npcs_for_client(game_state):
    result = {}
    for name, npc in game_state.npcs.items():
        if name == "太后":
            continue
        result[name] = {
            "name": name,
            "rank": npc.get("rank", "妃嫔"),
            "age": clamp_age(npc.get("age"), random.randint(PLAYER_MIN_AGE, 32), PLAYER_MIN_AGE, 80),
            "personality": npc.get("personality", "未知"),
            "icon": npc.get("icon", "🌸"),
            "children": npc.get("children", []),
            "is_pregnant": npc.get("is_pregnant", False),
            "pregnancy_month": npc.get("pregnancy_month", 0),
            "attributes": npc.get("attributes", {}),
            "family_background": npc.get("family_background", ""),
            "nobletitle": npc.get("nobletitle", None),
            "honorary_title": npc.get("honorary_title", None),
            "palace": npc.get("palace", ""),
            "is_heir": is_child_heir(game_state, name),
            "压力": npc.get("压力", 0),
            "alive": npc.get("alive", True),
            "is_active": npc.get("is_active", True),
            "death_cause": npc.get("death_cause"),
            "death_period": npc.get("death_period"),
        }
    return result

def get_intrigue_state(game_state):
    intrigue = getattr(game_state, "intrigue", None)
    if not isinstance(intrigue, dict):
        intrigue = {"heat": 0, "rumors": [], "dirt": {}, "last_action": None}
        game_state.intrigue = intrigue
    intrigue.setdefault("heat", 0)
    intrigue.setdefault("rumors", [])
    intrigue.setdefault("dirt", {})
    intrigue.setdefault("last_action", None)
    return intrigue


def summarize_intrigue(game_state):
    intrigue = get_intrigue_state(game_state)
    active_rumors = [r for r in intrigue.get("rumors", []) if isinstance(r, dict)]
    dirt_map = intrigue.get("dirt", {}) if isinstance(intrigue.get("dirt"), dict) else {}
    top_targets = []
    for name, payload in dirt_map.items():
        if not isinstance(payload, dict):
            continue
        score = int(payload.get("points", 0) or 0)
        if score > 0:
            top_targets.append({"name": name, "points": score, "label": payload.get("label") or "把柄"})
    top_targets.sort(key=lambda item: item["points"], reverse=True)
    return {
        "heat": max(0, int(intrigue.get("heat", 0) or 0)),
        "rumor_count": len(active_rumors),
        "dirt_count": len(top_targets),
        "top_dirt": top_targets[:3],
        "last_action": intrigue.get("last_action"),
        "rumors": active_rumors[:5],
    }


def _clamp_attr(game_state, attr_name, delta):
    current = game_state.attributes.get(attr_name, 0)
    max_val = game_state.get_attr_max(attr_name)
    updated = max(0, min(max_val, current + delta))
    game_state.attributes[attr_name] = updated
    return updated - current


def _touch_relation(game_state, target_name, delta=0, impression=None):
    rel = game_state.relationships.setdefault(target_name, {"好感": 0, "印象": "陌生", "互动次数": 0})
    rel["互动次数"] = rel.get("互动次数", 0) + 1
    if delta:
        rel["好感"] = max(-100, min(100, rel.get("好感", 0) + delta))
    if impression:
        rel["印象"] = impression
    return rel


def _append_intrigue_rumor(game_state, rumor):
    intrigue = get_intrigue_state(game_state)
    rumors = intrigue.setdefault("rumors", [])
    rumors.insert(0, rumor)
    if len(rumors) > 12:
        del rumors[12:]


def process_intrigue_period(game_state):
    intrigue = get_intrigue_state(game_state)
    period_events = []
    rumors = intrigue.get("rumors", [])
    kept_rumors = []
    for rumor in rumors:
        if not isinstance(rumor, dict):
            continue
        rumor["turns_left"] = int(rumor.get("turns_left", 0) or 0) - 1
        target = rumor.get("target") or "宫中某人"
        severity = int(rumor.get("severity", 1) or 1)
        if random.random() < min(0.78, 0.22 + severity * 0.08):
            if rumor.get("type") == "player":
                favor_loss = _clamp_attr(game_state, "宠爱", -random.randint(1, 2 + severity))
                prestige_loss = _clamp_attr(game_state, "威望", -random.randint(1, 3 + severity))
                intrigue["heat"] = min(100, intrigue.get("heat", 0) + 2)
                period_events.append(f"🕸️ 关于你的流言仍在蔓延，宠爱{favor_loss}，威望{prestige_loss}")
            else:
                npc = game_state.npcs.get(target)
                if npc and npc.get("alive", True):
                    attrs = npc.setdefault("attributes", {})
                    attrs["宠爱"] = max(0, attrs.get("宠爱", 30) - random.randint(1, 2 + severity))
                    attrs["威望"] = max(0, attrs.get("威望", 20) - random.randint(1, 2 + severity))
                    period_events.append(f"🕸️ {target}被流言所困，圣心与人望皆受损。")
        if rumor["turns_left"] > 0:
            kept_rumors.append(rumor)
    intrigue["rumors"] = kept_rumors
    dirt_map = intrigue.get("dirt", {}) if isinstance(intrigue.get("dirt"), dict) else {}
    for payload in dirt_map.values():
        if not isinstance(payload, dict):
            continue
        payload["age"] = int(payload.get("age", 0) or 0) + 1
        if payload["age"] > 6 and payload.get("points", 0) > 0:
            payload["points"] = max(0, int(payload.get("points", 0)) - 1)
    if intrigue.get("heat", 0) > 0:
        intrigue["heat"] = max(0, intrigue.get("heat", 0) - 1)
    return period_events


def get_intrigue_targets(game_state):
    intrigue = get_intrigue_state(game_state)
    dirt_map = intrigue.get("dirt", {}) if isinstance(intrigue.get("dirt"), dict) else {}
    targets = []
    for name, npc in game_state.npcs.items():
        if name == "太后" or not npc.get("alive", True):
            continue
        attrs = npc.get("attributes", {})
        dirt_payload = dirt_map.get(name, {}) if isinstance(dirt_map.get(name), dict) else {}
        targets.append({
            "name": name,
            "rank": npc.get("rank", "妃嫔"),
            "icon": npc.get("icon", "🌸"),
            "favor": int(attrs.get("宠爱", 0) or 0),
            "prestige": int(attrs.get("威望", 0) or 0),
            "dirt_points": int(dirt_payload.get("points", 0) or 0),
            "dirt_label": dirt_payload.get("label") or "暂无把柄",
        })
    targets.sort(key=lambda item: (-item["dirt_points"], -item["favor"], item["name"]))
    return targets



def handle_intrigue_action(game_state, action, target_name=None):
    intrigue = get_intrigue_state(game_state)
    dirt_map = intrigue.setdefault("dirt", {})
    action_defs = {
        "spy": {"cost": 12, "label": "刺探"},
        "rumor": {"cost": 18, "label": "放流言"},
        "blackmail": {"cost": 0, "label": "勒索"},
        "cleanse": {"cost": 15, "label": "洗白"},
    }
    if action not in action_defs:
        return None, "无效行动"

    target = None
    if action != "cleanse":
        target = game_state.npcs.get(target_name)
        if not target or not target.get("alive", True):
            return None, "目标不存在或已失势"
        if target_name == "太后":
            return None, "太后耳目众多，不宜轻动"

    silver_cost = action_defs[action]["cost"]
    if silver_cost > 0 and game_state.silver < silver_cost:
        return None, f"银两不足，需要{silver_cost}两"

    player_scheme = int(game_state.attributes.get("谋略", 0) or 0)
    player_mind = int(game_state.attributes.get("心计", 0) or 0)
    player_prestige = int(game_state.attributes.get("威望", 0) or 0)
    heat = int(intrigue.get("heat", 0) or 0)
    effects = {}
    events = []
    success = False
    message = ""
    silver_change = 0

    if action == "spy":
        if player_scheme < 15:
            return None, "谋略不足，难以布下耳目"
        chance = max(0.18, min(0.88, 0.38 + player_scheme / 180 + player_mind / 240 - heat / 220))
        if random.random() < chance:
            success = True
            gain = random.randint(1, 2) + (1 if player_scheme >= 70 or random.random() < 0.22 else 0)
            payload = dirt_map.setdefault(target_name, {"points": 0, "age": 0, "label": "私下错处"})
            payload["points"] = min(9, int(payload.get("points", 0) or 0) + gain)
            payload["age"] = 0
            payload["label"] = random.choice(["私相授受", "失仪把柄", "账目漏洞", "口舌错处"])
            intrigue["heat"] = min(100, heat + random.randint(2, 5))
            _touch_relation(game_state, target_name, -random.randint(1, 4), "似有戒备")
            message = f"你安插耳目探查{target_name}，握住了{gain}点把柄。"
            events.append(f"🕵️ 你探得{target_name}的{payload['label']}，可供日后拿捏。")
        else:
            intrigue["heat"] = min(100, heat + random.randint(5, 9))
            effects["威望"] = _clamp_attr(game_state, "威望", -random.randint(1, 3))
            _touch_relation(game_state, target_name, -random.randint(3, 7), "察觉你的试探")
            message = f"你派去的人手露了行迹，{target_name}起了疑心。"
            events.append(f"⚠️ {target_name}似乎察觉有人窥探，宫中风声顿紧。")
    elif action == "rumor":
        if player_mind < 18:
            return None, "心计不足，流言难成局"
        payload = dirt_map.get(target_name, {}) if isinstance(dirt_map.get(target_name), dict) else {}
        dirt_bonus = int(payload.get("points", 0) or 0)
        chance = max(0.15, min(0.9, 0.32 + player_mind / 190 + min(0.22, dirt_bonus * 0.06) - heat / 260))
        severity = max(1, min(4, 1 + dirt_bonus // 2 + (1 if player_prestige >= 60 else 0)))
        if random.random() < chance:
            success = True
            if dirt_bonus > 0:
                payload["points"] = max(0, dirt_bonus - 1)
            _append_intrigue_rumor(game_state, {
                "target": target_name,
                "type": "npc",
                "severity": severity,
                "turns_left": random.randint(2, 4),
                "text": f"{target_name}卷入{payload.get('label') or '失德风波'}",
            })
            intrigue["heat"] = min(100, heat + random.randint(4, 8))
            effects["宠爱"] = _clamp_attr(game_state, "宠爱", random.randint(0, 2))
            effects["威望"] = _clamp_attr(game_state, "威望", random.randint(1, 4))
            _touch_relation(game_state, target_name, -random.randint(4, 8), "对你心生怨怼")
            message = f"你借风放出关于{target_name}的流言，宫中议论纷纷。"
            events.append(f"🗣️ 流言已起：{target_name}短期内会受人非议。")
        else:
            intrigue["heat"] = min(100, heat + random.randint(6, 10))
            _append_intrigue_rumor(game_state, {
                "target": game_state.name,
                "type": "player",
                "severity": random.randint(1, 2),
                "turns_left": random.randint(2, 3),
                "text": "你搬弄是非反遭反噬",
            })
            effects["威望"] = _clamp_attr(game_state, "威望", -random.randint(2, 5))
            message = f"你布下的流言被人反咬，脏水泼回了自己身上。"
            events.append("🪤 流言反噬，你自己成了闲话中心。")
    elif action == "blackmail":
        payload = dirt_map.get(target_name, {}) if isinstance(dirt_map.get(target_name), dict) else {}
        dirt_points = int(payload.get("points", 0) or 0)
        if dirt_points < 2:
            return None, "把柄不足，难以逼迫对方就范"
        chance = max(0.2, min(0.92, 0.34 + player_mind / 210 + dirt_points * 0.08 + player_prestige / 320 - heat / 300))
        if random.random() < chance:
            success = True
            gain_silver = random.randint(12, 24) + dirt_points * random.randint(3, 5)
            game_state.silver += gain_silver
            silver_change += gain_silver
            payload["points"] = max(0, dirt_points - random.randint(1, 2))
            payload["age"] = 0
            intrigue["heat"] = min(100, heat + random.randint(5, 9))
            effects["威望"] = _clamp_attr(game_state, "威望", random.randint(1, 3))
            _touch_relation(game_state, target_name, -random.randint(6, 12), "对你又惧又恨")
            message = f"你以把柄逼迫{target_name}低头，对方送来银两息事宁人。"
            events.append(f"💰 {target_name}被你拿住命门，暗中送来{gain_silver}两银子。")
        else:
            payload["points"] = max(0, dirt_points - 1)
            intrigue["heat"] = min(100, heat + random.randint(8, 12))
            effects["威望"] = _clamp_attr(game_state, "威望", -random.randint(2, 4))
            _touch_relation(game_state, target_name, -random.randint(8, 14), "恨意难消")
            if random.random() < 0.45:
                _append_intrigue_rumor(game_state, {
                    "target": game_state.name,
                    "type": "player",
                    "severity": random.randint(1, 3),
                    "turns_left": random.randint(2, 4),
                    "text": f"你勒索{target_name}的风声走漏",
                })
                events.append("🪤 勒索未成，风声外泄，你反被宫人侧目。")
            else:
                events.append(f"⚠️ {target_name}强压怒火，你的威逼并未奏效。")
            message = f"{target_name}没有就范，还设法反咬了你一口。"
    elif action == "cleanse":
        player_rumors = [r for r in intrigue.get("rumors", []) if isinstance(r, dict) and r.get("type") == "player"]
        if heat <= 0 and not player_rumors:
            return None, "眼下并无需要洗白的风波"
        chance = max(0.22, min(0.93, 0.36 + player_prestige / 180 + player_mind / 260 - heat / 240))
        if random.random() < chance:
            success = True
            removed = 0
            kept_rumors = []
            for rumor in intrigue.get("rumors", []):
                if isinstance(rumor, dict) and rumor.get("type") == "player" and removed < 2:
                    removed += 1
                    continue
                kept_rumors.append(rumor)
            intrigue["rumors"] = kept_rumors
            intrigue["heat"] = max(0, heat - random.randint(8, 16))
            effects["威望"] = _clamp_attr(game_state, "威望", random.randint(1, 4))
            if removed:
                message = f"你上下打点、澄清风声，暂时压下了{removed}条针对你的流言。"
                events.append(f"🪶 你成功洗白名声，宫中关于你的闲话散去了{removed}桩。")
            else:
                message = "你花银两安抚宫人、打点关系，总算先把热度压了下去。"
                events.append("🪶 你花钱平事，宫中视线暂时从你身上移开。")
        else:
            intrigue["heat"] = max(0, heat - random.randint(1, 4))
            effects["威望"] = _clamp_attr(game_state, "威望", -random.randint(1, 3))
            message = "你试图洗白，却被人讥作欲盖弥彰。"
            events.append("😓 你出面辟谣反惹议论，虽稍稍降温，名声仍受拖累。")

    if silver_cost > 0:
        game_state.silver -= silver_cost
        silver_change -= silver_cost

    if silver_change:
        effects["银两"] = silver_change
    intrigue["last_action"] = {
        "action": action,
        "label": action_defs[action]["label"],
        "target": target_name,
        "success": success,
        "calendar": game_state.get_calendar_str(),
    }
    game_state.add_memory(message)
    game_state.add_attr_change({k: v for k, v in effects.items() if k in game_state.attributes}, f"情报行动：{action_defs[action]['label']}")
    return {
        "success": True,
        "action": action,
        "action_label": action_defs[action]["label"],
        "target": target_name,
        "narration": message,
        "effects": effects,
        "silver_change": silver_change,
        "intrigue": summarize_intrigue(game_state),
        "intrigue_events": events,
    }, None


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
        if name == game_state.name or name == "太后" or npc.get("rank") == "皇后":
            continue
        if not npc.get("alive", True):
            continue
        if npc.get("is_pregnant", False):
            event_happened, event_type = update_npc_pregnancy(npc, game_state.day)
            if event_happened:
                if event_type == "流产":
                    pregnancy_events.append(f"🌧️ {name} 不幸小产...")
                    if name in game_state.relationships:
                        game_state.relationships[name]["好感"] = max(-100, game_state.relationships[name]["好感"] - 8)
                    npc["attributes"]["健康"] = max(0, npc["attributes"]["健康"] - 10)
                    death_msg = try_childbirth_death(game_state, name, survived_child=False)
                    if death_msg:
                        pregnancy_events.append(death_msg)
                elif event_type == "生产":
                    gender = random.choice(["皇子", "公主"])
                    child_name = new_child_name(gender, game_state)
                    if "children" not in npc: npc["children"] = []
                    npc["children"].append(create_newborn_child(gender, child_name, game_state, mother_name=name))
                    birth_events.append(f"👶 {name} 诞下{gender}，取名{child_name}！")
                    death_msg = try_childbirth_death(game_state, name, survived_child=True)
                    if death_msg:
                        birth_events.append(death_msg)
                    current_rank = normalize_rank_name(npc.get("rank", "答应"))
                    if current_rank in RANK_LEVELS and random.random() < 0.5:
                        next_label = try_npc_birth_promotion(game_state, npc)
                        if next_label:
                            birth_events.append(f"  {name} 母凭子贵，晋升为 {next_label}！")
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
            mother_label = child.get("adoptive_mother") or name
            growth_events.extend(process_child_milestones(child, f"{mother_label}的", game_state))
    return growth_events

def check_and_consume_action(game_state):
    if not game_state.can_act():
        return False, game_state.remaining_actions
    game_state.consume_action()
    return True, game_state.remaining_actions

def game_over_response(game_state):
    """终局后拒绝一切推进性操作。"""
    ending = ending_payload(game_state)
    return jsonify({
        "error": f"此局已终——{ending['headline']}。请回顾一生或重建新档。",
        "game_over": True,
        "ending": ending,
    }), 409

def guard_action(game_state):
    """行动前统一守卫：先查终局，再扣行动点。

    返回 (ok, error_response)。所有消耗行动点的路由都经过这里，
    避免结局判定散落在各个 route 里出现遗漏。
    """
    ensure_ending_fields(game_state)
    if is_game_over(game_state):
        return False, game_over_response(game_state)
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return False, (jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429)
    return True, None

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

def mask_api_key(key):
    if not key:
        return "(empty)"
    k = str(key).strip()
    if len(k) <= 8:
        return "***"
    return f"{k[:4]}...{k[-4:]}"

def is_model_unavailable_error(err):
    msg = str(err).lower()
    return "model_not_found" in msg or "no available channel" in msg

def call_ai_chat(client, model, messages):
    if not model:
        print("[ai] 未提供模型，跳过 AI 调用")
        return None, None, None
    last_err = None
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.8,
            max_tokens=800,
            top_p=0.95,
            timeout=10,
        )
        return response, model, None
    except Exception as e:
        last_err = e
        if is_model_unavailable_error(e):
            print(f"[ai] model unavailable: {model}")
        else:
            raise
    return None, model, last_err

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
    from events import check_event, generate_local_events, generate_fallback_story
    event = check_event(game_state)
    prompt = build_prompt(game_state, player_action, npc_names, event)
    
    print(f"[ai] generate_story key={mask_api_key(api_key)} base={api_base} model={api_model}")
    
    narration = None
    ai_warning = None
    if api_key is not None and api_base is not None and api_model and api_key.strip() and api_base.strip():
        try:
            client = get_openai_client(api_key, api_base)
            if client:
                model = api_model
                messages = [
                    {"role": "system", "content": "你是才华横溢的宫斗小说作家，只输出故事内容，不要任何格式标记。尽量使用名单中的人物。"},
                    {"role": "user", "content": prompt}
                ]
                response, used_model, err = call_ai_chat(client, model, messages)
                if response:
                    narration = response.choices[0].message.content.strip()
                    print(f"[ai] ok len={len(narration)} model={used_model}")
                elif err:
                    print(f"[ai] failed: {err}")
                    if is_model_unavailable_error(err):
                        ai_warning = f"AI 模型不可用（{model}），已改用本地剧情。请在设置中点击「获取」刷新模型列表"
                    else:
                        ai_warning = "AI 调用失败，已改用本地剧情"
        except Exception as e:
            print(f"[ai] failed: {e}")
            ai_warning = "AI 调用失败，已改用本地剧情"
            narration = None
    else:
        print("[ai] no valid api key, skip")

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
        return {"narration": narration, "choices": ["继续", "查看状态", "保存游戏"], "effects": base_changes, "event_triggered": event["name"] if event else None, "ai_warning": ai_warning}

    # ===== AI 未返回任何内容（None），使用本地事件 =====
    print("[ai] using local fallback story")
    local_events = generate_local_events(game_state, max_count=1)
    if local_events:
        evt = local_events[0]
        narration = evt["desc"]
        for attr, delta in evt["effects"].items():
            if attr in game_state.attributes:
                game_state.attributes[attr] = max(0, min(game_state.get_attr_max(attr), game_state.attributes[attr] + delta))
    else:
        narration = generate_fallback_story(game_state)

    base_changes = {"宠爱": random.randint(-1, 3), "威望": random.randint(-1, 2), "心计": random.randint(-1, 2), "健康": random.randint(-1, 2)}
    if event:
        for attr, change in event.get("effects", {}).items():
            base_changes[attr] = base_changes.get(attr, 0) + change
        game_state.add_memory(f"{event['name']}")
    for attr, change in base_changes.items():
        if attr in game_state.attributes:
            game_state.attributes[attr] = max(0, min(game_state.get_attr_max(attr), game_state.attributes[attr] + change))
    return {"narration": narration, "choices": ["继续", "查看状态", "保存游戏"], "effects": base_changes, "event_triggered": event["name"] if event else None, "ai_warning": ai_warning}

# ============================================================
#  晋升条件（真实属性阈值 + 防重复）
# ============================================================
def check_promotion_condition(game_state):
    if getattr(game_state, "_promotion_done", False):
        return False
    if getattr(game_state, "_pending_promotion", None) is not None:
        return False
    if game_state.rank.name == "皇后":
        return False
    favor_req = get_favor_threshold(game_state.rank.name)
    favor = game_state.attributes.get("宠爱", 0)
    # 宠爱单独校验：专宠折扣仅略降，不能靠威望/才情绕过
    favor_ratio = 0.92 if is_super_favor(game_state) else 1.0
    if favor < int(favor_req * favor_ratio):
        return False
    attr_ratio = 0.94 if is_super_favor(game_state) else 1.0
    if not check_promotion_thresholds_met(game_state, attr_ratio):
        return False
    if get_promotion_block_reason(game_state):
        return False
    if not check_tenure_met(game_state) and not is_special_favor(game_state):
        return False
    return True


def check_birth_promotion_eligible(game_state):
    """诞子晋封：略减属性门槛，但仍须宠爱达标且至少有基本资历。"""
    if game_state.rank.name == "皇后":
        return False
    favor_req = get_favor_threshold(game_state.rank.name)
    favor = game_state.attributes.get("宠爱", 0)
    if favor < int(favor_req * 0.85):
        return False
    if not check_promotion_thresholds_met(game_state, 0.88):
        return False
    if get_promotion_block_reason(game_state):
        return False
    if get_rank_periods(game_state) < max(2, get_min_tenure(game_state.rank.name) // 2):
        return False
    return True


def try_player_promotion(game_state, allow_birth=False):
    """统一晋升入口：赏赐、转旬、生子等都必须经过条件检测。"""
    if getattr(game_state, "_promotion_done", False):
        return None
    eligible = check_birth_promotion_eligible(game_state) if allow_birth else check_promotion_condition(game_state)
    if not eligible:
        return None
    step = get_promotion_step(game_state)
    if not step:
        return None
    if step["type"] == "位份" and not can_promote_to_rank(game_state, step.get("target", "")):
        return None
    promo_msg = apply_promotion_step(game_state, step)
    if promo_msg:
        game_state._promotion_done = True
        game_state.add_memory(f"晋升为{game_state.get_display_rank()}")
        game_state.story_flags.append("晋升成功")
    return promo_msg

def get_promotion_wait_message(game_state):
    """属性已够但尚未晋升时，返回等待原因。"""
    if game_state.rank.name == "皇后":
        return None
    block = get_promotion_block_reason(game_state)
    if block:
        return f"⚠️ {block}"
    attr_ratio = 0.94 if is_super_favor(game_state) else 1.0
    if not check_promotion_thresholds_met(game_state, attr_ratio):
        if is_special_favor(game_state):
            return "⚠️ 虽有圣宠，但威望才情等尚不足以服众，还需历练"
        favor_req = get_favor_threshold(game_state.rank.name)
        favor = game_state.attributes.get("宠爱", 0)
        if favor < favor_req:
            return f"⚠️ 圣宠不足（需宠爱≥{favor_req}，当前{favor}），还需邀宠"
        return None
    if not check_tenure_met(game_state) and not is_special_favor(game_state):
        need = get_min_tenure(game_state.rank.name) - get_rank_periods(game_state)
        return f"⚠️ 位份资历不足，还需在「{game_state.rank.name}」位上历练 {max(1, need)} 旬"
    return None

def is_exceptional_promotion(game_state):
    return is_special_favor(game_state) and not check_tenure_met(game_state)

def get_flip_candidates(game_state):
    candidates = []
    player_name = game_state.name
    player_favor = game_state.attributes.get("宠爱", 0)
    player_app = game_state.attributes.get("容貌", 50)
    player_tal = game_state.attributes.get("才情", game_state.attributes.get("才艺", 50))
    
    player_weight = player_favor * 3 + player_app * 2 + player_tal * 1 + get_rank_power(game_state.rank.name, game_state.nobletitle) * 5
    if getattr(game_state, "is_pregnant", False):
        player_weight = max(0, player_weight // 5) + 10
    if game_state.rank.name == "皇后":
        player_weight += 20
    candidates.append({"name": player_name, "weight": player_weight, "is_player": True})
    
    for name, npc in game_state.npcs.items():
        if name == "太后":
            continue
        if not npc.get("alive", True):
            continue
        favor = game_state.relationships.get(name, {}).get("好感", 0)
        appearance = npc.get("attributes", {}).get("容貌", 50)
        talent = npc.get("attributes", {}).get("才艺", 50)
        weight = favor * 3 + appearance * 2 + talent * 1 + get_rank_power(npc.get("rank", "答应"), npc.get("nobletitle")) * 5
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

def is_valid_api_key(key):
    if not key or not str(key).strip():
        return False
    k = str(key).strip()
    if k.lower() in ('sk-xxx', 'sk-xx', 'xxx', 'your-api-key', 'none'):
        return False
    if len(k) < 20:
        return False
    return True


def get_user_api_config(request, player_id=None):
    config = {}
    header_key = request.headers.get('X-API-Key')
    if header_key is None:
        header_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    config['api_key'] = header_key or ''
    config['api_base'] = request.headers.get('X-API-Base') or 'https://cn.jixiangai.xyz/v1'
    config['api_model'] = request.headers.get('X-API-Model') or ''
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if data.get('api_key'):
            config['api_key'] = data.get('api_key', '')
        config['api_base'] = config['api_base'] or data.get('api_base', 'https://cn.jixiangai.xyz/v1')
        if not config['api_model']:
            config['api_model'] = data.get('api_model', '')
    if player_id and player_id in user_configs:
        stored = user_configs[player_id]
        if not is_valid_api_key(config['api_key']):
            config['api_key'] = stored.get('api_key', '')
        config['api_base'] = config['api_base'] or stored.get('api_base', 'https://cn.jixiangai.xyz/v1')
        if not config['api_model']:
            config['api_model'] = stored.get('api_model', '')
    # 浏览器已发送 X-API-Key（含空值）时，不偷偷用服务器 .env，避免全员走慢速 AI
    if request.headers.get('X-API-Key') is not None:
        config['api_key'] = config['api_key'] if is_valid_api_key(config['api_key']) else ''
    elif not is_valid_api_key(config['api_key']):
        env_key = os.getenv('OPENAI_API_KEY', '')
        config['api_key'] = env_key if is_valid_api_key(env_key) else ''
    if not config['api_base']:
        config['api_base'] = os.getenv('OPENAI_BASE_URL', 'https://cn.jixiangai.xyz/v1')
    return config

@app.route('/api/models', methods=['GET', 'OPTIONS'])
def proxy_models():
    """Proxy an OpenAI-compatible model list to avoid browser CORS restrictions."""
    if request.method == 'OPTIONS':
        return '', 200
    api_base = (request.headers.get('X-API-Base') or '').strip().rstrip('/')
    api_key_raw = (request.headers.get('Authorization') or request.headers.get('X-API-Key') or '').strip()
    # 统一为 Bearer 格式转发给上游
    if api_key_raw.lower().startswith('bearer '):
        api_key = api_key_raw[7:].strip()
    else:
        api_key = api_key_raw
    api_key = f'Bearer {api_key}' if api_key else ''
    parsed = urlparse(api_base)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return jsonify({"error": "API 地址必须是有效的 http/https URL"}), 400
    if not api_key:
        return jsonify({"error": "缺少 API Key"}), 400

    try:
        response = httpx.get(
            api_base + '/models',
            headers={"Authorization": api_key, "Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=15.0,
            follow_redirects=True,
        )
    except httpx.RequestError as exc:
        return jsonify({"error": f"请求模型服务失败: {exc}"}), 502

    content_type = response.headers.get('content-type', '')
    if 'application/json' in content_type.lower():
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": "模型服务返回了无效 JSON"}
    else:
        payload = {"error": response.text[:1000] or "模型服务返回空响应"}
    return jsonify(payload), response.status_code

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "version": "1.4.0",
        "events_loaded": len(EVENT_POOL),
    })


@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    # GET 配置通过查询参数读取，避免无 JSON 请求体时触发 415。
    if request.method == 'GET':
        player_id = request.args.get('player_id')
        if not player_id:
            return jsonify({"error": "缺少player_id"}), 400
        config = user_configs.get(player_id, {"custom_prompt": "", "romance_mode": False, "api_base": "https://cn.jixiangai.xyz/v1", "api_key": "", "api_model": ""})
        return jsonify(config)

    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    if not player_id:
        return jsonify({"error": "缺少player_id"}), 400
    user_configs[player_id] = {
        "custom_prompt": data.get('custom_prompt', ''),
        "romance_mode": data.get('romance_mode', False),
        "api_base": data.get('api_base', 'https://cn.jixiangai.xyz/v1'),
        "api_key": data.get('api_key', ''),
        "api_model": data.get('api_model', '')
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
    ok, err = guard_action(game_state)
    if not ok:
        return err
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
    ok, err = guard_action(game_state)
    if not ok:
        return err
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
        return jsonify({"npcs": {name: {"name": name, "rank": npc.get("rank","妃嫔"), "personality": npc.get("personality","未知"), "icon": npc.get("icon","🌸"), "relationship": game_state.relationships.get(name, {"好感":0,"印象":"陌生"}), "children": npc.get("children",[]), "is_pregnant": npc.get("is_pregnant",False), "pregnancy_month": npc.get("pregnancy_month",0), "attributes": npc.get("attributes",{}), "family_background": npc.get("family_background",""), "nobletitle": npc.get("nobletitle",None), "压力": npc.get("压力", 0), "alive": npc.get("alive", True), "death_cause": npc.get("death_cause")} for name, npc in game_state.npcs.items() if name != "太后"}})
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
    rank = npc.get("rank", "妃嫔")
    min_age = 35 if rank == "太后" else PLAYER_MIN_AGE
    max_age = 90 if rank == "太后" else 80
    default_age = random.randint(45, 65) if rank == "太后" else random.randint(PLAYER_MIN_AGE, 32)
    return jsonify({
        "name": name, "rank": rank, "age": clamp_age(npc.get("age"), default_age, min_age, max_age), "personality": npc.get("personality","未知"),
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
    ok, err = guard_action(game_state)
    if not ok:
        return err
    if npc_name not in game_state.npcs:
        return jsonify({"error": "NPC不存在"}), 404
    npc = game_state.npcs[npc_name]
    if not npc.get("alive", True):
        return jsonify({"error": "该妃嫔已不在后宫"}), 400
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
        pact = form_alliance(game_state, npc_name)
        result["narration"] = pact["narration"]
        result["effects"] = pact["effects"]
        result["alliance_level"] = pact["level"]
        result["alliance_pledge"] = pact["pledge"]
        game_state.add_memory(pact["memory"])
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
    ok, err = guard_action(game_state)
    if not ok:
        return err
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
    ok, err = guard_action(game_state)
    if not ok:
        return err
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
    ensure_ending_fields(game_state)
    if is_game_over(game_state):
        return game_over_response(game_state)
    api_config = get_user_api_config(request, player_id)

    # ---- 时间推进 ----
    old_month, old_year = game_state.month, game_state.year
    game_state.advance_calendar()
    month_changed = game_state.month != old_month or game_state.year != old_year
    game_state.reset_actions()
    game_state.current_time = "卯时"
    game_state._promotion_done = False
    if game_state.year != old_year:
        game_state.age = clamp_age(getattr(game_state, "age", PLAYER_MIN_AGE) + 1, PLAYER_MIN_AGE, PLAYER_MIN_AGE)
        if isinstance(getattr(game_state, "emperor", None), dict):
            game_state.emperor["age"] = clamp_age(game_state.emperor.get("age", 35) + 1, 35, 18, 80)
        for npc in game_state.npcs.values():
            if npc.get("alive", True):
                rank = npc.get("rank", "")
                minimum = 35 if rank == "太后" else PLAYER_MIN_AGE
                maximum = 90 if rank == "太后" else 80
                default_age = 50 if rank == "太后" else 18
                npc["age"] = clamp_age(npc.get("age", default_age) + 1, default_age, minimum, maximum)
        for servant in getattr(game_state, "servants", []):
            if getattr(servant, "is_active", True):
                servant.age = clamp_age(getattr(servant, "age", 18) + 1, 18, PLAYER_MIN_AGE, 80)

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
    npc_names = [n for n in list(game_state.npcs.keys()) if n not in ["太后", "皇后"] and game_state.npcs[n].get("alive", True)]
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
    player_death_ending = None
    if game_state.is_pregnant:
        game_state.pregnancy_month += PREGNANCY_STEP
        miscarriage_msg = check_player_miscarriage(game_state)
        if miscarriage_msg:
            pregnancy_update = miscarriage_msg
            player_death_ending = check_player_childbirth_death(game_state, survived_child=False)
        elif game_state.pregnancy_month >= 10:
            game_state.is_pregnant = False
            game_state.pregnancy_month = 0
            if random.random() < 0.15:
                game_state.attributes["健康"] = max(0, game_state.attributes["健康"] - 25)
                pregnancy_update = f"⚠️ 你难产了！健康-25，请好好休养。"
                game_state.add_memory(f"难产，健康-25")
                player_death_ending = check_player_childbirth_death(game_state, survived_child=False)
            else:
                gender = random.choice(["皇子", "公主"])
                child_name = new_child_name(gender, game_state)
                game_state.children.append(create_newborn_child(gender, child_name, game_state))
                game_state.has_children = True
                game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes["宠爱"] + 20)
                game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes["威望"] + 15)
                pregnancy_update = f"👶 你诞下{gender}，取名{child_name}！宠爱+20，威望+15"
                game_state.add_memory(f"诞下{gender}，取名{child_name}")
                player_death_ending = check_player_childbirth_death(game_state, survived_child=True)
                if not player_death_ending and random.random() < 0.35:
                    promo_msg = try_player_promotion(game_state, allow_birth=True)
                    if promo_msg:
                        pregnancy_update += f" 母凭子贵，{promo_msg.replace('📜 圣旨到！', '').strip()}"
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

    intrigue_events = process_intrigue_period(game_state)
    if intrigue_events:
        for msg in intrigue_events:
            intelligence.append(msg)
            game_state.add_memory(msg)

    death_events = process_consort_deaths(game_state)
    if death_events:
        for msg in death_events:
            intelligence.append(msg)
            game_state.add_memory(msg)

    alliance_events = process_alliance_period(game_state)
    for msg in alliance_events:
        intelligence.append(msg)

    prince_events = []
    for child in game_state.children:
        ensure_child_fields(child)
        child["age"] = child.get("age", 0) + CHILD_AGE_STEP
        prince_events.extend(process_child_milestones(child, "你的", game_state))
    child_life_events = process_player_child_events(game_state)
    prince_events.extend(child_life_events)
    if prince_events:
        for evt in prince_events:
            game_state.add_memory(evt)

    # ---- 子嗣过继相关随机动态 ----
    adoption_hints = []
    # 清理过期的“想收养”标记
    for n, npc in game_state.npcs.items():
        want_day = npc.get("wants_adopt_player_child")
        if want_day is not None:
            if game_state.day - int(want_day) > ADOPT_WANT_HINT_DAYS:
                npc.pop("wants_adopt_player_child", None)
    # 高位无子妃嫔有意收养玩家子嗣
    if random.random() < 0.12 and game_state.children:
        candidates = []
        for n, npc in game_state.npcs.items():
            if n in ("太后", "皇后") or n == game_state.name:
                continue
            if not npc.get("alive", True):
                continue
            if RANK_LEVELS.get(normalize_rank_name(npc.get("rank", "答应")), 0) < RANK_LEVELS.get("嫔", 0):
                continue
            if count_living_children(npc.get("children", [])) > 0:
                continue
            rel = game_state.relationships.get(n, {"好感": 0})
            if rel.get("好感", 0) >= 30:
                candidates.append(n)
        if candidates:
            npc_name = random.choice(candidates)
            child = random.choice([c for c in game_state.children if c.get("alive", True)])
            child_name = child.get("name", "皇嗣")
            game_state.npcs[npc_name]["wants_adopt_player_child"] = game_state.day
            adoption_hints.append(f"📜 {npc_name}膝下空虚，有意收养你的{child_name}，可去她的宫中提及过继之事")
    # 遗孤消息
    if random.random() < 0.08:
        orphans = []
        for n, npc in game_state.npcs.items():
            if npc.get("alive", True):
                continue
            for c in npc.get("children", []):
                if c.get("alive", True) and not c.get("adoptive_mother"):
                    orphans.append((n, c))
        if orphans:
            oname, ochild = random.choice(orphans)
            adoption_hints.append(f"🕯️ 故人{oname}的遗孤{ochild.get('name', '子嗣')}孤苦无依，你若去其旧居，或可收养此子")
    if adoption_hints:
        for hint in adoption_hints:
            intelligence.append(hint)
            game_state.add_memory(hint)

    # ===== 晋升触发（转旬时检测） =====
    promotion_message = None
    demotion_message = None
    depose_queen_message = None
    promoted_this_period = False
    empress_support_message = maybe_trigger_empress_support_event(game_state)
    if empress_support_message:
        intelligence.append(empress_support_message)
    if check_promotion_condition(game_state):
        exceptional = is_exceptional_promotion(game_state)
        promotion_msg = try_player_promotion(game_state)
        if promotion_msg:
            if exceptional:
                promotion_msg += "（皇帝专宠，破格晋封）"
            promotion_message = promotion_msg
            promoted_this_period = True
        else:
            step = get_promotion_step(game_state)
            target_label = (step.get("target") or "赐封号") if step else ""
            if step and step["type"] == "位份" and not can_promote_to_rank(game_state, step.get("target", "")):
                promotion_message = f"⚠️ {target_label} 人数已满，暂无法晋升。"
            elif step:
                promotion_message = f"⚠️ 晋封「{target_label}」条件未满足，请继续历练。"
            else:
                promotion_message = "你已位极人臣，无法再晋升。"
    else:
        relation_promo = _player_relationship_promotion(game_state)
        if relation_promo:
            promotion_message = relation_promo
            promoted_this_period = True
        else:
            wait_msg = get_promotion_wait_message(game_state)
            if wait_msg:
                promotion_message = wait_msg

    if not promoted_this_period:
        game_state.rank_periods = get_rank_periods(game_state) + 1

    # ===== 圣宠尽失时可能被降位 =====
    if not demotion_message and game_state.rank.name not in ("宫女", "秀女"):
        favor = game_state.attributes.get("宠爱", 0)
        if favor < 12 and random.random() < 0.12:
            demotion_message = demote_player(game_state, "圣宠尽失，朝野议论，被迫降位")
            if demotion_message:
                game_state.attributes["威望"] = max(0, game_state.attributes.get("威望", 0) - random.randint(8, 15))

    # ===== 废后（转旬时低概率触发，需满足资格且皇后失势） =====
    if check_depose_queen_eligible(game_state) and random.random() < 0.04:
        queen_name = get_queen_name(game_state)
        queen = game_state.npcs.get(queen_name, {})
        q_attrs = queen.get("attributes", {})
        if q_attrs.get("宠爱", 50) < 45 or q_attrs.get("威望", 50) < 50:
            depose_queen_message = try_depose_queen(
                game_state, "皇后失德失势，朝臣联名上奏，皇帝准了废后之请"
            )

    # ---- NPC晋升 / 降位 ----
    other_promotions = []
    other_demotions = []
    if game_state.month % 3 == 0:
        for name, npc in game_state.npcs.items():
            if name == "太后" or npc.get("rank") == "皇后" or name == game_state.name:
                continue
            if not npc.get("alive", True):
                continue
            attrs = npc.get("attributes", {})
            favor = attrs.get("宠爱", 0)
            prestige = attrs.get("威望", 0)
            current_rank = normalize_rank_name(npc.get("rank", "答应"))
            rank_power = get_rank_power(current_rank, npc.get("nobletitle"))
            if rank_power < 19 and favor > 50 + rank_power * 10 and prestige > 40 + rank_power * 8:
                if current_rank == "妃" and not npc.get("nobletitle"):
                    next_label = promote_npc_one_step(game_state, npc)
                    if next_label and random.random() < 0.25:
                        npc["attributes"]["宠爱"] = min(100, favor + random.randint(5, 12))
                        npc["attributes"]["威望"] = min(100, prestige + random.randint(5, 10))
                        other_promotions.append(f"✨ {name} 晋封为 {next_label}！")
                elif current_rank == "妃" and npc.get("nobletitle"):
                    target = pick_available_four_consort(game_state)
                    if target and npc_meets_rank_requirements(npc, target) and random.random() < 0.25:
                        next_label = promote_npc_one_step(game_state, npc)
                        if next_label:
                            npc["attributes"]["宠爱"] = min(100, favor + random.randint(5, 12))
                            npc["attributes"]["威望"] = min(100, prestige + random.randint(5, 10))
                            other_promotions.append(f"✨ {name} 晋升为 {next_label}！")
                elif current_rank in RANK_LEVELS:
                    idx = RANK_LEVELS[current_rank]
                    if idx < len(RANK_ORDER) - 1:
                        next_rank = RANK_ORDER[idx + 1]
                        if (can_promote_to_rank(game_state, next_rank)
                                and npc_meets_rank_requirements(npc, next_rank)
                                and random.random() < 0.25):
                            npc["rank"] = next_rank
                            npc["attributes"]["宠爱"] = min(100, favor + random.randint(5, 12))
                            npc["attributes"]["威望"] = min(100, prestige + random.randint(5, 10))
                            other_promotions.append(f"✨ {name} 晋升为 {next_rank}！")
            if favor < 20 and prestige < 25 and rank_power > 0 and random.random() < 0.08:
                    msg = demote_npc(game_state, name, "圣宠断绝，位份被削")
                    if msg:
                        other_demotions.append(msg)
        if other_promotions:
            game_state.add_memory(f"其他妃嫔晋升：{', '.join(other_promotions)}")
        if other_demotions:
            game_state.add_memory(f"妃嫔降位：{'; '.join(other_demotions)}")

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

    # ===== 皇帝健康衰退与驾崩/继承判定 =====
    emperor = game_state.emperor or {}
    emperor_health = emperor.get("health", 80)
    emperor_age = emperor.get("age", 35)
    emperor_illness = emperor.get("illness_stage", "安康")
    succession_pressure = emperor.get("succession_pressure", 0)
    emperor_death_msg = None
    emperor_abdicate_msg = None

    # 皇帝健康自然衰减（年龄越大衰减越快）
    decay_base = 0.3 if emperor_age < 40 else (0.6 if emperor_age < 50 else (1.2 if emperor_age < 60 else 2.0))
    if emperor_illness == "微恙":
        decay_base *= 2.0
    elif emperor_illness == "沉疴":
        decay_base *= 4.0
    if random.random() < decay_base / 10:  # 每旬约 decay_base/10 概率扣 1 点
        emperor_health = max(0, emperor_health - 1)
        emperor["health"] = emperor_health

    # 病情演变
    if emperor_health < 60 and emperor_illness == "安康" and random.random() < 0.05:
        emperor["illness_stage"] = "微恙"
        emperor_illness = "微恙"
        intelligence.append("🏥 皇帝偶感风寒，太医署已开方调理。")
    elif emperor_health < 40 and emperor_illness == "微恙" and random.random() < 0.08:
        emperor["illness_stage"] = "沉疴"
        emperor_illness = "沉疴"
        intelligence.append("🏥 皇帝病势加重，已卧床不起，太医院上下束手无策。")
    elif emperor_health < 20 and emperor_illness == "沉疴" and random.random() < 0.15:
        emperor["illness_stage"] = "弥留"
        emperor_illness = "弥留"
        intelligence.append("🕯️ 皇帝已至弥留之际，召宗室大臣入宫，恐时日无多。")

    # 立储压力累积
    if emperor_health < 50:
        pressure_gain = 1 if emperor_health >= 30 else 3
        succession_pressure += pressure_gain
        emperor["succession_pressure"] = succession_pressure

    # 驾崩判定
    heir_id = (game_state.heir_status or {}).get("heir_id")
    if emperor_health <= 0 or emperor_illness == "弥留":
        if emperor_health <= 0 or random.random() < 0.4:  # 弥留每旬 40% 概率驾崩
            # 皇帝驾崩
            emperor["health"] = 0
            emperor["alive"] = False
            emperor_death_msg = "🕯️ 皇帝驾崩，天下缟素！"
            intelligence.append(emperor_death_msg)
            game_state.add_memory(emperor_death_msg)

            if heir_id:
                heir_child = get_heir_child(game_state)
                if heir_child:
                    heir_mother = heir_child.get("adoptive_mother") or heir_child.get("birth_mother") or ""
                    if heir_mother == game_state.name:
                        # 你的子嗣继位 → 太后结局
                        ending = trigger_ending(game_state, "母仪天下",
                            f"皇帝驾崩，你的子嗣{heir_child.get('name','皇嗣')}继位为帝，尊你为太后")
                        intelligence.append(f"👑 新帝登基，尊你为太后，母仪天下！")
                        game_state.add_memory(f"👑 你的子嗣{heir_child.get('name','皇嗣')}登基为帝")
                    else:
                        # 他人子嗣继位 → 无依靠结局
                        intelligence.append(f"👑 新帝登基，但与你并无血缘，你在宫中再无依靠。")
                        game_state.add_memory("👑 新帝登基，你在宫中再无依靠")
                        # 若无子嗣，可能触发迟暮结局
                        if not game_state.children:
                            ending = trigger_ending(game_state, "迟暮宫墙",
                                "皇帝驾崩，你无子嗣倚靠，被移居别宫终老")
                else:
                    # 储君记录有但找不到子嗣，视为无储
                    intelligence.append("👑 新帝登基，但与你并无关联。")
                    game_state.add_memory("👑 新帝登基")
            else:
                # 无储君 → 新帝登基，玩家境遇下降
                intelligence.append("👑 国不可一日无君，宗室拥立新帝登基，但你未能在权力更迭中获利。")
                game_state.add_memory("👑 新帝登基，宫中格局大变")
                if not game_state.children:
                    # 无子嗣则威望暴跌，可能触发结局
                    game_state.attributes["威望"] = max(0, game_state.attributes.get("威望", 0) - 30)
                    if game_state.attributes.get("威望", 0) < 10:
                        ending = trigger_ending(game_state, "冷宫幽闭",
                            "先帝驾崩，新帝登基，你无宠无嗣无威望，被迁入冷宫")

    # 皇帝退位（健康极低且储君已立，低概率禅位）
    if not emperor.get("alive", True) is False and emperor_health < 25 and heir_id and random.random() < 0.05:
        emperor["alive"] = False
        emperor_abdicate_msg = "📜 皇帝以龙体欠安为由，下诏禅位于储君，自居太上皇。"
        intelligence.append(emperor_abdicate_msg)
        game_state.add_memory(emperor_abdicate_msg)
        heir_child = get_heir_child(game_state)
        if heir_child:
            heir_mother = heir_child.get("adoptive_mother") or heir_child.get("birth_mother") or ""
            if heir_mother == game_state.name:
                ending = trigger_ending(game_state, "母仪天下",
                    f"皇帝禅位，你的子嗣{heir_child.get('name','皇嗣')}登基为帝，尊你为太后")
                intelligence.append("👑 新帝登基，尊你为太后！")
            else:
                intelligence.append("👑 新帝登基，但与你并无血缘。")
                if not game_state.children:
                    game_state.attributes["威望"] = max(0, game_state.attributes.get("威望", 0) - 20)

    # ===== 终局判定（放在本旬所有结算之后，保证依据的是最终状态） =====
    ending = player_death_ending
    ending_warnings = []
    if not ending:
        ending, ending_warnings = evaluate_period_endings(game_state)
    else:
        # 生产致死已落定结局，仍需刷新失宠计数以保持存档一致
        ensure_ending_fields(game_state)
    for warn in ending_warnings:
        intelligence.append(warn)
        game_state.add_memory(warn)
    if ending:
        intelligence.append(f"{ending['icon']} 【{ending['key']}】{ending['reason']}")

    ensure_character_ages(game_state)
    npcs_with_children = serialize_npcs_for_client(game_state)
    dowager_data = game_state.npcs.get("太后")

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
        "dowager": dowager_data,
        "memories": game_state.get_recent_memories(5),
        "attr_change_log": game_state.attr_change_log[-5:],
        "player_name": game_state.name,
        "age": game_state.age,
        "display_rank": game_state.get_display_rank(),
        "rank_periods": get_rank_periods(game_state),
        "rank_tenure_required": get_min_tenure(game_state.rank.name),
        "special_favor": is_special_favor(game_state),
        "empress_status": get_empress_requirement_status(game_state),
        "remaining_actions": game_state.remaining_actions,
        "max_actions": game_state.max_actions,
        "promotion_message": promotion_message,
        "demotion_message": demotion_message,
        "depose_queen_message": depose_queen_message,
        "rank": game_state.rank.name,
        "other_promotions": other_promotions,
        "new_concubine": new_concubine,
        "pregnancy_update": pregnancy_update,
        "other_pregnancy_msgs": pregnancy_events,
        "other_birth_msgs": birth_events,
        "prince_events": prince_events,
        "growth_events": growth_events,
        "death_events": death_events,
        "intrigue": summarize_intrigue(game_state),
        "intrigue_events": intrigue_events,
        "ai_events_used": ai_events_used,
        "ai_events_fallback": ai_fallback,
        "ending": ending,
        "game_over": bool(ending),
        "ending_warnings": ending_warnings,
        "heir_status": game_state.heir_status,
        "palaces": PALACE_LIST,
        "emperor": game_state.emperor,
    })

@app.route('/api/intrigue/targets', methods=['GET'])
def intrigue_targets_api():
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    return jsonify({
        "targets": get_intrigue_targets(game_state),
        "intrigue": summarize_intrigue(game_state),
        "remaining_actions": game_state.remaining_actions,
        "max_actions": game_state.max_actions,
    })


@app.route('/api/intrigue', methods=['POST'])
def intrigue_action_api():
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    action = data.get('action')
    target_name = data.get('target')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err

    result, error = handle_intrigue_action(game_state, action, target_name)
    if error:
        game_state.remaining_actions = min(game_state.max_actions, game_state.remaining_actions + 1)
        return jsonify({"error": error}), 400

    autosave_session(player_id)
    return jsonify({
        **result,
        "targets": get_intrigue_targets(game_state),
        "attributes": game_state.attributes,
        "silver": game_state.silver,
        "relationships": game_state.relationships,
        "remaining_actions": game_state.remaining_actions,
        "max_actions": game_state.max_actions,
        "player_name": game_state.name,
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
    ok, err = guard_action(game_state)
    if not ok:
        return err
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
    ok, err = guard_action(game_state)
    if not ok:
        return err
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

CREATION_ATTR_KEYS = frozenset({"容貌", "才情", "心计", "健康", "才艺", "谋略", "魅力", "福运", "倾向"})


def apply_emperor_first_impression(game_state):
    """殿选后根据皇帝性格与玩家属性随机赐予宠爱、威望，并设定初印象。"""
    emperor = game_state.emperor or {}
    personality = emperor.get("personality", "明君")
    factors = emperor.get("favor_factors", {}).get(
        personality, {"容貌": 0.3, "才情": 0.3, "心计": 0.4}
    )
    attrs = game_state.attributes
    match_score = sum(attrs.get(attr, 40) * float(weight) for attr, weight in factors.items()) / 100.0

    stats = emperor.get("stats", {})
    lust = stats.get("好色", 40) / 100.0
    majesty = stats.get("威严", 50) / 100.0

    roll = random.random() * 0.35 + match_score * 0.5 + lust * 0.12 + random.uniform(-0.06, 0.1)
    if roll >= 0.78:
        impression = "一见倾心"
    elif roll >= 0.62:
        impression = "颇有好感"
    elif roll >= 0.46:
        impression = "清婉可人"
    elif roll >= 0.30:
        impression = "平平无奇"
    elif roll >= 0.16:
        impression = "冷淡疏离"
    else:
        impression = "心存戒备"

    rank_lift = max(0, game_state.rank.value - Rank.答应.value)
    favor_gain = int(random.randint(10, 24) + match_score * 20 + lust * 10 + rank_lift * 2)
    prestige_gain = int(random.randint(5, 14) + match_score * 8 + majesty * 6 + rank_lift)

    if impression == "一见倾心":
        favor_gain += random.randint(10, 18)
        prestige_gain += random.randint(4, 10)
    elif impression == "颇有好感":
        favor_gain += random.randint(5, 12)
        prestige_gain += random.randint(2, 6)
    elif impression in ("冷淡疏离", "心存戒备"):
        favor_gain = max(6, favor_gain - random.randint(8, 16))
        prestige_gain = max(4, prestige_gain - random.randint(2, 6))

    game_state.attributes["宠爱"] = min(
        game_state.get_attr_max("宠爱"),
        game_state.attributes.get("宠爱", 10) + favor_gain,
    )
    game_state.attributes["威望"] = min(
        game_state.get_attr_max("威望"),
        game_state.attributes.get("威望", 10) + prestige_gain,
    )

    rel_favor = min(100, max(5, 10 + favor_gain // 2))
    game_state.relationships.setdefault("皇帝", {"好感": 10, "印象": "初识", "互动次数": 0})
    game_state.relationships["皇帝"]["印象"] = impression
    game_state.relationships["皇帝"]["好感"] = rel_favor

    emp_name = emperor.get("name", "皇帝")
    msg = f"殿选之后，{emp_name}对你印象「{impression}」，宠爱+{favor_gain}，威望+{prestige_gain}"
    game_state.add_memory(msg)
    game_state.add_attr_change({"宠爱": favor_gain, "威望": prestige_gain}, "皇帝初印象")
    return {
        "impression": impression,
        "favor_gain": favor_gain,
        "prestige_gain": prestige_gain,
        "message": msg,
    }


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
    raw_age = character.get('age')
    if raw_age is not None and str(raw_age).strip() != "":
        try:
            requested_age = int(raw_age)
        except (TypeError, ValueError):
            return jsonify({"error": "年龄格式有误"}), 400
        if requested_age < PLAYER_MIN_AGE:
            return jsonify({"error": f"入宫年龄须满 {PLAYER_MIN_AGE} 岁"}), 400
        if requested_age > PLAYER_MAX_CREATE_AGE:
            return jsonify({"error": f"入宫年龄不得超过 {PLAYER_MAX_CREATE_AGE} 岁"}), 400
    api_config = get_user_api_config(request)
    client_id = extract_client_id(request, data)
    player_id = str(uuid.uuid4())
    game_state = GameState(player_id, Rank.答应)
    ensure_game_state_client_id(game_state, client_id)
    game_state.name = player_name
    game_state.appearance = character.get('appearance', '')
    game_state.talent = character.get('talent', '')
    game_state.personality = character.get('personality', '')
    game_state.background_desc = character.get('background_desc', '')
    game_state.traits = character.get('traits', [])
    game_state.custom_story = character.get('custom_story', '')
    game_state.age = clamp_age(character.get('age'), random.randint(PLAYER_MIN_AGE, 22), PLAYER_MIN_AGE, PLAYER_MAX_CREATE_AGE)
    
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
    game_state.max_servants = 6 + game_state.rank.value // 2
    
    if player_attributes:
        for attr, value in player_attributes.items():
            if attr not in CREATION_ATTR_KEYS:
                continue
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

    game_state.emperor["age"] = clamp_age(game_state.emperor.get("age"), random.randint(25, 55), 18, 80)
    game_state.attributes["宠爱"] = 10
    first_impression = apply_emperor_first_impression(game_state)
    
    game_state.npcs = generate_all_npcs(10, surname=royal_surname(game_state))
    if "太后" not in game_state.npcs:
        game_state.npcs["太后"] = {"name": "太后", "rank": "太后", "age": random.randint(45, 65), "personality": "威严慈祥", "personality_desc": "历经三朝，深谙宫闱之道", "icon": "👑", "attributes": {"威望":90,"心计":80,"健康":60,"宠爱":0,"容貌":70}, "relationship": {"好感":25,"印象":"和善","互动次数":0}, "is_active": True, "alive": True}
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
    
    ensure_character_ages(game_state)
    game_state.romance_mode = False
    game_state.custom_prompt = ""
    game_state._pending_promotion = None
    game_state._promotion_done = False
    sessions[player_id] = game_state
    user_configs[player_id] = {"custom_prompt": "", "romance_mode": False, "api_base": api_config.get('api_base', 'https://cn.jixiangai.xyz/v1'), "api_key": api_config.get('api_key', ''), "api_model": api_config.get('api_model', '')}
    npc_names = list(game_state.npcs.keys())
    story = generate_story(game_state, "入宫选秀，开启了后宫生涯", npc_names, api_config.get('api_key'), api_config.get('api_base'), api_config.get('api_model'))
    
    npcs_with_children = serialize_npcs_for_client(game_state)
    dowager_data = game_state.npcs.get("太后")
    autosave_session(player_id)
    return jsonify({"player_id": player_id, "player_name": player_name, "age": game_state.age, "family_background": game_state.family_background, "rank": game_state.rank.name, "nobletitle": game_state.nobletitle, "display_rank": game_state.get_display_rank(), "attributes": game_state.attributes, "attr_max": game_state.ATTR_MAX, "relationships": game_state.relationships, "emperor": game_state.emperor, "dowager": dowager_data, "storyline": game_state.storyline.value, "silver": game_state.silver, "npcs": npcs_with_children, "narration": story.get("narration","欢迎来到后宫。"), "choices": story.get("choices",["四处看看","去请安","回宫休息"]), "effects": story.get("effects",{}), "ai_warning": story.get("ai_warning"), "is_pregnant": game_state.is_pregnant, "children": game_state.children, "has_children": game_state.has_children, "rivalries": game_state.rivalries, "alliances": game_state.alliances, "intrigue": summarize_intrigue(game_state), "intrigue_events": [], "servants": [], "romance_mode": game_state.romance_mode, "year": game_state.year, "month": game_state.month, "day": game_state.day, "calendar_str": game_state.get_calendar_str(), "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions, "appearance": game_state.appearance, "talent": game_state.talent, "personality": game_state.personality, "traits": game_state.traits, "custom_story": game_state.custom_story, "first_impression": first_impression, "empress_status": get_empress_requirement_status(game_state)})

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
    ok, err = guard_action(game_state)
    if not ok:
        return err
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
        npc_names = [
            n for n, npc in game_state.npcs.items()
            if npc.get("alive", True) and npc.get("is_active", True) and n != "太后" and n != game_state.name
        ]
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
    ensure_character_ages(game_state)
    npcs_with_children = serialize_npcs_for_client(game_state)
    dowager_data = game_state.npcs.get("太后")
    autosave_session(player_id)
    return jsonify({"player_id": player_id, "rank": game_state.rank.name, "nobletitle": game_state.nobletitle, "display_rank": game_state.get_display_rank(), "attributes": game_state.attributes, "attr_max": game_state.ATTR_MAX, "relationships": game_state.relationships, "story_flags": game_state.story_flags, "storyline": game_state.storyline.value, "emperor": game_state.emperor, "dowager": dowager_data, "day": game_state.day, "month": game_state.month, "year": game_state.year, "calendar_str": game_state.get_calendar_str(), "silver": game_state.silver, "family_background": game_state.family_background, "npcs": npcs_with_children, "narration": story.get("narration","宫中岁月静好。"), "choices": story.get("choices",["继续","查看状态","保存游戏"]), "effects": story.get("effects",{}), "ai_warning": story.get("ai_warning"), "rivalry_event": rivalry_event, "event_triggered": story.get("event_triggered"), "memories": game_state.get_recent_memories(3), "is_pregnant": game_state.is_pregnant, "pregnancy_month": game_state.pregnancy_month, "children": game_state.children, "has_children": game_state.has_children, "rivalries": game_state.rivalries, "alliances": game_state.alliances, "intrigue": summarize_intrigue(game_state), "intrigue_events": [], "attr_change_log": game_state.attr_change_log[-5:], "servants": [s.to_dict() for s in game_state.get_active_servants()], "romance_mode": game_state.romance_mode, "player_name": game_state.name, "age": game_state.age, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions, "empress_status": get_empress_requirement_status(game_state)})

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
        ensure_character_ages(game_state)
        npcs_with_children = serialize_npcs_for_client(game_state)
        dowager_data = game_state.npcs.get("太后")
        ensure_ending_fields(game_state)
        return jsonify({"rank": game_state.rank.name, "nobletitle": game_state.nobletitle, "display_rank": game_state.get_display_rank(), "rank_periods": get_rank_periods(game_state), "rank_tenure_required": get_min_tenure(game_state.rank.name), "special_favor": is_special_favor(game_state), "empress_status": get_empress_requirement_status(game_state), "name": game_state.name, "age": game_state.age, "family_background": game_state.family_background, "attributes": game_state.attributes, "attr_max": game_state.ATTR_MAX, "relationships": game_state.relationships, "current_time": game_state.current_time, "day": game_state.day, "month": game_state.month, "year": game_state.year, "calendar_str": game_state.get_calendar_str(), "silver": game_state.silver, "story_flags": game_state.story_flags, "storyline": game_state.storyline.value, "emperor": game_state.emperor, "dowager": dowager_data, "memories": game_state.get_recent_memories(5), "inventory": game_state.inventory, "npcs": npcs_with_children, "is_pregnant": game_state.is_pregnant, "pregnancy_month": game_state.pregnancy_month, "children": game_state.children, "has_children": game_state.has_children, "rivalries": game_state.rivalries, "alliances": game_state.alliances, "intrigue": summarize_intrigue(game_state), "intrigue_events": [], "attr_change_log": game_state.attr_change_log[-10:], "servants": [s.to_dict() for s in game_state.get_active_servants()], "romance_mode": game_state.romance_mode, "player_name": game_state.name, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions, "appearance": getattr(game_state,'appearance',''), "talent": getattr(game_state,'talent',''), "personality": getattr(game_state,'personality',''), "traits": getattr(game_state,'traits',[]), "custom_story": getattr(game_state,'custom_story',''), "ending": ending_payload(game_state), "game_over": is_game_over(game_state), "neglect_periods": getattr(game_state, "neglect_periods", 0), "restored_from_save": need_restore, "heir_status": game_state.heir_status, "palaces": PALACE_LIST})
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
    """已废弃：请使用 /api/saves/mine 并按设备 client_id 过滤。"""
    client_id = extract_client_id(request=request)
    if not client_id:
        return jsonify({"saves": [], "error": "请使用本设备存档列表"}), 400
    known_raw = request.args.get("known_player_ids", "")
    known_ids = parse_known_player_ids(known_raw)
    return _list_saves_for_client(client_id, known_ids)


def _list_saves_for_client(client_id, known_player_ids=None):
    known_player_ids = set(known_player_ids or [])
    saves = []
    if not os.path.exists(SAVE_DIR):
        return jsonify({"saves": []})
    for filename in os.listdir(SAVE_DIR):
        if not filename.endswith('.json'):
            continue
        try:
            with open(os.path.join(SAVE_DIR, filename), 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not save_belongs_to_client(data, client_id, known_player_ids):
                continue
            game_data = data.get("game_state", {})
            base = filename[:-5]
            parts = base.split('_', 1)
            if len(parts) == 2:
                saves.append({
                    "player_id": parts[0],
                    "slot": parts[1],
                    "save_time": data.get("save_time", "未知"),
                    "player_name": game_data.get("name", "未知"),
                    "rank": game_data.get("display_rank", game_data.get("rank", "未知")),
                    "day": game_data.get("day", 1),
                })
        except Exception:
            continue
    saves.sort(key=lambda x: x.get("save_time", ""), reverse=True)
    return jsonify({"saves": saves})


@app.route('/api/saves/mine', methods=['GET'])
def my_saves():
    client_id = extract_client_id(request=request)
    if not client_id:
        return jsonify({"error": "缺少设备标识 client_id"}), 400
    known_raw = request.args.get("known_player_ids", "")
    known_ids = parse_known_player_ids(known_raw)
    return _list_saves_for_client(client_id, known_ids)


@app.route('/api/rank/petition', methods=['POST'])
def rank_petition_api():
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    action = data.get('action', '')
    target = data.get('target')
    candidate = data.get('candidate')
    result, message = process_rank_petition(game_state, action, target, candidate)
    if not result:
        game_state.remaining_actions += 1
        return jsonify({"error": message}), 400
    autosave_session(player_id)
    return jsonify({
        "success": True,
        "message": message,
        "result": result,
        "authority": queen_authority(game_state),
        "remaining_actions": game_state.remaining_actions,
        "player_rank": game_state.get_display_rank(),
        "target": game_state.npcs.get(target, {}) if target else None,
        "assistant": getattr(game_state, 'six_palace_assistant', None),
    })

@app.route('/api/save', methods=['POST'])
def save_game():
    data = request.get_json()
    player_id = data.get('player_id')
    slot_name = data.get('slot_name', 'default')
    if not player_id:
        return jsonify({"error": "缺少玩家ID"}), 400
    client_id = extract_client_id(request, data)
    if not client_id:
        return jsonify({"error": "缺少设备标识 client_id"}), 400
    known_ids = parse_known_player_ids(data.get("known_player_ids"))
    game_state, err = session_or_404(player_id, "会话不存在")
    if err:
        return err
    session_cid = getattr(game_state, "client_id", None)
    if session_cid and session_cid != client_id:
        return jsonify({"error": "会话与当前设备不匹配，无法保存"}), 403
    filename = os.path.join(SAVE_DIR, f"{player_id}_{slot_name}.json")
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            if not save_belongs_to_client(existing, client_id, known_ids):
                return jsonify({"error": "无权保存到该存档"}), 403
        except Exception:
            return jsonify({"error": "存档数据损坏"}), 500
    ensure_game_state_client_id(game_state, client_id)
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
    client_id = extract_client_id(request, data)
    if not client_id:
        return jsonify({"error": "缺少设备标识 client_id"}), 400
    known_ids = parse_known_player_ids(data.get("known_player_ids"))
    filename = os.path.join(SAVE_DIR, f"{player_id}_{slot_name}.json")
    if not os.path.exists(filename):
        return jsonify({"error": f"存档不存在: {slot_name}"}), 404
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            save_data = json.load(f)
        if not save_belongs_to_client(save_data, client_id, known_ids):
            return jsonify({"error": "无权读取该存档（可能属于其他设备）"}), 403
        if "game_state" not in save_data:
            return jsonify({"error": "存档数据损坏"}), 500
        game_state = GameState.from_save_data(save_data)
        ensure_game_state_client_id(game_state, client_id)
        if not hasattr(game_state, 'npcs') or not game_state.npcs:
            game_state.npcs = generate_all_npcs(10, surname=royal_surname(game_state))
            for name, npc in game_state.npcs.items():
                if name not in game_state.relationships:
                    game_state.relationships[name] = npc.get("relationship", {"好感":0,"印象":"陌生","互动次数":0})
        if not hasattr(game_state, '_pending_promotion'):
            game_state._pending_promotion = None
        game_state._promotion_done = False
        if not hasattr(game_state, 'scandal_strikes'):
            game_state.scandal_strikes = 0
        if not hasattr(game_state, 'rank_periods'):
            game_state.rank_periods = 0
        ensure_ending_fields(game_state)
        ensure_character_ages(game_state)
        sessions[player_id] = game_state
        api_config = get_user_api_config(request, player_id)
        existing = user_configs.get(player_id, {})
        user_configs[player_id] = {
            "custom_prompt": getattr(game_state, "custom_prompt", "") or existing.get("custom_prompt", ""),
            "romance_mode": getattr(game_state, "romance_mode", False) if hasattr(game_state, "romance_mode") else existing.get("romance_mode", False),
            "api_base": api_config.get("api_base") or existing.get("api_base", "https://cn.jixiangai.xyz/v1"),
            "api_key": api_config.get("api_key") or existing.get("api_key", ""),
            "api_model": api_config.get("api_model") or existing.get("api_model", ""),
        }
        loaded_state = game_state.to_dict()
        loaded_state["dowager"] = game_state.npcs.get("太后")
        loaded_state["empress_status"] = get_empress_requirement_status(game_state)
        return jsonify({"success": True, "message": f"读取存档成功 ({slot_name})", "game_state": loaded_state})
    except Exception as e:
        return jsonify({"error": f"读取存档失败: {str(e)}"}), 500

@app.route('/api/saves/<player_id>', methods=['GET'])
def list_saves(player_id):
    client_id = extract_client_id(request=request)
    if not client_id:
        return jsonify({"saves": [], "error": "缺少设备标识 client_id"}), 400
    known_ids = parse_known_player_ids(request.args.get("known_player_ids", ""))
    saves = []
    pattern = f"{player_id}_"
    if not os.path.exists(SAVE_DIR):
        return jsonify({"saves": []})
    for filename in os.listdir(SAVE_DIR):
        if filename.startswith(pattern) and filename.endswith('.json'):
            try:
                with open(os.path.join(SAVE_DIR, filename), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if client_id and not save_belongs_to_client(data, client_id, known_ids):
                    continue
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
    client_id = extract_client_id(request, data)
    if not client_id:
        return jsonify({"error": "缺少设备标识 client_id"}), 400
    known_ids = parse_known_player_ids(data.get("known_player_ids"))
    filename = os.path.join(SAVE_DIR, f"{player_id}_{slot_name}.json")
    if not os.path.exists(filename):
        return jsonify({"error": "存档不存在"}), 404
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            save_data = json.load(f)
        if not save_belongs_to_client(save_data, client_id, known_ids):
            return jsonify({"error": "无权删除该存档"}), 403
    except Exception:
        return jsonify({"error": "存档数据损坏"}), 500
    os.remove(filename)
    return jsonify({"success": True, "message": f"已删除存档 ({slot_name})"})

@app.route('/api/queen/authority', methods=['GET', 'POST'])
def queen_authority_api():
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id') or request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    authority = queen_authority(game_state)
    if request.method == 'GET':
        targets = [{"name": name, "rank": npc.get("rank", "妃嫔"), "alive": npc.get("alive", True),
                    "manageable": _is_queen_manageable_npc(npc)}
                   for name, npc in game_state.npcs.items()
                   if name != "太后" and npc.get("alive", True)]
        assistant_candidates = []
        if game_state.rank.name == "皇后":
            assistant_candidates.append({"name": game_state.name, "rank": game_state.rank.name, "is_player": True})
        for name, npc in game_state.npcs.items():
            if name == "太后" or not npc.get("alive", True):
                continue
            rank = normalize_rank_name(npc.get("rank", "答应"))
            if rank in RANK_LEVELS and RANK_LEVELS[rank] >= RANK_LEVELS["嫔"] and rank != "皇后":
                assistant_candidates.append({"name": name, "rank": npc.get("rank", "妃嫔"), "is_player": False})
        return jsonify({"success": True, "authority": authority, "targets": targets, "assistant_candidates": assistant_candidates})
    ok, err = guard_action(game_state)
    if not ok:
        return err
    target = data.get('target')
    action = data.get('action', '')
    result, message = apply_queen_authority(game_state, target, action)
    if not result:
        game_state.remaining_actions += 1
        return jsonify({"error": message}), 400
    autosave_session(player_id)
    return jsonify({"success": True, "authority": queen_authority(game_state), "result": result,
                    "message": message, "remaining_actions": game_state.remaining_actions,
                    "target": game_state.npcs.get(target, {})})


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
        ok, err = guard_action(game_state)
        if not ok:
            return err
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
    ok, err = guard_action(game_state)
    if not ok:
        return err
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
    ok, err = guard_action(game_state)
    if not ok:
        return err
    event = generate_palace_conflict(game_state, None, None, api_config.get('api_key'), api_config.get('api_base'), api_config.get('api_model'))
    if not event:
        return jsonify({"error": "没有合适的宫斗对象"}), 400
    game_state.add_memory(f"宫斗事件：{event['narration'][:30]}...")
    autosave_session(player_id)
    return jsonify({
        "success": True, "event": event,
        "attributes": game_state.attributes, "relationships": game_state.relationships,
        "rivalries": game_state.rivalries, "alliances": game_state.alliances,
        "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions,
        "demotion_message": event.get("demotion_message"),
        "npc_demotion_message": event.get("npc_demotion_message"),
        "depose_queen_message": event.get("depose_queen_message"),
        "death_message": event.get("death_message"),
        "ending": event.get("ending"),
        "game_over": bool(event.get("ending")),
        "rank": game_state.rank.name, "display_rank": game_state.get_display_rank(),
    })

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
    ok, err = guard_action(game_state)
    if not ok:
        return err
    if target not in game_state.npcs and target != game_state.name:
        return jsonify({"error": "目标不存在"}), 404
    if target == game_state.name:
        return jsonify({"error": "不能对自己发起宫斗"}), 400
    assist_servants = data.get('assist_servants', [])
    if not isinstance(assist_servants, list):
        assist_servants = []
    assist_servants = [n for n in assist_servants if isinstance(n, str) and n.strip()][:SERVANT_ASSIST_MAX]
    if assist_servants:
        roster = {s.name for s in game_state.get_active_servants()}
        invalid = [n for n in assist_servants if n not in roster]
        if invalid:
            return jsonify({"error": f"宫人不存在或已遣散：{', '.join(invalid)}"}), 400
    event = generate_palace_conflict(
        game_state, game_state.name, target,
        api_config.get('api_key'), api_config.get('api_base'), api_config.get('api_model'),
        conflict_type, assist_servants=assist_servants,
    )
    if not event:
        return jsonify({"error": "宫斗事件生成失败"}), 400
    event["type"] = conflict_type
    game_state.add_memory(f"主动宫斗：{event['narration'][:30]}...")
    autosave_session(player_id)
    return jsonify({
        "success": True, "event": event,
        "attributes": game_state.attributes, "relationships": game_state.relationships,
        "rivalries": game_state.rivalries, "alliances": game_state.alliances,
        "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions,
        "demotion_message": event.get("demotion_message"),
        "npc_demotion_message": event.get("npc_demotion_message"),
        "depose_queen_message": event.get("depose_queen_message"),
        "death_message": event.get("death_message"),
        "ending": event.get("ending"),
        "game_over": bool(event.get("ending")),
        "servants": [s.to_dict() for s in game_state.get_active_servants()],
        "rank": game_state.rank.name, "display_rank": game_state.get_display_rank(),
    })

@app.route('/api/ending', methods=['GET'])
def api_ending():
    """查询当前局的结局与一生回顾。

    未结束时 game_over 为 false，summary 仍返回当前的阶段性统计，
    方便前端做「一生回顾」的实时预览。
    """
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ensure_ending_fields(game_state)
    ending = ending_payload(game_state)
    return jsonify({
        "success": True,
        "game_over": bool(ending),
        "ending": ending,
        "summary": ending["summary"] if ending else build_life_summary(game_state),
        "neglect_periods": getattr(game_state, "neglect_periods", 0),
        "scandal_strikes": getattr(game_state, "scandal_strikes", 0),
        "catalog": [
            {"key": k, "icon": v["icon"], "category": v["category"], "headline": v["headline"]}
            for k, v in ENDINGS.items()
        ],
    })

@app.route('/api/conflict/types', methods=['GET'])
def get_conflict_types():
    return jsonify({"types": [{"key": k, "name": k, "desc": v["desc"]} for k, v in CONFLICT_TYPES.items()]})

@app.route('/api/conflict/targets', methods=['GET'])
def get_conflict_targets():
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    targets = [{"name": name, "rank": npc.get("rank","妃嫔"), "personality": npc.get("personality","未知"), "icon": npc.get("icon","🌸")} for name, npc in game_state.npcs.items() if name != "太后" and npc.get("alive", True)]
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
    ok, err = guard_action(game_state)
    if not ok:
        return err

    if mother_name and mother_name != game_state.name:
        if mother_name not in game_state.npcs:
            return jsonify({"error": "目标不存在"}), 404
        children = game_state.npcs[mother_name].get("children", [])
    else:
        children = game_state.children

    if child_index < 0 or child_index >= len(children):
        return jsonify({"error": "子嗣不存在"}), 404
    child = children[child_index]
    ensure_child_fields(child)
    child_name = child.get("name", "未命名")
    age = int(child.get("age", 0))
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
        child["emperor_favor"] = min(100, child.get("emperor_favor", 30) + random.randint(3, 8))
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 3)
        effects = {"威望": 3}
        narration = f"你为{child_name}赐字「{char}」，威望+3，圣宠亦增"
    elif action == "探望":
        aff_gain = random.randint(4, 10)
        health_gain = random.randint(1, 4)
        child["affection"] = min(100, child.get("affection", 30) + aff_gain)
        child["health"] = min(100, child.get("health", 70) + health_gain)
        child["mood"] = "开心" if child.get("health", 70) < 60 else random.choice(["开心", "平静"])
        effects = {"affection": aff_gain, "health": health_gain}
        lines = [
            f"你亲自探望{child_name}，母子情深，亲密度+{aff_gain}",
            f"你陪{child_name}玩耍，孩童笑颜如花，亲密度+{aff_gain}",
            f"你为{child_name}掖被盖毯，健康+{health_gain}，亲密度+{aff_gain}",
        ]
        narration = random.choice(lines)
    elif action == "教导":
        if age < 4:
            return jsonify({"error": "年纪尚幼，还无法受教", "success": False}), 400
        player_talent = game_state.attributes.get("才情", 50)
        wit_gain = random.randint(3, 8) + player_talent // 25
        talent_gain = random.randint(1, 4)
        child["wit"] = min(100, child.get("wit", 40) + wit_gain)
        child["talent"] = min(100, child.get("talent", 50) + talent_gain)
        child["affection"] = min(100, child.get("affection", 30) + random.randint(2, 6))
        child["mood"] = "闷闷不乐" if child.get("personality") == "倔强叛逆" and random.random() < 0.25 else "平静"
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 2)
        effects = {"wit": wit_gain, "talent": talent_gain, "威望": 2}
        narration = f"你亲自教导{child_name}，学识+{wit_gain}，天资+{talent_gain}，威望+2"
    elif action == "请安":
        if age < 3:
            return jsonify({"error": "年纪太小，尚不能向皇帝请安", "success": False}), 400
        favor_gain = random.randint(5, 14) + child.get("wit", 40) // 20
        child["emperor_favor"] = min(100, child.get("emperor_favor", 30) + favor_gain)
        player_favor = random.randint(3, 8) + favor_gain // 5
        game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + player_favor)
        effects = {"emperor_favor": favor_gain, "宠爱": player_favor}
        narration = f"你带{child_name}向皇帝请安，皇帝龙颜大悦，恩宠+{favor_gain}，你的宠爱+{player_favor}"
    elif action == "延师":
        if game_state.silver < 10:
            return jsonify({"error": "银两不足，延师需10两", "success": False}), 400
        child["tutor_level"] = child.get("tutor_level", 0) + 1
        wit_gain = random.randint(4, 10)
        child["wit"] = min(100, child.get("wit", 40) + wit_gain)
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
        effects = {"wit": wit_gain, "威望": 2, "silver": -10}
        lvl = child.get("tutor_level", 1)
        narration = f"你为{child_name}延请名师（第{lvl}次），学识+{wit_gain}，耗费10银两，威望+2"
    elif action == "赏赐":
        if game_state.silver < 5:
            return jsonify({"error": "银两不足，赏赐需5两", "success": False}), 400
        affection_gain = random.randint(5, 12)
        talent_gain = random.randint(1, 3)
        child["affection"] = min(100, child.get("affection", 0) + affection_gain)
        child["talent"] = min(100, child.get("talent", 50) + talent_gain)
        child["mood"] = "开心"
        game_state.silver = max(0, game_state.silver - 5)
        game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + 3)
        effects = {"宠爱": 3, "silver": -5, "talent": talent_gain}
        narration = f"你赏赐{child_name}珍宝，耗费5银两，宠爱+3，亲密度+{affection_gain}，天资+{talent_gain}"
    elif action == "讲故事":
        if age < 2:
            return jsonify({"error": "年纪尚幼，还听不懂故事", "success": False}), 400
        theme = random.choice(STORY_THEMES)
        aff_gain = random.randint(5, 10)
        wit_gain = random.randint(1, 4) if age >= 4 else 0
        child["affection"] = min(100, child.get("affection", 30) + aff_gain)
        child["mood"] = "开心"
        if wit_gain:
            child["wit"] = min(100, child.get("wit", 40) + wit_gain)
        personality = child.get("personality", "温顺可人")
        lines = [
            f"你讲「{theme}」给{child_name}听，{personality}的{child_name}听得入迷，亲密度+{aff_gain}",
            f"{child_name}依偎在你膝头听「{theme}」，眼中闪着光，亲密度+{aff_gain}",
            f"你轻声讲述「{theme}」，{child_name}咯咯笑着拍手，亲密度+{aff_gain}",
        ]
        narration = random.choice(lines)
        if wit_gain:
            narration += f"，学识+{wit_gain}"
        effects = {"affection": aff_gain}
        if wit_gain:
            effects["wit"] = wit_gain
    elif action == "玩耍":
        if age < 1:
            return jsonify({"error": "尚在襁褓，不宜嬉戏", "success": False}), 400
        aff_gain = random.randint(6, 14)
        health_gain = random.randint(0, 3)
        child["affection"] = min(100, child.get("affection", 30) + aff_gain)
        child["health"] = min(100, child.get("health", 70) + health_gain)
        child["mood"] = random.choice(["开心", "兴奋"])
        play_lines = [
            f"你与{child_name}在院中捉迷藏，欢声笑语，亲密度+{aff_gain}",
            f"你陪{child_name}放风筝，孩童笑颜如花，亲密度+{aff_gain}",
            f"你与{child_name}堆雪人、掷雪球，其乐融融，亲密度+{aff_gain}",
            f"你教{child_name}踢毽子，身手越发矫健，亲密度+{aff_gain}，健康+{health_gain}",
        ]
        narration = random.choice(play_lines)
        effects = {"affection": aff_gain, "health": health_gain}
    elif action == "祈福":
        if game_state.silver < 8:
            return jsonify({"error": "银两不足，祈福需8两", "success": False}), 400
        health_gain = random.randint(8, 18)
        child["health"] = min(100, child.get("health", 70) + health_gain)
        child["mood"] = "平静"
        game_state.silver = max(0, game_state.silver - 8)
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 2)
        effects = {"health": health_gain, "silver": -8, "威望": 2}
        blessing = random.choice(["平安符", "长命锁", "如意结", "辟邪玉"])
        narration = f"你在佛前为{child_name}求得一{blessing}，祈福耗费8两，健康+{health_gain}，威望+2"
    elif action == "习武":
        if child.get("gender") != "皇子":
            return jsonify({"error": "公主无需习武", "success": False}), 400
        if age < 6:
            return jsonify({"error": "年纪尚幼，不宜习武", "success": False}), 400
        health_gain = random.randint(2, 6)
        wit_gain = random.randint(2, 5)
        talent_gain = random.randint(1, 3)
        child["health"] = min(100, child.get("health", 70) + health_gain)
        child["wit"] = min(100, child.get("wit", 40) + wit_gain)
        child["talent"] = min(100, child.get("talent", 50) + talent_gain)
        child["mood"] = "兴奋"
        if random.random() < 0.3:
            fav_gain = random.randint(3, 8)
            child["emperor_favor"] = min(100, child.get("emperor_favor", 30) + fav_gain)
            narration = f"你督促{child_name}习武，皇帝听闻龙颜欣慰，圣宠+{fav_gain}，健康+{health_gain}，学识+{wit_gain}"
            effects = {"health": health_gain, "wit": wit_gain, "emperor_favor": fav_gain}
        else:
            narration = f"你陪{child_name}练剑骑马，身手日渐矫健，健康+{health_gain}，学识+{wit_gain}，天资+{talent_gain}"
            effects = {"health": health_gain, "wit": wit_gain, "talent": talent_gain}
    elif action == "女红":
        if child.get("gender") != "公主":
            return jsonify({"error": "皇子无需女红", "success": False}), 400
        if age < 5:
            return jsonify({"error": "年纪尚幼，还拿不动针线", "success": False}), 400
        talent_gain = random.randint(4, 9)
        aff_gain = random.randint(3, 7)
        child["talent"] = min(100, child.get("talent", 50) + talent_gain)
        child["affection"] = min(100, child.get("affection", 30) + aff_gain)
        child["mood"] = "开心"
        craft = random.choice(["绣花手帕", "香囊", "团扇", "荷包"])
        narration = f"你教{child_name}绣{craft}，针脚渐巧，天资+{talent_gain}，亲密度+{aff_gain}"
        effects = {"talent": talent_gain, "affection": aff_gain}
    else:
        return jsonify({"error": "未知互动"}), 400

    bonus = maybe_child_bonus_event(game_state, child, child_name)
    if bonus:
        narration += f"。{bonus}"
    add_child_event(child, narration)
    game_state.add_memory(narration)
    autosave_session(player_id)
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

# ============================================================
#  子嗣命名 / 改名
# ============================================================

@app.route('/api/child/rename', methods=['POST'])
def child_rename():
    """为自己的子嗣命名或改名。

    mode = 'custom' 时使用 name 字段（1-6 个汉字，自动补国姓、检查重名）；
    mode = 'random' 时按国姓随机取名，且不与宫中现有皇嗣重名。
    仅限玩家亲生或收养在膝下的子嗣，不消耗行动点。
    """
    data = request.get_json() or {}
    player_id = data.get('player_id')
    child_index = data.get('child_index', 0)
    mode = (data.get('mode') or 'custom').strip()
    game_state, err = session_or_404(player_id)
    if err:
        return err

    children = game_state.children
    try:
        child_index = int(child_index)
    except (TypeError, ValueError):
        return jsonify({"error": "子嗣序号有误", "success": False}), 400
    if child_index < 0 or child_index >= len(children):
        return jsonify({"error": "子嗣不存在", "success": False}), 404

    child = children[child_index]
    ensure_child_fields(child)
    old_name = child.get("name", "")

    if mode == 'random':
        new_name = new_child_name(
            child.get("gender", "皇子"),
            game_state,
            extra_used=None,
        )
    else:
        raw = data.get('name')
        new_name, err_msg = validate_child_name(raw, game_state, current_name=old_name)
        if err_msg:
            return jsonify({"error": err_msg, "success": False}), 400

    if new_name == old_name:
        return jsonify({"error": "新名与原名相同", "success": False}), 400

    child["name"] = new_name
    child["named_by_player"] = True
    narration = f"你为{'皇子' if child.get('gender') == '皇子' else '公主'}定名「{new_name}」" if not old_name else f"你将{old_name}更名为「{new_name}」"
    add_child_event(child, f"📜 {narration}")
    game_state.add_memory(narration)
    autosave_session(player_id)
    return jsonify({
        "success": True,
        "narration": narration,
        "name": new_name,
        "old_name": old_name,
        "child": child,
        "children": game_state.children,
    })


# ============================================================
#  子嗣过继系统
# ============================================================

@app.route('/api/child/adopt', methods=['POST'])
def child_adopt():
    """子嗣过继：收养他人之子 / 将己子送养他人抚养 / 归宗 / 接回。

    direction = 'in'     收养 mother_name 的子嗣（child_index）
    direction = 'out'    将自己的子嗣（child_index）送养给 mother_name（须位份高于你）
    direction = 'return' 将自己收养的子嗣归宗，送还生母（child_index 为你的子嗣）
    direction = 'recall' 从养母处接回自己亲生子嗣（child_index 为对方膝下的子嗣）
    """
    data = request.get_json() or {}
    player_id = data.get('player_id')
    direction = data.get('direction')
    mother_name = (data.get('mother_name') or '').strip()
    try:
        child_index = int(data.get('child_index', -1))
    except (TypeError, ValueError):
        return jsonify({"error": "子嗣序号无效", "success": False}), 400
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if direction not in ("in", "out", "return", "recall"):
        return jsonify({"error": "方向参数错误", "success": False}), 400

    ok, err = guard_action(game_state)
    if not ok:
        return err

    my_rank_idx = RANK_LEVELS.get(game_state.rank.name, 0)
    period_label = f"建元{game_state.year}年{game_state.month}月"

    if direction == "in":
        # ---------- 收养他人之子 ----------
        if not mother_name or mother_name not in game_state.npcs:
            return jsonify({"error": "目标妃嫔不存在", "success": False}), 404
        npc = game_state.npcs[mother_name]
        child, pos = resolve_living_child(npc.get("children", []), child_index)
        if child is None:
            return jsonify({"error": "子嗣不存在", "success": False}), 404
        ensure_child_fields(child)
        child_name = child.get("name", "未命名")
        gender = child.get("gender", "皇子")
        age = int(child.get("age", 0) or 0)
        is_orphan = not npc.get("alive", True)
        # 校验
        if age > ADOPT_MAX_AGE:
            return jsonify({"error": f"子嗣已{age}岁，年长不宜再过继", "success": False}), 400
        if my_rank_idx < RANK_LEVELS.get(ADOPT_MIN_RANK, 0):
            return jsonify({"error": f"须{ADOPT_MIN_RANK}及以上位份方可收养子嗣", "success": False}), 400
        if count_living_children(game_state.children) >= ADOPT_MAX_CHILDREN:
            return jsonify({"error": f"后宫子嗣已满（上限{ADOPT_MAX_CHILDREN}人），不宜再收养", "success": False}), 400
        if child.get("adopted_count", 0) >= ADOPT_MAX_TRANSFERS:
            return jsonify({"error": "此子已被过继多次，宗人府不许再行转继", "success": False}), 400
        already_adopted_to_living = False
        if child.get("adoptive_mother") and child["adoptive_mother"] in game_state.npcs:
            if game_state.npcs[child["adoptive_mother"]].get("alive", True) and child["adoptive_mother"] != game_state.name:
                already_adopted_to_living = True
        if already_adopted_to_living:
            return jsonify({"error": "该子嗣已有养母抚养，不便夺爱", "success": False}), 400
        # 生母/养母在世时需其同意
        willingness = adoption_willingness(game_state, npc, child)
        if not is_orphan and willingness < 40:
            rel = game_state.relationships.get(mother_name, {"好感": 0})
            if rel.get("好感", 0) < 40 and my_rank_idx <= RANK_LEVELS.get(npc.get("rank", "答应"), 0):
                return jsonify({"error": f"{mother_name}割舍不下亲子{child_name}，过继未成", "success": False}), 400
        # 皇子（皇嗣）专属：需更高位份 + 皇帝圣宠门槛 + 皇帝恩准
        if gender == "皇子":
            required_rank = ADOPT_PRINCE_MIN_RANK
            if my_rank_idx < RANK_LEVELS.get(required_rank, 0):
                return jsonify({"error": f"皇嗣尊贵，须{required_rank}及以上位份方可收养", "success": False}), 400
            favor = game_state.attributes.get("宠爱", 0)
            if favor < ADOPT_PRINCE_EMPEROR_FAVOR:
                return jsonify({"error": f"圣宠不足（需宠爱≥{ADOPT_PRINCE_EMPEROR_FAVOR}），皇帝不忍皇嗣旁落，暂不允许收养", "success": False}), 400
            approved, emperor_note = should_use_emperor_approval(game_state, child, "in")
            if not approved:
                return jsonify({"error": f"奏请过继皇嗣{child_name}，{emperor_note}，只得作罢", "success": False}), 400
        else:
            approved, emperor_note = should_use_emperor_approval(game_state, child, "in")
            if not approved:
                return jsonify({"error": f"奏请过继{child_name}，{emperor_note}，只得作罢", "success": False}), 400
        # 费用（遗孤减半）
        base_cost = ADOPT_IN_COST_PRINCE if gender == "皇子" else ADOPT_IN_COST
        cost = max(10, base_cost // 2) if is_orphan else base_cost
        if game_state.silver < cost:
            return jsonify({"error": f"银两不足，过继仪式需{cost}两", "success": False}), 400

        # 执行过继
        game_state.silver -= cost
        if pos >= 0:
            npc.get("children", []).pop(pos)
        game_state.children.append(child)
        game_state.has_children = True
        child["adopted"] = True
        child["adopted_count"] = child.get("adopted_count", 0) + 1
        child["birth_mother"] = child.get("birth_mother") or mother_name
        child["adoptive_mother"] = game_state.name
        child["adopted_age"] = age
        child["adopted_at"] = period_label
        child["affection"] = max(10, child.get("affection", 30) - 15) if age >= 1 else random.randint(30, 50)
        child["mood"] = "平静"
        add_adoption_history(child, "收养", mother_name if not is_orphan else f"遗孤·{mother_name}", game_state.name, f"过继仪式{cost}两", game_state.day)

        if is_orphan:
            wei_gain = 10 + (8 if gender == "皇子" else 4)
            fav_gain = 6
            message = f"🕯️ {mother_name}已逝，其子{child_name}孤苦无依。你向皇帝恳请收养遗孤，皇帝赞你仁厚，准其归你抚养。威望+{wei_gain}，宠爱+{fav_gain}"
            if "太后" in game_state.relationships:
                game_state.relationships["太后"]["好感"] = min(100, game_state.relationships["太后"].get("好感", 25) + 5)
        else:
            wei_gain = 10 + (6 if gender == "皇子" else 2)
            fav_gain = 4
            message = f"📜 经皇帝恩准，{mother_name}所出{gender}{child_name}过继至你膝下抚养，威望+{wei_gain}，宠爱+{fav_gain}"
            if mother_name in game_state.relationships:
                game_state.relationships[mother_name]["好感"] = max(-100, game_state.relationships[mother_name].get("好感", 0) - random.randint(15, 25))
                game_state.relationships[mother_name]["印象"] = "怨恨"
            npc["压力"] = min(100, npc.get("压力", 0) + random.randint(8, 15))
            message += f"。{mother_name}虽万般不舍，亦无可奈何"
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + wei_gain)
        game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + fav_gain)
        add_child_event(child, message)
        game_state.add_memory(message)
        narration = message

    elif direction == "out":
        # ---------- 送养己子 ----------
        if not mother_name or mother_name not in game_state.npcs:
            return jsonify({"error": "目标妃嫔不存在", "success": False}), 404
        target = game_state.npcs[mother_name]
        if not target.get("alive", True):
            return jsonify({"error": "对方已不在人世", "success": False}), 400
        child, pos = resolve_living_child(game_state.children, child_index)
        if child is None:
            return jsonify({"error": "子嗣不存在", "success": False}), 404
        ensure_child_fields(child)
        child_name = child.get("name", "未命名")
        gender = child.get("gender", "皇子")
        age = int(child.get("age", 0) or 0)
        if age > ADOPT_MAX_AGE:
            return jsonify({"error": f"子嗣已{age}岁，年长不宜再过继", "success": False}), 400
        if child.get("adopted_count", 0) >= ADOPT_MAX_TRANSFERS:
            return jsonify({"error": "此子已被过继多次，宗人府不许再行转继", "success": False}), 400
        target_rank_idx = RANK_LEVELS.get(target.get("rank", "答应"), 0)
        if target_rank_idx < RANK_LEVELS.get(ADOPT_TARGET_MIN_RANK, 0):
            return jsonify({"error": f"对方位份不足，须{ADOPT_TARGET_MIN_RANK}及以上方可抚养皇嗣", "success": False}), 400
        if target_rank_idx <= my_rank_idx and target.get("rank") != "皇后":
            return jsonify({"error": "对方位份未高于你，按宫规不可将皇嗣托付给她抚养", "success": False}), 400
        if game_state.rank.name == "皇后":
            return jsonify({"error": "你贵为皇后，所出皆为嫡出，不可送养", "success": False}), 400
        if count_living_children(target.get("children", [])) >= ADOPT_MAX_CHILDREN:
            return jsonify({"error": "对方子嗣已满", "success": False}), 400
        # 对方是否愿意收养
        want_flag = target.get("wants_adopt_player_child")
        willing_recv = receiver_willingness(game_state, target, child)
        if want_flag is not None:
            willing_recv = max(willing_recv, 80)   # 对方正有此意，乐见其成
        rel = game_state.relationships.get(mother_name, {"好感": 0})
        if willing_recv < 35 and rel.get("好感", 0) < 30:
            return jsonify({"error": f"{mother_name}以膝下已可照拂婉拒了你的托付", "success": False}), 400
        cost = ADOPT_OUT_COST_PRINCE if gender == "皇子" else ADOPT_OUT_COST
        if want_flag is not None:
            cost = max(10, cost - 10)   # 对方主动求子，礼金减免
        if game_state.silver < cost:
            return jsonify({"error": f"银两不足，过继仪式需{cost}两", "success": False}), 400

        game_state.silver -= cost
        if pos >= 0:
            game_state.children.pop(pos)
        target.setdefault("children", []).append(child)
        if want_flag is not None:
            target.pop("wants_adopt_player_child", None)
        if not game_state.children:
            game_state.has_children = False
        child["adopted"] = True
        child["adopted_count"] = child.get("adopted_count", 0) + 1
        child["birth_mother"] = child.get("birth_mother") or game_state.name
        child["adoptive_mother"] = mother_name
        child["adopted_age"] = age
        child["adopted_at"] = period_label
        child["affection"] = max(10, random.randint(25, 45))
        child["mood"] = "思念"
        add_adoption_history(child, "送养", game_state.name, mother_name, f"仪式{cost}两", game_state.day)

        wei_gain = 3
        fav_gain = 8
        if mother_name in game_state.relationships:
            game_state.relationships[mother_name]["好感"] = min(100, game_state.relationships[mother_name].get("好感", 0) + 18)
            game_state.relationships[mother_name]["印象"] = "感激"
        target["压力"] = max(0, target.get("压力", 0) - random.randint(5, 10))
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + wei_gain)
        game_state.attributes["宠爱"] = max(0, game_state.attributes.get("宠爱", 0) - fav_gain)
        if gender == "皇子":
            game_state.attributes["威望"] = max(0, game_state.attributes.get("威望", 0) - 3)
        message = f"📜 你奏请将{gender}{child_name}过继给{mother_name}抚养。对方感激涕零，好感+18，你的贡献威望+{wei_gain}，宠爱-{fav_gain}"
        message += f"。纵然不舍，为孩子的将来，你忍痛割爱"
        add_child_event(child, message)
        game_state.add_memory(message)
        narration = message

    elif direction == "return":
        # ---------- 归宗：将自己收养的子嗣送还生母 ----------
        child, pos = resolve_living_child(game_state.children, child_index)
        if child is None:
            return jsonify({"error": "子嗣不存在", "success": False}), 404
        ensure_child_fields(child)
        if not child.get("adopted", False) or child.get("adoptive_mother") != game_state.name:
            return jsonify({"error": "此子并非过继在你膝下，无需归宗", "success": False}), 400
        birth_mother = child.get("birth_mother")
        if not birth_mother or birth_mother == game_state.name or birth_mother not in game_state.npcs:
            return jsonify({"error": "生母不在宫中，无法归宗", "success": False}), 400
        bm_npc = game_state.npcs[birth_mother]
        if not bm_npc.get("alive", True):
            return jsonify({"error": "生母已然仙逝，此子只能由你养育到底", "success": False}), 400
        if count_living_children(bm_npc.get("children", [])) >= ADOPT_MAX_CHILDREN:
            return jsonify({"error": "生母膝下子嗣已满，暂难迎回", "success": False}), 400
        # 皇嗣（皇子）归宗须皇帝恩准，以免动摇宗谱
        child_name = child.get("name", "未命名")
        if child.get("gender") == "皇子":
            approved, emperor_note = should_use_emperor_approval(game_state, child, "return")
            if not approved:
                return jsonify({"error": f"奏请皇嗣{child_name}归宗，{emperor_note}，只得作罢", "success": False}), 400
        if game_state.silver < ADOPT_RETURN_COST:
            return jsonify({"error": f"银两不足，归宗仪式需{ADOPT_RETURN_COST}两", "success": False}), 400
        game_state.silver -= ADOPT_RETURN_COST
        if pos >= 0:
            game_state.children.pop(pos)
        bm_npc.setdefault("children", []).append(child)
        if not game_state.children:
            game_state.has_children = False
        child["adopted"] = False
        child["adoptive_mother"] = ""
        child["adopted_count"] = child.get("adopted_count", 0) + 1
        child["via_return"] = True
        child["mood"] = "兴奋"
        add_adoption_history(child, "归宗", game_state.name, birth_mother, f"归宗仪式{ADOPT_RETURN_COST}两", game_state.day)
        if birth_mother in game_state.relationships:
            game_state.relationships[birth_mother]["好感"] = min(100, game_state.relationships[birth_mother].get("好感", 0) + 15)
            game_state.relationships[birth_mother]["印象"] = "感激"
        bm_npc["压力"] = max(0, bm_npc.get("压力", 0) - random.randint(5, 10))
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 3)
        message = f"📜 你将养子{child_name}归宗，送还生母{birth_mother}膝下，骨肉团聚，威望+3"
        add_child_event(child, message)
        game_state.add_memory(message)
        narration = message

    else:
        # ---------- 接回：从养母处接回自己亲生子嗣 ----------
        if not mother_name or mother_name not in game_state.npcs:
            return jsonify({"error": "目标妃嫔不存在", "success": False}), 404
        npc = game_state.npcs[mother_name]
        child, pos = resolve_living_child(npc.get("children", []), child_index)
        if child is None:
            return jsonify({"error": "子嗣不存在", "success": False}), 404
        ensure_child_fields(child)
        child_name = child.get("name", "未命名")
        gender = child.get("gender", "皇子")
        age = int(child.get("age", 0) or 0)
        if not child.get("adoptive_mother") == mother_name:
            return jsonify({"error": "此子并非由对方抚养，无法接回", "success": False}), 400
        if not child.get("birth_mother") == game_state.name:
            return jsonify({"error": "此子并非你亲生，不可接回", "success": False}), 400
        if age > ADOPT_MAX_AGE:
            return jsonify({"error": f"子嗣已{age}岁，特尔宗已建档，不易归还", "success": False}), 400
        if count_living_children(game_state.children) >= ADOPT_MAX_CHILDREN:
            return jsonify({"error": "你膝下子嗣已满", "success": False}), 400
        # 皇嗣（皇子）接回亦须皇帝恩准，以免皇嗣归属反复
        if gender == "皇子":
            approved, emperor_note = should_use_emperor_approval(game_state, child, "recall")
            if not approved:
                return jsonify({"error": f"奏请接回皇嗣{child_name}，{emperor_note}，只得作罢", "success": False}), 400
        # 对方是否愿意放手
        if npc.get("alive", True):
            rel = game_state.relationships.get(mother_name, {"好感": 0}).get("好感", 0)
            willing = receiver_keep_willingness(game_state, npc, child, rel)
            if willing < 40 and my_rank_idx <= RANK_LEVELS.get(npc.get("rank", "答应"), 0):
                return jsonify({"error": f"{mother_name}视{child_name}如己出，不肯放手，还请改日再议", "success": False}), 400
        cost = ADOPT_BACK_COST
        if npc.get("alive", True):
            cost = max(10, cost // 2)
        if game_state.silver < cost:
            return jsonify({"error": f"银两不足，接回仪式需{cost}两", "success": False}), 400
        game_state.silver -= cost
        if pos >= 0:
            npc.get("children", []).pop(pos)
        game_state.children.append(child)
        game_state.has_children = True
        child["adopted"] = False
        child["adoptive_mother"] = ""
        child["adopted_count"] = child.get("adopted_count", 0) + 1
        child["mood"] = "开心"
        add_adoption_history(child, "接回", mother_name, game_state.name, f"接回仪式{cost}两", game_state.day)
        if npc.get("alive", True):
            if mother_name in game_state.relationships:
                game_state.relationships[mother_name]["好感"] = max(-100, game_state.relationships[mother_name].get("好感", 0) - random.randint(12, 22))
                game_state.relationships[mother_name]["印象"] = "怨怼"
            npc["压力"] = min(100, npc.get("压力", 0) + random.randint(5, 10))
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 4)
        message = f"📜 你奏请将{gender}{child_name}从{mother_name}处接回：孩子扑进你怀中，亲热地喊「母妃」，排除了分离的阴霾。威望+4"
        add_child_event(child, message)
        game_state.add_memory(message)
        narration = message

    ensure_character_ages(game_state)
    autosave_session(player_id)
    return jsonify({
        "success": True,
        "narration": narration,
        "age": game_state.age,
        "children": game_state.children,
        "has_children": game_state.has_children,
        "npcs": serialize_npcs_for_client(game_state),
        "attributes": game_state.attributes,
        "relationships": game_state.relationships,
        "silver": game_state.silver,
        "remaining_actions": game_state.remaining_actions,
        "max_actions": game_state.max_actions,
    })

# ============================================================
#  立储/废储、徽号、宫殿分配 API
# ============================================================

@app.route('/api/heir', methods=['POST'])
def set_heir():
    """立储/废储。action: 'set' 立储 / 'clear' 废储。child_uid 指定子嗣。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    action = data.get('action', 'set')
    child_uid = data.get('child_uid')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)

    if not isinstance(game_state.heir_status, dict):
        game_state.heir_status = default_heir_status()

    if action == 'clear':
        old = get_heir_child(game_state)
        game_state.heir_status = default_heir_status()
        message = "📜 皇帝降旨废储，储君之位悬空。" if old else "储君之位本为空悬，无需废立。"
        if old:
            game_state.add_memory(f"📜 {old.get('name','皇子')}被废黜储君之位")
            for c in game_state.children:
                if c.get("name") == old.get("name"):
                    c["mood"] = "低落"
        return jsonify({"success": True, "narration": message, "heir_status": game_state.heir_status})

    if not child_uid:
        return jsonify({"error": "缺少子嗣标识 child_uid", "success": False}), 400

    # 查找子嗣
    child = None
    child_mother = ""
    for c in game_state.children:
        if str(c.get("uid")) == str(child_uid) or c.get("name") == child_uid:
            child = c
            child_mother = game_state.name
            break
    if child is None:
        for name, npc in game_state.npcs.items():
            for c in npc.get("children", []):
                if str(c.get("uid")) == str(child_uid) or c.get("name") == child_uid:
                    child = c
                    child_mother = name
                    break
            if child is not None:
                break
    if child is None:
        return jsonify({"error": "子嗣不存在", "success": False}), 404
    ensure_child_fields(child)

    # 校验：仅限皇子
    if child.get("gender") != "皇子":
        return jsonify({"error": "只有皇子方可立为储君", "success": False}), 400
    if not child.get("alive", True):
        return jsonify({"error": "此子已不在人世，无法立储", "success": False}), 400
    # 校验：玩家需位份与宠爱
    rank_idx = RANK_LEVELS.get(game_state.rank.name, 0)
    if rank_idx < RANK_LEVELS.get("嫔", 0):
        return jsonify({"error": "位份不足，须嫔及以上方可奏请立储", "success": False}), 400
    favor = game_state.attributes.get("宠爱", 0)
    if favor < 40:
        return jsonify({"error": "圣宠不足（需宠爱≥40），皇帝对储君人选另有考量", "success": False}), 400
    # 校验：储君是否已存在
    if (game_state.heir_status or {}).get("heir_id"):
        return jsonify({"error": "已有储君在册，废立乃国之大事，不宜轻动", "success": False}), 400
    # 皇帝在世才可立储
    if not (game_state.emperor or {}).get("alive", True):
        return jsonify({"error": "先帝已崩，无需再立储君", "success": False}), 400

    # 立储成功
    child_uid_str = str(child.get("uid") or child.get("name") or "")
    game_state.heir_status = {
        "heir_id": child_uid_str,
        "heir_name": child.get("name", "皇子"),
        "heir_mother": child.get("birth_mother") or child_mother,
        "regent": "",
        "regent_title": "",
        "established_at": f"建元{game_state.year}年{game_state.month}月",
        "last_event": "册立太子",
        "deposed": (game_state.heir_status or {}).get("deposed", []) if isinstance((game_state.heir_status or {}).get("deposed", []), list) else [],
        "regent_active": False,
    }
    child["is_heir"] = True
    child["mood"] = "意气风发"
    # 威望与宠爱变化
    game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 10)
    if child_mother in game_state.relationships and child_mother != game_state.name:
        game_state.relationships[child_mother]["好感"] = min(100, game_state.relationships[child_mother].get("好感", 0) + 20)
        game_state.relationships[child_mother]["印象"] = "感激"
    message = f"👑 皇帝御笔亲书，册立皇子{child.get('name','')}为太子！你母凭子贵，威望+10"
    if child_mother == game_state.name:
        message += "，阖宫侧目"
    game_state.add_memory(message)
    return jsonify({
        "success": True,
        "narration": message,
        "heir_status": game_state.heir_status,
        "child": child,
        "attributes": game_state.attributes,
    })

@app.route('/api/honor', methods=['POST'])
def grant_honor():
    """赐徽号/撤徽号。action: 'grant' 赐 / 'revoke' 撤。child_uid + honor_title。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    action = data.get('action', 'grant')
    child_uid = data.get('child_uid')
    honor_title = (data.get('honor_title') or '').strip()
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)

    child = None
    for c in game_state.children:
        if str(c.get("uid")) == str(child_uid) or c.get("name") == child_uid:
            child = c
            break
    if child is None:
        for name, npc in game_state.npcs.items():
            for c in npc.get("children", []):
                if str(c.get("uid")) == str(child_uid) or c.get("name") == child_uid:
                    child = c
                    break
            if child is not None:
                break
    if child is None:
        return jsonify({"error": "子嗣不存在", "success": False}), 404
    ensure_child_fields(child)

    if action == 'revoke':
        old_title = child.get("honorary_title")
        if not old_title:
            return jsonify({"error": "此子并无徽号", "success": False}), 400
        child["honorary_title"] = None
        message = f"📜 皇帝收回了{child.get('name','皇子')}的徽号「{old_title}」。"
        game_state.add_memory(message)
        return jsonify({"success": True, "narration": message, "child": child})

    # 赐徽号
    if not honor_title or len(honor_title) > 3:
        return jsonify({"error": "徽号须为1~3个字", "success": False}), 400
    # 皇帝在世才可赐徽号
    if not (game_state.emperor or {}).get("alive", True):
        return jsonify({"error": "先帝已崩，新朝自有新徽号", "success": False}), 400
    rank_idx = RANK_LEVELS.get(game_state.rank.name, 0)
    if rank_idx < RANK_LEVELS.get("嫔", 0):
        return jsonify({"error": "位份不足，须嫔及以上方可奏请徽号", "success": False}), 400
    if game_state.silver < 20:
        return jsonify({"error": "银两不足，请封徽号需20两", "success": False}), 400
    game_state.silver -= 20
    child["honorary_title"] = honor_title
    child["mood"] = "得意"
    # 若是储君，威望提升更多
    wei_gain = 8 if child.get("is_heir") or (game_state.heir_status or {}).get("heir_id") == str(child.get("uid")) else 4
    game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + wei_gain)
    message = f"🏮 你奏请皇帝为皇子{child.get('name','')}赐徽号「{honor_title}」，皇帝欣然应允，耗费20两，威望+{wei_gain}"
    game_state.add_memory(message)
    return jsonify({
        "success": True,
        "narration": message,
        "child": child,
        "attributes": game_state.attributes,
        "silver": game_state.silver,
    })

@app.route('/api/palace', methods=['POST'])
def assign_palace():
    """宫殿分配。action: 'assign' 分配 / 'vacate' 迁出。child_uid + palace_name。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    action = data.get('action', 'assign')
    child_uid = data.get('child_uid')
    palace_name = (data.get('palace_name') or '').strip()
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)

    child = None
    for c in game_state.children:
        if str(c.get("uid")) == str(child_uid) or c.get("name") == child_uid:
            child = c
            break
    if child is None:
        for name, npc in game_state.npcs.items():
            for c in npc.get("children", []):
                if str(c.get("uid")) == str(child_uid) or c.get("name") == child_uid:
                    child = c
                    break
            if child is not None:
                break
    if child is None:
        return jsonify({"error": "子嗣不存在", "success": False}), 404
    ensure_child_fields(child)

    if action == 'vacate':
        old_palace = child.get("palace")
        if not old_palace:
            return jsonify({"error": "此子并无宫殿居所", "success": False}), 400
        child["palace"] = ""
        message = f"🏛️ 你为皇子{child.get('name','')}奏请迁出{old_palace}。"
        game_state.add_memory(message)
        return jsonify({"success": True, "narration": message, "child": child})

    # 分配宫殿
    if not palace_name or palace_name not in PALACE_LIST:
        return jsonify({"error": "宫殿不在可选之列", "success": False}), 400
    if not (game_state.emperor or {}).get("alive", True):
        return jsonify({"error": "先帝已崩，宫殿由新朝另行安排", "success": False}), 400
    rank_idx = RANK_LEVELS.get(game_state.rank.name, 0)
    if rank_idx < RANK_LEVELS.get("嫔", 0):
        return jsonify({"error": "位份不足，须嫔及以上方可奏请宫殿", "success": False}), 400
    if game_state.silver < 15:
        return jsonify({"error": "银两不足，修缮宫殿需15两", "success": False}), 400
    # 检查宫殿是否已被他人占用
    occupied_by = None
    for c in game_state.children:
        if c.get("palace") == palace_name and str(c.get("uid")) != str(child.get("uid")):
            occupied_by = c.get("name")
            break
    if occupied_by is None:
        for name, npc in game_state.npcs.items():
            for c in npc.get("children", []):
                if c.get("palace") == palace_name and str(c.get("uid")) != str(child.get("uid")):
                    occupied_by = c.get("name")
                    break
            if occupied_by is not None:
                break
    if occupied_by:
        return jsonify({"error": f"{palace_name}已有主（{occupied_by}），不可再分配", "success": False}), 400

    game_state.silver -= 15
    old_palace = child.get("palace")
    child["palace"] = palace_name
    child["mood"] = "安稳"
    wei_gain = 5 if child.get("is_heir") or (game_state.heir_status or {}).get("heir_id") == str(child.get("uid")) else 2
    game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + wei_gain)
    moved = f"自{old_palace}迁入" if old_palace else "入住"
    message = f"🏛️ 你奏请为皇子{child.get('name','')}安排{palace_name}，皇帝允准，{moved}，耗费15两，威望+{wei_gain}"
    game_state.add_memory(message)
    return jsonify({
        "success": True,
        "narration": message,
        "child": child,
        "attributes": game_state.attributes,
        "silver": game_state.silver,
    })

@app.route('/api/abort', methods=['POST'])
def abort_pregnancy():
    data = request.get_json()
    player_id = data.get('player_id')
    target = data.get('target')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
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
@app.route('/api/chonghua', methods=['GET'])
def get_chonghua():
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ch = game_state.chonghua or {"founded": False, "level": 1, "budget": 0, "children": [], "log": []}
    game_state.chonghua = ch
    # 权限判断：皇后/皇贵妃/贵妃 或 协理六宫 可管理全部子嗣
    rank_name = ''
    try:
        rank_name = game_state.rank.name if hasattr(game_state.rank, 'name') else str(game_state.rank)
    except:
        rank_name = ''
    manage_ranks = ['皇后', '皇贵妃', '贵妃']
    has_permission = rank_name in manage_ranks or bool(getattr(game_state, 'manage_six_palaces', False))
    # 自动收容：重华宫已开设且子嗣年幼则自动入馆
    if ch.get('founded'):
        # 遍历范围依据权限
        pools = [getattr(game_state, 'children', [])]
        if has_permission:
            for npc in getattr(game_state, 'npcs', {}).values():
                children = npc.get('children', []) if isinstance(npc, dict) else []
                if children:
                    pools.append(children)
        for pool in pools:
            for c in pool:
                if not c.get('alive', True):
                    continue
                if c.get('in_chonghua'):
                    continue
                age = int(c.get('age', 0) or 0)
                if age <= 3:
                    c['in_chonghua'] = True
                    c['chonghua_since'] = f'{getattr(game_state, "year", 0)}年{getattr(game_state, "month", 0)}月'
                    ch.setdefault('log', []).append({'msg': f'{c.get("name")}自动入馆', 'time': getattr(game_state, 'day', 0)})
    # 汇总子嗣列表
    children = []
    seen = set()
    def add_child_from_pool(pool):
        for c in pool:
            if not c.get('alive', True):
                continue
            uid = c.get('uid') or c.get('name')
            key = (uid, c.get('name'))
            if key in seen:
                continue
            seen.add(key)
            children.append({
                'uid': uid,
                'name': c.get('name'),
                'age': c.get('age', 0),
                'gender': c.get('gender', ''),
                'in_chonghua': bool(c.get('in_chonghua', False)),
                'palace': c.get('palace', ''),
                'mother': c.get('mother', '')
            })
    add_child_from_pool(getattr(game_state, 'children', []))
    if has_permission:
        for npc in getattr(game_state, 'npcs', {}).values():
            children_pool = npc.get('children', []) if isinstance(npc, dict) else []
            add_child_from_pool(children_pool)
    ch_copy = dict(ch)
    ch_copy['children'] = children
    info = {
        'manage_ranks': manage_ranks,
        'min_prestige': 80,
        'found_cost': 200,
        'has_permission': has_permission
    }
    return jsonify({'chonghua': ch_copy, 'info': info})

@app.route('/api/chonghua/action', methods=['POST'])
def chonghua_action():
    data = request.get_json() or {}
    player_id = data.get('player_id')
    action = data.get('action')
    uid = data.get('uid')
    amount = data.get('amount', 0)
    game_state, err = session_or_404(player_id)
    if err:
        return err
    # chonghua 操作不消耗行动点
    ch = game_state.chonghua or {"founded": False, "level": 1, "budget": 0, "children": [], "log": []}
    game_state.chonghua = ch
    def add_log(msg):
        ch.setdefault('log', []).append({'msg': msg, 'time': getattr(game_state, 'day', 0)})
        if len(ch['log']) > 50:
            ch['log'] = ch['log'][-50:]
    if action == 'found':
        if ch.get('founded'):
            return jsonify({'success': False, 'error': '重华宫已开设'}), 400
        if game_state.attributes.get('威望', 0) < 80:
            return jsonify({'success': False, 'error': '威望不足'}), 400
        if game_state.silver < 200:
            return jsonify({'success': False, 'error': '银两不足'}), 400
        game_state.silver -= 200
        ch['founded'] = True
        ch['level'] = 1
        ch['budget'] = 0
        add_log('重华宫开设成功')
        return jsonify({'success': True, 'message': '重华宫开设成功，耗费200两', 'silver': game_state.silver, 'chonghua': ch})
    if action == 'upgrade':
        if not ch.get('founded'):
            return jsonify({'success': False, 'error': '未开设'}), 400
        cost = 300 * ch.get('level', 1)
        if game_state.silver < cost:
            return jsonify({'success': False, 'error': '银两不足'}), 400
        game_state.silver -= cost
        ch['level'] = ch.get('level', 1) + 1
        add_log(f'重华宫扩建至等级{ch["level"]}')
        return jsonify({'success': True, 'message': f'扩建成功，等级提升至{ch["level"]}，耗费{cost}两', 'silver': game_state.silver, 'chonghua': ch})
    if action == 'patronize':
        if not ch.get('founded'):
            return jsonify({'success': False, 'error': '未开设'}), 400
        amt = int(amount or 0)
        if amt <= 0:
            return jsonify({'success': False, 'error': '金额无效'}), 400
        if game_state.silver < amt:
            return jsonify({'success': False, 'error': '银两不足'}), 400
        game_state.silver -= amt
        ch['budget'] = ch.get('budget', 0) + amt
        add_log(f'拨用度{amt}两')
        return jsonify({'success': True, 'message': f'拨用度{amt}两成功', 'silver': game_state.silver, 'chonghua': ch})
    # child operations
    if action in ('admit', 'tutor', 'adopt', 'release'):
        if not ch.get('founded'):
            return jsonify({'success': False, 'error': '未开设'}), 400
        # 权限判断
        rank_name = ''
        try:
            rank_name = game_state.rank.name if hasattr(game_state.rank, 'name') else str(game_state.rank)
        except:
            rank_name = ''
        manage_ranks = ['皇后', '皇贵妃', '贵妃']
        has_permission = rank_name in manage_ranks or bool(getattr(game_state, 'manage_six_palaces', False))
        # 查找目标子嗣
        child = None
        def find_child(uid):
            # 先找玩家自有
            for c in getattr(game_state, 'children', []):
                if c.get('name') == uid or str(c.get('uid')) == str(uid):
                    return c
            if has_permission:
                for npc in getattr(game_state, 'npcs', {}).values():
                    for c in npc.get('children', []) if isinstance(npc, dict) else []:
                        if c.get('name') == uid or str(c.get('uid')) == str(uid):
                            return c
            return None
        child = find_child(uid)
        if not child:
            return jsonify({'success': False, 'error': '子嗣不存在'}), 404
        # 计算在馆人数
        def count_inside():
            cnt = 0
            for c in getattr(game_state, 'children', []):
                if c.get('in_chonghua'):
                    cnt += 1
            if has_permission:
                for npc in getattr(game_state, 'npcs', {}).values():
                    for c in npc.get('children', []) if isinstance(npc, dict) else []:
                        if c.get('in_chonghua'):
                            cnt += 1
            return cnt
        if action == 'admit':
            if child.get('in_chonghua'):
                return jsonify({'success': False, 'error': '已在馆'}), 400
            capacity = ch.get('level', 1) * 2
            inside = count_inside()
            if inside >= capacity:
                return jsonify({'success': False, 'error': '容量已满'}), 400
            child['in_chonghua'] = True
            child['chonghua_since'] = f'{getattr(game_state, "year", 0)}年{getattr(game_state, "month", 0)}月'
            add_log(f'{child.get("name")}入馆')
            return jsonify({'success': True, 'message': f'{child.get("name")}已收容至重华宫', 'chonghua': ch})
        if action == 'release':
            if not child.get('in_chonghua'):
                return jsonify({'success': False, 'error': '不在馆'}), 400
            child['in_chonghua'] = False
            child.pop('chonghua_since', None)
            add_log(f'{child.get("name")}迁出')
            return jsonify({'success': True, 'message': f'{child.get("name")}已迁出', 'chonghua': ch})
        if action == 'tutor':
            if not child.get('in_chonghua'):
                return jsonify({'success': False, 'error': '不在馆'}), 400
            add_log(f'{child.get("name")}授业')
            return jsonify({'success': True, 'message': f'为{child.get("name")}授业', 'chonghua': ch})
        if action == 'adopt':
            child['adoptive_mother'] = game_state.name
            add_log(f'{child.get("name")}过继')
            return jsonify({'success': True, 'message': f'{child.get("name")}过继归名', 'chonghua': ch})
    return jsonify({'success': False, 'error': '未知操作'}), 400


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
    print("Fengyi Game Backend v1.4.0")
    print("=" * 60)
    print(f"Open: http://0.0.0.0:{port}")
    print("Frontend and API are served from the same origin")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=debug)