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
from models import GameState, Rank, Storyline, Servant, RANK_ORDER, FOUR_CONSORT_TITLES, ORDINARY_NOBLETITLES, NOBLETITLES, normalize_rank_name, get_rank_power, is_four_consort_title, default_heir_status, COURT_FACTIONS, normalize_court_faction_favor, default_heir_race, normalize_heir_race, normalize_inner_palace, RANK_POWER
from models import (
    default_heir_consorts, default_heir_consort_member,
    normalize_heir_consorts, normalize_heir_status,
)
from scenarios import START_SCENARIOS, apply_scenario
from events import (
    get_daily_actions, apply_daily_action,
    generate_regency_event, find_regency_event,
    generate_heir_rebellion_event, generate_heir_special_event,
    generate_incognito_adventure, generate_consort_selection_event,
    find_consort_candidate, generate_consort_conflict_event,
    generate_consort_fun_event,
)
from heir_content import (
    HEIR_CONSORT_RANKS, HEIR_CONSORT_LIMITS, HEIR_CONSORT_GRADE,
    HEIR_CONSORT_MAX_TOTAL, HEIR_CONSORT_PERSONALITIES,
    HEIR_CONSORT_FUN_TAGS, HEIR_CONSORT_ENTRY_FLAVOR,
    HEIR_DEFIANCE_CHAIN,
)
from names import (
    generate_female_name, generate_emperor_name_local, generate_child_name,
    generate_servant_name, extract_surname, NPC_SURNAMES,
    CHILD_GIVEN_NAME_CATEGORIES, CHILD_GIVEN_CHARS, is_valid_given_char,
)
from confidant_events import get_random_confidant_event, trigger_confidant_event, pick_confidant_target
from recommend_system import (
    METHODS,
    compute_rate, player_recommend, attach_npc_recommendations,
    resolve_npc_recommendations, interfere_npc_rec, remedy as recommend_remedy,
    tick_recommendations, sync_edition, recommend_payload, eligibility_blockers,
)
from royal_clan import (
    seed_royal_clan, get_royal_clan, process_royal_clan_period,
    royal_overview_payload, royal_male_action, royal_female_action,
    respond_royal_pending,
)
from cold_palace import (
    is_player_imprisoned,
    enter_cold_palace, player_self_action, player_release_attempt,
    interact_inmate, cold_manage, cold_period_tick, cold_overview_payload,
)
from dowager_system import (
    is_dowager_active, enter_dowager_mode, generate_court_affairs,
    respond_court_affair, dowager_action, return_power,
    dowager_period_tick, dowager_payload, get_dowager,
    set_harem_mode, harem_action, HAREM_MODES,
    respond_meddle, consort_action, is_regnant,
    respond_reign_agenda, reign_abdicate,
)
from affair_system import (
    get_affairs, develop_affair, use_affair_perk, mitigate_risk,
    probe_npc_affair, dispose_npc_affair, swap_eligibility,
    swap_start_plan, swap_execute, swap_aftercare, swap_case_respond,
    process_affair_period, affair_overview_payload,
)
from family_backgrounds import (
    generate_background_story,
    generate_concubine_identity,
    generate_official_background,
    get_family_score,
    _pick_official_title,
    GRADE_BASE_SCORE,
    generate_player_clan,
    generate_npc_clan,
    process_clan_period,
    generate_family_events,
    apply_family_choice,
    ensure_clans,
)
from names import random_given, random_surname, EMPEROR_GIVEN
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
    resolve_heir_succession_ending,
)
import httpx
from urllib.parse import urlparse
from ai_service import generate_period_events, _strip_reasoning, get_openai_client

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
    # 前端静态文件禁止浏览器缓存，保证代码更新后立即生效
    if request.path.endswith(('.html', '.js', '.css')):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
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
    "贵妃": {"容貌": 30, "才情": 30, "心计": 20, "威望": 20},
    "皇贵妃": {"容貌": 36, "才情": 36, "心计": 24, "威望": 24},
    "皇后": {"容貌": 42, "才情": 42, "心计": 28, "威望": 28},
}

# 四妃现为「妃」位份下的专属封号（淑/德/贤/宸），各限 1 人；
# 位份数量限制只按真正的 Rank 名统计，四妃名额单独由 FOUR_CONSORT_TITLE_LIMIT 控制。
RANK_LIMITS = {
    "皇后": 1, "皇贵妃": 1, "贵妃": 2,
    "妃": 5, "嫔": 6,
    "婕妤": 8, "美人": 8, "才人": 10, "贵人": 12, "常在": 15,
    "答应": 18, "秀女": 22, "官女子": 28, "更衣": 32, "宫女": 40,
}
FOUR_CONSORT_TITLE_LIMIT = 1  # 每个四妃封号（淑/德/贤/宸）各限 1 人

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
    "妃": {"宠爱": 400, "威望": 265, "才情": 84, "心计": 80},
    "贵妃": {"宠爱": 460, "威望": 300, "才情": 86, "心计": 82},
    "皇贵妃": {"宠爱": 560, "威望": 360, "才情": 88, "心计": 84},
}

# 「妃」位份内的封号晋升门槛（在位份为「妃」时按当前封号阶段校验）：
#   无号妃 → 普通封号妃 → 四妃封号妃（淑/德/贤/宸）→ 才可晋贵妃。
# 键为「当前所处封号阶段」。
CONSORT_TITLE_THRESHOLDS = {
    "none": {"宠爱": 340, "威望": 225, "才情": 82, "心计": 78},      # 无号妃 → 请普通封号
    "ordinary": {"宠爱": 380, "威望": 250, "才情": 84, "心计": 80},  # 普通封号妃 → 册立四妃
}

MIN_RANK_TENURE = {
    "宫女": 2, "更衣": 2, "官女子": 3, "秀女": 3, "答应": 5,
    "常在": 5, "贵人": 6, "才人": 6, "美人": 7, "婕妤": 7,
    "嫔": 8, "妃": 10,
    "贵妃": 14, "皇贵妃": 16,
}
# 「妃」位份内两级封号晋升所需的额外历练旬数（在妃位上累计）。
CONSORT_TITLE_TENURE = {
    "none": 4,       # 晋妃后须历练若干旬方可请普通封号
    "ordinary": 8,   # 得普通封号后须再历练方可册立四妃
}

SPECIAL_FAVOR_RATIO = 1.70   # 宠爱达门槛 170% → 可破格跳过资历（专宠）
SUPER_FAVOR_RATIO = 2.05     # 宠爱达门槛 205% → 属性要求略降
SPECIAL_FAVOR_ABSOLUTE_MIN = 95  # 低位份门槛过低时，专宠至少须达此宠爱

DEMOTION_SEVERE_CONFLICTS = {"陷害", "告发"}
DEMOTION_MODERATE_CONFLICTS = {"谣言", "争辩", "争宠"}

DOWAGER_REGENCY_MAX_AGE = 16   # 新帝年幼于此则由太后垂帘听政

PROMOTION_EXTRA_REQUIREMENTS = {
    "妃": {"min_children": 1, "hint": "母凭子贵——须诞育过子嗣（无论存殁）方可封妃"},
    "四妃封号": {"min_children": 1, "hint": "册立四妃（淑德贤宸）须至少诞下一名皇嗣（母凭子贵）"},
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

def pick_available_four_consort_title(game_state):
    """挑一个尚空缺的四妃封号（淑/德/贤/宸），无空缺返回 None。"""
    for title in FOUR_CONSORT_TITLES:
        if can_use_four_consort_title(game_state, title):
            return title
    return None

def count_four_consort_title(game_state, title):
    """统计当前后宫（含玩家）持某四妃封号的人数。已故者不占名额。"""
    count = 0
    for name, npc in game_state.npcs.items():
        if not npc.get("alive", True):
            continue
        if normalize_rank_name(npc.get("rank")) == "妃" and npc.get("nobletitle") == title:
            count += 1
    if game_state.rank.name == "妃" and game_state.nobletitle == title:
        count += 1
    return count

def can_use_four_consort_title(game_state, title):
    """四妃封号是否仍有名额（各限 FOUR_CONSORT_TITLE_LIMIT）。"""
    if title not in FOUR_CONSORT_TITLES:
        return False
    return count_four_consort_title(game_state, title) < FOUR_CONSORT_TITLE_LIMIT

def grant_consort_nobletitle(game_state):
    """无号妃 → 普通封号妃（位份仍为妃，封号取自普通封号池）。"""
    if game_state.rank.name != "妃" or game_state.nobletitle:
        return None
    candidates = list(ORDINARY_NOBLETITLES) or list(NOBLETITLES)
    game_state.nobletitle = random.choice(candidates)
    return f"皇帝赐封号：『{game_state.nobletitle}』，册为「{game_state.get_display_rank()}」"

def consort_stage(game_state):
    """妃位内的封号阶段：'none'（无号）/'ordinary'（普通封号）/'four'（四妃封号）；非妃位返回 None。"""
    if game_state.rank.name != "妃":
        return None
    if not game_state.nobletitle:
        return "none"
    if is_four_consort_title(game_state.nobletitle):
        return "four"
    return "ordinary"

def get_promotion_step(game_state):
    rank = game_state.rank.name
    if rank == "妃":
        stage = consort_stage(game_state)
        if stage == "none":
            return {"type": "赐封号"}
        if stage == "ordinary":
            target = pick_available_four_consort_title(game_state)
            return {"type": "四妃封号", "target": target}
        # stage == "four"：四妃封号妃 → 贵妃
        next_rank = get_next_rank_name(rank)
        if next_rank:
            return {"type": "位份", "target": next_rank}
        return None
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
    if step["type"] == "四妃封号":
        # 普通封号妃 → 四妃封号妃（位份仍为妃，仅换封号）
        target = step.get("target")
        if not target or not can_use_four_consort_title(game_state, target):
            return None
        game_state.nobletitle = target
        game_state.rank_periods = 0
        return f"📜 圣旨到！册立为四妃之「{game_state.get_display_rank()}」！"
    target = step.get("target")
    if not target:
        return None
    if not can_promote_to_rank(game_state, target):
        return None
    old_title = game_state.nobletitle
    # 晋位份（如四妃封号妃→贵妃）时清空妃位封号
    if game_state.rank.name == "妃":
        game_state.nobletitle = None
    if set_player_rank(game_state, target):
        return f"📜 圣旨到！恭喜晋升为「{game_state.get_display_rank()}」！"
    game_state.nobletitle = old_title
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
    if current == "妃" and game_state.nobletitle:
        # 四妃封号妃 → 普通封号妃；普通封号妃 → 无号妃
        old_display = game_state.get_display_rank()
        if is_four_consort_title(game_state.nobletitle):
            game_state.nobletitle = random.choice(list(ORDINARY_NOBLETITLES) or list(NOBLETITLES))
            new_display = game_state.get_display_rank()
        else:
            game_state.nobletitle = None
            new_display = "妃"
        game_state._promotion_done = False
        game_state.rank_periods = 0
        msg = f"📉 降位旨意：由「{old_display}」降为「{new_display}」"
    else:
        prev = get_prev_rank(current)
        if not prev or not set_player_rank(game_state, prev):
            return None
        # 贵妃降为妃时，给一个四妃封号（贴合「妃位顶层」）
        if current == "贵妃":
            title = pick_available_four_consort_title(game_state) or random.choice(FOUR_CONSORT_TITLES)
            game_state.nobletitle = title
        elif game_state.rank.value < Rank.妃.value and game_state.nobletitle:
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
    if current == "妃" and npc.get("nobletitle"):
        # 四妃封号妃 → 普通封号妃；普通封号妃 → 无号妃
        old_display = npc_display_rank(npc)
        if is_four_consort_title(npc.get("nobletitle")):
            npc["nobletitle"] = random.choice(list(ORDINARY_NOBLETITLES) or list(NOBLETITLES))
            msg = f"📉 {npc_name}由「{old_display}」降为「{npc_display_rank(npc)}」"
        else:
            npc["nobletitle"] = None
            msg = f"📉 {npc_name}由「{old_display}」降为「妃」"
    else:
        prev = get_prev_rank(current)
        if not prev:
            return None
        npc["rank"] = prev
        # 贵妃降为妃时补一个四妃封号
        if current == "贵妃":
            title = pick_available_four_consort_title(game_state) or random.choice(FOUR_CONSORT_TITLES)
            npc["nobletitle"] = title
            msg = f"📉 {npc_name}由「贵妃」降为「{npc_display_rank(npc)}」"
        else:
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

def get_queen_name(game_state, include_player=False):
    """返回皇后名。include_player=True 时，玩家自身为皇后也会被识别。"""
    if include_player and getattr(game_state.rank, "name", "") == "皇后":
        return game_state.name
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
    current_rank_name = normalize_rank_name(current_rank_name)
    if current_rank_name not in RANK_LEVELS:
        return None
    idx = RANK_LEVELS[current_rank_name]
    if idx >= len(RANK_ORDER) - 1:
        return None
    return RANK_ORDER[idx + 1]

def get_min_tenure(rank_name):
    return MIN_RANK_TENURE.get(rank_name, 2)

def get_active_min_tenure(game_state):
    """妃位内按封号阶段返回历练旬数，其余按位份返回。"""
    if game_state.rank.name == "妃":
        stage = consort_stage(game_state)
        if stage in CONSORT_TITLE_TENURE:
            return CONSORT_TITLE_TENURE[stage]
        # stage == "four"：四妃封号妃 → 贵妃，用「妃」的历练要求
        return MIN_RANK_TENURE.get("妃", 2)
    return get_min_tenure(game_state.rank.name)

def get_rank_periods(game_state):
    return getattr(game_state, "rank_periods", 0)

def check_tenure_met(game_state):
    return get_rank_periods(game_state) >= get_active_min_tenure(game_state)


def get_active_favor_threshold(game_state):
    """当前晋升目标的宠爱门槛（妃位内按封号阶段）。"""
    threshold = get_active_promotion_threshold(game_state)
    if not threshold:
        return 999
    return threshold.get("宠爱", 999)

def is_special_favor(game_state):
    """皇帝专宠：宠爱远超当阶门槛，可破格跳过资历限制。"""
    favor = game_state.attributes.get("宠爱", 0)
    required = get_active_favor_threshold(game_state)
    ratio_req = int(required * SPECIAL_FAVOR_RATIO)
    return favor >= max(ratio_req, SPECIAL_FAVOR_ABSOLUTE_MIN)

def is_super_favor(game_state):
    """圣宠无极：属性要求亦略降。"""
    favor = game_state.attributes.get("宠爱", 0)
    required = get_active_favor_threshold(game_state)
    ratio_req = int(required * SUPER_FAVOR_RATIO)
    return favor >= max(ratio_req, SPECIAL_FAVOR_ABSOLUTE_MIN + 40)

def get_promotion_block_reason(game_state):
    step = get_promotion_step(game_state)
    if not step:
        return None
    if step["type"] == "赐封号":
        return None
    if step["type"] == "四妃封号":
        if not step.get("target"):
            return "四妃（淑德贤宸）封号已满，暂无空缺"
        req = PROMOTION_EXTRA_REQUIREMENTS.get("四妃封号")
        if req:
            min_children = req.get("min_children", 0)
            children_had = [c for c in game_state.children if isinstance(c, dict)]
            if min_children > 0 and len(children_had) < min_children:
                return req.get("hint", "晋升条件未满足")
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
        # 子嗣存殁皆计（死胎/夭折也算生育过）
        children_had = [c for c in game_state.children if isinstance(c, dict)]
        if len(children_had) < min_children:
            return req.get("hint", "晋升条件未满足")
    return None

def check_promotion_thresholds_met(game_state, attr_ratio=1.0):
    threshold = get_active_promotion_threshold(game_state)
    if threshold is None:
        return False
    attrs = game_state.attributes
    for attr, value in threshold.items():
        required = max(1, int(value * attr_ratio))
        if attrs.get(attr, 0) < required:
            return False
    return True

def get_active_promotion_threshold(game_state):
    """返回当前晋升目标对应的属性门槛：
    - 妃位内不同封号阶段用 CONSORT_TITLE_THRESHOLDS；
    - 其余位份用 PROMOTION_THRESHOLDS。
    无匹配返回 None。"""
    if game_state.rank.name == "妃":
        stage = consort_stage(game_state)
        if stage in CONSORT_TITLE_THRESHOLDS:
            return CONSORT_TITLE_THRESHOLDS[stage]
        # stage == "four"：四妃封号妃 → 贵妃，用「妃」的位份门槛
        return PROMOTION_THRESHOLDS.get("妃")
    return PROMOTION_THRESHOLDS.get(game_state.rank.name)

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
        if not npc.get("alive", True):
            continue
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

# 珍宝出售价格表（两）
TREASURE_SELL_PRICES = {
    "翡翠镯子": 25, "玛瑙项链": 20, "金镶玉簪": 30, "珊瑚摆件": 35,
    "珍珠冠": 40, "白玉如意": 28, "碧玉屏风": 45, "金丝绣衣": 22,
    "鎏金香炉": 38, "翡翠如意": 26, "点翠凤钗": 32, "东珠耳坠": 28,
    "羊脂玉佩": 35, "红珊瑚珠": 18, "百花锦缎": 15, "夜明珠": 60,
    "和田玉璧": 42, "金漆妆奁": 30, "银鎏金钗": 20, "青玉笔洗": 24,
}
DEFAULT_TREASURE_SELL_PRICE = 15


def get_treasure_sell_price(name: str) -> int:
    """返回指定珍宝的出售价格，未收录则使用默认价。"""
    return TREASURE_SELL_PRICES.get(name, DEFAULT_TREASURE_SELL_PRICE)


@app.route('/api/inventory/sell', methods=['POST'])
def sell_inventory_item():
    """出售背包中的珍宝换取银两。请求体：{player_id, item_name, count?}"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    item_name = (data.get('item_name') or '').strip()
    count = max(1, int(data.get('count', 1) or 1))
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    if not item_name:
        return jsonify({"error": "未指定物品名称"}), 400
    owned = sum(1 for n in game_state.inventory if n == item_name)
    if owned <= 0:
        return jsonify({"error": f"背包中没有「{item_name}」"}), 400
    if count > owned:
        return jsonify({"error": f"数量超出持有上限（持有{owned}件）"}), 400
    price_each = get_treasure_sell_price(item_name)
    total_silver = price_each * count
    # 移除对应数量的物品
    removed = 0
    new_inv = []
    for n in game_state.inventory:
        if n == item_name and removed < count:
            removed += 1
            continue
        new_inv.append(n)
    game_state.inventory = new_inv
    game_state.silver = max(0, game_state.silver + total_silver)
    changes = {"银两": total_silver}
    desc = f"变卖「{item_name}」×{count}，得银{total_silver}两"
    game_state.add_attr_change(changes, f"变卖：{item_name}")
    game_state.add_memory(desc)
    autosave_session(player_id)
    return jsonify({
        "success": True,
        "message": desc,
        "silver": game_state.silver,
        "inventory": game_state.inventory,
        "sold": {"name": item_name, "count": count, "price_each": price_each, "total": total_silver},
        "remaining_actions": game_state.remaining_actions,
        "max_actions": game_state.max_actions,
    })

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
        # 无号妃 → 普通封号妃（不含四妃封号，四妃需走册立流程）
        if game_state.rank.name == "妃" and not game_state.nobletitle:
            title_msg = grant_consort_nobletitle(game_state)
            if title_msg:
                return {"type": "封号", "name": game_state.nobletitle, "desc": title_msg, "silver": 0, "effects": {"宠爱": 8, "威望": 12}}
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
# ============================================================
#  心腹系统
# ============================================================
CONFIDANT_LOYALTY_REQUIRED = 70   # 立为心腹所需最低忠诚
CONFIDANT_PROMOTE_COST = 100      # 立心腹赏赐银两
CONFIDANT_ASSIST_EXTRA = 10.0     # 心腹协助宫斗的额外加成
CONFIDANT_BETRAY_LOYALTY = 40     # 忠诚低于此值时有背叛风险

def confidant_servant(game_state):
    """返回当前心腹宫人对象，无则 None。"""
    if not game_state.confidant:
        return None
    for s in game_state.get_active_servants():
        if s.name == game_state.confidant:
            return s
    return None

def remember_confidant_event(game_state, text):
    """记录心腹关键事件（最多保留 20 条）。"""
    mem = getattr(game_state, "confidant_memory", None)
    if not isinstance(mem, list):
        mem = []
    mem.append(f"[第{game_state.day}日] {text}")
    game_state.confidant_memory = mem[-20:]

def confidant_payload(game_state):
    """心腹系统对前端的数据。"""
    s = confidant_servant(game_state)
    return {
        "confidant": game_state.confidant,
        "confidant_data": s.to_dict() if s else None,
        "confidant_loyalty_required": CONFIDANT_LOYALTY_REQUIRED,
        "confidant_promote_cost": CONFIDANT_PROMOTE_COST,
        "confidant_memory": list(getattr(game_state, "confidant_memory", []) or [])[-8:],
    }

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
        if s.name == getattr(game_state, "confidant", None):
            bonus += CONFIDANT_ASSIST_EXTRA
            if "知人善任" in getattr(game_state, "traits", []):
                bonus += 5.0  # 知人善任：心腹协助加成+5
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
    if not step or step.get("type") not in ("位份", "四妃封号"):
        return None
    if get_promotion_block_reason(game_state):
        return None
    target_rank = step.get("target")
    if not target_rank:
        return None
    if step.get("type") == "位份" and not can_promote_to_rank(game_state, target_rank):
        return None
    if step.get("type") == "四妃封号" and not can_use_four_consort_title(game_state, target_rank):
        return None
    # 盟友美言的底层晋升逻辑不可以大于（放宽于）晋升必须条件：宠爱与属性等硬门槛
    # 必须先行达标，与 check_promotion_condition 采用同一套门槛（含专宠折扣）。
    # 盟友美言仅能帮衬资历（免除历练旬数），不能绕过圣宠与才德等晋升必须条件。
    favor_req = get_active_favor_threshold(game_state)
    favor = game_state.attributes.get("宠爱", 0)
    favor_ratio = 0.92 if is_super_favor(game_state) else 1.0
    if favor < int(favor_req * favor_ratio):
        return None
    attr_ratio = 0.94 if is_super_favor(game_state) else 1.0
    if not check_promotion_thresholds_met(game_state, attr_ratio):
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
    if game_state.attributes.get("宠爱", 0) >= max(40, int(get_active_favor_threshold(game_state) * 0.7)):
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
    if not (api_key and api_base and api_model and str(api_key).strip() and str(api_base).strip() and str(api_model).strip()):
        print(f"[conflict] 未配置完整 API（key={mask_api_key(api_key)} base={api_base} model={api_model}），使用本地宫斗模板")
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
                narration = _strip_reasoning(response.choices[0].message.content)
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
    if rank == "妃":
        # 妃位内：无号→普通封号→四妃封号→贵妃
        if not npc.get("nobletitle"):
            return promote_npc_one_step(game_state, npc)
        if not is_four_consort_title(npc.get("nobletitle")):
            # 普通封号 → 四妃封号（需满足四妃母凭子贵门槛与空缺）
            if not npc_meets_rank_requirements(npc, "四妃封号"):
                return None
            if not pick_available_four_consort_title(game_state):
                return None
            return promote_npc_one_step(game_state, npc)
        # 四妃封号妃 → 贵妃
        if not can_promote_to_rank(game_state, "贵妃") or not npc_meets_rank_requirements(npc, "贵妃"):
            return None
        return promote_npc_one_step(game_state, npc)
    next_rank = get_next_rank_name(rank)
    if not next_rank or not can_promote_to_rank(game_state, next_rank) or not npc_meets_rank_requirements(npc, next_rank):
        return None
    npc["rank"] = next_rank
    return next_rank

def promote_npc_one_step(game_state, npc):
    rank = normalize_rank_name(npc.get("rank", "答应"))
    if rank == "妃":
        if not npc.get("nobletitle"):
            # 无号妃 → 普通封号妃
            candidates = list(ORDINARY_NOBLETITLES) or list(NOBLETITLES)
            npc["nobletitle"] = random.choice(candidates)
            return f"{npc['nobletitle']}妃"
        if not is_four_consort_title(npc.get("nobletitle")):
            # 普通封号妃 → 四妃封号妃
            title = pick_available_four_consort_title(game_state)
            if not title:
                return None
            npc["nobletitle"] = title
            return f"{title}妃"
        # 四妃封号妃 → 贵妃
        if not can_promote_to_rank(game_state, "贵妃"):
            return None
        npc["nobletitle"] = None
        npc["rank"] = "贵妃"
        return "贵妃"
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
        "妃": 3,
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
        "clan": generate_npc_clan(name, rank, family_meta),
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

# ============================================================
#  公主择婿与省亲 · 配置常量
# ============================================================
PRINCESS_MARRY_MIN_AGE = 15          # 及笄可议婚年龄
PRINCESS_FORCE_MARRY_AGE = 20        # 年满此岁的公主必须出嫁（依制强制择婿）
PRINCESS_SUITOR_MIN = 3              # 每次相看候选驸马下限
PRINCESS_SUITOR_MAX = 5              # 每次相看候选驸马上限
BETROTH_COST = 60                   # 定亲纳采礼（银两）
MARRY_COST = 150                    # 出降 / 和亲大典（银两）
INSPECT_COST_ACTION = 1             # 细察候选人耗行动点
PRINCESS_VISIT_INTERVAL = 6         # 出嫁后省亲最短间隔（旬）
MANSION_MAX_LEVEL = 5               # 公主府规模上限
MANSION_UPGRADE_BASE = 120          # 公主府扩建基数（×等级）

# 公主隐藏择偶偏好（情感锚点）；与候选人 hidden_tags / 明属性挂钩
PRINCESS_PREFERENCES = ["文雅清流", "英武豪迈", "温厚持重", "俊逸风流", "务实干练"]

# 候选驸马隐藏标签（细察后揭示）：好坏参半，制造张力
SUITOR_HIDDEN_TAGS = [
    {"key": "情深义重", "good": True, "desc": "对公主一往情深，婚后琴瑟和谐"},
    {"key": "文采斐然", "good": True, "desc": "才名远播，清流敬重"},
    {"key": "少年英才", "good": True, "desc": "年少有为，前途无量"},
    {"key": "家风清正", "good": True, "desc": "门风严谨，无骄纵之气"},
    {"key": "外戚之相", "good": False, "desc": "家族权重，恐成外戚坐大之患"},
    {"key": "风流成性", "good": False, "desc": "素有薄幸之名，恐负公主"},
    {"key": "志大才疏", "good": False, "desc": "眼高手低，难担大任"},
    {"key": "党争漩涡", "good": False, "desc": "身陷派系倾轧，祸福难料"},
]

# 皇帝人格 → 择婿决策类型映射（作为「皇帝亲裁」时的权重）
EMPEROR_DECISION_TYPE = {
    "明君": "平衡型",
    "痴情": "慈父型",
    "昏君": "功利型",
    "多疑": "功利型",
}

# 决策类型 → 各维度权重（用于评估候选人「圣意契合度」，供玩家参考）
DECISION_WEIGHTS = {
    "慈父型": {"looks": 0.20, "talent": 0.20, "family": 0.15, "ambition": 0.15, "preference_match": 0.30},
    "功利型": {"family": 0.45, "ambition": 0.25, "talent": 0.20, "preference_match": 0.10},
    "平衡型": {"family": 0.30, "talent": 0.30, "looks": 0.20, "preference_match": 0.20},
}


PRINCE_MARRY_MIN_AGE = 18          # 皇子成年开府议婚年龄
PRINCE_SUITOR_MIN = 3              # 每次相看皇子妃候选人下限
PRINCE_SUITOR_MAX = 5              # 每次相看皇子妃候选人上限
PRINCE_BETROTH_COST = 80           # 皇子定亲纳采礼（银两）
PRINCE_MARRY_COST = 200            # 皇子大婚大典（银两）
PRINCE_INSPECT_COST_ACTION = 1     # 细察皇子妃候选人耗行动点

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


def validate_ownership_transfer(game_state, child, my_rank_idx, is_orphan=False):
    """过继/重华宫亲养共用的资格校验（模块三统一归属管理）。

    返回错误文案；None 表示全部通过。生母意愿、费用与关系反噬两条链路政策不同，留在各自流程内。
    """
    child_name = child.get("name", "未命名")
    gender = child.get("gender", "皇子")
    age = int(child.get("age", 0) or 0)
    if age > ADOPT_MAX_AGE:
        return f"子嗣已{age}岁，年长不宜再过继"
    if count_living_children(game_state.children) >= ADOPT_MAX_CHILDREN:
        return f"后宫子嗣已满（上限{ADOPT_MAX_CHILDREN}人），不宜再收养"
    if child.get("adopted_count", 0) >= ADOPT_MAX_TRANSFERS:
        return "此子已被过继多次，宗人府不许再行转继"
    if my_rank_idx < RANK_LEVELS.get(ADOPT_MIN_RANK, 0):
        return f"须{ADOPT_MIN_RANK}及以上位份方可收养子嗣"
    if gender == "皇子":
        if my_rank_idx < RANK_LEVELS.get(ADOPT_PRINCE_MIN_RANK, 0):
            return f"皇嗣尊贵，须{ADOPT_PRINCE_MIN_RANK}及以上位份方可收养"
        if game_state.attributes.get("宠爱", 0) < ADOPT_PRINCE_EMPEROR_FAVOR:
            return f"圣宠不足（需宠爱≥{ADOPT_PRINCE_EMPEROR_FAVOR}），皇帝不忍皇嗣旁落，暂不允许收养"
        approved, note = should_use_emperor_approval(game_state, child, "in")
        if not approved:
            return f"奏请过继皇嗣{child_name}，{note}，只得作罢"
    return None


def apply_child_ownership_transfer(game_state, child, *, source_npc=None, source_index=-1,
                                   mode_label, cost=0, cost_note="", from_name="",
                                   adjust_affection=True):
    """过继/重华宫亲养共用的归属变更机械操作（模块三统一归属管理）。

    扣费、从原生母名下移除、改写 adopted 标记与档案、入玩家子嗣列表、记入过继史。
    """
    if cost:
        game_state.silver -= cost
    if isinstance(source_npc, dict) and isinstance(source_index, int) and \
            0 <= source_index < len(source_npc.get("children", []) or []):
        source_npc["children"].pop(source_index)
    age = int(child.get("age", 0) or 0)
    child["adopted"] = True
    child["adopted_count"] = int(child.get("adopted_count", 0) or 0) + 1
    child["birth_mother"] = child.get("birth_mother") or from_name
    child["adoptive_mother"] = game_state.name
    child["adopted_age"] = age
    child["adopted_at"] = f"建元{game_state.year}年{game_state.month}月"
    if adjust_affection:
        child["affection"] = max(10, child.get("affection", 30) - 15) if age >= 1 else random.randint(30, 50)
    child["mood"] = "平静"
    game_state.children.append(child)
    game_state.has_children = True
    add_adoption_history(child, mode_label, from_name, game_state.name, cost_note, game_state.day)


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
    # 旧档迁移：有 talent/health/wit 但无 stats 时，从旧字段生成 stats
    if "stats" not in child:
        gender = child.get("gender", "皇子")
        if gender == "公主":
            child["stats"] = {"文采": child.get("talent", 40), "容貌": random.randint(40, 70),
                              "体魄": child.get("health", 70), "心性": child.get("wit", 40),
                              "仪态": random.randint(30, 60)}
        else:
            child["stats"] = {"文治": child.get("talent", 40), "武略": random.randint(20, 50),
                              "体魄": child.get("health", 70), "心性": child.get("wit", 40),
                              "仪容": random.randint(30, 60)}
    child.setdefault("want_return_home", False)
    child.setdefault("honorary_title", None)   # 徽号
    child.setdefault("palace", "")             # 所居宫殿
    child.setdefault("guardian", "")           # 监护人（空表示由重华宫统一抚养）
    child.setdefault("in_chonghua", False)     # 是否在重华宫在馆
    child.setdefault("uid", None)              # 唯一标识
    # ---- 公主择婿与省亲（仅对 gender=="公主" 有实际意义，字段对所有子嗣安全存在） ----
    child.setdefault("marriage_status", "未议")   # 未议 → 议婚中 → 已定 → 已嫁 → 和亲 / 守寡
    child.setdefault("suitors", [])               # 当前候选驸马列表（每旬缓存）
    child.setdefault("suitors_period", None)       # 候选人生成于哪一旬（防重复刷新）
    child.setdefault("consort", None)              # 已定 / 已嫁后的驸马对象
    child.setdefault("mansion", None)              # 公主府经营对象（出嫁后建立）
    child.setdefault("marriage_events", [])        # 婚后事件流水
    child.setdefault("preference", None)           # 公主本人隐藏择偶偏好（情感锚点）
    child.setdefault("marriage_authority", None)   # 婚事决策权归属（皇帝下放给生母/皇后时为其名）
    child.setdefault("marriage_decider", None)      # 择婿主持人：皇帝亲选 / 生母自选 / 皇后择婿（依皇帝态度而定）
    child.setdefault("last_visit_period", None)    # 上次省亲的旬标记
    ensure_child_stats(child)
    return child

def ensure_child_uid(game_state, child):
    """保证子嗣拥有稳定唯一的 uid（旧存档 uid 为 None 时补发）。"""
    uid = child.get("uid")
    if uid:
        return str(uid)
    try:
        seq = int(getattr(game_state, "child_uid_seq", 1) or 1)
    except (TypeError, ValueError):
        seq = 1
    uid = f"c{seq}"
    game_state.child_uid_seq = seq + 1
    child["uid"] = uid
    return uid


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


# ---- 子嗣五维系统 ----
# 皇子：文治/武略/体魄/心性/仪容；公主：文采/容貌/体魄/心性/仪态
CHILD_STAT_KEYS = {
    "皇子": ["文治", "武略", "体魄", "心性", "仪容"],
    "公主": ["文采", "容貌", "体魄", "心性", "仪态"],
}
# 属性互斥对：成长时一方提升，另一方受抑（出生值不受钳制）
CHILD_STAT_PAIRS = {
    "皇子": [("文治", "武略"), ("体魄", "心性")],
    "公主": [("文采", "容貌"), ("体魄", "心性")],
}
CHILD_STAT_ICONS = {
    "文治": "📜", "武略": "⚔️", "体魄": "💪", "心性": "🧘", "仪容": "🌟",
    "文采": "🖌️", "容貌": "🌹", "仪态": "🎎",
}


def ensure_child_stats(child):
    """补全五维字段（兼容旧存档）。

    旧字段迁移映射：health → 体魄；wit → 心性；talent → 文治/武略（皇子随机）/文采（公主）。
    emperor_favor 原样保留（帝眷独立于五维）。
    """
    gender = child.get("gender", "皇子")
    keys = CHILD_STAT_KEYS.get(gender, CHILD_STAT_KEYS["皇子"])
    stats = child.get("stats")
    if not isinstance(stats, dict):
        stats = {}
    for key in keys:
        if not isinstance(stats.get(key), (int, float)):
            if key == "体魄":
                stats[key] = int(child.get("health", 70))
            elif key == "心性":
                stats[key] = int(child.get("wit", 40))
            elif key == "武略":
                stats[key] = int(child.get("talent", 50)) if random.random() < 0.5 else 45
            elif key in ("文治", "文采"):
                stats[key] = int(child.get("talent", 50)) if random.random() < 0.5 else 40
            else:  # 仪容/仪态
                stats[key] = 55
    child["stats"] = stats
    return stats


def _mother_is_legitimate(game_state, mother_name):
    """嫡出判定：生母位份为皇后。"""
    if not mother_name:
        return False
    if mother_name == getattr(game_state, "name", ""):
        return game_state.rank.name == "皇后"
    npc = (game_state.npcs or {}).get(mother_name)
    return isinstance(npc, dict) and npc.get("rank") == "皇后"


def calc_child_birth_stats(gender, game_state, mother_name=None):
    """按遗传公式计算子嗣出生五维（保底10 + 皇帝×权重 + 母妃×权重 + 随机0~8 + 修正）。

    遗传映射：
    - 文治/文采：皇帝仁德×0.25 + 母妃才情×0.30
    - 武略（皇子）：皇帝威严×0.25 + 母妃倾向×0.25
    - 仪容/容貌：(皇帝威严+好色)/2 ×0.20 + 母妃容貌×0.35（权重最高）
    - 体魄：皇帝健康×0.20 + 母妃健康×0.20
    - 心性：皇帝好色逆映射×0.15 + 母妃心计×0.25
    - 仪态（公主）：皇帝仁德×0.20 + (母妃容貌+才情)/2 ×0.30
    修正：母妃健康≥80→体魄+3；<40→体魄-5~10；嫡出→心性+3~5、体魄+3~5
    """
    emperor = game_state.emperor or {}
    estats = emperor.get("stats") or {}
    runde = estats.get("仁德", 50)
    weiyan = estats.get("威严", 50)
    emp_health = emperor.get("health", 80) or 80
    haose = estats.get("好色", 30)

    if mother_name:
        npc = (game_state.npcs or {}).get(mother_name)
        if not isinstance(npc, dict) or mother_name == getattr(game_state, "name", ""):
            mattrs = getattr(game_state, "attributes", {}) or {}
        else:
            mattrs = npc.get("attributes") or {}
    else:
        mattrs = getattr(game_state, "attributes", {}) or {}
    m_caiqing = mattrs.get("才情", 50)
    m_rongmao = mattrs.get("容貌", 60)
    m_health = mattrs.get("健康", 80)
    m_xinji = mattrs.get("心计", 40)
    m_qingxiang = mattrs.get("倾向", 35)

    def _base(emp_part, mother_part):
        return 10 + emp_part + mother_part + random.randint(0, 8)

    if gender == "公主":
        stats = {
            "文采": _base(runde * 0.25, m_caiqing * 0.30),
            "容貌": _base((weiyan + haose) / 2 * 0.20, m_rongmao * 0.35),
            "体魄": _base(emp_health * 0.20, m_health * 0.20),
            "心性": _base((100 - haose) * 0.15, m_xinji * 0.25),
            "仪态": _base(runde * 0.20, (m_rongmao + m_caiqing) / 2 * 0.30),
        }
    else:
        stats = {
            "文治": _base(runde * 0.25, m_caiqing * 0.30),
            "武略": _base(weiyan * 0.25, m_qingxiang * 0.25),
            "体魄": _base(emp_health * 0.20, m_health * 0.20),
            "心性": _base((100 - haose) * 0.15, m_xinji * 0.25),
            "仪容": _base((weiyan + haose) / 2 * 0.20, m_rongmao * 0.35),
        }
    # 孕期修正（以母妃当下健康近似孕期状态）
    if m_health >= 80:
        stats["体魄"] += 3
    elif m_health < 40:
        stats["体魄"] -= random.randint(5, 10)
    # 嫡出修正
    if _mother_is_legitimate(game_state, mother_name):
        stats["心性"] += random.randint(3, 5)
        stats["体魄"] += random.randint(3, 5)
    for k, v in stats.items():
        stats[k] = int(max(5, min(100, round(v))))
    return stats


def grow_child_stat(child, key, amount):
    """成长单维属性：提升 key（应用标签乘数），互斥对属性受抑。返回 (gained, suppressed) 供叙事。"""
    gender = child.get("gender", "皇子")
    ensure_child_stats(child)
    ensure_child_tags(child)
    stats = child["stats"]
    key = key if key in stats else next(iter(stats))
    gain = max(0, int(amount))
    # 标签成长乘数（勤奋/先天不足/娇纵/孤僻/尚武）
    gain = int(round(gain * child_tag_growth_bonus(child, key)))
    stats[key] = int(max(0, min(100, stats.get(key, 0) + gain)))
    suppressed = None
    if gain:
        for a, b in CHILD_STAT_PAIRS.get(gender, []):
            if key == a:
                suppressed = b
                break
            if key == b:
                suppressed = a
                break
        if suppressed is not None:
            drop = max(1, gain // 2)
            before = stats.get(suppressed, 0)
            stats[suppressed] = int(max(0, min(100, before - drop)))
    return stats[key], (suppressed, gain // 2) if suppressed and gain else None


# ---- 子嗣标签系统 ----
# 最多 5 标签/人；互斥标签自动替换；来源：出生/成长/随机事件
CHILD_TAG_MAX = 5
CHILD_TAG_INFO = {
    "类父":     {"icon": "👑", "desc": "形神酷似天家，皇帝初始好感+10"},
    "肖母":     {"icon": "💞", "desc": "眉眼性情随母，与母妃互动好感额外+2"},
    "先天不足": {"icon": "🕯️", "desc": "体魄成长-20%，3岁前每旬3%夭折概率"},
    "勤奋":     {"icon": "📖", "desc": "全属性成长+5%"},
    "娇纵":     {"icon": "🍭", "desc": "心性成长-20%"},
    "孤僻":     {"icon": "🌫️", "desc": "心性成长+15%，亲密度上限60"},
    "尚武":     {"icon": "🏹", "desc": "武略成长+10%，文治成长-5%（仅皇子）"},
    "倾国倾城": {"icon": "🌹", "desc": "驸马门第自动升一档（仅公主）"},
    "遇险":     {"icon": "⚡", "desc": "体魄-10，心性+5"},
    "异梦":     {"icon": "🌙", "desc": "随机属性+8，得「预言」"},
}
# 互斥标签组：获得新标签时若持有互斥标签，自动替换之
CHILD_TAG_EXCLUSIVE = {
    "勤奋": {"娇纵"},
    "娇纵": {"勤奋"},
    "孤僻": {"肖母"},
    "肖母": {"孤僻"},
}


def ensure_child_tags(child):
    """补全 tags 字段（兼容旧存档），并同步特殊规则标记。"""
    tags = child.get("tags")
    if not isinstance(tags, list):
        tags = []
    gender = child.get("gender", "皇子")
    stats = ensure_child_stats(child)
    # 特殊规则 → 标签双向同步
    if gender == "公主" and stats.get("容貌", 0) >= 85:
        child["beauty_grace"] = True
        if "倾国倾城" not in tags:
            tags.append("倾国倾城")
    elif gender == "皇子" and stats.get("仪容", 0) >= 80:
        child["handsome_grace"] = True
    child["tags"] = tags
    return tags


def grant_child_tag(child, tag):
    """授予标签：互斥自动替换，上限 CHILD_TAG_MAX。返回 (granted, replaced)。"""
    if tag not in CHILD_TAG_INFO:
        return False, None
    tags = ensure_child_tags(child)
    if tag in tags:
        return False, None
    replaced = None
    excl = CHILD_TAG_EXCLUSIVE.get(tag, set())
    for old in list(tags):
        if old in excl:
            tags.remove(old)
            replaced = old
            break
    if len(tags) >= CHILD_TAG_MAX:
        # 上限已满：挤掉最早的一个标签
        tags.pop(0)
    tags.append(tag)
    return True, replaced


def child_tag_growth_bonus(child, key):
    """标签对指定属性成长的乘数（>0，1=无修正）。"""
    tags = child.get("tags") or []
    bonus = 1.0
    if "勤奋" in tags:
        bonus *= 1.05
    if "娇纵" in tags and key == "心性":
        bonus *= 0.80
    if "孤僻" in tags and key == "心性":
        bonus *= 1.15
    if "先天不足" in tags and key == "体魄":
        bonus *= 0.80
    if "尚武" in tags and child.get("gender") == "皇子":
        if key == "武略":
            bonus *= 1.10
        elif key == "文治":
            bonus *= 0.95
    return bonus



def apply_child_tag_stats(child, tag):
    """标签附带的一次性数值效果，返回叙事片段列表。"""
    msgs = []
    ensure_child_stats(child)
    stats = child["stats"]
    gender = child.get("gender", "皇子")
    if tag == "先天不足":
        msgs.append("先天不足，体魄成长-20%，幼年需多加照料")
    elif tag == "遇险":
        stats["体魄"] = int(max(0, min(100, stats.get("体魄", 50) - 10)))
        stats["心性"] = int(max(0, min(100, stats.get("心性", 50) + 5)))
        msgs.append("体魄-10，心性+5")
    elif tag == "异梦":
        keys = [k for k in stats]
        rk = random.choice(keys)
        stats[rk] = int(max(0, min(100, stats.get(rk, 50) + 8)))
        child["has_prophecy"] = True
        msgs.append(f"{rk}+8，得「预言」")
    elif tag == "类父":
        child["emperor_favor"] = min(100, child.get("emperor_favor", 30) + 10)
        msgs.append("皇帝好感+10")
    return msgs


# ============================================================
#  子嗣标签事件系统（20 事件 × 四阶段，每子每旬最多 1 件）
# ============================================================
CHILD_TAG_EVENT_CHANCE = 0.10   # 每子每旬触发概率
CHILD_TAG_EVENT_QUEUE_MAX = 3

# choice: {text, effects:{stats键/affection/health/emperor_favor:delta}, tag?, cost?, success?, fail_text?, gender?}
CHILD_TAG_EVENTS = [
    # ---- 婴儿/幼儿 ----
    {"id": "first_smile", "min_age": 2, "max_age": 12,
     "narrative": "{name}今日忽然对你露出第一个真正的笑容，眼睛弯弯如新月，满殿生辉。",
     "choices": [
         {"text": "抱在怀里细看", "effects": {"affection": 8}},
         {"text": "请太医验看", "effects": {"health": 4}},
     ]},
    {"id": "teething", "min_age": 4, "max_age": 18,
     "narrative": "{name}近来啼哭不止，小脸红扑扑——是在长牙。太医道需以清凉之物舒缓。",
     "choices": [
         {"text": "送翡翠牙咬", "effects": {"health": 3, "affection": 3}},
         {"text": "顺其自然", "effects": {"health": -3}},
     ]},
    {"id": "strange_dream_baby", "min_age": 6, "max_age": 24,
     "narrative": "乳母急报：{name}睡梦中喃喃说着「龙」「火」二字，惊醒后竟安然无恙。此兆吉是凶？",
     "choices": [
         {"text": "视为吉兆，大宴祈福", "tag": "异梦", "effects": {"emperor_favor": 5}},
         {"text": "压下不传", "effects": {}},
     ]},
    {"id": "first_words", "min_age": 10, "max_age": 24,
     "narrative": "{name}咿咿呀呀间，竟清晰唤出了「母」字，声如银铃，满殿皆惊。",
     "choices": [
         {"text": "抱他/她细看", "effects": {"affection": 8}},
         {"text": "请女官启蒙", "effects": {"心性": 6}, "cost": 20},
     ]},
    # ---- 童年 ----
    {"id": "grab_week", "min_age": 12, "max_age": 14,
     "narrative": "{name}抓周之日，案上摆满书卷、金印、弓箭、算盘。{name}蹒跚上前，目光在诸物间游移……",
     "choices": [
         {"text": "引导向书卷", "tag": "勤奋", "effects": {"文治": 6}},
         {"text": "引导向弓箭", "tag": "尚武", "effects": {"武略": 6}, "gender": "皇子"},
         {"text": "顺其自然", "effects": {"心性": 3}},
     ]},
    {"id": "kindergarten_play", "min_age": 24, "max_age": 108,
     "narrative": "御花园里，{name}与同岁兄弟姐妹嬉戏，不慎跌入浅池，宫人惊慌。",
     "choices": [
         {"text": "亲自救起，悉心安抚", "effects": {"affection": 10, "health": 2}},
         {"text": "斥责宫人看护不周", "effects": {"health": 5, "affection": -3}},
     ]},
    {"id": "study_struggle", "min_age": 36, "max_age": 108,
     "narrative": "太傅上禀：{name}近日读书时常常走神，功课一塌糊涂，问之则支吾。",
     "choices": [
         {"text": "循循善诱", "effects": {"文治": 5, "affection": 4}},
         {"text": "加罚功课", "effects": {"文治": 8, "心性": -4, "affection": -5}},
     ]},
    {"id": "sick_fever", "min_age": 12, "max_age": 120,
     "narrative": "{name}忽发高热，太医说是时疫之气，需静养旬日方可痊愈。",
     "choices": [
         {"text": "亲守药炉", "effects": {"health": 10, "affection": 8}},
         {"text": "委付乳母", "effects": {"health": 4, "affection": -2}},
     ]},
    {"id": "kind_to_servant", "min_age": 24, "max_age": 120,
     "narrative": "{name}将自己的点心分给了扫洒宫女，小宫女谢恩落泪。",
     "choices": [
         {"text": "嘉奖其善心", "tag": "肖母", "effects": {"心性": 6}},
         {"text": "道宫中无此规矩", "effects": {"心性": -3, "affection": -2}},
     ]},
    # ---- 少年 ----
    {"id": "debate_win", "min_age": 120, "max_age": 180,
     "narrative": "皇子们庭辩政事，{name}以经史之学驳得对方哑口无言，文官班列侧目相看。",
     "choices": [
         {"text": "奏报皇帝", "effects": {"文治": 8, "emperor_favor": 6}},
         {"text": "劝其收敛锋芒", "effects": {"心性": 6, "emperor_favor": 2}},
     ]},
    {"id": "martial_awakening", "min_age": 120, "max_age": 180,
     "narrative": "校场秋操，{name}一箭中的百步之外的靶心，满场喝彩。武官纷纷侧目。",
     "choices": [
         {"text": "奏请赐弓", "effects": {"武略": 10, "emperor_favor": 5}, "gender": "皇子"},
         {"text": "恐其恃勇，加授文典", "effects": {"武略": 4, "文治": 4}, "gender": "皇子"},
     ]},
    {"id": "princess_reputation", "min_age": 120, "max_age": 180,
     "narrative": "{name}的一首新词传入坊间，「才名动京华」的说法开始流传。世家纷纷遣使问名。",
     "choices": [
         {"text": "盛赞其才", "effects": {"文采": 8, "emperor_favor": 5}, "gender": "公主"},
         {"text": "诫其深居简出", "effects": {"心性": 4, "文采": 2}, "gender": "公主"},
     ]},
    {"id": "rebellious", "min_age": 120, "max_age": 180,
     "narrative": "{name}竟顶撞了太后身边的嬷嬷，被斥「不懂规矩」。{name}摔门而去，闷闷不乐。",
     "choices": [
         {"text": "深夜寻回，长谈", "effects": {"心性": 6, "affection": 8}},
         {"text": "责以规矩", "effects": {"心性": 4, "affection": -6}},
     ]},
    # ---- 青年 ----
    {"id": "border_news", "min_age": 192, "max_age": 240,
     "narrative": "边关急报：蛮族犯境。朝议历练皇子，有人举荐{name}监军，也有人主张历练文臣。",
     "choices": [
         {"text": "举荐{name}监军", "effects": {"武略": 12, "emperor_favor": 6}, "gender": "皇子"},
         {"text": "举荐{name}赞画军务", "effects": {"文治": 10, "emperor_favor": 6}},
     ]},
    {"id": "dangers_omen", "min_age": 120, "max_age": 240,
     "narrative": "{name}自宫道归来，面色苍白：「今日遇刺，若非侍卫及时……」",
     "choices": [
         {"text": "奏请皇帝彻查", "tag": "遇险", "effects": {"emperor_favor": 8, "心性": 4}},
         {"text": "隐忍，暗中部署", "effects": {"心性": 8}, "success": 0.7, "fail_text": "刺客背后势力未明，暗中调查无果"},
     ]},
    {"id": "philanthropy", "min_age": 120, "max_age": 240,
     "narrative": "水患之年，{name}主动散出月例采买粥棚，百姓称「{name}菩萨」。",
     "choices": [
         {"text": "奏明圣上", "effects": {"文治": 6, "emperor_favor": 8}},
         {"text": "暗中补其用度", "effects": {"affection": 6}, "cost": 50},
     ]},
    {"id": "starfall", "min_age": 120, "max_age": 240,
     "narrative": "昨夜流星坠于北境，钦天监观星后密奏：「此星主皇子，吉凶未定。」",
     "choices": [
         {"text": "焚毁密奏", "tag": "异梦", "effects": {"emperor_favor": -2}},
         {"text": "呈给皇帝", "effects": {"心性": 6, "emperor_favor": 4}},
     ]},
]


def generate_child_tag_events(game_state):
    """转旬时：为每名存活子嗣按阶段/概率掷一次标签事件（每子每旬最多 1 件，队列上限 3）。"""
    if not isinstance(getattr(game_state, "child_event_queue", None), list):
        game_state.child_event_queue = []
    if len(game_state.child_event_queue) >= CHILD_TAG_EVENT_QUEUE_MAX:
        return
    for child in game_state.children:
        if len(game_state.child_event_queue) >= CHILD_TAG_EVENT_QUEUE_MAX:
            break
        if not child.get("alive", True):
            continue
        ensure_child_fields(child)
        ensure_child_stats(child)
        age = round(float(child.get("age", 0)) * 12)
        triggered = set(child.get("triggered_events") or [])
        candidates = [e for e in CHILD_TAG_EVENTS
                      if e["min_age"] <= age <= e["max_age"] and e["id"] not in triggered]
        if not candidates or random.random() >= CHILD_TAG_EVENT_CHANCE:
            continue
        ev = random.choice(candidates)
        triggered.add(ev["id"])
        child["triggered_events"] = sorted(triggered)
        game_state.child_event_queue.append({
            "id": f"{ev['id']}_{child.get('uid', '')}",
            "event_id": ev["id"],
            "child_uid": child.get("uid", ""),
            "child_name": child.get("name", "皇嗣"),
            "gender": child.get("gender", "皇子"),
            "narrative": ev["narrative"].format(name=child.get("name", "皇嗣")),
            "choices": ev["choices"],
        })


def apply_child_tag_choice(game_state, ev, choice):
    """结算子嗣标签事件选项。返回 {narration, effects}。"""
    child = next((c for c in game_state.children if c.get("uid") == ev.get("child_uid")), None)
    if child is None:
        return {"narration": "该事件已了结。", "effects": {}}
    ensure_child_stats(child)
    gender = child.get("gender", "皇子")
    if choice.get("gender") and choice["gender"] != gender:
        return {"narration": "此事与他/她身份不符，无从处置。", "effects": {}}
    cost = int(choice.get("cost", 0) or 0)
    if cost and game_state.silver < cost:
        return {"narration": f"需花费 {cost} 两银子，你囊中不足。", "effects": {}}
    if cost:
        game_state.silver -= cost
    if choice.get("success") and random.random() > choice["success"]:
        return {"narration": choice.get("fail_text") or "事与愿违，未能如愿。", "effects": {}}
    effects = {}
    for key, delta in (choice.get("effects") or {}).items():
        if key in ("affection", "health", "emperor_favor"):
            base = int(child.get(key, 0) or 0)
            child[key] = int(max(0, min(100, base + delta)))
            effects[key] = delta
        else:
            grow_child_stat(child, key, delta)
            effects[key] = delta
    if choice.get("tag"):
        granted, replaced = grant_child_tag(child, choice["tag"])
        tag_msgs = apply_child_tag_stats(child, choice["tag"])
        if granted or tag_msgs:
            effects["标签"] = choice["tag"]
            if replaced:
                effects["替换"] = replaced
    narr = f"{ev.get('child_name', '皇嗣')}：你选择了「{choice.get('text', '处置')}」。"
    parts = [f"{k}{'+' if isinstance(v, int) and v > 0 else ''}{v}" for k, v in effects.items() if v != 0]
    if parts:
        narr += "（" + "、".join(parts) + "）"
    add_child_event(child, narr)
    return {"narration": narr, "effects": effects}


# ============================================================
#  协理六宫事件系统（10 模板 × 5 大类，每旬 1~2 件，队列上限 2）
# ============================================================
GOVERNANCE_EVENT_QUEUE_MAX = 2
GOVERNANCE_HISTORY_MAX = 30

# choice.effects 支持键：NPC名→好感变化、"威望"（玩家威望）、"压力_A/B"、"银两"
# NPC 名由生成时用 {a} {b} 占位替换为实际妃嫔
GOVERNANCE_EVENT_TEMPLATES = [
    # ---- 人事纠纷（30%）----
    {"id": "g_favor_dispute", "type": "人事纠纷", "icon": "🏛️", "title": "争宠告状",
     "desc": "{a}跪在你面前，哭诉 {b} 抢了她侍寝的日子，言语间带着刺。",
     "choices": [
         {"text": "按规矩查档裁定", "icon": "⚖️", "effects": {"{a}": 10, "{b}": -6, "威望": 2}},
         {"text": "各打五十大板", "icon": "🤝", "effects": {"{a}": -3, "{b}": -3, "威望": -1}},
         {"text": "私下安抚，息事宁人", "icon": "🌙", "effects": {"{a}": 3, "{b}": 3}},
     ]},
    {"id": "g_servant_conflict", "type": "人事纠纷", "icon": "🏛️", "title": "宫人争执",
     "desc": "{a}与 {b} 的宫人当街推搡，各不相让。两宫都盯着你怎么定夺。",
     "choices": [
         {"text": "各罚俸禄一月", "icon": "⚖️", "effects": {"{a}": -2, "{b}": -2, "威望": 3}},
         {"text": "位份低者多担责", "icon": "🔥", "effects": {"{a}": 5, "{b}": -10}},
         {"text": "调走涉事宫人", "icon": "🌙", "effects": {"{a}": 1, "{b}": 1}},
     ]},
    {"id": "g_rank_petition", "type": "人事纠纷", "icon": "🏛️", "title": "位份之争",
     "desc": "{a} 请托你向皇后/圣上言其功劳，称 {b}「窃取其功」。此事如何处置？",
     "choices": [
         {"text": "秉公回绝，各安其位", "icon": "⚖️", "effects": {"{a}": -5, "{b}": 3, "威望": 3}},
         {"text": "替 {a} 进言", "icon": "📜", "effects": {"{a}": 12, "{b}": -8, "威望": -2}},
     ]},
    # ---- 宫务管理（25%）----
    {"id": "g_budget_theft", "type": "宫务管理", "icon": "📜", "title": "月例挪用",
     "desc": "内务府呈报：本月有宫例银两去向不明，查至 {a} 宫中。{b} 出面向你求情。",
     "choices": [
         {"text": "彻查到底，追回银两", "icon": "⚖️", "effects": {"{a}": -15, "{b}": 5, "银两": 80, "威望": 4}},
         {"text": "罚 {a} 补交，从轻发落", "icon": "🤝", "effects": {"{a}": -8, "银两": 40, "威望": 1}},
         {"text": "听 {b} 情面，大事化小", "icon": "🌙", "effects": {"{a}": 4, "{b}": 8, "威望": -3}},
     ]},
    {"id": "g_supply_short", "type": "宫务管理", "icon": "📜", "title": "用度短缺",
     "desc": "冬衣未至，{a} 宫人手足无依。内务府推说库银见底，请你定夺补给与否。",
     "choices": [
         {"text": "从你的私库拨银补给", "icon": "🪙", "effects": {"{a}": 12, "银两": -100, "威望": 2}},
         {"text": "奏请内务府加拨", "icon": "📜", "effects": {"{a}": 6}},
         {"text": "按旧例拖延", "icon": "🌙", "effects": {"{a}": -6, "威望": -1}},
     ]},
    {"id": "g_court_discipline", "type": "宫务管理", "icon": "📜", "title": "宫宴失仪",
     "desc": "昨日宫宴上 {b} 当众讥讽 {a} 失仪，满座哗然。皇帝尚未听闻。",
     "choices": [
         {"text": "罚 {b} 向 {a} 赔罪", "icon": "⚖️", "effects": {"{a}": 10, "{b}": -12, "威望": 3}},
         {"text": "隐瞒不报", "icon": "🌙", "effects": {"{a}": -4, "{b}": 4, "威望": -2}},
     ]},
    # ---- 人情博弈（20%）----
    {"id": "g_bribe", "type": "人情博弈", "icon": "🎭", "title": "暗送殷勤",
     "desc": "{a} 差心腹送来两匣珠玉，附书道：「他日若得圣眷，不忘姐姐恩典。」",
     "choices": [
         {"text": "收下并应允", "icon": "🎁", "effects": {"{a}": 15, "银两": 60, "威望": -3}},
         {"text": "原样退回", "icon": "⚖️", "effects": {"{a}": -8, "威望": 2}},
         {"text": "收下不允诺", "icon": "🌙", "effects": {"{a}": 5, "银两": 60}},
     ]},
    {"id": "g_plea", "type": "人情博弈", "icon": "🎭", "title": "泣血求情",
     "desc": "{b} 的妹妹触法当杖，{b} 跪求你向皇后说情，并许诺「愿为姐姐驱使」。",
     "choices": [
         {"text": "应允并代为说情", "icon": "🤝", "effects": {"{b}": 15, "威望": -2}},
         {"text": "法不容情，婉拒", "icon": "⚖️", "effects": {"{b}": -10, "威望": 3}},
     ]},
    # ---- 突发事件（15%）----
    {"id": "g_fire", "type": "突发事件", "icon": "⚠️", "title": "失火警讯",
     "desc": "深夜 {a} 宫失火，宫人四散。幸未伤人，但 {b} 疑心是 {a} 借火行事。",
     "choices": [
         {"text": "彻查纵火，安抚两宫", "icon": "⚖️", "effects": {"{a}": -5, "{b}": 5, "威望": 4}},
         {"text": "以「失手」结案", "icon": "🌙", "effects": {"{a}": 3, "{b}": -5, "威望": -2}},
     ]},
    {"id": "g_poison_scare", "type": "突发事件", "icon": "⚠️", "title": "疑云毒药",
     "desc": "{a} 饮了 {b} 宫送来的莲子羹后腹痛不止，太医疑有剧毒。{a} 誓要讨个说法。",
     "choices": [
         {"text": "封 {b} 宫彻查", "icon": "⚖️", "effects": {"{a}": 12, "{b}": -20, "威望": 3, "压力_{b}": 15}},
         {"text": "和稀泥，各让一步", "icon": "🤝", "effects": {"{a}": -3, "{b}": -3}},
         {"text": "信 {b} 是无辜的", "icon": "🌙", "effects": {"{a}": -15, "{b}": 10}},
     ]},
    # ---- 派系斗争（10%）----
    {"id": "g_faction_purge", "type": "派系斗争", "icon": "👑", "title": "派系倾轧",
     "desc": "{a} 暗中拉拢宫人，意图在位份册上除名 {b}。若坐实，朝中清流也将被牵连。",
     "choices": [
         {"text": "将 {a} 拿问", "icon": "⚖️", "effects": {"{a}": -25, "{b}": 12, "威望": 6, "压力_{a}": 20}},
         {"text": "敲打 {a}，警告 {b}", "icon": "🎯", "effects": {"{a}": -10, "{b}": -5, "威望": 2}},
         {"text": "置身事外", "icon": "🌙", "effects": {"{a}": 5, "{b}": -5, "威望": -3}},
     ]},
]


def _gov_pick_npcs(game_state):
    """选两名存活妃嫔（排除太后/玩家本人），高位在前。"""
    names = [n for n, c in (game_state.npcs or {}).items()
             if n != "太后" and n != game_state.name and isinstance(c, dict) and c.get("alive", True)]
    if len(names) < 2:
        return None, None
    a, b = random.sample(names, 2)
    if RANK_LEVELS.get(normalize_rank_name(game_state.npcs[a].get("rank", "答应")), 0) < \
       RANK_LEVELS.get(normalize_rank_name(game_state.npcs[b].get("rank", "答应")), 0):
        a, b = b, a
    return a, b


def generate_governance_events(game_state):
    """转旬时：玩家有协理权时生成 1~2 件协理事件。连处理 2 旬后冷却 1 旬。"""
    if not isinstance(getattr(game_state, "governance_events", None), list):
        game_state.governance_events = []
    if not isinstance(getattr(game_state, "governance_history", None), list):
        game_state.governance_history = []
    has_auth = False
    try:
        qa = queen_authority(game_state)
        has_auth = game_state.rank.name == "皇后" or qa.get("is_player") \
            or qa.get("assistant") == game_state.name or qa.get("can_assist_six_palaces")
    except Exception:
        pass
    if not has_auth:
        game_state.governance_events = []
        return
    cooldown = int(getattr(game_state, "governance_cooldown", 0) or 0)
    if cooldown > 0:
        game_state.governance_cooldown = cooldown - 1
        return
    streak = int(getattr(game_state, "governance_handled_streak", 0) or 0)
    if streak >= 2:
        game_state.governance_handled_streak = 0
        game_state.governance_cooldown = 1
        return
    if len(game_state.governance_events) >= GOVERNANCE_EVENT_QUEUE_MAX:
        return
    for _ in range(random.choice([1, 2])):
        if len(game_state.governance_events) >= GOVERNANCE_EVENT_QUEUE_MAX:
            break
        tpl = random.choice(GOVERNANCE_EVENT_TEMPLATES)
        a, b = _gov_pick_npcs(game_state)
        if not a or not b:
            continue
        choices = []
        for ch in tpl["choices"]:
            eff = {k.format(a=a, b=b): v for k, v in (ch.get("effects") or {}).items()}
            choices.append({"text": ch["text"].format(a=a, b=b), "icon": ch.get("icon", ""), "effects": eff})
        game_state.governance_events.append({
            "id": f"gov_{tpl['id']}_{game_state.year}_{game_state.month}_{len(game_state.governance_events)}",
            "type": tpl["type"], "icon": tpl["icon"], "title": tpl["title"].format(a=a, b=b),
            "desc": tpl["desc"].format(a=a, b=b),
            "choices": choices,
            "involved": [a, b],
            "period": f"{game_state.year}年{game_state.month}月",
        })


def apply_governance_choice(game_state, ev, choice):
    """结算协理事件选项。返回 {narration, effects}。"""
    effects = {}
    involved = ev.get("involved") or []
    for k, v in (choice.get("effects") or {}).items():
        v = int(v)
        if k == "银两":
            game_state.silver = max(0, game_state.silver + v)
            effects["银两"] = v
        elif k == "威望":
            old = int(game_state.attributes.get("威望", 0) or 0)
            game_state.attributes["威望"] = int(max(0, min(game_state.get_attr_max("威望"), old + v)))
            effects["威望"] = v
        elif k.startswith("压力_"):
            target = k.split("_", 1)[1]
            npc = (game_state.npcs or {}).get(target)
            if isinstance(npc, dict):
                npc["压力"] = int(max(0, min(100, int(npc.get("压力", 0) or 0) + v)))
                effects[f"压力·{target}"] = v
        else:
            npc = (game_state.npcs or {}).get(k)
            if isinstance(npc, dict) and isinstance(npc.get("relationship"), dict):
                rel = npc["relationship"]
                rel["好感"] = int(max(-100, min(100, int(rel.get("好感", 0) or 0) + v)))
                effects[k] = v
            # 裁决同时影响 NPC 间关系网（涉及对方）
            if len(involved) == 2 and k in involved:
                other = involved[1] if k == involved[0] else involved[0]
                modify_npc_rel(game_state, k, other, int(v * 0.5), ev.get("title", ""),
                               ev.get("period"), notify=False)
    narr = f"「{ev.get('title', '')}」你裁决：{choice.get('text', '')}。"
    parts = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in effects.items() if v != 0]
    if parts:
        narr += "（" + "、".join(parts) + "）"
    game_state.governance_history.insert(0, {
        "id": ev.get("id"), "title": ev.get("title"), "type": ev.get("type"),
        "choice": choice.get("text"), "period": ev.get("period"),
    })
    game_state.governance_history = game_state.governance_history[:GOVERNANCE_HISTORY_MAX]
    game_state.governance_handled_streak = int(getattr(game_state, "governance_handled_streak", 0) or 0) + 1
    return {"narration": narr, "effects": effects}


# ---- NPC 妃嫔关系网引擎 ----
# 妃嫔之间自动产生好感变化/结盟/结仇，让后宫自我运转
NPC_REL_TIERS = [
    (-100, -50, "死敌", "💀", "#c0392b"),
    (-50, -20, "仇敌", "⚔️", "#e74c3c"),
    (-20, -5, "对手", "🎯", "#e67e22"),
    (-5, 5, "中立", "—", "#95a5a6"),
    (5, 20, "友善", "🤝", "#27ae60"),
    (20, 50, "朋友", "🌸", "#a1887f"),
    (50, 80, "知己", "💛", "#f39c12"),
    (80, 101, "同盟", "👑", "#d4af37"),
]
# 性格对冲对：冲突概率提升
NPC_PERSONALITY_CLASH = {
    ("温婉贤淑", "阴险毒辣"), ("温婉贤淑", "妖艳张扬"),
    ("高傲冷艳", "活泼开朗"), ("端庄大方", "阴险毒辣"),
    ("清冷孤傲", "妖艳张扬"), ("懦弱胆小", "野心勃勃"),
}
NPC_REL_LOG_MAX = 40


def npc_rel_tier(score):
    """好感分 → (类型名, 图标, 颜色)。"""
    s = int(score)
    for lo, hi, name, icon, color in NPC_REL_TIERS:
        if lo <= s < hi:
            return name, icon, color
    return "中立", "—", "#95a5a6"


def _ensure_npc_rel(game_state, a, b, period):
    """取/建 A→B 的关系条目（含初始好感：位份差 + 性格 + 随机）。"""
    net = game_state.npc_relationships
    row = net.setdefault(a, {})
    if not isinstance(row.get(b), dict):
        na, nb = (game_state.npcs or {}).get(a), (game_state.npcs or {}).get(b)
        la = RANK_LEVELS.get(normalize_rank_name((na or {}).get("rank", "答应")), 0)
        lb = RANK_LEVELS.get(normalize_rank_name((nb or {}).get("rank", "答应")), 0)
        base = random.randint(-15, 20)
        if la > lb:
            base -= random.randint(1, 5)   # 高位对低位略疏
        elif lb > la:
            base += random.randint(1, 5)
        pa = (na or {}).get("personality", "")
        pb = (nb or {}).get("personality", "")
        if (pa, pb) in NPC_PERSONALITY_CLASH or (pb, pa) in NPC_PERSONALITY_CLASH:
            base -= random.randint(5, 15)
        elif pa and pa == pb:
            base += random.randint(5, 12)
        row[b] = {
            "好感": int(max(-100, min(100, base))),
            "印象": random.choice(["友善", "疏离", "信任"]) if base > 0 else random.choice(["疏离", "敌视"]),
            "关系类型": "中立",
            "历史事件": [],
            "最后互动旬": period,
        }
    return row[b]


def get_npc_rel(game_state, a, b):
    """查询 A→B 关系（不创建）。"""
    return ((game_state.npc_relationships or {}).get(a) or {}).get(b)


def modify_npc_rel(game_state, a, b, delta, reason="", period=None, notify=True):
    """修改 A→B 好感并记录；重大变化（|delta|≥10 或类型跨越）推送事件。"""
    if a == b or not a or not b:
        return
    if period is None:
        period = f"{game_state.year}年{game_state.month}月"
    entry = _ensure_npc_rel(game_state, a, b, period)
    old = int(entry.get("好感", 0))
    old_tier, _, _ = npc_rel_tier(old)
    new = int(max(-100, min(100, old + delta)))
    entry["好感"] = new
    entry["最后互动旬"] = period
    if delta and reason:
        entry.setdefault("历史事件", []).insert(0, {"事件": reason, "变化": int(delta), "旬": period})
        entry["历史事件"] = entry["历史事件"][:10]
    new_tier, _, _ = npc_rel_tier(new)
    entry["关系类型"] = new_tier
    entry["印象"] = new_tier if new_tier in ("仇敌", "知己", "同盟") else entry.get("印象", "疏离")
    if notify and (abs(delta) >= 10 or new_tier != old_tier):
        line = f"🌸 {a} 与 {b}「{reason or '关系变化'}」：{new_tier}（好感 {new}）"
        game_state.relationship_events.append({"msg": line, "period": period, "a": a, "b": b})
        game_state.relationship_log.insert(0, line)
        game_state.relationship_log = game_state.relationship_log[:NPC_REL_LOG_MAX]


def sync_npc_rel_to_player(game_state):
    """关系网 → 玩家可见的 rivalries/alliances 增量同步（只增强，不覆盖玩家主动操作值）。"""
    if not isinstance(getattr(game_state, "rivalries", None), dict):
        game_state.rivalries = {}
    if not isinstance(getattr(game_state, "alliances", None), dict):
        game_state.alliances = {}
    for a, row in (game_state.npc_relationships or {}).items():
        for b, entry in row.items():
            if b not in (game_state.npcs or {}) or not isinstance(entry, dict):
                continue
            score = int(entry.get("好感", 0))
            if score <= -20:
                game_state.rivalries[b] = max(game_state.rivalries.get(b, 0), min(100, -score))
            if score >= 50:
                game_state.alliances[b] = max(game_state.alliances.get(b, 0), min(100, score - 40))


TRUST_INTEL_POOL = [
    "皇帝近日常往御书房召见兵部的人，怕是要有边事。",
    "内务府这季度的份例被克扣了一成，好几个宫都在传。",
    "皇后娘娘昨儿把掌事嬷嬷骂了一顿，中宫最近不太平。",
    "某位主子深夜遣人出宫，送的东西怕是不小。",
    "太医院最近常往慈宁宫跑，太后的凤体怕是有恙。",
]


def generate_npc_visits(game_state, max_visits=2):
    """NPC 主动上门：由主控互动写入的 attitude 状态轴（好感/信任/畏惧/爱慕/敌意）驱动。

    每旬最多 max_visits 条；没有 attitude 数据（旧存档/未互动过）时静默返回。
    """
    msgs = []
    candidates = []
    for name, npc in (game_state.npcs or {}).items():
        if name in ("太后", "皇后"):
            continue
        if not isinstance(npc, dict) or not npc.get("alive", True):
            continue
        att = npc.get("attitude") or {}
        if not isinstance(att, dict) or not att:
            continue
        love = int(att.get("爱慕", 0) or 0)
        hate = int(att.get("敌意", 0) or 0)
        trust = int(att.get("信任", 0) or 0)
        fear = int(att.get("畏惧", 0) or 0)
        favor = int(att.get("好感", 0) or 0)
        if love >= 60:
            candidates.append((0.5, "love", name))
        elif hate >= 60:
            candidates.append((0.5, "hate", name))
        elif trust >= 70:
            candidates.append((0.4, "trust", name))
        elif fear >= 70:
            candidates.append((0.4, "fear", name))
        elif favor >= 55:
            candidates.append((0.25, "favor", name))
    if not candidates:
        return msgs
    random.shuffle(candidates)
    for chance, kind, name in candidates:
        if len(msgs) >= max_visits:
            break
        if random.random() > chance:
            continue
        if kind == "love":
            gain = random.randint(8, 20)
            game_state.silver += gain
            msgs.append(f"🕊️ {name}主动来访，赠上一匣胭脂水粉（银两+{gain}）——她眼里藏不住的心思，宫里人都看在眼里。")
            game_state.add_memory(f"{name}主动来访赠礼")
        elif kind == "hate":
            game_state.rivalries[name] = game_state.rivalries.get(name, 0) + random.randint(5, 12)
            msgs.append(f"⚠️ {name}遣人在你必经的甬道上「无意」撞翻了你新制的裙裳——她对你的敌意，已经摆在明面上了。")
            game_state.add_memory(f"{name}上门挑衅")
        elif kind == "trust":
            intel = random.choice(TRUST_INTEL_POOL)
            msgs.append(f"🌙 {name}屏退左右，悄声告诉你：{intel}")
            game_state.add_memory(f"{name}私下密告消息")
        elif kind == "fear":
            game_state.relationships.setdefault(name, {"好感": 0, "印象": "初识"})
            cur = game_state.relationships[name].get("好感", 0)
            game_state.relationships[name]["好感"] = min(100, cur + 3)
            msgs.append(f"🍵 {name}亲自捧了盏新茶来请安，说话时眼神不敢与你相接——她怕你，也开始讨好你。")
        else:  # favor
            msgs.append(f"🌸 {name}遣宫人递来帖子，邀你改日同往御花园赏花。")
            game_state.add_memory(f"收到{name}的赏花帖")
    return msgs


def process_npc_relationships(game_state):
    """每旬执行：NPC 之间关系自然变化 + 偶发事件。返回叙事消息列表（进情报）。"""
    msgs = []
    if not isinstance(getattr(game_state, "npc_relationships", None), dict):
        game_state.npc_relationships = {}
    if not isinstance(getattr(game_state, "relationship_events", None), list):
        game_state.relationship_events = []
    if not isinstance(getattr(game_state, "relationship_log", None), list):
        game_state.relationship_log = []
    period = f"{game_state.year}年{game_state.month}月"
    alive = [n for n, c in (game_state.npcs or {}).items()
             if c.get("alive", True) and n != "太后"]
    if len(alive) < 2:
        return msgs

    pairs = [(a, b) for a in alive for b in alive if a != b]

    # ① 好感自然衰减：向 0 靠近 1~2 点
    for a, b in pairs:
        entry = _ensure_npc_rel(game_state, a, b, period)
        score = int(entry.get("好感", 0))
        if score == 0:
            continue
        move = random.choice([1, 2])
        entry["好感"] = int(max(-100, min(100, score - move if score > 0 else score + move)))

    # ② 压力传导：高压者对所有人好感-1；心情愉悦者 +1
    for a in alive:
        pres = int((game_state.npcs[a] or {}).get("压力", 0) or 0)
        if pres >= 70 or pres <= 20:
            step = -1 if pres >= 70 else 1
            for b in alive:
                if a == b:
                    continue
                entry = _ensure_npc_rel(game_state, a, b, period)
                entry["好感"] = int(max(-100, min(100, entry.get("好感", 0) + step)))

    # ③ 位份相近自然亲近/冲突（每月）
    if game_state.day <= 10:
        for a, b in pairs:
            la = RANK_LEVELS.get(normalize_rank_name((game_state.npcs[a] or {}).get("rank", "答应")), 0)
            lb = RANK_LEVELS.get(normalize_rank_name((game_state.npcs[b] or {}).get("rank", "答应")), 0)
            if abs(la - lb) > 1:
                continue
            pa = (game_state.npcs[a] or {}).get("personality", "")
            pb = (game_state.npcs[b] or {}).get("personality", "")
            clash = (pa, pb) in NPC_PERSONALITY_CLASH or (pb, pa) in NPC_PERSONALITY_CLASH
            chance = 0.05 if clash else (0.25 if (pa and pa == pb) else 0.15)
            if random.random() < chance:
                if clash:
                    delta, reason = -random.randint(2, 6), "言语冲撞"
                else:
                    delta, reason = random.randint(1, 3), "同病相怜"
                modify_npc_rel(game_state, a, b, delta, reason, period)
                modify_npc_rel(game_state, b, a, delta, reason, period, notify=False)

    # ④ 每月偶发大事（全后宫最多 2 件，避免轰炸）
    if game_state.day <= 10:
        big = []
        # 御花园偶遇
        if random.random() < 0.30:
            a, b = random.sample(alive, 2)
            good = random.random() < 0.55
            delta = random.randint(5, 12) if good else -random.randint(5, 12)
            reason = "御花园偶遇相谈甚欢" if good else "御花园偶遇言语不和"
            modify_npc_rel(game_state, a, b, delta, reason, period)
            modify_npc_rel(game_state, b, a, int(delta * 0.8), reason, period, notify=False)
            big.append(f"🌸 {reason}，{a}与{b}间的气氛随之变化")
        # 高位施恩/训斥低位
        if random.random() < 0.20:
            hi = [n for n in alive if RANK_LEVELS.get(normalize_rank_name((game_state.npcs[n] or {}).get("rank", "答应")), 0) >= RANK_LEVELS.get("嫔", 0)]
            lo = [n for n in alive if n not in hi]
            if hi and lo:
                a, b = random.choice(hi), random.choice(lo)
                good = random.random() < 0.5
                delta = random.randint(3, 8) if good else -random.randint(5, 15)
                reason = f"{a}赏脸施恩" if good else f"{a}当众训斥"
                modify_npc_rel(game_state, b, a, delta, reason, period)
                big.append(f"🏛️ {reason}，{b}心中暗记")
        # 野心勃勃者暗生嫌隙
        if random.random() < 0.20:
            ambit = [n for n in alive if (game_state.npcs[n] or {}).get("personality") == "野心勃勃"]
            if ambit:
                a = random.choice(ambit)
                rivals = [n for n in alive if n != a
                          and RANK_LEVELS.get(normalize_rank_name((game_state.npcs[n] or {}).get("rank", "答应")), 0)
                          > RANK_LEVELS.get(normalize_rank_name((game_state.npcs[a] or {}).get("rank", "答应")), 0)]
                if rivals:
                    b = random.choice(rivals)
                    modify_npc_rel(game_state, a, b, -random.randint(5, 15), "暗地里觊觎上位", period, notify=False)
        # 强者结拜 / 旧怨激化
        for a in alive:
            row = (game_state.npc_relationships or {}).get(a) or {}
            for b, entry in list(row.items()):
                if b == a or b not in (game_state.npcs or {}) or not isinstance(entry, dict):
                    continue
                s = int(entry.get("好感", 0))
                if s >= 70 and random.random() < 0.15:
                    modify_npc_rel(game_state, a, b, random.randint(15, 25), "月下焚香结为干姐妹", period)
                    modify_npc_rel(game_state, b, a, random.randint(15, 25), "月下焚香结为干姐妹", period, notify=False)
                    big.append(f"💛 {a}与{b}月下结拜，情同姐妹")
                elif s <= -40 and random.random() < 0.10:
                    modify_npc_rel(game_state, a, b, -random.randint(5, 15), "旧怨再激，形同陌路", period, notify=False)
        # 重大关系事件同步为情报流言，统一呈现在情报面板（display-only：目标"后宫"不触发属性损伤）
        for rel_msg in big[:2]:
            _append_intrigue_rumor(game_state, {
                "target": "后宫", "type": "npc", "severity": 2,
                "turns_left": random.randint(2, 4),
                "text": rel_msg, "source": "relationship_net",
            })
        msgs.extend(big[:2])

    # ⑤ 同步到玩家可见的 rivalries/alliances
    sync_npc_rel_to_player(game_state)
    return msgs


def npc_relationships_payload(game_state):
    """返回前端关系网数据（含类型/图标/颜色）。"""
    out = {}
    for a, row in (getattr(game_state, "npc_relationships", {}) or {}).items():
        if a not in (game_state.npcs or {}):
            continue
        out[a] = {}
        for b, entry in row.items():
            if b not in (game_state.npcs or {}) or not isinstance(entry, dict):
                continue
            s = int(entry.get("好感", 0))
            tier, icon, color = npc_rel_tier(s)
            out[a][b] = {
                "score": s, "tier": tier, "icon": icon, "color": color,
                "impress": entry.get("印象", ""),
                "events": (entry.get("历史事件") or [])[:5],
            }
    return out


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
        # 重华宫相关字段：宫殿归属、监护人、是否在馆
        "palace": "",
        "guardian": "",
        "in_chonghua": False,
    }
    # 五维遗传（出生值含噪声，不受互斥钳制）
    child["stats"] = calc_child_birth_stats(gender, game_state, mother_name)
    # 旧属性从遗传五维派生（不再独立随机），保持现有逻辑兼容
    _s = child["stats"]
    child["talent"] = _s.get("文治", _s.get("文采", 40))
    child["health"] = _s.get("体魄", 70)
    child["wit"] = _s.get("心性", 40)
    # 标签系统：特殊规则 + 出生随机标签
    special = []
    stats = child["stats"]
    ensure_child_tags(child)
    if gender == "公主" and stats.get("容貌", 0) >= 85:
        grant_child_tag(child, "倾国倾城")
        special.append("🌹 生而倾国，他日择驸马，门第必高一档")
    if gender == "皇子" and stats.get("仪容", 0) >= 80:
        grant_child_tag(child, "类父")
        special.append("🌟 天生贵仪，他日立储，群臣必加三分称许")
    # 出生随机标签（概率性，最多再给1个）
    if random.random() < 0.30:
        birth_pool = [t for t in CHILD_TAG_INFO if t not in ("倾国倾城",)]
        bt = random.choice(birth_pool)
        granted, _ = grant_child_tag(child, bt)
        if granted:
            info = CHILD_TAG_INFO[bt]
            tag_msgs = apply_child_tag_stats(child, bt)
            special.append(f"{info['icon']} 生来{bt}：{'，'.join(tag_msgs)}")
    if special:
        add_child_event(child, "✨ 天资异禀：" + "；".join(special))
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
            # 生成公主隐藏择偶偏好（情感锚点），十岁初显性情
            if not child.get("preference"):
                child["preference"] = random.choice(PRINCESS_PREFERENCES)
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
    elif age_years == 15 and not child.get("fifteen_years", False):
        child["fifteen_years"] = True
        if gender == "公主":
            # 及笄礼：解锁择婿。marriage_status 若仍是「未议」则不改，仅点亮入口叙事
            if not child.get("preference"):
                child["preference"] = random.choice(PRINCESS_PREFERENCES)
            events.append(f"🌺 {prefix}公主 {child_name} 已及笄，可议婚论嫁，宫中始为其相看驸马。")
            if game_state:
                game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 3)
        else:
            child["wit"] = min(100, child.get("wit", 40) + random.randint(4, 10))
            events.append(f"🎓 {prefix}皇子 {child_name} 年已十五，学问渐成，可参赞政务。")
    elif age_years == 18 and not child.get("eighteen_years", False):
        child["eighteen_years"] = True
        if gender == "皇子":
            # ---- 皇子成年开府 & 择妃剧情 ----
            title = child.get("title") or random.choice(["雍王", "晋王", "楚王", "齐王", "赵王", "魏王"])
            child["title"] = title
            mansion_name = f"{title}府"
            child["mansion"] = {"name": mansion_name, "level": 1, "income": random.randint(20, 50), "reputation": 60, "log": []}
            child["marriage_status"] = "议婚中"
            # 不再自动指定正妃，改为生成候选人列表供交互面板使用
            child["suitors"] = generate_prince_suitors(game_state, child)
            child["suitors_period"] = period_stamp(game_state) if 'period_stamp' in globals() else None
            flavor_open = (
                f"🏛️ {prefix}皇子 {child_name} 年满十八，依制开府建牙，赐第{mansion_name}！"
                f"圣上亲题匾额，内务府拨银三千两修缮，王府初具气象。"
            )
            events.append(flavor_open)
            add_child_event(child, flavor_open)
            child.setdefault("marriage_events", []).insert(0, flavor_open)
            if game_state:
                game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 8)
                game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + 5)
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

    # ---- 已出嫁公主：省亲与公主府随机事件 ----
    events.extend(process_princess_marriage_events(game_state))
    # ---- 成年公主强制出嫁催办（含 NPC 所出） ----
    events.extend(process_princess_force_marriage(game_state))
    return events


# ============================================================
#  公主择婿与省亲 · 核心逻辑
# ============================================================

def period_stamp(game_state):
    """当前一旬的唯一标记，用于「每旬限一次」与省亲间隔计算。"""
    return f'{getattr(game_state, "year", 0)}-{getattr(game_state, "month", 0)}-{getattr(game_state, "day", 0)}'


def is_princess(child):
    return isinstance(child, dict) and child.get("gender") == "公主"


def princess_marriage_decider(game_state, child):
    """依皇帝态度（性格 + 对玩家宠爱）决定公主择婿主持人。

    - 皇帝态度冷淡（宠爱低）：皇帝亲选，玩家只能旁观；
    - 皇帝态度中庸：交由孩子生母（若生母在世且为妃嫔）自选，否则皇帝亲选；
    - 皇帝态度亲厚（宠爱高或痴情人格）：可交由皇后择婿或生母自选。

    返回字符串：'皇帝亲选' / '生母自选' / '皇后择婿'。
    结果缓存在 child['marriage_decider']，一经定下不再随宠爱浮动。
    """
    cached = child.get("marriage_decider")
    if cached:
        return cached
    # 若玩家已请旨亲裁，主持人即为玩家（生母自选的一种）
    if child.get("marriage_authority"):
        child["marriage_decider"] = "生母自选"
        return "生母自选"
    emp = getattr(game_state, "emperor", None)
    personality = emp.get("personality", "明君") if isinstance(emp, dict) else "明君"
    favor = 0
    try:
        favor = int(game_state.attributes.get("宠爱", 0) or 0)
    except (TypeError, ValueError):
        favor = 0
    # 生母是否在世且可主持（玩家本人或在世妃嫔）
    mother_name = child.get("adoptive_mother") or child.get("birth_mother") or ""
    mother_alive = False
    if mother_name and mother_name == getattr(game_state, "name", ""):
        mother_alive = True
    else:
        npc = (getattr(game_state, "npcs", {}) or {}).get(mother_name)
        if isinstance(npc, dict) and npc.get("alive", True):
            mother_alive = True
    if personality == "痴情" or favor >= 70:
        decider = "生母自选" if mother_alive else "皇后择婿"
    elif personality in ("昏君", "多疑") or favor < 30:
        decider = "皇帝亲选"
    else:
        decider = "生母自选" if mother_alive else "皇帝亲选"
    child["marriage_decider"] = decider
    return decider


def iter_all_princesses(game_state):
    """遍历后宫所有在世公主（含玩家与 NPC 所出），返回 (owner_name, owner_type, index, child)。"""
    for idx, c in enumerate(getattr(game_state, "children", []) or []):
        if is_princess(c) and c.get("alive", True):
            yield (game_state.name, "player", idx, c)
    for name, npc in (getattr(game_state, "npcs", {}) or {}).items():
        if not isinstance(npc, dict) or name == game_state.name or name == "太后":
            continue
        for idx, c in enumerate(npc.get("children", []) or []):
            if is_princess(c) and c.get("alive", True):
                yield (name, "npc", idx, c)



def princess_prestige_tier(game_state, child):
    """公主体面度：由生母位份 + 公主圣宠 + 记名嫡出综合，得出 low/mid/high。"""
    favor = int(child.get("emperor_favor", 30) or 30)
    mother_name = child.get("adoptive_mother") or child.get("birth_mother") or ""
    mother_power = 0
    if mother_name and mother_name == getattr(game_state, "name", ""):
        mother_power = get_rank_power(game_state.rank.name, getattr(game_state, "nobletitle", None))
    else:
        npc = (getattr(game_state, "npcs", {}) or {}).get(mother_name)
        if isinstance(npc, dict):
            mother_power = get_rank_power(normalize_rank_name(npc.get("rank", "答应")), npc.get("nobletitle"))
        else:
            mother_power = get_rank_power(game_state.rank.name, getattr(game_state, "nobletitle", None))
    is_heir_line = bool(child.get("is_heir"))
    score = mother_power * 3 + favor * 0.5 + (20 if is_heir_line else 0)
    if score >= 70:
        return "high"
    if score >= 40:
        return "mid"
    return "low"


def suitor_grade_weights(tier):
    """体面度→候选门第权重（grade 1..9，权重越大越常见）。"""
    return {
        "low":  [1, 2, 4, 8, 14, 18, 20, 16, 10],
        "mid":  [3, 6, 10, 16, 20, 16, 12, 7, 4],
        "high": [16, 20, 18, 14, 10, 7, 4, 2, 1],
    }.get(tier, [3, 6, 10, 16, 20, 16, 12, 7, 4])


def roll_hidden_tags(grade):
    """按门第抽取隐藏标签：高门更易「外戚之相」，寒门更易「志大才疏」。"""
    tags = []
    pool = list(SUITOR_HIDDEN_TAGS)
    n = random.randint(1, 2)
    picks = random.sample(pool, min(n, len(pool)))
    for t in picks:
        if t["key"] == "外戚之相" and grade > 3 and random.random() < 0.6:
            continue
        if t["key"] == "少年英才" and grade > 6 and random.random() < 0.5:
            continue
        tags.append(t["key"])
    return tags


def suitor_male_name():
    """生成驸马姓名：官宦子弟多用清朗男名，姓氏取民间姓。"""
    surname = random_surname(NPC_SURNAMES)
    return surname + random_given(EMPEROR_GIVEN, 0.5)


def suitor_female_name():
    """生成皇子妃/秀女姓名：复用 names.py 中的女名生成逻辑。"""
    from names import generate_female_name
    return generate_female_name()


def next_suitor_uid(game_state):
    seq = int(getattr(game_state, "child_uid_seq", 1) or 1)
    game_state.child_uid_seq = seq + 1
    return f"s{seq}"


def generate_prince_suitors(game_state, child):
    """为皇子生成一批候选正妃，返回列表。门第随皇子体面度上移。"""
    tier = princess_prestige_tier(game_state, child)  # 复用公主体面度算法
    weights = suitor_grade_weights(tier)
    grades = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    count = random.randint(PRINCE_SUITOR_MIN, PRINCE_SUITOR_MAX)
    suitors = []
    for _ in range(count):
        grade = random.choices(grades, weights=weights)[0]
        faction = random.choice(list(COURT_FACTIONS.keys()))
        base = GRADE_BASE_SCORE.get(grade, 45)
        suitor = {
            "uid": next_suitor_uid(game_state),
            "name": suitor_female_name(),
            "father_title": _pick_official_title(grade),
            "faction": faction,
            "grade": grade,
            "family_score": base,
            "family": base,
            "talent": random.randint(35, 95),
            "looks": random.randint(35, 95),
            "age": random.randint(15, 22),
            "ambition": random.randint(20, 90),
            "hidden_tags": roll_hidden_tags(grade),
            "inspected": False,
        }
        suitors.append(suitor)
    return suitors


def generate_suitors(game_state, child):
    """为公主生成一批候选驸马，返回列表。门第随体面度上移。"""
    tier = princess_prestige_tier(game_state, child)
    weights = suitor_grade_weights(tier)
    grades = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    count = random.randint(PRINCESS_SUITOR_MIN, PRINCESS_SUITOR_MAX)
    suitors = []
    for _ in range(count):
        grade = random.choices(grades, weights=weights)[0]
        faction = random.choice(list(COURT_FACTIONS.keys()))
        base = GRADE_BASE_SCORE.get(grade, 45)
        suitor = {
            "uid": next_suitor_uid(game_state),
            "name": suitor_male_name(),
            "father_title": _pick_official_title(grade),
            "faction": faction,
            "grade": grade,
            "family_score": base,
            "family": base,
            "talent": random.randint(35, 95),
            "looks": random.randint(35, 95),
            "age": random.randint(16, 26),
            "ambition": random.randint(20, 90),
            "hidden_tags": roll_hidden_tags(grade),
            "inspected": False,
        }
        suitors.append(suitor)
    return suitors


def suitor_public_view(suitor):
    """候选人对玩家的呈现：未细察时隐藏野心与标签。"""
    view = {
        "uid": suitor.get("uid"),
        "name": suitor.get("name"),
        "father_title": suitor.get("father_title"),
        "faction": suitor.get("faction"),
        "family": suitor.get("family"),
        "talent": suitor.get("talent"),
        "looks": suitor.get("looks"),
        "age": suitor.get("age"),
        "inspected": bool(suitor.get("inspected")),
    }
    if suitor.get("inspected"):
        view["ambition"] = suitor.get("ambition")
        view["hidden_tags"] = suitor.get("hidden_tags", [])
        view["hidden_tag_descs"] = [
            next((t["desc"] for t in SUITOR_HIDDEN_TAGS if t["key"] == k), k)
            for k in suitor.get("hidden_tags", [])
        ]
    else:
        view["ambition"] = None
        view["hidden_tags"] = []
    return view


def emperor_decision_type(game_state, child):
    """当前婚事决策类型：决策权已下放给生母/皇后时用「慈父型」（重情）；否则由皇帝人格映射。"""
    if child.get("marriage_authority"):
        return "慈父型"
    personality = ""
    emp = getattr(game_state, "emperor", None)
    if isinstance(emp, dict):
        personality = emp.get("personality", "")
    return EMPEROR_DECISION_TYPE.get(personality, "平衡型")


def preference_match_score(child, suitor):
    """公主偏好与候选人的契合度（0–100）。"""
    pref = child.get("preference")
    if not pref:
        return 50
    talent = suitor.get("talent", 50)
    looks = suitor.get("looks", 50)
    faction = suitor.get("faction", "")
    tags = suitor.get("hidden_tags", [])
    score = 50
    if pref == "文雅清流":
        score = talent * 0.7 + (20 if faction == "文官党" else 0)
        if "文采斐然" in tags:
            score += 15
    elif pref == "英武豪迈":
        score = (looks * 0.4 + talent * 0.3) + (25 if faction == "武官党" else 0)
        if "少年英才" in tags:
            score += 12
    elif pref == "温厚持重":
        score = 60 + (15 if "家风清正" in tags else 0) - (20 if "风流成性" in tags else 0)
    elif pref == "俊逸风流":
        score = looks * 0.85
        if "风流成性" in tags:
            score += 10
    elif pref == "务实干练":
        score = talent * 0.5 + suitor.get("ambition", 50) * 0.3 - (15 if "志大才疏" in tags else 0)
    return max(0, min(100, int(score)))


def suitor_court_favor_score(game_state, child, suitor):
    """候选人「圣意契合度」：按当前决策类型加权各维度，供玩家参考。"""
    dtype = emperor_decision_type(game_state, child)
    weights = DECISION_WEIGHTS.get(dtype, DECISION_WEIGHTS["平衡型"])
    dims = {
        "looks": suitor.get("looks", 50),
        "talent": suitor.get("talent", 50),
        "family": suitor.get("family", 50),
        "ambition": suitor.get("ambition", 50),
        "preference_match": preference_match_score(child, suitor),
    }
    total = 0.0
    for k, w in weights.items():
        total += dims.get(k, 50) * w
    return max(0, min(100, int(total)))


def find_player_prince(game_state, child_uid):
    """按 uid 找到皇子，返回 (index, child) 或 (-1, None)。

    先在玩家子嗣中查找；找不到时再遍历 NPC 妃嫔所出的皇子。
    """
    for idx, c in enumerate(getattr(game_state, "children", []) or []):
        ensure_child_fields(c)
        if str(c.get("uid")) == str(child_uid) and c.get("gender") == "皇子":
            return idx, c
    for name, npc in (getattr(game_state, "npcs", {}) or {}).items():
        if not isinstance(npc, dict) or name == game_state.name or name == "太后":
            continue
        for idx, c in enumerate(npc.get("children", []) or []):
            ensure_child_fields(c)
            if str(c.get("uid")) == str(child_uid) and c.get("gender") == "皇子":
                return idx, c
    return -1, None


def prince_serialize(game_state, child):
    """皇子择妃/婚姻状态序列化，供前端渲染。"""
    ensure_child_fields(child)
    suitors = child.get("suitors") or []
    suitor_views = []
    for s in suitors:
        v = suitor_public_view(s)
        v["court_favor"] = suitor_court_favor_score(game_state, child, s)
        suitor_views.append(v)
    mother_name = child.get("adoptive_mother") or child.get("birth_mother") or ""
    is_own = mother_name == getattr(game_state, "name", "") or child in (getattr(game_state, "children", []) or [])
    return {
        "uid": child.get("uid"),
        "name": child.get("name"),
        "age": int(child.get("age", 0)),
        "title": child.get("title", ""),
        "marriage_status": child.get("marriage_status", "未议"),
        "suitors": suitor_views,
        "consort": serialize_offspring_holder(child.get("consort")),
        "mansion": child.get("mansion"),
        "marriage_events": (child.get("marriage_events") or [])[:8],
        "mother": mother_name,
        "is_own": bool(is_own),
    }


def find_player_princess(game_state, child_uid):
    """按 uid 找到公主，返回 (index, child) 或 (-1, None)。

    先在玩家子嗣中查找；找不到时再遍历 NPC 妃嫔所出的公主，
    使 NPC 抚养/所生的公主也能进入择婿与婚嫁流程（index 对 NPC
    公主表示其在生母 children 列表中的下标，调用方仅原地改 child，
    不依赖 index 归属）。
    """
    for idx, c in enumerate(getattr(game_state, "children", []) or []):
        ensure_child_fields(c)
        if str(c.get("uid")) == str(child_uid) and is_princess(c):
            return idx, c
    for name, npc in (getattr(game_state, "npcs", {}) or {}).items():
        if not isinstance(npc, dict) or name == game_state.name or name == "太后":
            continue
        for idx, c in enumerate(npc.get("children", []) or []):
            ensure_child_fields(c)
            if str(c.get("uid")) == str(child_uid) and is_princess(c):
                return idx, c
    return -1, None



def default_mansion():
    return {"level": 1, "income": 0, "reputation": 50, "log": []}


def apply_marriage_court_effect(game_state, child):
    """公主出降后，驸马家族势力抬升其所属派系的朝堂好感度；命中外戚之相则埋隐患。"""
    consort = child.get("consort") or {}
    faction = consort.get("faction")
    power = int(consort.get("family_score", 50) or 50)
    favor = normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None))
    if faction in favor:
        favor[faction] = max(0, min(100, favor[faction] + round(power / 20)))
    game_state.court_faction_favor = favor
    notes = []
    if "外戚之相" in consort.get("hidden_tags", []):
        notes.append(f"⚠️ {consort.get('name','驸马')}出身权门，朝野已有『外戚坐大』之虑。")
    return notes


def subsidize_princess_mother(game_state, child, occasion="出嫁"):
    """出嫁公主随机补贴母亲（生母或养母）。

    - 若生母为玩家本人：随机加银两；
    - 若生母为在世 NPC 妃嫔：给其加银两与对玩家好感；
    返回补贴文案（无补贴时返回 None）。
    """
    if random.random() >= 0.55:
        return None
    mother_name = child.get("adoptive_mother") or child.get("birth_mother") or ""
    if not mother_name:
        return None
    amount = random.randint(20, 80)
    pname = child.get("name", "公主")
    if mother_name == getattr(game_state, "name", ""):
        game_state.silver = getattr(game_state, "silver", 0) + amount
        game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + random.randint(1, 3))
        return f"🎁 {pname}{occasion}后不忘母恩，遣人送来体己银{amount}两孝敬于你（银两+{amount}）"
    npc = (getattr(game_state, "npcs", {}) or {}).get(mother_name)
    if isinstance(npc, dict) and npc.get("alive", True):
        npc["silver"] = int(npc.get("silver", 0) or 0) + amount
        if mother_name in game_state.relationships:
            game_state.relationships[mother_name]["好感"] = min(100, game_state.relationships[mother_name].get("好感", 0) + random.randint(1, 4))
        return f"🎁 {pname}{occasion}后厚赠生母{mother_name}体己银{amount}两，{mother_name}感念不已"
    return None


def process_princess_force_marriage(game_state):
    """年满 PRINCESS_FORCE_MARRY_AGE 的公主必须出嫁：逐旬催办，
    连续拖延则由主持人（皇帝/生母/皇后）代为定夺赐婚。含 NPC 所出公主。
    """
    events = []
    for owner, otype, idx, child in iter_all_princesses(game_state):
        ensure_child_fields(child)
        age = int(child.get("age", 0) or 0)
        status = child.get("marriage_status", "未议")
        if age < PRINCESS_FORCE_MARRY_AGE or status in ("已嫁", "和亲"):
            continue
        pname = child.get("name", "公主")
        decider = princess_marriage_decider(game_state, child)
        overdue = int(child.get("force_marry_overdue", 0) or 0) + 1
        child["force_marry_overdue"] = overdue
        # 前两旬仅催办提示，给玩家自主择婿的时间
        if overdue < 3:
            if decider == "生母自选":
                msg = f"⏳ {pname}已年满{age}，依制早该出降，宗人府屡次催办，母族当尽早择定佳婿"
            elif decider == "皇后择婿":
                msg = f"⏳ {pname}已年满{age}，中宫皇后有意代为择婿，宗人府正在拟定人选"
            else:
                msg = f"⏳ {pname}已年满{age}，皇帝将亲为择定驸马，只待钦点"
            add_child_event(child, msg)
            child.setdefault("marriage_events", []).insert(0, msg)
            events.append(msg)
            continue
        # 拖延过久：由主持人强制赐婚
        if status == "已定" and child.get("consort"):
            consort = child.get("consort") or {}
        else:
            consort = _auto_pick_consort(game_state, child, decider)
            child["consort"] = consort
        child["marriage_status"] = "已嫁"
        child["mansion"] = default_mansion()
        child["suitors"] = []
        child["suitors_period"] = None
        child["force_marry_overdue"] = 0
        if decider == "皇帝亲选":
            who = "皇帝亲自钦点"
        elif decider == "皇后择婿":
            who = "皇后代为择定"
        else:
            who = f"其母{child.get('adoptive_mother') or child.get('birth_mother') or ''}操办"
        msg = f"🎊 {pname}年岁已长，依制出降——{who}驸马{consort.get('name','')}，婚事就此了结"
        add_child_event(child, msg)
        child.setdefault("marriage_events", []).insert(0, msg)
        events.append(msg)
        # 仅玩家名下公主出降才联动朝堂与威望
        if otype == "player":
            court_notes = apply_marriage_court_effect(game_state, child)
            game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + random.randint(3, 7))
            for note in court_notes:
                events.append(note)
        sub = subsidize_princess_mother(game_state, child, occasion="出嫁")
        if sub:
            events.append(sub)
    return [e for e in events if e]


def _auto_pick_consort(game_state, child, decider):
    """主持人代为择婿时，按主持人风格从候选中挑选驸马；无候选则临时生成。"""
    suitors = child.get("suitors") or generate_suitors(game_state, child)
    if not suitors:
        # 兜底：临时生成一个中等门第驸马
        return {
            "name": suitor_male_name(),
            "faction": random.choice(list(COURT_FACTIONS.keys())),
            "father_title": "闲散宗室",
            "family_score": random.randint(45, 65),
            "hidden_tags": [],
            "talent": random.randint(40, 80),
            "looks": random.randint(40, 80),
            "age": random.randint(18, 28),
            "ambition": random.randint(30, 70),
        }
    if decider == "皇帝亲选":
        # 皇帝重门第/派系权衡：取朝堂加分最高者
        pick = max(suitors, key=lambda s: suitor_court_favor_score(game_state, child, s))
    elif decider == "皇后择婿":
        # 皇后求稳：取门第居中、野心不高者
        pick = min(suitors, key=lambda s: (s.get("ambition", 50), -s.get("family_score", 50)))
    else:
        # 生母/慈父：优先契合公主偏好
        pick = max(suitors, key=lambda s: preference_match_score(child, s))
    return dict(pick)


def process_princess_marriage_events(game_state):
    """已出嫁公主的省亲与公主府随机事件（挂转旬 tick）。"""
    events = []
    stamp = period_stamp(game_state)
    for child in getattr(game_state, "children", []) or []:
        if not is_princess(child):
            continue
        ensure_child_fields(child)
        if child.get("marriage_status") not in ("已嫁", "和亲"):
            continue
        mansion = child.get("mansion") or {}
        if mansion:
            income = int(mansion.get("income", 0) or 0)
            if income:
                game_state.silver = getattr(game_state, "silver", 0) + income
        # 驸马家族每旬为玩家贡献朝堂声望（幅度随家族势力），记忆按月节流防刷屏
        consort = child.get("consort") or {}
        faction = consort.get("faction")
        if faction and faction in normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None)):
            base = max(1, int(int(consort.get("family_score", 50) or 50) / 30))
            gain = random.randint(base, base + 2)
            favor = normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None))
            favor[faction] = min(100, int(favor.get(faction, 50) or 0) + gain)
            game_state.court_faction_favor = favor
            note_month = f"{game_state.year}-{game_state.month}"
            if child.get("last_favor_note_month") != note_month:
                child["last_favor_note_month"] = note_month
                game_state.add_memory(f"📈 {faction}因驸马{consort.get('name', '')}之故，朝堂声望+{gain}")
        last = child.get("last_visit_period")
        if last != stamp and random.random() < 0.28 and child.get("marriage_status") == "已嫁":
            child["last_visit_period"] = stamp
            events.append(_princess_visit_event(game_state, child))
        if child.get("marriage_status") == "已嫁" and random.random() < 0.18:
            events.append(_mansion_random_event(game_state, child))
    return [e for e in events if e]


def _princess_visit_event(game_state, child):
    """按公主偏好与驸马隐藏标签生成省亲基调。"""
    name = child.get("name", "公主")
    consort = child.get("consort") or {}
    match = preference_match_score(child, consort)
    tags = consort.get("hidden_tags", [])
    if match < 40 or "风流成性" in tags:
        loss = random.randint(3, 7)
        child["affection"] = max(0, child.get("affection", 30) - loss)
        child["mood"] = "闷闷不乐"
        game_state.attributes["宠爱"] = max(0, game_state.attributes.get("宠爱", 0) - 2)
        msg = f"🥀 {name}回宫省亲，强颜欢笑，言语间难掩委屈，母女相对唏嘘（亲密-{loss}）"
    else:
        gain = random.randint(2, 6)
        child["affection"] = min(100, child.get("affection", 30) + gain)
        child["mood"] = "开心"
        game_state.attributes["宠爱"] = min(game_state.get_attr_max("宠爱"), game_state.attributes.get("宠爱", 0) + 2)
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 2)
        msg = f"🌸 {name}偕驸马回宫省亲，举止雍容，母女团聚其乐融融（亲密+{gain}）"
    add_child_event(child, msg)
    child.setdefault("marriage_events", []).insert(0, msg)
    # 省亲时小概率带回外孙/外孙女，归入玩家名下代为抚养（视为养孙）
    if random.random() < 0.08:
        grand_gender = random.choice(["皇子", "公主"])
        grand_name = new_child_name(grand_gender, game_state)
        grand_child = create_newborn_child(grand_gender, grand_name, game_state, mother_name=name)
        grand_child["adopted"] = True
        grand_child["adoptive_mother"] = game_state.name
        grand_child["adopted_age"] = 0
        grand_child["adopted_at"] = f"建元{game_state.year}年{game_state.month}月"
        grand_child["mood"] = "开心"
        grand_child["affection"] = 50
        game_state.children.append(grand_child)
        game_state.has_children = True
        extra_msg = f" 👶 {name}省亲时带回外孙{grand_name}，由你代为抚养。"
        msg += extra_msg
        add_child_event(grand_child, "随母省亲，归入外祖母膝下")
        game_state.add_memory(f"👶 {name}省亲带回{grand_gender}{grand_name}，归你膝下代养")
    return msg


# ---- 王府/东宫后代折叠面板（设计稿 v1.0） ----
def ensure_descendant_fields(game_state, gc, mansion_name=""):
    """孙辈（皇嗣婚后所出）字段补全：uid / 五维 / 安置状态。五维首次展示时生成后保持稳定。"""
    if not gc.get("uid"):
        try:
            seq = int(getattr(game_state, "child_uid_seq", 1) or 1)
        except (TypeError, ValueError):
            seq = 1
        gc["uid"] = f"g{seq}"
        game_state.child_uid_seq = seq + 1
    for attr, lo, hi in (("文治", 20, 70), ("武略", 15, 65), ("体魄", 40, 85),
                         ("心性", 20, 70), ("仪容", 30, 80)):
        if attr not in gc:
            gc[attr] = random.randint(lo, hi)
    if "安置状态" not in gc:
        gc["安置状态"] = "已入重华宫" if gc.get("in_chonghua") else "在府"
    if not gc.get("安置地"):
        gc["安置地"] = "重华宫" if gc.get("in_chonghua") else (mansion_name or "府邸")
    return gc


def get_descendants(game_state, child):
    """皇嗣的后代 = 其婚配对象名下的 offspring（单一数据源，避免与 GameState.children 双轨）。"""
    consort = child.get("consort") or {}
    return [g for g in (consort.get("offspring") or [])
            if isinstance(g, dict) and g.get("alive", True)]


def mansion_descendants_payload(game_state, child):
    mansion = child.get("mansion") or {}
    out = []
    for gc in get_descendants(game_state, child):
        ensure_descendant_fields(game_state, gc, mansion.get("name", ""))
        out.append({
            "uid": gc.get("uid"), "name": gc.get("name", "未命名"),
            "gender": gc.get("relation", "皇孙"),
            "age": round(float(gc.get("age", 0) or 0)),
            "stats": {k: gc.get(k) for k in ("文治", "武略", "体魄", "心性", "仪容")},
            "安置状态": gc.get("安置状态", "在府"), "安置地": gc.get("安置地", ""),
            "father": gc.get("father", ""), "spouse": gc.get("spouse", ""),
        })
    return out


def _mansion_random_event(game_state, child):
    """公主府随机事件：产业增收 / 驸马纳妾 / 驸马升迁等。"""
    name = child.get("name", "公主")
    consort = child.get("consort") or {}
    mansion = child.get("mansion")
    if not isinstance(mansion, dict):
        mansion = default_mansion()
        child["mansion"] = mansion
    roll = random.random()
    if roll < 0.35:
        inc = random.randint(3, 10)
        mansion["income"] = int(mansion.get("income", 0) or 0) + inc
        msg = f"🏯 {name}公主府名下田庄增收，岁入渐丰（每旬进项+{inc}两）"
    elif roll < 0.6 and "风流成性" in consort.get("hidden_tags", []):
        child["affection"] = max(0, child.get("affection", 30) - random.randint(2, 5))
        child["mood"] = "闷闷不乐"
        mansion["reputation"] = max(0, int(mansion.get("reputation", 50) or 50) - random.randint(3, 8))
        msg = f"💔 {consort.get('name','驸马')}欲纳妾室，{name}心中郁郁，公主府声望受损"
    elif roll < 0.8:
        rep = random.randint(3, 8)
        mansion["reputation"] = min(100, int(mansion.get("reputation", 50) or 50) + rep)
        msg = f"🎊 {name}公主府大宴宾客，冠盖云集，府邸声望+{rep}"
    else:
        faction = consort.get("faction")
        favor = normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None))
        if faction in favor:
            favor[faction] = min(100, favor[faction] + random.randint(1, 4))
        game_state.court_faction_favor = favor
        msg = f"📜 {consort.get('name','驸马')}获朝廷擢用，{faction or '其党'}声势更盛"
    add_child_event(child, msg)
    child.setdefault("marriage_events", []).insert(0, msg)
    return msg




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



# ============================================================
#  夺嫡暗流（储君空悬时的多方博弈）
# ============================================================

HEIR_RACE_MIN_AGE = 8          # 参与夺嫡的最低年龄
HEIR_RACE_MOTHER_WEIGHT = {    # 生母位份权重
    "皇后": 20, "皇贵妃": 15, "贵妃": 10,
    "妃": 5,
}


def _iter_all_princes(game_state):
    """遍历后宫所有皇子，返回 (uid, child, mother_name, is_player_child)。"""
    for c in game_state.children:
        if c.get("gender") == "皇子":
            uid = ensure_child_uid(game_state, c)
            yield uid, c, game_state.name, True
    for name, npc in game_state.npcs.items():
        if name == "太后":
            continue
        for c in npc.get("children", []):
            if c.get("gender") == "皇子":
                uid = ensure_child_uid(game_state, c)
                yield uid, c, name, False


def _prince_mother_rank_weight(game_state, mother_name):
    """按生母位份返回夺嫡权重。"""
    if mother_name == getattr(game_state, "name", ""):
        rank_name = game_state.rank.name
    else:
        npc = (getattr(game_state, "npcs", {}) or {}).get(mother_name)
        rank_name = normalize_rank_name(npc.get("rank", "答应")) if isinstance(npc, dict) else "答应"
    return HEIR_RACE_MOTHER_WEIGHT.get(rank_name, 0)


def _find_prince_by_uid(game_state, uid):
    """按 uid 找皇子，返回 (child, mother_name) 或 (None, None)。"""
    for u, c, mother, _is_player in _iter_all_princes(game_state):
        if str(u) == str(uid):
            return c, mother
    return None, None


def compute_heir_momentum_base(game_state, child, mother_name):
    """夺嫡势头基础值：圣宠 + 生母位份 + 年龄权重。"""
    favor = int(child.get("emperor_favor", 30) or 30)
    age = float(child.get("age", 0) or 0)
    base = favor * 0.4 + _prince_mother_rank_weight(game_state, mother_name)
    if age >= 15:
        base += 10
    elif age >= 10:
        base += 5
    return base


def _heir_race_settle(game_state, uid, child, mother_name):
    """夺嫡结果落定：写入 heir_status。"""
    ensure_child_fields(child)
    if not isinstance(game_state.heir_status, dict):
        game_state.heir_status = default_heir_status()
    child["is_heir"] = True
    child["mood"] = "意气风发"
    prev = game_state.heir_status if isinstance(game_state.heir_status, dict) else {}
    game_state.heir_status = normalize_heir_status({
        "deposed": prev.get("deposed", []),
        "heir_id": str(uid),
        "heir_name": child.get("name", "皇子"),
        "heir_mother": child.get("birth_mother") or mother_name,
        "established_at": f"建元{game_state.year}年{game_state.month}月",
        "last_event": "夺嫡定储",
    })
    game_state.heir_consorts = default_heir_consorts()
    if mother_name == game_state.name:
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + 15)


def process_heir_race(game_state):
    """夺嫡暗流转旬结算：储君空悬时激活，逐旬更新皇子势头并可能触发立储。

    返回情报消息列表（写入 intelligence_list）。
    """
    events = []
    if not isinstance(getattr(game_state, "heir_race", None), dict):
        game_state.heir_race = default_heir_race()
    race = game_state.heir_race
    race["events"] = []  # 本旬事件流水，每旬重置

    heir_id = (game_state.heir_status or {}).get("heir_id")
    emperor = game_state.emperor or {}
    emperor_alive = emperor.get("alive", True)

    # 储君已立或皇帝不在，夺嫡休眠
    if heir_id or not emperor_alive:
        race["active"] = False
        if heir_id:
            race["outcome"] = "settled"
        return events

    # 收集候选皇子（≥8 岁、在世）
    princes = []
    for uid, child, mother, is_player in _iter_all_princes(game_state):
        if child.get("alive", True) and float(child.get("age", 0) or 0) >= HEIR_RACE_MIN_AGE:
            princes.append((uid, child, mother, is_player))

    if len(princes) < 1:
        race["active"] = False
        race["candidates"] = []
        return events

    # 激活夺嫡期
    was_active = race.get("active", False)
    race["active"] = True
    race["outcome"] = None
    race["candidates"] = [uid for uid, _c, _m, _p in princes]
    if not was_active:
        msg = "⚜️ 储君之位空悬，诸皇子渐长，朝野暗流涌动，夺嫡之争已然开启。"
        events.append(msg)
        race["events"].append(msg)
        game_state.add_memory(msg)

    momentum = race.get("momentum", {})
    if not isinstance(momentum, dict):
        momentum = {}

    # 逐旬更新每位候选皇子势头
    valid_uids = set(race["candidates"])
    for uid, child, mother, is_player in princes:
        base = compute_heir_momentum_base(game_state, child, mother)
        prev = momentum.get(uid)
        if prev is None:
            cur = base + random.randint(-3, 3)
        else:
            drift = (base - prev) * 0.25
            cur = prev + drift + random.choice([-1, -1, 0, 1, 1]) * random.randint(1, 5)
        momentum[uid] = max(0, min(100, int(round(cur))))
    # 清理已出局（非候选）的旧记录
    for uid in list(momentum.keys()):
        if uid not in valid_uids:
            momentum.pop(uid, None)
    race["momentum"] = momentum

    # 随机叙事事件（边疆捷报 / 失仪等），影响个别皇子势头
    if princes and random.random() < 0.5:
        uid, child, mother, is_player = random.choice(princes)
        name = child.get("name", "皇子")
        good = random.random() < 0.55
        delta = random.randint(3, 9)
        if good:
            momentum[uid] = max(0, min(100, momentum.get(uid, 0) + delta))
            flavor = random.choice([
                f"👑 {name}获边疆捷报，势头大涨（+{delta}）",
                f"📜 {name}朝会奏对得体，颇得群臣称许（+{delta}）",
                f"🎋 {name}贤名远播，宗室多有附议（+{delta}）",
            ])
        else:
            momentum[uid] = max(0, min(100, momentum.get(uid, 0) - delta))
            flavor = random.choice([
                f"⚠️ {name}朝仪失措，被御史弹劾，声望受损（-{delta}）",
                f"🕯️ {name}行事乖张，皇帝闻之不悦（-{delta}）",
                f"📉 {name}结党之嫌被议，势头受挫（-{delta}）",
            ])
        events.append(flavor)
        race["events"].append(flavor)

    # 储君呼声与皇帝议储
    ranked = sorted(princes, key=lambda t: momentum.get(t[0], 0), reverse=True)
    if ranked:
        top_uid, top_child, top_mother, _tp = ranked[0]
        top_m = momentum.get(top_uid, 0)
        second_m = momentum.get(ranked[1][0], 0) if len(ranked) > 1 else 0
        top_name = top_child.get("name", "皇子")
        if top_m >= 80 and (top_m - second_m) >= 30:
            msg = f"📣 朝野呼声高涨，{top_name}势倾诸皇子，储位之相已现！"
            events.append(msg)
            race["events"].append(msg)
            game_state.add_memory(msg)

        emperor_health = int(emperor.get("health", 80) or 80)
        if top_m >= 95 and emperor_health < 50 and random.random() < 0.5:
            _heir_race_settle(game_state, top_uid, top_child, top_mother)
            msg = f"👑 皇帝召宗室大臣入宫议储，当廷册立{top_name}为太子！夺嫡尘埃落定。"
            events.append(msg)
            race["events"].append(msg)
            game_state.add_memory(msg)
            race["active"] = False
            race["outcome"] = "settled"

    return events

# ============================================================
#  太子系统：监国政务 / 成长特质 / 微服私访 / 内宅
# ============================================================

HEIR_REGENCY_MIN_AGE = 12          # 太子满此岁数方可监国
HEIR_REBELLION_MIN_AGE = 14        # 叛逆期起始年龄
HEIR_SPECIAL_MIN_GAP = 3           # 特殊危机事件的最小间隔（旬）
HEIR_CONSORT_SELECT_AGE = 16       # 选妃年龄
HEIR_INCOGNITO_COST = 30           # 微服私访耗银
HEIR_INCOGNITO_ACTION = 1          # 微服私访耗行动点
HEIR_REGENCY_EVENT_CHANCE = 0.55   # 每旬出现政务的概率
HEIR_LOG_LIMIT = 20                # 各类日志保留条数

# 贤明值 → 特质阈值（(下限, 上限, 特质名)）
HEIR_MERIT_TRAITS = [
    (60, 101, "圣君"),
    (25, 60, "贤明"),
    (-60, -25, "昏聩"),
    (-101, -60, "暴虐"),
]


def heir_state(game_state):
    """取（并就地归一化）储君状态字典。所有太子系统读写都先走这里。"""
    hs = getattr(game_state, "heir_status", None)
    if not isinstance(hs, dict) or "regency_merit" not in hs:
        hs = normalize_heir_status(hs)
        game_state.heir_status = hs
    hs.setdefault("heir_counters", {})
    hs.setdefault("heir_traits", [])
    return hs


def heir_consorts_state(game_state):
    """取（并就地归一化）东宫内宅字典。"""
    hc = getattr(game_state, "heir_consorts", None)
    if not isinstance(hc, dict) or set(HEIR_CONSORT_RANKS) - set(hc.keys()):
        hc = normalize_heir_consorts(hc)
        game_state.heir_consorts = hc
    return hc


def heir_consort_members(game_state, include_primary=True):
    """按位份从高到低返回内宅成员列表（仅在世者）。"""
    hc = heir_consorts_state(game_state)
    members = []
    if include_primary and isinstance(hc.get("太子妃"), dict) and hc["太子妃"].get("alive", True):
        members.append(hc["太子妃"])
    for rank in HEIR_CONSORT_RANKS[1:]:
        for m in hc.get(rank, []):
            if m.get("alive", True):
                members.append(m)
    return members


def heir_consort_total(game_state):
    return len(heir_consort_members(game_state))


def heir_counter_bump(hs, key, step=1):
    """累加太子行为计数器（供不正经结局阈值判定）。"""
    if not key:
        return 0
    counters = hs.setdefault("heir_counters", {})
    try:
        cur = int(counters.get(key, 0) or 0)
    except (TypeError, ValueError):
        cur = 0
    counters[key] = cur + step
    return counters[key]


def heir_add_trait(hs, trait):
    """为太子添加特质标签（去重）。返回是否新增。"""
    if not trait:
        return False
    traits = hs.setdefault("heir_traits", [])
    if trait in traits:
        return False
    traits.append(trait)
    return True


def heir_clamp_merit(hs, delta):
    """调整贤明值并返回实际变化量。"""
    try:
        cur = int(hs.get("regency_merit", 0) or 0)
    except (TypeError, ValueError):
        cur = 0
    updated = max(-100, min(100, cur + int(delta)))
    hs["regency_merit"] = updated
    return updated - cur


def heir_clamp_affection(hs, delta):
    try:
        cur = int(hs.get("heir_affection", 50) or 50)
    except (TypeError, ValueError):
        cur = 50
    updated = max(0, min(100, cur + int(delta)))
    hs["heir_affection"] = updated
    return updated - cur


def heir_clamp_harmony(hs, delta):
    try:
        cur = int(hs.get("consort_harmony", 60) or 60)
    except (TypeError, ValueError):
        cur = 60
    updated = max(0, min(100, cur + int(delta)))
    hs["consort_harmony"] = updated
    return updated - cur


def heir_refresh_merit_traits(game_state):
    """按贤明值区间刷新「圣君 / 贤明 / 昏聩 / 暴虐」标签（四者互斥）。"""
    hs = heir_state(game_state)
    try:
        merit = int(hs.get("regency_merit", 0) or 0)
    except (TypeError, ValueError):
        merit = 0
    traits = hs.setdefault("heir_traits", [])
    exclusive = {name for _lo, _hi, name in HEIR_MERIT_TRAITS}
    target = None
    for lo, hi, name in HEIR_MERIT_TRAITS:
        if lo <= merit < hi:
            target = name
            break
    for name in list(traits):
        if name in exclusive and name != target:
            traits.remove(name)
    if target and target not in traits:
        traits.append(target)
        return target
    return None


def heir_log_push(hs, key, entry, limit=HEIR_LOG_LIMIT):
    """写入太子系统日志（新的在前，超出上限截断）。"""
    log = hs.setdefault(key, [])
    if not isinstance(log, list):
        log = []
        hs[key] = log
    log.insert(0, entry)
    del log[limit:]
    return log


def heir_period_label(game_state):
    return f"{getattr(game_state, 'year', 1)}年{getattr(game_state, 'month', 1)}月"


def heir_apply_choice(game_state, choice, notify_prefix=""):
    """统一结算一个太子事件选项。

    支持字段：merit / affection / attrs / counter / traits / silver / harmony / favor。
    返回 (变化描述列表, 结算摘要 dict)。
    """
    hs = heir_state(game_state)
    notes = []
    summary = {"merit": 0, "affection": 0, "attrs": {}, "silver": 0, "harmony": 0, "traits": []}

    merit_delta = int(choice.get("merit", 0) or 0)
    if merit_delta:
        actual = heir_clamp_merit(hs, merit_delta)
        summary["merit"] = actual
        if actual:
            notes.append(f"贤明{'+' if actual > 0 else ''}{actual}")

    aff_delta = int(choice.get("affection", 0) or 0)
    if aff_delta:
        actual = heir_clamp_affection(hs, aff_delta)
        summary["affection"] = actual
        if actual:
            notes.append(f"太子亲近{'+' if actual > 0 else ''}{actual}")

    harmony_delta = int(choice.get("harmony", 0) or 0)
    if harmony_delta:
        actual = heir_clamp_harmony(hs, harmony_delta)
        summary["harmony"] = actual
        if actual:
            notes.append(f"内宅和睦{'+' if actual > 0 else ''}{actual}")

    for attr, delta in (choice.get("attrs") or {}).items():
        if attr not in game_state.attributes:
            continue
        actual = _clamp_attr(game_state, attr, int(delta))
        if actual:
            summary["attrs"][attr] = actual
            notes.append(f"{attr}{'+' if actual > 0 else ''}{actual}")

    silver_delta = int(choice.get("silver", 0) or 0)
    if silver_delta:
        game_state.silver = max(0, game_state.silver + silver_delta)
        summary["silver"] = silver_delta
        notes.append(f"银两{'+' if silver_delta > 0 else ''}{silver_delta}")

    heir_counter_bump(hs, choice.get("counter"))

    for trait in (choice.get("traits") or []):
        if heir_add_trait(hs, trait):
            summary["traits"].append(trait)
            notes.append(f"太子习性「{trait}」")

    # 内宅好感变化（favor: {位份或姓名: 增量}）
    for key, delta in (choice.get("favor") or {}).items():
        for member in heir_consort_members(game_state):
            if member.get("rank") == key or member.get("name") == key:
                member["favor"] = max(0, min(100, int(member.get("favor", 50)) + int(delta)))
                break

    trait_changed = heir_refresh_merit_traits(game_state)
    if trait_changed:
        notes.append(f"太子已有「{trait_changed}」之名")
    if notify_prefix and notes:
        notes[0] = notify_prefix + notes[0]
    return notes, summary


def get_heir_ruling_style(game_state):
    """推定/初始化太子治国倾向（儒家 / 法家 / 道家）。

    优先取已固化的 heir_ruling_style；未定时按太子妃出身 + 太子天赋随机定调并写回。
    """
    hs = heir_state(game_state)
    style = hs.get("heir_ruling_style")
    if style in ("儒家", "法家", "道家"):
        return style

    weights = {"儒家": 1.0, "法家": 1.0, "道家": 1.0}
    # 太子妃出身影响：其 ruling_style 权重翻倍
    consort = (heir_consorts_state(game_state) or {}).get("太子妃")
    if isinstance(consort, dict):
        cand = find_consort_candidate(consort.get("name", "")) or {}
        cand_style = cand.get("ruling_style") or consort.get("ruling_style")
        if cand_style in weights:
            weights[cand_style] += 2.0
    # 太子天赋：才学高偏儒，机敏高偏法，健康好、心宽偏道
    child = get_heir_child(game_state)
    if isinstance(child, dict):
        ensure_child_fields(child)
        weights["儒家"] += int(child.get("talent", 50) or 50) / 50.0
        weights["法家"] += int(child.get("wit", 50) or 50) / 50.0
        weights["道家"] += int(child.get("health", 70) or 70) / 70.0

    pool = list(weights.keys())
    style = random.choices(pool, weights=[weights[k] for k in pool], k=1)[0]
    hs["heir_ruling_style"] = style
    return style


def heir_activate_regency(game_state, reason="册立太子"):
    """立储后激活监国：写入初始状态并投放第一件政务。返回提示文案列表。"""
    hs = heir_state(game_state)
    msgs = []
    if hs.get("regency_active"):
        return msgs
    child = get_heir_child(game_state)
    if not child:
        return msgs
    ensure_child_fields(child)
    try:
        age = float(child.get("age", 0) or 0)
    except (TypeError, ValueError):
        age = 0
    if age < HEIR_REGENCY_MIN_AGE:
        msgs.append(f"📜 {child.get('name', '太子')}年方{int(age)}，尚幼，待满{HEIR_REGENCY_MIN_AGE}岁方可监国听政。")
        return msgs

    hs["regency_active"] = True
    hs["last_event"] = reason
    style = get_heir_ruling_style(game_state)
    msg = (f"⚖️ 皇帝下诏令{child.get('name', '太子')}入文华殿监国听政，"
           f"六部奏本自此先过东宫。太傅评其秉性偏于{style}之道。")
    msgs.append(msg)
    game_state.add_memory(msg)
    heir_log_push(hs, "regency_events", {
        "period": heir_period_label(game_state),
        "title": "开府监国",
        "detail": msg,
    })

    # 开府即投放第一件政务，令玩家立刻有事可议
    if not isinstance(hs.get("pending_regency_event"), dict):
        first = generate_regency_event(exclude_ids=heir_recent_regency_ids(hs))
        if first:
            hs["pending_regency_event"] = first
            first_msg = (f"📜 东宫开府第一桩{first.get('category', '')}政务已呈："
                         f"{first.get('description', '')}")
            msgs.append(first_msg)
    return msgs


def heir_recent_regency_ids(hs, keep=6):
    """近 keep 条政务的 id，避免短期重复。"""
    ids = []
    for entry in (hs.get("regency_events") or [])[:keep]:
        if isinstance(entry, dict) and entry.get("event_id"):
            ids.append(entry["event_id"])
    return ids


def heir_auto_decide(game_state, event):
    """太子按治国倾向自行决断一件政务，返回 (选项键, 选项字典)。

    倾向匹配的选项权重更高；亲近度低时更可能任性择另一项。
    """
    hs = heir_state(game_state)
    style = get_heir_ruling_style(game_state)
    choices = event.get("choices") or {}
    keys = list(choices.keys())
    if not keys:
        return None, None
    weights = []
    for k in keys:
        w = 1.0
        if choices[k].get("bias") == style:
            w += 2.5
        # 亲近度越低越叛逆：偏向贤明值更低的那一项
        try:
            aff = int(hs.get("heir_affection", 50) or 50)
        except (TypeError, ValueError):
            aff = 50
        if aff < 40 and int(choices[k].get("merit", 0) or 0) < 0:
            w += 1.5
        weights.append(w)
    pick = random.choices(keys, weights=weights, k=1)[0]
    return pick, choices[pick]


def heir_resolve_pending_regency(game_state, hs):
    """上一旬玩家未进言的政务，由太子自行决断并结算。返回消息列表。"""
    msgs = []
    pending = hs.get("pending_regency_event")
    if not isinstance(pending, dict):
        return msgs
    key, choice = heir_auto_decide(game_state, pending)
    hs["pending_regency_event"] = None
    if not choice:
        return msgs
    heir_name = hs.get("heir_name") or "太子"
    notes, _summary = heir_apply_choice(game_state, choice)
    detail = f"🖋️ 你未及进言，{heir_name}已自行批红：「{choice.get('text', '')}」"
    if notes:
        detail += "（" + "，".join(notes) + "）"
    msgs.append(detail)
    game_state.add_memory(detail)
    heir_log_push(hs, "regency_events", {
        "period": heir_period_label(game_state),
        "event_id": pending.get("id"),
        "title": pending.get("category", "政务"),
        "decided_by": "太子自决",
        "choice": choice.get("text", ""),
        "detail": detail,
    })
    return msgs


def process_heir_regency(game_state):
    """监国政务的转旬结算：结算上旬遗留 → 投放新政务。返回消息列表。"""
    msgs = []
    hs = heir_state(game_state)
    if not hs.get("heir_id"):
        return msgs

    child = get_heir_child(game_state)
    if not child or not child.get("alive", True):
        return msgs
    ensure_child_fields(child)

    # 太子成年后自动开府监国
    if not hs.get("regency_active"):
        msgs.extend(heir_activate_regency(game_state, reason="太子成年监国"))
        if not hs.get("regency_active"):
            return msgs

    # 1. 上旬未处置的政务由太子自决
    msgs.extend(heir_resolve_pending_regency(game_state, hs))

    # 2. 投放本旬新政务
    if random.random() < HEIR_REGENCY_EVENT_CHANCE:
        event = generate_regency_event(exclude_ids=heir_recent_regency_ids(hs))
        hs["pending_regency_event"] = event
        msg = f"📜 东宫呈上{event.get('category', '')}政务：{event.get('description', '')}"
        msgs.append(msg)
    return msgs


def process_heir_growth_events(game_state):
    """太子叛逆期 / 特殊危机事件的转旬投放。返回消息列表。"""
    msgs = []
    hs = heir_state(game_state)
    if not hs.get("heir_id"):
        return msgs
    child = get_heir_child(game_state)
    if not child or not child.get("alive", True):
        return msgs
    ensure_child_fields(child)
    try:
        age = float(child.get("age", 0) or 0)
    except (TypeError, ValueError):
        age = 0

    # 已有待决事件时不再叠加
    if isinstance(hs.get("pending_heir_event"), dict):
        return msgs

    period_no = int(getattr(game_state, "year", 1)) * 12 + int(getattr(game_state, "month", 1))

    # 1. 特殊危机（间隔 ≥ HEIR_SPECIAL_MIN_GAP 旬）
    last_special = hs.get("last_special_period")
    gap_ok = not isinstance(last_special, int) or (period_no - last_special) >= HEIR_SPECIAL_MIN_GAP
    if hs.get("regency_active") and gap_ok:
        event = generate_heir_special_event()
        if event:
            hs["pending_heir_event"] = event
            hs["last_special_period"] = period_no
            msgs.append(f"⚠️ 东宫急报「{event.get('name')}」：{event.get('description', '')}")
            return msgs

    # 2. 叛逆期事件
    if age >= HEIR_REBELLION_MIN_AGE:
        event = generate_heir_rebellion_event(age)
        if event:
            hs["pending_heir_event"] = event
            msgs.append(f"🧒 太子又生事端「{event.get('name')}」：{event.get('description', '')}")
    return msgs

def heir_consort_rank_full(game_state, rank):
    """该位份是否已满编。"""
    hc = heir_consorts_state(game_state)
    limit = HEIR_CONSORT_LIMITS.get(rank, 0)
    if rank == "太子妃":
        return isinstance(hc.get("太子妃"), dict) and hc["太子妃"].get("alive", True)
    return len([m for m in hc.get(rank, []) if m.get("alive", True)]) >= limit


def heir_consort_add(game_state, rank, name=None, family="", personality="",
                     favor=None, faction="", fun_tag="", talent=None, looks=None,
                     ruling_style=None):
    """向内宅添加一名成员。位份满编或总数超上限时返回 None。"""
    hc = heir_consorts_state(game_state)
    if rank not in HEIR_CONSORT_RANKS:
        return None
    if heir_consort_rank_full(game_state, rank):
        return None
    if heir_consort_total(game_state) >= HEIR_CONSORT_MAX_TOTAL:
        return None

    if not name:
        name, bg = generate_concubine_identity()
        family = family or bg.get("summary") or bg.get("official_name") or ""
    member = default_heir_consort_member(
        name,
        family=family,
        personality=personality or random.choice(HEIR_CONSORT_PERSONALITIES),
        favor=random.randint(35, 65) if favor is None else favor,
        rank=rank,
    )
    member["faction"] = faction
    member["fun_tag"] = fun_tag or random.choice(HEIR_CONSORT_FUN_TAGS)
    member["talent"] = random.randint(35, 80) if talent is None else int(talent)
    member["looks"] = random.randint(45, 85) if looks is None else int(looks)
    member["entered_at"] = heir_period_label(game_state)
    if ruling_style:
        member["ruling_style"] = ruling_style

    if rank == "太子妃":
        hc["太子妃"] = member
    else:
        hc.setdefault(rank, []).append(member)
    return member


def heir_consort_fill(game_state, count=None):
    """按位份从低到高自动填充侧室（礼部按例送人）。返回新增成员列表。"""
    hs = heir_state(game_state)
    if not isinstance(heir_consorts_state(game_state).get("太子妃"), dict):
        return []          # 未册太子妃则不进侧室
    added = []
    if count is None:
        count = random.randint(1, 2)
    for _ in range(max(0, int(count))):
        # 从低位份往高位份找空缺：奉仪 → 昭训 → 承徽 → 良媛 → 良娣
        target_rank = None
        for rank in reversed(HEIR_CONSORT_RANKS[1:]):
            if not heir_consort_rank_full(game_state, rank):
                target_rank = rank
                break
        if not target_rank:
            break
        member = heir_consort_add(game_state, target_rank)
        if not member:
            break
        added.append(member)
    if added:
        flavor = random.choice(HEIR_CONSORT_ENTRY_FLAVOR)
        names = "、".join(f"{m['name']}（{m['rank']}）" for m in added)
        msg = f"🎐 东宫新添内眷：{names}。{flavor}"
        heir_log_push(hs, "consort_events", {
            "period": heir_period_label(game_state),
            "title": "内官入册",
            "detail": msg,
        }, limit=10)
        game_state.add_memory(msg)
    return added


def process_heir_consorts(game_state):
    """内宅转旬结算：选妃触发 → 侧室填充 → 宠爱波动 → 内宅事件投放。"""
    msgs = []
    hs = heir_state(game_state)
    if not hs.get("heir_id"):
        return msgs
    child = get_heir_child(game_state)
    if not child or not child.get("alive", True):
        return msgs
    ensure_child_fields(child)
    try:
        age = float(child.get("age", 0) or 0)
    except (TypeError, ValueError):
        age = 0
    hc = heir_consorts_state(game_state)
    heir_name = hs.get("heir_name") or child.get("name") or "太子"

    # 1. 到龄选妃：只投一次，等玩家在面板上择定
    if age >= HEIR_CONSORT_SELECT_AGE and not isinstance(hc.get("太子妃"), dict):
        if not isinstance(hs.get("consort_selection"), dict):
            selection = generate_consort_selection_event()
            hs["consort_selection"] = selection
            msgs.append(f"💐 {heir_name}已及婚龄，礼部呈上三家名册待你择定：" +
                        "、".join(f"{c['name']}（{c['faction']}）" for c in selection["candidates"]))
        return msgs

    # 2. 已册太子妃：礼部按例续送侧室
    if isinstance(hc.get("太子妃"), dict):
        if heir_consort_total(game_state) < HEIR_CONSORT_MAX_TOTAL and random.random() < 0.30:
            added = heir_consort_fill(game_state)
            if added:
                names = "、".join(f"{m['name']}（{m['rank']}）" for m in added)
                msgs.append(f"🎐 礼部按例为东宫添置内眷：{names}")

    members = heir_consort_members(game_state)
    if not members:
        return msgs

    # 3. 宠爱自然波动：和睦度越低，波动越剧烈
    try:
        harmony = int(hs.get("consort_harmony", 60) or 60)
    except (TypeError, ValueError):
        harmony = 60
    swing = 3 if harmony >= 60 else 6
    for member in members:
        member["favor"] = max(0, min(100, int(member.get("favor", 50)) + random.randint(-swing, swing)))

    # 4. 内宅事件（宫斗 / 趣味），已有待决则跳过
    if not isinstance(hs.get("pending_consort_event"), dict) and random.random() < 0.35:
        ranks_present = {m.get("rank") for m in members}
        if len(members) >= 2 and random.random() < 0.6:
            event = generate_consort_conflict_event(available_ranks=ranks_present)
            msgs.append(f"🏮 东宫内宅起了风波「{event.get('name')}」：{event.get('scene', '')}")
        else:
            event = generate_consort_fun_event()
            msgs.append(f"🎋 东宫内宅趣事「{event.get('name')}」：{event.get('description', '')}")
        hs["pending_consort_event"] = event
    return msgs


# ============================================================
#  婚后子嗣系统：皇子 / 公主 / 东宫内宅 —— 婚后持续生子（孙辈）
# ============================================================
PROGENY_CONCEPTION_BASE = 0.10        # 每旬基础受孕概率（依生育力修正）
PROGENY_URGE_COST = 20                # 催皇嗣生：耗银两
PROGENY_URGE_BOOST = 0.18             # 催生当旬受孕概率加成
PROGENY_URGE_ACTION = 1               # 催生耗行动点（经 guard_action 扣除）
PROGENY_POSTPARTUM_COOLDOWN = 2       # 分娩后休养旬数（避免连续怀孕）
PROGENY_AGE_STEP = CHILD_AGE_STEP


def ensure_offspring_fields(holder):
    """补全「婚配对象」的子嗣字段（兼容旧存档 / 结构缺失）。"""
    if not isinstance(holder, dict):
        return holder
    holder.setdefault("offspring", [])           # 孙辈出生记录（出生即写入）
    holder.setdefault("is_pregnant", False)
    holder.setdefault("pregnancy_month", 0.0)    # 怀胎月数（0→10）
    holder.setdefault("fertility", random.randint(35, 85))
    holder.setdefault("conceive_boost", 0)       # 当旬催生加成（0/1）
    holder.setdefault("postpartum_cooldown", 0)  # 产后休养旬数
    holder.setdefault("urged_this_period", False)
    return holder


def _grandchild_name(game_state, holder, parent_gender, name_gender):
    """为婚配对象生育的孙辈取名。
    皇子/太子之孙随国姓；公主出降之孙随驸马姓；和亲之孙取民间姓。
    """
    if parent_gender == "公主":
        surname = extract_surname(holder.get("name", ""))
        if not surname or surname == "某":
            surname = random_surname(NPC_SURNAMES)
        used = collect_used_child_names(game_state)
        return generate_child_name(name_gender, used=used, surname=surname)
    return new_child_name(name_gender, game_state)


def _grandchild_birth_record(game_state, holder, parent_gender, royal_parent_name, consort_name):
    """生成一名孙辈记录。"""
    sex = random.choice(["男", "女"])
    name_gender = "皇子" if sex == "男" else "公主"
    name = _grandchild_name(game_state, holder, parent_gender, name_gender)
    royal = parent_gender == "皇子"
    relation = (("皇孙" if sex == "男" else "皇孙女") if royal
                else ("外孙" if sex == "男" else "外孙女"))
    return {
        "name": name,
        "sex": sex,
        "relation": relation,
        "age": 0.0,
        "birth_year": getattr(game_state, "year", 1),
        "birth_month": getattr(game_state, "month", 1),
        "birth_day": getattr(game_state, "day", 1),
        "father": royal_parent_name,          # 皇子/太子/公主名
        "spouse": consort_name,               # 驸马/正妃名
        "alive": True,
    }


def process_offspring_for_holder(game_state, holder, royal_parent_name, consort_name, parent_gender, father_is_royal):
    """结算一处婚配对象的转旬生育：怀胎 → 分娩 → 孙辈成长。返回事件消息列表。"""
    msgs = []
    ensure_offspring_fields(holder)
    # 孙辈成长
    for gc in holder.get("offspring", []):
        if isinstance(gc, dict) and gc.get("alive", True):
            gc["age"] = float(gc.get("age", 0) or 0) + PROGENY_AGE_STEP
    # 产后休养倒计时
    if int(holder.get("postpartum_cooldown", 0) or 0) > 0:
        holder["postpartum_cooldown"] = max(0, int(holder.get("postpartum_cooldown", 0) or 0) - 1)
    # 怀胎推进 / 分娩
    if holder.get("is_pregnant"):
        month = float(holder.get("pregnancy_month", 0) or 0) + PREGNANCY_STEP
        holder["pregnancy_month"] = month
        if month >= 10:
            gc = _grandchild_birth_record(game_state, holder, parent_gender, royal_parent_name, consort_name)
            holder.setdefault("offspring", []).insert(0, gc)
            holder["is_pregnant"] = False
            holder["pregnancy_month"] = 0.0
            holder["postpartum_cooldown"] = PROGENY_POSTPARTUM_COOLDOWN
            if father_is_royal:
                msg = (f"🎉 {royal_parent_name}喜得{gc['relation']}：{gc['name']}"
                       f"（生母{consort_name}），皇嗣绵延，宗庙有继")
            else:
                msg = (f"🎉 {royal_parent_name}与驸马{consort_name}喜得{gc['relation']}：{gc['name']}，"
                       f"公主府添丁进喜")
            msgs.append(msg)
    # 受孕（未怀孕且已过休养期）
    if not holder.get("is_pregnant") and not int(holder.get("postpartum_cooldown", 0) or 0):
        fertility = int(holder.get("fertility", 50) or 50)
        chance = PROGENY_CONCEPTION_BASE * (0.6 + fertility / 200.0)
        boost = int(holder.get("conceive_boost", 0) or 0)
        if boost:
            chance += PROGENY_URGE_BOOST
            holder["conceive_boost"] = 0
            holder["urged_this_period"] = False
        if random.random() < chance:
            holder["is_pregnant"] = True
            holder["pregnancy_month"] = 0.0
            who = f"{royal_parent_name}的{holder.get('rank', '')}" if holder.get("rank") else royal_parent_name
            msgs.append(f"🤰 {who}传出有孕之喜，{('东宫' if father_is_royal else '府中')}上下皆欢")
    return msgs


def process_offspring_system(game_state):
    """婚后子嗣系统总入口（转旬调用）：处理玩家与 NPC 的皇子/公主/东宫内宅生育。"""
    msgs = []
    # 1. 公主（出降 / 和亲）
    for _owner, _otype, _idx, c in iter_all_princesses(game_state):
        if c.get("marriage_status") not in ("已嫁", "和亲"):
            continue
        ensure_child_fields(c)
        consort = ensure_offspring_fields(c.get("consort"))
        if not isinstance(consort, dict):
            continue
        msgs.extend(process_offspring_for_holder(
            game_state, consort, c.get("name", "公主"),
            consort.get("name", "驸马"), "公主", False))
    # 2. 皇子（已婚）
    for _uid, c, _mother, _is_player in _iter_all_princes(game_state):
        if c.get("marriage_status") not in ("已婚", "已娶"):
            continue
        ensure_child_fields(c)
        consort = ensure_offspring_fields(c.get("consort"))
        if not isinstance(consort, dict):
            continue
        msgs.extend(process_offspring_for_holder(
            game_state, consort, c.get("name", "皇子"),
            consort.get("name", "正妃"), "皇子", True))
    # 3. 东宫内宅
    hs = heir_state(game_state)
    if hs.get("heir_id"):
        heir_child = get_heir_child(game_state)
        heir_name = hs.get("heir_name") or (heir_child.get("name") if heir_child else "太子")
        for member in heir_consort_members(game_state):
            msgs.extend(process_offspring_for_holder(
                game_state, member, heir_name, member.get("name", "内眷"),
                "皇子", True))
    return msgs


def serialize_offspring_holder(holder):
    """将婚配对象序列化给前端：孙辈 / 怀孕 / 生育力 / 可否催生。"""
    if not isinstance(holder, dict):
        return holder
    ensure_offspring_fields(holder)
    out = dict(holder)
    out["offspring"] = holder.get("offspring", [])
    out["is_pregnant"] = bool(holder.get("is_pregnant", False))
    out["pregnancy_month"] = float(holder.get("pregnancy_month", 0) or 0)
    out["fertility"] = int(holder.get("fertility", 50) or 50)
    out["conceive_boost"] = int(holder.get("conceive_boost", 0) or 0)
    out["postpartum_cooldown"] = int(holder.get("postpartum_cooldown", 0) or 0)
    return out


def process_heir_defiance(game_state):
    """不孝 / 逼宫四阶段事件链：按亲近度递降推进。返回消息列表。"""
    msgs = []
    hs = heir_state(game_state)
    if not hs.get("heir_id"):
        return msgs
    child = get_heir_child(game_state)
    if not child or not child.get("alive", True):
        return msgs
    ensure_child_fields(child)
    try:
        age = float(child.get("age", 0) or 0)
    except (TypeError, ValueError):
        age = 0
    if age < HEIR_REBELLION_MIN_AGE:
        return msgs
    # 已有待决事件时不叠加（不孝事件与叛逆/危机共用 pending_heir_event 槽位）
    if isinstance(hs.get("pending_heir_event"), dict):
        return msgs

    try:
        affection = int(hs.get("heir_affection", 50) or 50)
        stage = int(hs.get("defiance_stage", 0) or 0)
    except (TypeError, ValueError):
        affection, stage = 50, 0

    for entry in HEIR_DEFIANCE_CHAIN:
        if entry["stage"] != stage + 1:
            continue
        if affection > entry["threshold"]:
            break
        if random.random() >= 0.6:      # 达到阈值后每旬 60% 概率推进
            break
        event = {
            "kind": "defiance",
            "id": f"def_{entry['stage']}",
            "stage": entry["stage"],
            "name": entry["name"],
            "description": entry["description"],
            "flavor": entry.get("flavor", ""),
            "choices": {k: dict(v) for k, v in entry["choices"].items()},
        }
        hs["pending_heir_event"] = event
        hs["defiance_stage"] = entry["stage"]
        msg = f"💔 母子之间生了嫌隙「{entry['name']}」：{entry['description']}"
        msgs.append(msg)
        heir_log_push(hs, "defiance_log", {
            "period": heir_period_label(game_state),
            "stage": entry["stage"],
            "title": entry["name"],
            "detail": msg,
        })
        break
    return msgs


def heir_resolve_pending_heir_event(game_state, hs):
    """上旬玩家未处置的叛逆/危机/不孝事件：视作放任，按 A/B 随机落定并结算。"""
    msgs = []
    pending = hs.get("pending_heir_event")
    if not isinstance(pending, dict):
        return msgs
    choices = pending.get("choices") or {}
    if not choices:
        hs["pending_heir_event"] = None
        return msgs
    key = random.choice(list(choices.keys()))
    choice = choices[key]
    hs["pending_heir_event"] = None
    notes, _summary = heir_apply_choice(game_state, choice)
    heir_name = hs.get("heir_name") or "太子"
    detail = f"🕯️ 「{pending.get('name', '东宫之事')}」你未曾插手，{heir_name}身边的人自行做了处置：{choice.get('detail', '')}"
    if notes:
        detail += "（" + "，".join(notes) + "）"
    msgs.append(detail)
    game_state.add_memory(detail)
    heir_log_push(hs, "heir_event_log", {
        "period": heir_period_label(game_state),
        "event_id": pending.get("id"),
        "kind": pending.get("kind", ""),
        "title": pending.get("name", ""),
        "decided_by": "放任",
        "choice": choice.get("text", ""),
        "detail": detail,
    })
    return msgs


def heir_resolve_pending_consort_event(game_state, hs):
    """上旬玩家未处置的内宅事件：太子妃自行料理，随机落定。"""
    msgs = []
    pending = hs.get("pending_consort_event")
    if not isinstance(pending, dict):
        return msgs
    options = pending.get("options") or pending.get("choices") or {}
    if not options:
        hs["pending_consort_event"] = None
        return msgs
    key = random.choice(list(options.keys()))
    choice = options[key]
    hs["pending_consort_event"] = None
    notes, _summary = heir_apply_choice(game_state, choice)
    detail = f"🏮 「{pending.get('name', '内宅之事')}」你未曾过问，太子妃自行料理了：{choice.get('detail', '')}"
    if notes:
        detail += "（" + "，".join(notes) + "）"
    msgs.append(detail)
    heir_log_push(hs, "consort_events", {
        "period": heir_period_label(game_state),
        "event_id": pending.get("id"),
        "title": pending.get("name", ""),
        "decided_by": "太子妃自决",
        "choice": choice.get("text", ""),
        "detail": detail,
    }, limit=10)
    return msgs


def process_heir_system(game_state):
    """太子系统总入口（转旬调用）。

    顺序：结算上旬遗留 → 监国政务 → 成长/危机事件 → 不孝事件链 → 内宅。
    返回消息列表，由 next_period 写入 intelligence。
    """
    hs = heir_state(game_state)
    if not hs.get("heir_id"):
        return []
    msgs = []
    msgs.extend(heir_resolve_pending_heir_event(game_state, hs))
    msgs.extend(heir_resolve_pending_consort_event(game_state, hs))
    msgs.extend(process_heir_regency(game_state))
    msgs.extend(process_heir_growth_events(game_state))
    msgs.extend(process_heir_defiance(game_state))
    msgs.extend(process_heir_consorts(game_state))
    return msgs


def heir_consort_payload(game_state):
    """内宅前端载荷：按位份分组 + 编制统计。"""
    hc = heir_consorts_state(game_state)
    groups = []
    for rank in HEIR_CONSORT_RANKS:
        if rank == "太子妃":
            members = [hc["太子妃"]] if isinstance(hc.get("太子妃"), dict) else []
        else:
            members = list(hc.get(rank, []))
        groups.append({
            "rank": rank,
            "grade": HEIR_CONSORT_GRADE.get(rank, ""),
            "limit": HEIR_CONSORT_LIMITS.get(rank, 0),
            "count": len([m for m in members if m.get("alive", True)]),
            "members": [{
                "name": m.get("name", ""),
                "rank": rank,
                "family": m.get("family", ""),
                "personality": m.get("personality", ""),
                "fun_tag": m.get("fun_tag", ""),
                "favor": m.get("favor", 50),
                "faction": m.get("faction", ""),
                "talent": m.get("talent", 50),
                "looks": m.get("looks", 50),
                "alive": m.get("alive", True),
                "is_pregnant": m.get("is_pregnant", False),
                "children": m.get("children", []),
                "entered_at": m.get("entered_at", ""),
                "offspring": m.get("offspring", []),
                "pregnancy_month": float(m.get("pregnancy_month", 0) or 0),
                "fertility": int(m.get("fertility", 50) or 50),
                "conceive_boost": int(m.get("conceive_boost", 0) or 0),
                "postpartum_cooldown": int(m.get("postpartum_cooldown", 0) or 0),
            } for m in members],
        })
    return {
        "groups": groups,
        "total": heir_consort_total(game_state),
        "max_total": HEIR_CONSORT_MAX_TOTAL,
        "limits": HEIR_CONSORT_LIMITS,
        "grades": HEIR_CONSORT_GRADE,
    }


def heir_panel_payload(game_state):
    """储君面板总载荷：监国 + 成长 + 内宅，供 /api/heir/state 与转旬返回。"""
    hs = heir_state(game_state)
    child = get_heir_child(game_state)
    if child:
        ensure_child_fields(child)
    try:
        age = float(child.get("age", 0) or 0) if child else 0
    except (TypeError, ValueError):
        age = 0
    period_key_now = chonghua_period_key(game_state)
    return {
        "heir_status": hs,
        "has_heir": bool(hs.get("heir_id")),
        "heir_name": hs.get("heir_name", ""),
        "heir_age": int(age),
        "heir_foster_mother": get_heir_mother_name(game_state),
        "regency_active": bool(hs.get("regency_active")),
        "regency_merit": hs.get("regency_merit", 0),
        "ruling_style": hs.get("heir_ruling_style"),
        "heir_traits": hs.get("heir_traits", []),
        "heir_affection": hs.get("heir_affection", 50),
        "heir_counters": hs.get("heir_counters", {}),
        "defiance_stage": hs.get("defiance_stage", 0),
        "consort_harmony": hs.get("consort_harmony", 60),
        "pending_regency_event": hs.get("pending_regency_event"),
        "pending_heir_event": hs.get("pending_heir_event"),
        "pending_consort_event": hs.get("pending_consort_event"),
        "consort_selection": hs.get("consort_selection"),
        "regency_events": (hs.get("regency_events") or [])[:8],
        "heir_event_log": (hs.get("heir_event_log") or [])[:8],
        "defiance_log": (hs.get("defiance_log") or [])[:5],
        "consort_events": (hs.get("consort_events") or [])[:6],
        "consorts": heir_consort_payload(game_state),
        "can_advise": bool(hs.get("pending_regency_event")) and hs.get("last_regency_input") != period_key_now,
        "incognito_cost": HEIR_INCOGNITO_COST,
        "incognito_action_cost": HEIR_INCOGNITO_ACTION,
        "silver": game_state.silver,
        "remaining_actions": game_state.remaining_actions,
        "urge_cost": PROGENY_URGE_COST,
        "urge_action_cost": PROGENY_URGE_ACTION,
    }






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

def inner_palace_can_manage(game_state):
    """内务府为六宫公器，仅皇后或受命协理六宫者可掌管。

    太后垂帘期：亲掌/共治之下太后仍可掌内务府，放权后交还新后（不可再管）。
    """
    if is_dowager_active(game_state):
        d = get_dowager(game_state)
        return d.get("harem_mode", "共治") in ("亲掌", "共治")
    if game_state.rank.name == "皇后":
        return True
    return _get_six_palace_assistant(game_state) == game_state.name


@app.before_request
def _guard_inner_palace_routes():
    """内务府管理操作（POST）须皇后或协理六宫者；只读 GET（status/performance）不拦截。"""
    path = request.path or ''
    if request.method != 'POST' or not path.startswith('/api/inner_palace/'):
        return None
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    if not player_id:
        return None
    game_state, err = session_or_404(player_id)
    if err:
        return None
    if not inner_palace_can_manage(game_state):
        return jsonify({'error': '内务府为六宫公器，须皇后或受命协理六宫者方可掌管'}), 403
    return None



def enforce_six_palace_assistant(game_state):
    """皇后去世/病重/怀孕时必须设一位协理六宫（嫔位及以上、非皇后；NPC 或主控均可）。

    转旬检查：现任协理失效（薨逝/离宫）或皇后失能且无协理时，自动择优任命
    （位份最高者优先，次看威望）。中宫虚悬时不强制。返回情报消息列表。
    """
    queen_name = get_queen_name(game_state, include_player=True)
    if not queen_name:
        return []
    reason = ""
    if queen_name == game_state.name:
        if getattr(game_state, "is_pregnant", False):
            reason = "身怀六甲"
        elif int(game_state.attributes.get("健康", 100) or 0) < 30:
            reason = "凤体违和"
    else:
        qnpc = (game_state.npcs or {}).get(queen_name) or {}
        if not qnpc.get("alive", True):
            reason = "薨逝"
        elif qnpc.get("is_pregnant"):
            reason = "身怀六甲"
        elif int((qnpc.get("attributes") or {}).get("健康", 100) or 0) < 30:
            reason = "凤体违和"
    if not reason:
        return []
    if _get_six_palace_assistant(game_state):
        return []  # 已有协理襄助

    my_idx = RANK_LEVELS.get(game_state.rank.name, 0)
    candidates = []
    if queen_name != game_state.name and my_idx >= RANK_LEVELS.get("嫔", 0):
        candidates.append((game_state.name, my_idx, int(game_state.attributes.get("威望", 0) or 0), True))
    for name, npc in (game_state.npcs or {}).items():
        if not isinstance(npc, dict) or not npc.get("alive", True):
            continue
        if name in ("太后", queen_name, game_state.name):
            continue
        idx = RANK_LEVELS.get(normalize_rank_name(npc.get("rank", "答应")), 0)
        if idx < RANK_LEVELS.get("嫔", 0):
            continue
        if npc.get("is_pregnant") or int((npc.get("attributes") or {}).get("健康", 100) or 0) < 30:
            continue
        candidates.append((name, idx, int((npc.get("attributes") or {}).get("威望", 0) or 0), False))
    if not candidates:
        return []
    candidates.sort(key=lambda c: (-c[1], -c[2]))
    chosen, _idx, _pw, is_player = candidates[0]
    game_state.six_palace_assistant = chosen
    if not is_player:
        npc = game_state.npcs[chosen]
        npc["assists_six_palaces"] = True
    msg = f"🏛️ 皇后{reason}，宫务不可一日无人主持——着{chosen}协理六宫"
    game_state.add_memory(msg)
    return [msg]

def npc_manage_inner_palace(game_state):
    """玩家非内务府掌管者时，由现任皇后/协理六宫者自动经营：
    每旬自动向皇帝请拨内帑（约五成准奏），并用库银自动升级产业（每旬至多一项）。

    玩家本人是皇后或协理者时不干预（由玩家手动掌管）。返回情报消息列表。
    """
    qa = queen_authority(game_state)
    holder = qa.get("assistant") or qa.get("holder") or ""
    if not holder or holder == game_state.name:
        return []
    npc = (game_state.npcs or {}).get(holder)
    if not isinstance(npc, dict) or not npc.get("alive", True):
        return []
    ip = normalize_inner_palace(getattr(game_state, "inner_palace", None))
    msgs = []
    acted = False
    # ① 自动请拨内帑
    if random.random() < 0.5:
        grant = random.randint(5000, 8000)
        ip["budget"] = int(ip.get("budget", 0) or 0) + grant
        msgs.append(f"🏛️ 内务府：{holder}奏请内帑，拨银{grant}两入库")
        acted = True
    # ② 自动经营产业：从等级最低的可升项目做起，每旬至多一项
    projects = ip.get("projects") or {}
    for pname, proj in sorted(projects.items(), key=lambda kv: int((kv[1] or {}).get("level", 0) or 0)):
        level = int((proj or {}).get("level", 0) or 0)
        cost = 100 + 80 * level
        if level < 5 and int(ip.get("budget", 0) or 0) >= cost:
            ip["budget"] = int(ip.get("budget", 0) or 0) - cost
            proj["level"] = level + 1
            proj["invested"] = int(proj.get("invested", 0) or 0) + cost
            proj["income_per_period"] = proj["level"] * 5
            msgs.append(f"🏛️ 内务府：{holder}经营产业，{pname}升至{proj['level']}级（收益{proj['income_per_period']}两/旬）")
            acted = True
            break
    if acted:
        from inner_palace_system import _ip_log
        _ip_log(ip, f"{holder}掌内务府：请帑与产业经营")
        game_state.inner_palace = ip
    return msgs

def guard_action(game_state):
    """行动前统一守卫：先查终局与冷宫囚禁，再扣行动点。

    返回 (ok, error_response)。所有消耗行动点的路由都经过这里，
    避免结局判定散落在各个 route 里出现遗漏。
    """
    ensure_ending_fields(game_state)
    if is_game_over(game_state):
        return False, game_over_response(game_state)
    if is_player_imprisoned(game_state):
        return False, (jsonify({"error": "你身陷冷宫，宫里的门为你关上了（可从冷宫面板寻求出路）"}), 423)
    can_act, remaining = check_and_consume_action(game_state)
    if not can_act:
        return False, (jsonify({"error": f"行动点不足，剩余 {remaining} 点"}), 429)
    return True, None


# ============================================================
#  内务府玩家干预 API
# ============================================================
@app.route('/api/inner_palace/status', methods=['GET'])
def inner_palace_status():
    """只读查询内务府状态（含 Phase 1-5 全部字段）。"""
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    return jsonify({**ip, 'can_manage': inner_palace_can_manage(game_state)})


@app.route('/api/inner_palace/purchase', methods=['POST'])
def inner_palace_purchase():
    """采买物资：消耗 budget 增加库存，消耗 1 行动点。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    item = (data.get('item') or '').strip()
    qty = max(1, int(data.get('qty', 1) or 1))
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, e = guard_action(game_state)
    if not ok:
        return e
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    game_state.inner_palace = ip
    market = ip.get('market', {})
    price = int(market.get(item, 0) or 0)
    if price <= 0:
        return jsonify({'error': f'未知名目「{item}」'}), 400
    cost = price * qty
    if int(ip.get('budget', 0) or 0) < cost:
        return jsonify({'error': f'库银不足（需{cost}两，余{ip.get("budget",0)}两）'}), 400
    ip['budget'] -= cost
    storehouse = ip.setdefault('storehouse', {})
    storehouse[item] = int(storehouse.get(item, 0) or 0) + qty
    from inner_palace_system import _ip_log
    _ip_log(ip, f'采买{item}{qty}单位，花费{cost}两')
    return jsonify({'message': f'采买{item}{qty}单位成功，花费{cost}两', 'budget': ip['budget'], 'storehouse': storehouse})


@app.route('/api/inner_palace/embezzle', methods=['POST'])
def inner_palace_embezzle():
    """玩家勾结总管贪墨：成功则 budget-、player.silver+；失败则威望-。消耗 1 行动点。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, e = guard_action(game_state)
    if not ok:
        return e
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    game_state.inner_palace = ip
    chief = ip.get('chief', {})
    corruption = int(chief.get('corruption', 0) or 0)
    loyalty = int(chief.get('loyalty', 0) or 0)
    # 成功率：贪腐越高越容易，忠诚越高越难
    success_rate = min(0.9, max(0.1, (corruption / 100.0) * 0.6 + (1 - loyalty / 100.0) * 0.3))
    import random as _rnd
    from inner_palace_system import _ip_log
    if _rnd.random() < success_rate:
        amount = _rnd.randint(20, 60)
        ip['budget'] = max(0, int(ip.get('budget', 0) or 0) - amount)
        game_state.silver = int(getattr(game_state, 'silver', 0) or 0) + amount
        ev = _rnd.randint(2, 5)
        ip['corruption_evidence'] = int(ip.get('corruption_evidence', 0) or 0) + ev
        _ip_log(ip, f'玩家贪墨{amount}两，罪证+{ev}')
        return jsonify({'message': f'贪墨成功！获得{amount}两，但留下了蛛丝马迹…', 'silver': game_state.silver, 'budget': ip['budget']})
    else:
        loss = _rnd.randint(3, 8)
        game_state.attributes['威望'] = max(0, int(game_state.attributes.get('威望', 0) or 0) - loss)
        _ip_log(ip, f'玩家贪墨败露，威望-{loss}')
        return jsonify({'message': f'贪墨败露！你威望-{loss}', 'prestige': game_state.attributes['威望']})


@app.route('/api/inner_palace/audit', methods=['POST'])
def inner_palace_audit():
    """查账：若 corruption_evidence > 0 则查出罪证、威望+；否则可能被反噬。消耗 1 行动点。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, e = guard_action(game_state)
    if not ok:
        return e
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    game_state.inner_palace = ip
    evidence = int(ip.get('corruption_evidence', 0) or 0)
    from inner_palace_system import _ip_log
    import random as _rnd
    if evidence > 0:
        found = min(evidence, _rnd.randint(5, 15))
        ip['corruption_evidence'] = max(0, evidence - found)
        gain = _rnd.randint(3, 8)
        game_state.attributes['威望'] = min(game_state.get_attr_max('威望'), int(game_state.attributes.get('威望', 0) or 0) + gain)
        ip['audited_this_period'] = True
        _ip_log(ip, f'查账有功，清除罪证{found}，威望+{gain}')
        return jsonify({'message': f'查账成功！清除罪证{found}点，威望+{gain}', 'prestige': game_state.attributes['威望'], 'evidence': ip['corruption_evidence']})
    else:
        # 无证据时可能反噬
        if _rnd.random() < 0.3:
            loss = _rnd.randint(2, 5)
            game_state.attributes['威望'] = max(0, int(game_state.attributes.get('威望', 0) or 0) - loss)
            _ip_log(ip, f'查账无果反被诬，威望-{loss}')
            return jsonify({'message': f'查账未发现异常，反被总管倒打一耙，威望-{loss}', 'prestige': game_state.attributes['威望']})
        ip['audited_this_period'] = True
        _ip_log(ip, '查账无异常')
        return jsonify({'message': '查账完毕，未发现异常。'})


# ============================================================
#  内务府扩展：Phase 1 权谋（克扣/赏赐/宫宴）
# ============================================================
# Phase 2 总管派系
IP_CHIEF_FACTION_CHOICES = ["皇后派", "太后派", "皇帝派", "中立"]
# Phase 1 宫宴规格
IP_BANQUET_TIERS = {
    "奢华": {"cost": 100, "pre": 8, "fav": 5},
    "中等": {"cost": 50, "pre": 4, "fav": 3},
    "简朴": {"cost": 20, "pre": 2, "fav": 1},
}


def _ip_banquet_effectiveness(ip):
    """总管技能越高，办宴效果加成越多（100%~150%）。"""
    skill = int((ip.get('chief') or {}).get('skill', 50) or 50)
    return 100 + min(50, skill // 2)


@app.route('/api/inner_palace/cut_stipend', methods=['POST'])
def inner_palace_cut_stipend():
    """克扣份例：某目标月例按比例缩减数旬。成功则库银逐旬回补，
    但目标好感/健康受损，且存在被总管揭发的风险。消耗 1 行动点。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    target = (data.get('target') or '').strip()
    try:
        pct = int(data.get('pct', 30) or 30)
    except (TypeError, ValueError):
        pct = 30
    pct = max(10, min(50, pct))
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, e = guard_action(game_state)
    if not ok:
        return e
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    game_state.inner_palace = ip
    npc = (game_state.npcs or {}).get(target)
    if not isinstance(npc, dict) or not npc.get('alive', True):
        return jsonify({'error': f'目标「{target}」不存在或已故'}), 400
    if target == '太后':
        return jsonify({'error': '太后的份例不可克扣'}), 400
    rank = normalize_rank_name(npc.get('rank', ''))
    base_amt = int(ip.get('monthly_stipend', {}).get(rank, 0) or 0)
    if base_amt <= 0:
        return jsonify({'error': f'{target}当前位份无月例可克'}), 400
    cuts = ip.setdefault('stipend_cuts', {})
    if target in cuts and isinstance(cuts[target], dict) and cuts[target].get('periods', 0) > 0:
        return jsonify({'error': f'对{target}的克扣仍在生效中'}), 400
    cuts[target] = {'amount': pct, 'periods': min(30, max(3, int(data.get('periods', 10) or 10))),
                    'start_period': int(game_state.day or 0)}
    from inner_palace_system import _ip_log
    _ip_log(ip, f'暗中克扣{target}份例{pct}%，持续{cuts[target]["periods"]}旬')
    return jsonify({'message': f'已授意内务府暗中克扣{target}的份例{pct}%（{cuts[target]["periods"]}旬）。小心别被察觉。',
                    'target': target, 'pct': pct, 'periods': cuts[target]['periods']})


@app.route('/api/inner_palace/give_bonus', methods=['POST'])
def inner_palace_give_bonus():
    """额外赏赐：立即花费库银，数旬内每月例之外加发赏银。
    目标好感+、健康+。消耗 1 行动点。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    target = (data.get('target') or '').strip()
    try:
        amount = int(data.get('amount', 20) or 20)
    except (TypeError, ValueError):
        amount = 20
    amount = max(1, min(100, amount))
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, e = guard_action(game_state)
    if not ok:
        return e
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    game_state.inner_palace = ip
    npc = (game_state.npcs or {}).get(target)
    if not isinstance(npc, dict) or not npc.get('alive', True):
        return jsonify({'error': f'目标「{target}」不存在或已故'}), 400
    if target == '太后':
        return jsonify({'error': '请通过请安或奏请太后，不必走内务府'}), 400
    periods = min(30, max(3, int(data.get('periods', 5) or 5)))
    cost = amount * periods
    budget = int(ip.get('budget', 0) or 0)
    if budget < cost:
        return jsonify({'error': f'库银不足（需{cost}两，余{budget}两）'}), 400
    ip['budget'] = budget - cost
    gifts = ip.setdefault('bonus_gifts', {})
    cur = gifts.get(target)
    if isinstance(cur, dict) and int(cur.get('periods', 0) or 0) > 0:
        cur['amount'] = min(100, int(cur.get('amount', 0) or 0) + amount)
        cur['periods'] = min(30, int(cur.get('periods', 0) or 0) + periods)
    else:
        gifts[target] = {'amount': amount, 'periods': periods, 'start_period': int(game_state.day or 0)}
    rel = game_state.relationships.get(target)
    if isinstance(rel, dict):
        rel['好感'] = min(100, int(rel.get('好感', 0) or 0) + 5)
    npc['health'] = min(100, int(npc.get('health', 50) or 50) + 3)
    from inner_palace_system import _ip_log
    _ip_log(ip, f'额外赏赐{target}：{gifts[target]["amount"]}两/旬×{gifts[target]["periods"]}旬，本次拨{cost}两')
    return jsonify({'message': f'已拨银{cost}两，{gifts[target]["periods"]}旬内{target}每月例之外多领{gifts[target]["amount"]}两。好感+5。',
                    'budget': ip['budget']})


@app.route('/api/inner_palace/banquet', methods=['POST'])
def inner_palace_banquet():
    """承办宫宴：立即花费库银，获得威望与皇帝好感（总管技能加成）。
    消耗 1 行动点。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    tier = (data.get('tier') or '中等').strip()
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, e = guard_action(game_state)
    if not ok:
        return e
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    game_state.inner_palace = ip
    spec = IP_BANQUET_TIERS.get(tier)
    if not spec:
        return jsonify({'error': f'未知宫宴规格「{tier}」，可选：{"、".join(IP_BANQUET_TIERS)}'}), 400
    budget = int(ip.get('budget', 0) or 0)
    if budget < spec['cost']:
        return jsonify({'error': f'库银不足（需{spec["cost"]}两，余{budget}两）'}), 400
    ip['budget'] = budget - spec['cost']
    eff = _ip_banquet_effectiveness(ip)
    pre = max(1, spec['pre'] * eff // 100)
    fav = max(1, spec['fav'] * eff // 100)
    try:
        pmax = game_state.get_attr_max('威望')
    except Exception:
        pmax = 999
    game_state.attributes['威望'] = max(0, min(pmax, int(game_state.attributes.get('威望', 0) or 0) + pre))
    em = game_state.relationships.get('皇帝')
    if isinstance(em, dict):
        em['好感'] = min(100, int(em.get('好感', 0) or 0) + fav)
    record = {'period': int(game_state.day or 0), 'tier': tier, 'cost': spec['cost'],
              'pre': pre, 'fav': fav}
    ip['banquet'] = record
    hist = ip.get('banquet_history')
    if not isinstance(hist, list):
        hist = []
    hist.append(record)
    ip['banquet_history'] = hist[-20:]
    from inner_palace_system import _ip_log
    _ip_log(ip, f'承办{tier}宫宴，花费{spec["cost"]}两，威望+{pre}')
    return jsonify({'message': f'{tier}宫宴举办成功！花费{spec["cost"]}两，威望+{pre}，皇帝好感+{fav}。',
                    'pre': pre, 'fav': fav, 'budget': ip['budget'], 'record': record})


# ============================================================
#  内务府扩展：Phase 2 总管任免 / Phase 3 私库
# ============================================================
def _ip_new_chief_data():
    """随机生成一位新总管（含派系）。"""
    from names import generate_servant_name
    import random as _rnd
    return {
        'name': generate_servant_name('太监'),
        'loyalty': _rnd.randint(35, 75),
        'corruption': _rnd.randint(15, 60),
        'skill': _rnd.randint(45, 85),
        'faction': _rnd.choice(IP_CHIEF_FACTION_CHOICES),
        'tenure': 0,
        'performance': 0,
        'appointed_by': '现任',
        'dismissed': 0,
    }


@app.route('/api/inner_palace/chief/appoint', methods=['POST'])
def inner_palace_chief_appoint():
    """任命新总管：花费 100 两与 1 行动点，随机生成新总管（含派系）。
    原总管若贪腐高，会留下罪证尾巴。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, e = guard_action(game_state)
    if not ok:
        return e
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    game_state.inner_palace = ip
    budget = int(ip.get('budget', 0) or 0)
    if budget < 100:
        return jsonify({'error': f'任命总管需仪银100两（余{budget}两）'}), 400
    ip['budget'] = budget - 100
    old = ip.get('chief') or {}
    old['dismissed'] = int(old.get('dismissed', 0) or 0) + 1
    ev = max(0, min(15, int(old.get('corruption', 0) or 0) // 10))
    if ev > 0:
        ip['corruption_evidence'] = int(ip.get('corruption_evidence', 0) or 0) + ev
    new_chief = _ip_new_chief_data()
    ip['chief'] = new_chief
    game_state.chief_faction = new_chief['faction']
    from inner_palace_system import _ip_log
    _ip_log(ip, f'任命{new_chief["name"]}为新总管（{new_chief["faction"]}），花费100两')
    return jsonify({'message': f'新总管{new_chief["name"]}（{new_chief["faction"]}）走马上任。忠{new_chief["loyalty"]}/贪{new_chief["corruption"]}/能{new_chief["skill"]}'
                    + (f'；前任留下罪证{ev}点。' if ev else ''),
                    'chief': new_chief, 'budget': ip['budget']})


@app.route('/api/inner_palace/chief/dismiss', methods=['POST'])
def inner_palace_chief_dismiss():
    """弹劾解职总管：需威望≥80 或罪证≥20，花费 50 两与 1 行动点。
    罪证清零，但总管绩效-15。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, e = guard_action(game_state)
    if not ok:
        return e
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    game_state.inner_palace = ip
    prestige = int(game_state.attributes.get('威望', 0) or 0)
    evidence = int(ip.get('corruption_evidence', 0) or 0)
    if prestige < 80 and evidence < 20:
        return jsonify({'error': f'弹劾总管需威望≥80（当前{prestige}）或罪证≥20（当前{evidence}）'}), 400
    budget = int(ip.get('budget', 0) or 0)
    if budget < 50:
        return jsonify({'error': f'弹劾需运作银两50两（余{budget}两）'}), 400
    ip['budget'] = budget - 50
    chief = ip.get('chief') or {}
    old_name = chief.get('name', '总管')
    ip['corruption_evidence'] = 0
    chief['dismissed'] = int(chief.get('dismissed', 0) or 0) + 1
    chief['performance'] = max(-100, int(chief.get('performance', 0) or 0) - 15)
    from inner_palace_system import _ip_log
    _ip_log(ip, f'弹劾解职总管{old_name}，花费50两，罪证清零')
    return jsonify({'message': f'{old_name}被弹劾解职，内务府重新洗牌。罪证已清零。',
                    'budget': ip['budget']})


@app.route('/api/inner_palace/private_purse/enable', methods=['POST'])
def inner_palace_purse_enable():
    """开通私库：威望≥80 时允许公银转私银。不消耗行动点。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ensure_ending_fields(game_state)
    if is_game_over(game_state):
        return game_over_response(game_state)
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    game_state.inner_palace = ip
    purse = ip.get('private_purse')
    if not isinstance(purse, dict):
        purse = ip['private_purse'] = {'enabled': False, 'total_transferred': 0,
                                       'last_transfer_period': 0, 'transfer_logs': []}
    if purse.get('enabled'):
        return jsonify({'error': '私库已开通'}), 400
    prestige = int(game_state.attributes.get('威望', 0) or 0)
    if prestige < 80:
        return jsonify({'error': f'威望不足（需≥80，当前{prestige}），开私库需足够分量'}), 400
    purse['enabled'] = True
    from inner_palace_system import _ip_log
    _ip_log(ip, '开通私库：可授意内务府公银转私银')
    return jsonify({'message': '私库已开通。此后可将内务府库银转入你的私库。'})


@app.route('/api/inner_palace/private_purse/transfer', methods=['POST'])
def inner_palace_purse_transfer():
    """私库划转：每旬限一次，每次上限50两。成功率取决于总管忠诚与贪腐。
    失败则被察觉（威望-，留罪证）。消耗 1 行动点。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    try:
        amount = int(data.get('amount', 20) or 20)
    except (TypeError, ValueError):
        amount = 20
    amount = max(1, min(50, amount))
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, e = guard_action(game_state)
    if not ok:
        return e
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    game_state.inner_palace = ip
    purse = ip.get('private_purse')
    if not isinstance(purse, dict) or not purse.get('enabled'):
        return jsonify({'error': '私库尚未开通（需威望≥80）'}), 400
    period = int(game_state.day or 0)
    if int(purse.get('last_transfer_period', 0) or 0) >= period:
        return jsonify({'error': '本旬已划转过，请下旬再试'}), 400
    budget = int(ip.get('budget', 0) or 0)
    if budget < amount:
        return jsonify({'error': f'库银不足（余{budget}两）'}), 400
    chief = ip.get('chief') or {}
    success_rate = max(0.3, min(0.95,
        0.5 + (int(chief.get('loyalty', 50) or 50) - 50) / 200.0
        - int(ip.get('corruption_evidence', 0) or 0) / 200.0
        - int(chief.get('corruption', 0) or 0) / 400.0))
    import random as _rnd
    from inner_palace_system import _ip_log
    if _rnd.random() < success_rate:
        ip['budget'] = budget - amount
        game_state.silver = int(getattr(game_state, 'silver', 0) or 0) + amount
        purse['last_transfer_period'] = period
        purse['total_transferred'] = int(purse.get('total_transferred', 0) or 0) + amount
        _ip_log(ip, f'私库划转{amount}两，成功')
        return jsonify({'message': f'银两悄然转入私库{amount}两，账面分文不动。',
                        'silver': game_state.silver, 'budget': ip['budget']})
    loss = _rnd.randint(3, 6)
    ev = _rnd.randint(3, 8)
    game_state.attributes['威望'] = max(0, int(game_state.attributes.get('威望', 0) or 0) - loss)
    ip['corruption_evidence'] = int(ip.get('corruption_evidence', 0) or 0) + ev
    logs = purse.get('transfer_logs')
    if not isinstance(logs, list):
        logs = []
    logs.append(f'[{period}] 划转{amount}两被察觉，威望-{loss}，罪证+{ev}')
    purse['transfer_logs'] = logs[-30:]
    _ip_log(ip, f'私库划转{amount}两被察觉，威望-{loss}，罪证+{ev}')
    return jsonify({'message': f'划转之事被察觉！{chief.get("name", "总管")}神色有异。威望-{loss}，罪证+{ev}',
                    'prestige': game_state.attributes['威望']})


# ============================================================
#  内务府扩展：Phase 4 考绩 / Phase 5 产业
# ============================================================
@app.route('/api/inner_palace/performance', methods=['GET'])
def inner_palace_performance():
    """只读查询季度考绩状态。"""
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    reviews = ip.get('performance_reviews') or {}
    day = int(getattr(game_state, 'day', 0) or 0)
    return jsonify({
        'last_review': reviews.get('last_review', 0),
        'score': reviews.get('score', 0),
        'grade': reviews.get('grade', ''),
        'next_review': reviews.get('next_review', 30),
        'periods_left': max(0, int(reviews.get('next_review', 30) or 30) - day),
        'history': (reviews.get('history') or [])[-6:],
        'projects': ip.get('projects', {}),
    })


@app.route('/api/inner_palace/project/upgrade', methods=['POST'])
def inner_palace_project_upgrade():
    """产业投资/升级：皇庄/织造局/茶庄，每级收益+5两，上限5级。
    花费 = 100 + 80×(当前等级)。消耗 1 行动点。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    name = (data.get('name') or '').strip()
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, e = guard_action(game_state)
    if not ok:
        return e
    ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    game_state.inner_palace = ip
    projects = ip.get('projects') or {}
    proj = projects.get(name)
    if not isinstance(proj, dict):
        return jsonify({'error': f'未知名目「{name}」，可选：皇庄、织造局、茶庄'}), 400
    level = int(proj.get('level', 0) or 0)
    if level >= 5:
        return jsonify({'error': f'{name}已达最高等级（5级）'}), 400
    cost = 100 + 80 * level
    budget = int(ip.get('budget', 0) or 0)
    if budget < cost:
        return jsonify({'error': f'库银不足（升级{name}需{cost}两，余{budget}两）'}), 400
    ip['budget'] = budget - cost
    proj['level'] = level + 1
    proj['invested'] = int(proj.get('invested', 0) or 0) + cost
    proj['income_per_period'] = proj['level'] * 5
    from inner_palace_system import _ip_log
    _ip_log(ip, f'投资{name}升至{proj["level"]}级，花费{cost}两，收益{proj["income_per_period"]}两/旬')
    return jsonify({'message': f'{name}升级至{proj["level"]}级！每旬收益{proj["income_per_period"]}两。',
                    'project': proj, 'budget': ip['budget']})
# ============================================================
#  AI服务
# ============================================================
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
                    {"role": "system", "content": "你是才华横溢的宫斗小说作家，只输出故事正文本身，绝对不要输出任何思考过程、分析、解释或 <think> 之类的标记。尽量使用名单中的人物。"},
                    {"role": "user", "content": prompt}
                ]
                response, used_model, err = call_ai_chat(client, model, messages)
                if response:
                    narration = _strip_reasoning(response.choices[0].message.content)
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
    if game_state.rank.name == "皇后":
        return False
    favor_req = get_active_favor_threshold(game_state)
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
    favor_req = get_active_favor_threshold(game_state)
    favor = game_state.attributes.get("宠爱", 0)
    if favor < int(favor_req * 0.85):
        return False
    if not check_promotion_thresholds_met(game_state, 0.88):
        return False
    if get_promotion_block_reason(game_state):
        return False
    if get_rank_periods(game_state) < max(2, get_active_min_tenure(game_state) // 2):
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
    if step["type"] == "四妃封号" and not can_use_four_consort_title(game_state, step.get("target", "")):
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
        favor_req = get_active_favor_threshold(game_state)
        favor = game_state.attributes.get("宠爱", 0)
        if favor < favor_req:
            return f"⚠️ 圣宠不足（需宠爱≥{favor_req}，当前{favor}），还需邀宠"
        return None
    if not check_tenure_met(game_state) and not is_special_favor(game_state):
        need = get_active_min_tenure(game_state) - get_rank_periods(game_state)
        return f"⚠️ 位份资历不足，还需在「{game_state.get_display_rank()}」位上历练 {max(1, need)} 旬"
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
    return jsonify({"servants": [s.to_dict() for s in game_state.get_active_servants()], "max": game_state.max_servants, "count": len(game_state.get_active_servants()), **confidant_payload(game_state)})

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
    if game_state.confidant == name:
        game_state.confidant = None
        remember_confidant_event(game_state, f"{name}已被遣散，心腹之职就此作废")
        game_state.add_memory(f"心腹{name}已被遣散")
        msg += f"，心腹{name}一同被遣散"
    return jsonify({"success": True, "message": msg, "confidant": confidant_payload(game_state)})

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

@app.route('/api/servant/promote_confidant', methods=['POST'])
def promote_confidant():
    data = request.get_json()
    player_id = data.get('player_id')
    name = data.get('name')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    target = None
    for s in game_state.get_active_servants():
        if s.name == name:
            target = s
            break
    if not target:
        return jsonify({"error": "未找到该宫人"}), 404
    if game_state.confidant:
        return jsonify({"error": f"你已有心腹「{game_state.confidant}」，请先解除"}), 400
    if not getattr(target, "has_confidant_potential", True):
        return jsonify({"error": f"{name}心思浅薄，不堪托付心事"}), 400
    if target.loyalty < CONFIDANT_LOYALTY_REQUIRED:
        return jsonify({"error": f"{name}忠诚仅{target.loyalty}，需≥{CONFIDANT_LOYALTY_REQUIRED}方可托付（可用训练提升忠诚）"}), 400
    if game_state.silver < CONFIDANT_PROMOTE_COST:
        return jsonify({"error": f"银两不足，需要{CONFIDANT_PROMOTE_COST}两"}), 400
    game_state.silver -= CONFIDANT_PROMOTE_COST
    game_state.confidant = name
    loyalty_gain = random.randint(3, 8)
    if "忠心耿耿" in getattr(game_state, "traits", []):
        loyalty_gain += 5  # 忠心耿耿：立心腹时忠诚额外+5
    target.loyalty = min(100, target.loyalty + loyalty_gain)
    game_state.add_memory(f"立{name}为心腹（忠诚{target.loyalty}）")
    remember_confidant_event(game_state, f"{name}被立为心腹，忠诚升至{target.loyalty}")
    return jsonify({"success": True, "message": f"🔒 你以重赏托付{target.type}{name}为心腹，忠诚+{loyalty_gain}。他/她会在宫斗中助你，并替你打探宫中秘事。", "servant": target.to_dict(), "confidant": confidant_payload(game_state), "silver": game_state.silver, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})

@app.route('/api/servant/release_confidant', methods=['POST'])
def release_confidant():
    data = request.get_json()
    player_id = data.get('player_id')
    name = data.get('name')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if not game_state.confidant:
        return jsonify({"error": "你当前没有心腹"}), 400
    if game_state.confidant != name:
        return jsonify({"error": f"{name}并非你的心腹"}), 400
    game_state.confidant = None
    remember_confidant_event(game_state, f"{name}被解除心腹之职")
    game_state.add_memory(f"解除{name}心腹之职")
    return jsonify({"success": True, "message": f"你收回了对{name}的信任，{name}不再是你的心腹。", "confidant": confidant_payload(game_state)})

@app.route('/api/confidant/events', methods=['GET'])
def get_confidant_events():
    """获取当前可触发的心腹事件"""
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    
    event = get_random_confidant_event(game_state)
    if not event:
        return jsonify({"event": None})
    
    # 填充事件描述中的变量
    desc = event["desc"]
    if game_state.confidant:
        desc = desc.replace("{name}", game_state.confidant)
    target = pick_confidant_target(game_state)
    desc = desc.replace("{target}", target)
    
    return jsonify({
        "event": {
            "id": event["id"],
            "name": event["name"],
            "desc": desc,
            "choices": [{"text": c["text"], "cost": c.get("cost", {})} for c in event["choices"]],
            "target": target
        }
    })

@app.route('/api/confidant/trigger', methods=['POST'])
def trigger_confidant_event_api():
    """触发心腹事件"""
    data = request.get_json()
    player_id = data.get('player_id')
    event_id = data.get('event_id')
    choice_index = data.get('choice_index', 0)
    
    game_state, err = session_or_404(player_id)
    if err:
        return err
    
    result = trigger_confidant_event(game_state, event_id, choice_index, target=data.get('target') or None)
    
    if "error" in result:
        return jsonify(result), 400
    
    return jsonify({
        "success": True,
        "narration": result.get("narration", ""),
        "effect": result.get("effect", {}),
        "silver": game_state.silver,
        "remaining_actions": game_state.remaining_actions,
        "confidant": confidant_payload(game_state)
    })


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


def dowager_meet_emperor(game_state, action):
    """太后垂帘期与新帝相见：宠爱无意义，改记母子亲近/帝威/摄政权威。"""
    d = get_dowager(game_state)
    emp = d["emperor"]
    ok, err = guard_action(game_state)
    if not ok:
        return err
    table = {
        "serve_tea": ("赐茶叙话", {"帝心": (3, 6)}, 0),
        "discuss": ("垂问朝政", {"帝威": (1, 3), "权威": (1, 3)}, 0),
        "recite_poem": ("课以诗书", {"帝威": (2, 4), "帝心": (1, 3)}, 0),
        "ask_reward": ("索取尊养", {"权威": (2, 4), "帝心": (-4, -1)}, 0),
        "request_funding": ("索内帑充慈宁", {"权威": (1, 3)}, 0),
    }
    if action not in table:
        return jsonify({"error": "无效行为"}), 400
    desc, effects, cost = table[action]
    from dowager_system import _apply_effects
    rolled = {k: random.randint(a, b) for k, (a, b) in effects.items()}
    applied = _apply_effects(game_state, d, rolled)
    if action == "request_funding":
        grant = random.randint(200, 500)
        d["treasury"] = max(0, d["treasury"] - grant // 4)
        game_state.silver += grant
        applied["私帑"] = grant
    narr_map = {
        "serve_tea": f"你赐{emp['name']}一盏茶，母子对坐半晌，说的都是些家常。",
        "discuss": f"你垂问{emp['name']}近日的奏本，他答得有条有理——总算有几分帝王气象了。",
        "recite_poem": f"你亲自考{emp['name']}的功课，他背得磕磕绊绊，你却听得认真。",
        "ask_reward": f"你向{emp['name']}索要尊养之物，他一一应下，只是眼里那点犹豫，你看得分明。",
        "request_funding": f"你开口向内帑取钱，{emp['name']}批了——太后要用，谁敢说不。",
    }
    parts = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in applied.items() if v]
    narration = narr_map[action] + ("（" + "、".join(parts) + "）" if parts else "")
    game_state.add_memory(f"太后{desc}：{emp['name']}")
    return jsonify({"success": True, "narration": narration, "effects": applied,
                    "dowager": dowager_payload(game_state),
                    "silver": game_state.silver,
                    "remaining_actions": game_state.remaining_actions,
                    "max_actions": game_state.max_actions})


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
    # 太后垂帘期：与「皇帝」的互动改为母子相见（宠爱不再有意义，改记权威与帝心）
    if is_dowager_active(game_state):
        return dowager_meet_emperor(game_state, action)
    action_map = {'serve_tea': {'desc': '献茶', 'effects': {'宠爱': (1,5), '威望': (0,2)}, 'cost': 10}, 'discuss': {'desc': '奏对', 'effects': {'宠爱': (2,6), '威望': (2,5), '谋略': (1,4)}, 'cost': 0}, 'recite_poem': {'desc': '献诗', 'effects': {'宠爱': (3,8), '才情': (2,5)}, 'cost': 0}, 'ask_reward': {'desc': '求赏赐', 'effects': {'宠爱': (0,3), '威望': (0,2)}, 'cost': 0}, 'request_funding': {'desc': '请拨内帑', 'effects': {}, 'cost': 0}}
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
    elif action == 'request_funding':
        # 奏请皇帝拨内帑充实内务府库银（仅皇后/协理六宫，每旬一次，随机5000-8000）
        if not inner_palace_can_manage(game_state):
            return jsonify({"error": "内务府为六宫公器，须皇后或受命协理六宫者方可奏请拨款"}), 403
        ip = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
        _pk = f"{game_state.year}-{game_state.month}-{0 if game_state.day <= 10 else (1 if game_state.day <= 20 else 2)}"
        if ip.get('last_funding_period') == _pk:
            return jsonify({"error": "本旬已奏请拨款内务府，下旬再来"}), 400
        grant = random.randint(5000, 8000)
        ip['budget'] = int(ip.get('budget', 0) or 0) + grant
        ip['last_funding_period'] = _pk
        from inner_palace_system import _ip_log
        _ip_log(ip, f'奏请皇帝拨内帑{grant}两充实内务府')
        game_state.inner_palace = ip
        game_state.add_memory(f"💰 奏请皇帝拨内帑{grant}两充实内务府库银")
        narration = f"你奏请皇帝拨内帑充实内务府，皇帝准奏，拨银{grant}两入库。"
        changes['内务府库银'] = grant
    else:
        narration = f"你向皇帝{act['desc']}，皇帝龙颜大悦，好感度+{favor_delta}，"
        if changes:
            change_str = "、".join([f"{k}{'+' if v>0 else ''}{v}" for k, v in changes.items() if k != '银两' or v != 0])
            narration += f"属性变化：{change_str}"
        else:
            narration += "一切如常。"
    if action not in ('ask_reward', 'request_funding'):
        game_state.add_memory(f"皇帝{act['desc']}，{narration}")
    game_state.add_attr_change(changes, f"皇帝{act['desc']}")
    intimacy_weights = {'serve_tea': 1, 'discuss': 1, 'recite_poem': 2, 'ask_reward': 1}
    if action in intimacy_weights:
        record_player_intimacy(game_state, intimacy_weights[action])
    return jsonify({"success": True, "narration": narration, "effects": changes, "reward": reward_info, "pregnancy": None, "is_pregnant": game_state.is_pregnant, "pregnancy_month": game_state.pregnancy_month, "attributes": game_state.attributes, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})

def _current_period_index(game_state):
    """当前旬序：0=上旬 1=中旬 2=下旬。"""
    return 0 if game_state.day <= 10 else (1 if game_state.day <= 20 else 2)

# ============================================================
#  选秀系统：皇帝/太后/皇后三方共决 + 太后皇后举荐
# ============================================================

DRAFT_SCALES = {
    "大选": {"candidates": 6, "admits": (3, 4)},
    "小选": {"candidates": 3, "admits": (1, 2)},
    "劝选": {"candidates": 4, "admits": (2, 3)},
}
DRAFT_INFLUENCE_COST = 30   # 打点内务府花费
DRAFT_ENDORSE_BONUS = 12    # 太后/皇后举荐加成
DRAFT_INFLUENCE_BONUS = 10  # 玩家打点加成


def _draft_period_key(game_state):
    return f"{game_state.year}-{game_state.month}-{_current_period_index(game_state)}"


def _draft_emperor_factors(game_state):
    emp = game_state.emperor or {}
    factors = (emp.get("favor_factors") or {}).get(emp.get("personality", "明君"))
    if not isinstance(factors, dict) or not factors:
        factors = {"容貌": 0.3, "才情": 0.4, "心计": 0.3}
    return factors


def _draft_score_emperor(game_state, cand):
    factors = _draft_emperor_factors(game_state)
    total_w = sum(factors.values()) or 1.0
    return sum(float(cand.get("attributes", {}).get(k, 50)) * w for k, w in factors.items()) / total_w


def _draft_family_score(cand):
    meta = cand.get("family_meta") or {}
    try:
        return float(meta.get("score", 50))
    except (TypeError, ValueError):
        return 50.0


def _draft_score_dowager(cand):
    a = cand.get("attributes", {})
    # 太后重门第清白与品行，厌心机深重者
    return (_draft_family_score(cand) * 0.45 + (100 - a.get("心计", 50)) * 0.25
            + a.get("健康", 60) * 0.15 + a.get("才情", 50) * 0.15)


def _draft_score_queen(cand):
    a = cand.get("attributes", {})
    # 皇后重后宫平衡：容貌过于出挑者视为威胁
    return ((100 - abs(a.get("容貌", 60) - 65)) * 0.40 + a.get("才情", 50) * 0.25
            + a.get("心计", 50) * 0.20 + a.get("健康", 60) * 0.15)


def start_draft(game_state, scale="大选"):
    """开启一届选秀：生成候选名册并公示太后/皇后举荐。返回消息列表。"""
    msgs = []
    cfg = DRAFT_SCALES.get(scale, DRAFT_SCALES["大选"])
    candidates = []
    for _ in range(cfg["candidates"]):
        npc = generate_npc(is_queen=False)
        while any(c["name"] == npc["name"] for c in candidates) or npc["name"] in game_state.npcs:
            npc = generate_npc(is_queen=False)
        npc["rank"] = "秀女"  # 采选阶段未定位份，统一称秀女
        npc["endorsed_by"] = []
        npc["influenced"] = False
        candidates.append(npc)

    # 太后举荐（始终在）：偏好门第高、心计浅的秀女
    dowager_pick = max(candidates, key=_draft_score_dowager)
    dowager_pick.setdefault("endorsed_by", []).append("太后")

    # 皇后举荐：皇后 NPC 在位时自动行使；玩家为皇后时留待玩家亲裁
    queen_name = get_queen_name(game_state, include_player=True)
    player_is_queen = getattr(game_state.rank, "name", "") == "皇后"
    if player_is_queen:
        queen_endorse_pending = True
    elif queen_name:
        queen_pick = max((c for c in candidates if "太后" not in c["endorsed_by"]),
                         key=_draft_score_queen, default=None)
        if queen_pick is None:
            queen_pick = random.choice(candidates)
        queen_pick.setdefault("endorsed_by", []).append("皇后")
        queen_endorse_pending = False
    else:
        queen_endorse_pending = False  # 中宫虚悬，皇后票缺位

    game_state.draft = {
        "active": True,
        "scale": scale,
        "started_key": _draft_period_key(game_state),
        "candidates": candidates,
        "player_influenced": None,
        "queen_endorse_pending": queen_endorse_pending,
    }
    # 妃嫔举荐：届次重置 + NPC 举荐竞争（待处理，留一旬干扰窗口）
    sync_edition(game_state)
    attach_npc_recommendations(game_state, msgs)
    # 宗室女入宫候选：玩家推荐的宗室女注入本届名册（§8 选秀联动）
    rc = get_royal_clan(game_state)
    for fname in list(rc.get("draft_inject", [])):
        f = rc["females"].get(fname)
        if not f or f.get("injected"):
            continue
        f["injected"] = True
        f["标记"] = list(set((f.get("标记") or []) + ["已入候选"]))
        cand = generate_npc(is_queen=False)
        while any(c["name"] == cand["name"] for c in candidates) or cand["name"] in game_state.npcs:
            cand = generate_npc(is_queen=False)
        cand["name"] = fname
        cand["icon"] = "🏵️"
        cand["rank"] = "秀女"
        cand["royal_father"] = f.get("父系", "")
        cand["family_background"] = f.get("身份") or "宗室之女"
        if isinstance(cand.get("family_meta"), dict):
            cand["family_meta"]["surname"] = fname[:1]
        cand["clan"] = generate_npc_clan(fname, "秀女", cand.get("family_meta"))
        cand["endorsed_by"] = []
        cand["influenced"] = False
        candidates.append(cand)
        msgs.append(f"🏵️ 宗人府呈报：{fname}奉旨入册候选")
    rc["draft_inject"] = [n for n in rc.get("draft_inject", []) if not rc["females"].get(n, {}).get("injected")]
    names_desc = "、".join(f"{c['icon']}{c['name']}（{c['rank']}，{c.get('family_background', '出身不详')}）" for c in candidates)
    msgs.append(f"📜 {scale}启程：礼部呈上采选名册——{names_desc}。")
    endorsed_t = [c for c in candidates if "太后" in c["endorsed_by"]]
    if endorsed_t:
        msgs.append(f"👵 太后属意 {'、'.join(c['name'] for c in endorsed_t)}，谓其「门第清白，性子端方」。")
    if player_is_queen:
        msgs.append("👑 中宫之位在你，皇后属意之人尚待你亲裁（可在选秀名册中举荐）。")
    elif any("皇后" in c["endorsed_by"] for c in candidates):
        eq = [c for c in candidates if "皇后" in c["endorsed_by"]]
        msgs.append(f"👑 皇后属意 {'、'.join(c['name'] for c in eq)}。")
    game_state.add_memory(f"{scale}开选，共{len(candidates)}名秀女入册")
    return msgs

def draft_panel_payload(game_state):
    """选秀名册面板数据（无进行中的选秀时为 None）。"""
    d = getattr(game_state, "draft", None)
    if not isinstance(d, dict) or not d.get("active"):
        return None
    player_is_queen = getattr(game_state.rank, "name", "") == "皇后"
    cands = []
    for c in d.get("candidates", []):
        cands.append({
            "name": c["name"], "icon": c.get("icon", "🌸"), "rank": c.get("rank", "秀女"),
            "family_background": c.get("family_background", "出身不详"),
            "attributes": {k: c.get("attributes", {}).get(k, 0) for k in ("容貌", "才情", "心计", "健康")},
            "endorsed_by": c.get("endorsed_by", []),
            "influenced": bool(c.get("influenced")),
            "npc_rec": c.get("npc_rec_pending"),
            "rec_state": ("failed" if c.get("rec_failed") else ("ok" if c.get("guaranteed_admit") else None)),
            "impression_bonus": int(c.get("impression_bonus", 0) or 0),
        })
    can_influence = (d.get("player_influenced") is None
                     and RANK_LEVELS.get(game_state.rank.name, 0) >= RANK_LEVELS.get("贵人", 6))
    return {
        "scale": d.get("scale", "大选"),
        "candidates": cands,
        "player_influenced": d.get("player_influenced"),
        "queen_endorse_pending": bool(d.get("queen_endorse_pending")) and player_is_queen,
        "can_influence": can_influence,
        "can_influence_cost": DRAFT_INFLUENCE_COST,
        "is_player_queen": player_is_queen,
        "recommend": recommend_payload(game_state),
    }


def process_draft(game_state):
    """转旬结算选秀：跨旬后由皇帝/太后/皇后三方合议放榜，入选者入宫。

    返回 (消息列表, new_concubine 或 None)。
    """
    d = getattr(game_state, "draft", None)
    if not isinstance(d, dict) or not d.get("active"):
        return [], None
    if d.get("started_key") == _draft_period_key(game_state):
        return [], None  # 开选当旬只公示，下一旬放榜

    candidates = d.get("candidates", [])
    if not candidates:
        game_state.draft = None
        return [], None

    has_queen = get_queen_name(game_state, include_player=True) is not None
    admits_lo, admits_hi = DRAFT_SCALES.get(d.get("scale", "大选"), DRAFT_SCALES["大选"])["admits"]

    def total_score(c):
        s_emp = _draft_score_emperor(game_state, c)
        s_dow = _draft_score_dowager(c)
        bonus = DRAFT_ENDORSE_BONUS * len([e for e in c.get("endorsed_by", []) if e in ("太后", "皇后")])
        if c.get("influenced"):
            bonus += DRAFT_INFLUENCE_BONUS
        if has_queen:
            return 0.45 * s_emp + 0.30 * s_dow + 0.25 * _draft_score_queen(c) + bonus
        # 中宫虚悬：皇帝份额扩大
        return 0.60 * s_emp + 0.40 * s_dow + bonus

    # 妃嫔举荐：先结算 NPC 举荐竞争（成功者保送入宫）
    rec_msgs = resolve_npc_recommendations(game_state)

    eligible = [c for c in candidates if not c.get("rec_failed")]
    ranked = sorted(eligible, key=total_score, reverse=True)
    admit_n = min(random.randint(admits_lo, admits_hi), len(ranked))
    # 举荐保送者必入选（§4.1/§6.2），其余按合议分数取足名额
    admitted = [c for c in ranked if c.get("guaranteed_admit")]
    for c in ranked:
        if len(admitted) >= admit_n:
            break
        if c not in admitted:
            admitted.append(c)

    new_names = []
    for npc in admitted:
        npc.pop("endorsed_by", None)
        npc.pop("influenced", None)
        npc.pop("npc_rec_pending", None)
        # 举荐保送：由举荐档位决定位份池；否则皇帝拟定区间，皇后最终定夺
        pool = npc.pop("guaranteed_pool", None)
        if pool:
            npc["rank"] = random.choice(pool)
        else:
            emp_score = _draft_score_emperor(game_state, npc)
            if has_queen:
                # 皇后在位：皇帝只给区间（答应~贵人 / 常在~嫔），皇后拍板
                if emp_score >= 70:
                    pool = ["贵人", "常在", "答应"]
                elif emp_score >= 55:
                    pool = ["常在", "答应", "官女子"]
                else:
                    pool = ["答应", "官女子", "更衣"]
                npc["rank"] = random.choice(pool)
                npc["_rank_pending_queen"] = True
            else:
                # 中宫虚悬：皇帝直接定具体位份
                if emp_score >= 75:
                    npc["rank"] = random.choice(["贵人", "嫔"])
                elif emp_score >= 60:
                    npc["rank"] = random.choice(["常在", "贵人"])
                elif emp_score >= 45:
                    npc["rank"] = random.choice(["答应", "常在"])
                else:
                    npc["rank"] = random.choice(["官女子", "答应"])
        game_state.npcs[npc["name"]] = npc
        # 举荐的「知遇之恩」：入宫时折入初始好感（§5.3）
        favor_offset = int(npc.pop("favor_offset", 0) or 0)
        if npc.pop("virtue_tag", None) and isinstance(npc.get("clan"), dict):
            npc["clan"].setdefault("标记", []).append("贤名")
        game_state.relationships[npc["name"]] = {
            "好感": max(-100, min(100, random.randint(-10, 30) + favor_offset)),
            "印象": "知遇" if favor_offset > 0 else "陌生", "互动次数": 0}
        new_names.append(f"{npc['icon']}{npc['name']}（{npc['rank']}）")
    # 宗室女中选入宫：登记回宗室名册（两翼联动 §6）
    rc = get_royal_clan(game_state)
    for npc in admitted:
        if npc.get("royal_father") or npc["name"] in rc["females"]:
            f = rc["females"].get(npc["name"])
            if f:
                f["标记"] = list(set((f.get("标记") or []) + ["已入宫"]))
                f["婚配状态"] = "已嫁"
    new_concubine = {"names": new_names, "is_daxuan": d.get("scale") == "大选"} if new_names else None

    joiner = "、皇后" if has_queen else ""
    msgs = list(rec_msgs)
    if new_names:
        msgs.append(f"🎊 {d.get('scale', '大选')}放榜：皇帝、太后{joiner}三宫合议，{'、'.join(new_names)} 入宫！")
        rejected = [c["name"] for c in ranked if c not in admitted]
        if rejected:
            msgs.append(f"🍂 落选归家：{'、'.join(rejected)}。")
    else:
        msgs = [f"📜 {d.get('scale', '大选')}放榜：诸秀皆不入三宫之眼，此届空手而归。"]
    game_state.add_memory(f"{d.get('scale', '大选')}放榜，{'、'.join(n.split('（')[0] for n in new_names) or '无人'}入宫")
    game_state.draft = None
    return msgs, new_concubine


@app.route('/api/draft/action', methods=['POST'])
def draft_action():
    """选秀期间的玩家动作：influence=打点内务府抬一人；endorse=玩家以皇后身份举荐。"""
    data = request.get_json()
    player_id = data.get('player_id')
    action = data.get('action')
    target = data.get('candidate')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    d = getattr(game_state, "draft", None)
    if not isinstance(d, dict) or not d.get("active"):
        return jsonify({"error": "当前没有进行中的选秀"}), 400
    cand = next((c for c in d.get("candidates", []) if c.get("name") == target), None)
    if cand is None:
        return jsonify({"error": "名册上查无此人"}), 400

    if action == 'endorse':
        if getattr(game_state.rank, "name", "") != "皇后":
            return jsonify({"error": "唯有中宫主位可行使皇后举荐之权"}), 403
        if not d.get("queen_endorse_pending"):
            return jsonify({"error": "本届选秀你已行过皇后举荐之权"}), 400
        for c in d["candidates"]:
            c["endorsed_by"] = [e for e in c.get("endorsed_by", []) if e != "皇后"]
        cand.setdefault("endorsed_by", []).append("皇后")
        d["queen_endorse_pending"] = False
        game_state.add_memory(f"选秀举荐：你以皇后之名举荐了{target}")
        return jsonify({"success": True, "narration": f"你以凤印之名，将「皇后属意」四字落在{target}名下。",
                        "draft_panel": draft_panel_payload(game_state)})

    if action == 'influence':
        ok, err = guard_action(game_state)
        if not ok:
            return err
        if d.get("player_influenced") is not None:
            return jsonify({"error": "本届选秀已打点过，不宜再动"}), 400
        if game_state.silver < DRAFT_INFLUENCE_COST:
            return jsonify({"error": f"银两不足，打点需{DRAFT_INFLUENCE_COST}两"}), 400
        game_state.silver -= DRAFT_INFLUENCE_COST
        cand["influenced"] = True
        d["player_influenced"] = target
        game_state.add_memory(f"选秀打点：花{DRAFT_INFLUENCE_COST}两暗中照拂{target}")
        return jsonify({"success": True,
                        "narration": f"你托内务府的人给{target}递了一碗水，采选的秤，悄悄偏了半分。（-{DRAFT_INFLUENCE_COST}两）",
                        "silver": game_state.silver,
                        "remaining_actions": game_state.remaining_actions,
                        "max_actions": game_state.max_actions,
                        "draft_panel": draft_panel_payload(game_state)})

    return jsonify({"error": "无效行为"}), 400


# ---- 妃嫔举荐秀女（RECOMMEND_SYSTEM.md） ----

_RECOMMEND_NARRATION = {
    ("成功", "圣心大悦"): "皇帝听闻你的举荐，龙颜大悦：「爱妃眼光果真不俗，朕明日便召她殿选！」",
    ("成功", "欣然应允"): "皇帝沉吟片刻，笑道：「既是爱妃举荐，朕便见一见吧。」",
    ("成功", "勉强同意"): "皇帝略一颔首：「姑且留牌子吧，成不成，看她自己的造化。」",
    ("失败", "沉吟不语"): "皇帝听完，久久沉吟不语，只淡淡「嗯」了一声。看来此事悬了。",
    ("失败", "龙颜不悦"): "皇帝眉头紧锁：「此事朕自有分寸，不必爱妃多言。」你屏退而出，心下惴惴。",
}


@app.route('/api/draft/recommend', methods=['GET'])
def draft_recommend_preview():
    """举荐预览：资格校验 + 三种方式的成功率（§5.2）。"""
    player_id = request.args.get('player_id')
    candidate = request.args.get('candidate')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    d = getattr(game_state, "draft", None)
    cand = next((c for c in (d.get("candidates", []) if isinstance(d, dict) else [])
                 if c.get("name") == candidate), None) if candidate else None
    blockers = eligibility_blockers(game_state, cand)
    methods = []
    if not blockers:
        from recommend_system import _rank_index
        for key, m in METHODS.items():
            rank_ok = _rank_index(game_state.rank.name) >= _rank_index(m["min_rank"])
            methods.append({
                "key": key, "name": m["name"], "icon": m["icon"], "desc": m["desc"],
                "cost": f'行动点{m["actions"]}' + (f'·银两{m["silver"]}' if m["silver"] else ''),
                "rate": compute_rate(game_state, cand, key) if rank_ok else None,
                "locked": None if rank_ok else f"需位份≥{m['min_rank']}",
            })
    return jsonify({"eligible": not blockers, "blockers": blockers, "methods": methods,
                    "competition": bool(cand and cand.get("npc_rec_pending")),
                    "impression_bonus": int(cand.get("impression_bonus", 0) or 0) if cand else 0})


@app.route('/api/draft/recommend', methods=['POST'])
def draft_recommend_action():
    """执行举荐（§四/§4.1）：掷骰定成败，档位定效果。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    result = player_recommend(game_state, data.get('candidate'), data.get('method'),
                              retry=bool(data.get('retry')))
    if "error" in result:
        return jsonify(result), 400
    tier = result["tier"]
    narration = _RECOMMEND_NARRATION.get(("成功" if result["success"] else "失败", tier), "")
    parts = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in result["effects"].items() if v]
    if parts:
        narration += "（" + "、".join(parts) + "）"
    if result["success"]:
        narration += f"✅ {result['candidate']}已蒙圣意属意，放榜时自会留用册封。"
    game_state.add_memory(f"举荐结果：{tier}")
    return jsonify({"success": True, **result, "narration": narration,
                    "draft_panel": draft_panel_payload(game_state), "avatars": avatar_payload(game_state),
        "dowager_mode": is_dowager_active(game_state),
                    "silver": game_state.silver,
                    "attributes": game_state.attributes,
                    "remaining_actions": game_state.remaining_actions,
                    "max_actions": game_state.max_actions})


@app.route('/api/draft/interfere', methods=['POST'])
def draft_interfere():
    """干扰 NPC 举荐（§6.3）：进谗言 / 截留举荐信 / 私下警告。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    result = interfere_npc_rec(game_state, data.get('npc'), data.get('way'))
    if "error" in result:
        return jsonify(result), 400
    return jsonify({"success": True, **result,
                    "draft_panel": draft_panel_payload(game_state),
                    "silver": game_state.silver,
                    "remaining_actions": game_state.remaining_actions,
                    "max_actions": game_state.max_actions})


@app.route('/api/draft/remedy', methods=['POST'])
def draft_remedy():
    """举荐补救（§8.3）：retry=再次举荐 / meet=安排偶遇 / dowager=请太后说情。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    kind = data.get('kind')
    result = recommend_remedy(game_state, kind, data.get('candidate'))
    if "error" in result:
        return jsonify(result), 400
    resp = {"success": True, **result}
    if kind == "retry":
        resp.update({"draft_panel": draft_panel_payload(game_state),
                     "silver": game_state.silver,
                     "attributes": game_state.attributes,
                     "remaining_actions": game_state.remaining_actions,
                     "max_actions": game_state.max_actions})
    return jsonify(resp)


@app.route('/api/emperor/advise_draft', methods=['POST'])
def emperor_advise_draft():
    """劝皇帝开选秀。成功则有新人入宫（贤德无妒之名，威望+；同时引入新的竞争者）。"""
    data = request.get_json()
    player_id = data.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    if "皇帝" not in game_state.relationships:
        game_state.relationships["皇帝"] = {"好感": 10, "印象": "初识", "互动次数": 0}
    # 本旬限一次：用带旬标记的 story_flag 做冷却
    period_flag = f"draft_advise:{game_state.year}-{game_state.month}-{_current_period_index(game_state)}"
    if period_flag in _story_flags(game_state):
        return jsonify({"error": "本旬已向皇帝进言选秀之事，不宜再提。"}), 400
    _add_story_flag(game_state, period_flag)
    game_state.relationships["皇帝"]["互动次数"] += 1
    favor = game_state.relationships["皇帝"].get("好感", 0)
    prestige = game_state.attributes.get("威望", 0)
    chance = 0.35 + min(0.30, favor / 200.0) + min(0.20, prestige / 500.0)
    chance = min(chance, 0.9)
    changes = {}
    new_concubine = None
    draft_panel = None
    if random.random() < chance:
        prestige_gain = random.randint(3, 6)
        favor_gain = random.randint(3, 7)
        max_prestige = game_state.get_attr_max("威望")
        game_state.attributes["威望"] = min(max_prestige, prestige + prestige_gain)
        changes["威望"] = prestige_gain
        game_state.relationships["皇帝"]["好感"] = min(100, favor + favor_gain)
        draft_msgs = start_draft(game_state, "劝选")
        draft_panel = draft_panel_payload(game_state)
        narration = (
            f"你于御前进言，请皇帝广纳淑女、充盈后宫，以固国本。皇帝赞你贤德无妒，"
            f"当即准奏，命礼部备选。你的威望+{prestige_gain}，皇帝好感+{favor_gain}。"
        )
        narration += "\n" + "\n".join(draft_msgs)
        game_state.add_memory(f"劝皇帝选秀获准（贤德无妒，威望+{prestige_gain}）")
        game_state.add_attr_change(changes, "劝皇帝选秀")
    else:
        favor_gain = random.randint(1, 3)
        game_state.relationships["皇帝"]["好感"] = min(100, favor + favor_gain)
        narration = "你劝皇帝开选秀，皇帝以国库未丰、边事未靖为由，暂将此议搁下，只夸你识大体。"
        game_state.add_memory("劝皇帝选秀未果，皇帝以时机未至为由暂缓")
    return jsonify({
        "success": True,
        "narration": narration,
        "effects": changes,
        "new_concubine": new_concubine,
        "draft_panel": draft_panel,
        "attributes": game_state.attributes,
        "remaining_actions": game_state.remaining_actions,
        "max_actions": game_state.max_actions,
    })


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
    # 太后垂帘期：你即太后，此路由改为受新后/妃嫔问安（角色反转）
    if is_dowager_active(game_state):
        d = get_dowager(game_state)
        from dowager_system import _apply_effects, ensure_new_queen
        q = ensure_new_queen(game_state, d) or "新后"
        applied = _apply_effects(game_state, d, {"权威": random.randint(1, 3)})
        d["queen_favor"] = max(0, min(100, int(d.get("queen_favor", 50)) + random.randint(1, 3)))
        return jsonify({"success": True,
                        "narration": f"🍵 {q}率新帝妃嫔至慈宁宫问安，你受了礼，赐了茶。"
                                     f"（摄政权威+{applied.get('摄政权威', 0)}，新后敬顺+）",
                        "effects": applied, "dowager": dowager_payload(game_state),
                        "remaining_actions": game_state.remaining_actions,
                        "max_actions": game_state.max_actions})
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

def _guard_dowager_forbidden(game_state, what="此事"):
    """太后垂帘期不再参与的后宫行为（争宠/侍寝/选秀入册等）。"""
    if is_dowager_active(game_state):
        return jsonify({"error": f"你已是太后，{what}已非你所与——六宫之事可于慈宁宫垂帘处置"}), 409
    return None


@app.route('/api/emperor/flip', methods=['POST'])
def emperor_flip():
    data = request.get_json()
    player_id = data.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    blocked = _guard_dowager_forbidden(game_state, "翻牌侍寝")
    if blocked:
        return blocked

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
    health_gain = 0
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
        "health_gain": health_gain,
        "attributes": game_state.attributes,
        "relationships": game_state.relationships,
        "message": f"皇帝{'前来探望' if visit_mode else '翻了'}{pai_name}的牌子！{'宠爱+'+str(favor_gain) if favor_gain>0 else ''}{'健康+'+str(health_gain) if visit_mode else ''}{'威望+'+str(prestige_gain) if prestige_gain>0 else ''}",
        "pregnancy": pregnancy_msg,
        "reward": reward_info
    })


# ============================================================
#  重要事件分级（供前端串行弹窗）
# ============================================================
# 每条 (关键词元组, 级别, 图标, 标题)；级别越小越先弹
KEY_EVENT_RULES = (
    (("终局", "赐死", "白绫", "薨逝", "驾崩", "伏诛", "病殁", "幽居", "倾覆", "废为庶人"), 1, "🕯️", "大事不谐"),
    (("案发", "谋逆", "复辟", "举兵", "事败", "败露", "抄没", "除爵", "除宗籍"), 1, "⚖️", "祸起萧墙"),
    (("登基", "继位", "称制", "改元", "还政", "撤帘", "临朝"), 1, "👑", "天命更移"),
    (("晋封", "册立", "晋为", "晋位", "受封", "加封", "凤印"), 2, "📜", "恩旨下达"),
    (("诞下", "喜得", "皇孙", "生下", "临盆", "有孕", "怀胎"), 2, "👶", "宗庙添丁"),
    (("放榜", "选秀", "留用", "册封为", "奉旨入册"), 2, "🌸", "新人入宫"),
    (("冷宫", "打入", "贬入", "出冷宫", "特赦"), 2, "🏚️", "宫门开合"),
    (("危", "警", "⚠️", "弹劾", "察觉", "记恨", "背叛", "收买", "叛"), 3, "⚠️", "暗流涌动"),
    (("宗室", "亲王", "郡王", "长公主", "大宗正"), 3, "🏵️", "宗室动静"),
    (("家族", "母家", "外戚", "权臣", "朝堂", "国是", "内帑"), 3, "🏛️", "前朝消息"),
)
KEY_EVENT_MAX = 6          # 单次转旬最多弹窗数（其余仍入日志）


def classify_key_events(lines):
    """从转旬情报中挑出需要弹窗确认的重要事件，按级别排序。"""
    out = []
    for raw in (lines or []):
        text = str(raw or "").strip()
        if not text:
            continue
        for keys, level, icon, title in KEY_EVENT_RULES:
            if any(k in text for k in keys):
                out.append({"level": level, "icon": icon, "title": title, "text": text})
                break
    out.sort(key=lambda e: e["level"])
    return out[:KEY_EVENT_MAX]


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

    # ---- 心腹系统：每旬日结 ----
    cf = confidant_servant(game_state)
    if cf:
        cf.loyalty = min(100, cf.loyalty + random.randint(1, 3))
        betray_chance = 0.25
        if "恩威并施" in getattr(game_state, "traits", []):
            betray_chance *= 0.8  # 恩威并施：心腹背叛风险-20%
        if cf.loyalty < CONFIDANT_BETRAY_LOYALTY and random.random() < betray_chance:
            betrayal_gain = random.randint(5, 10)
            game_state.attributes["威望"] = max(0, game_state.attributes["威望"] - betrayal_gain)
            intelligence.append(f"⚠️ 你的心腹{cf.name}忠诚度低迷（{cf.loyalty}），似乎有人暗中收买他，威望-{betrayal_gain}")
            game_state.add_memory(f"心腹{cf.name}似有异动，威望-{betrayal_gain}")
            remember_confidant_event(game_state, f"{cf.name}忠诚低迷（{cf.loyalty}），似乎被人收买，威望-{betrayal_gain}")
        elif random.random() < 0.55:
            topics = [
                f"贴身伺候的{cf.name}禀报：{random.choice(['某位娘娘的宫里最近出入了一些生面孔','皇后娘娘这几日对某位妃嫔格外冷淡','皇帝最近总批到深夜，朝中似有大事','御膳房悄悄给某位娘娘的份例减了成'])}",
                f"{cf.name}悄悄提醒你：{random.choice(['有人在御花园埋了东西，形迹可疑','有位娘娘的贴身丫鬟和宫外的人递了信','太后近日召见了几位年长妃嫔','某位娘娘最近在打听你的子嗣消息'])}",
                f"{cf.name}暗中帮你打点：{random.choice(['你宫里几位新来的宫人，他都替你留意过了','你送出去的几份人情，他都记在簿子上','你对手的宫里这几日的动静，他都替你盯着'])}",
            ]
            intelligence.append(f"🔒 {random.choice(topics)}")
            remember_confidant_event(game_state, f"为你打探了宫中秘事")
        game_state.add_memory(f"心腹{cf.name}忠诚{cf.loyalty}")
    elif game_state.confidant:
        # 心腹已不在（被遣散/离职）：清理残留
        game_state.confidant = None

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

    # ---- 内务府自治结算：月例/库存/物价/总管AI/NPC讨要/重华宫联动 ----
    from inner_palace_system import inner_palace_period_tick
    try:
        ip_events = inner_palace_period_tick(
            game_state,
            normalize_inner_palace,
            RANK_POWER,
            chonghua_count_inside=chonghua_count_inside,
            CHONGHUA_UPKEEP_PER_CHILD=CHONGHUA_UPKEEP_PER_CHILD,
        )
        for msg in ip_events:
            intelligence.append(msg)
        # 非主控掌管内务府时，现任皇后/协理者自动请帑与经营产业
        for msg in npc_manage_inner_palace(game_state):
            intelligence.append(msg)
        # 皇后去世/病重/怀孕时，必须设一位协理六宫
        for msg in enforce_six_palace_assistant(game_state):
            intelligence.append(msg)
            game_state.add_memory(msg)
    except Exception as e:
        import traceback
        traceback.print_exc()
        intelligence.append(f'⚠️ 内务府结算异常：{e}')


    # ---- 重华宫转旬结算：出馆/收容/用度/教养 ----
    chonghua_events = chonghua_period_tick(game_state)
    for msg in chonghua_events:
        intelligence.append(msg)
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
    # ---- 子嗣标签事件（每子每旬最多 1 件，队列弹窗） ----
    generate_child_tag_events(game_state)
    # ---- 协理六宫事件（每旬 1~2 件，弹窗裁决） ----
    generate_governance_events(game_state)
    # ---- 前朝关联：家族补全/升降位/风险结算 + 家族事件（弹窗处置） ----
    for evt in process_clan_period(game_state):
        intelligence.append(evt)
    generate_family_events(game_state)
    # ---- 宗室系统：立场演化/世系繁衍/谋逆链/宗室事件 ----
    for evt in process_royal_clan_period(game_state):
        intelligence.append(evt)
    # ---- 冷宫系统：在押者衰减/事件/玩家冷宫循环 ----
    for evt in cold_period_tick(game_state):
        intelligence.append(evt)
    # ---- 出轨/私通 + 狸猫换子：风险累积/阈值事件/孕程/案发 ----
    for evt in process_affair_period(game_state):
        intelligence.append(evt)
    # ---- 太后垂帘听政：朝会奏事/财政民心/新帝成长/亲政与失势 ----
    for evt in dowager_period_tick(game_state):
        intelligence.append(evt)
    # ---- NPC 妃嫔关系网：每旬自然变化 ----
    for rel_msg in process_npc_relationships(game_state):
        intelligence.append(rel_msg)
    # ---- NPC 主动上门：按互动状态轴（好感/信任/畏惧/爱慕/敌意）驱动 ----
    for visit_msg in generate_npc_visits(game_state):
        intelligence.append(visit_msg)
    # ---- 夺嫡暗流：储君空悬时逐旬更新皇子势头 ----
    heir_race_events = process_heir_race(game_state)
    for evt in heir_race_events:
        intelligence.append(evt)
    # ---- 太子系统：监国政务 / 叛逆危机 / 不孝事件链 / 东宫内宅 ----
    heir_system_events = process_heir_system(game_state)
    for evt in heir_system_events:
        intelligence.append(evt)
    # ---- 婚后子嗣系统：皇子 / 公主 / 东宫内宅生子 ----
    for evt in process_offspring_system(game_state):
        intelligence.append(evt)
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
            if step and step["type"] == "赐封号":
                target_label = "赐封号"
            elif step and step["type"] == "四妃封号":
                target_label = (f"{step.get('target')}妃" if step.get("target") else "四妃封号")
            else:
                target_label = (step.get("target") if step else "") or ""
            if step and step["type"] == "位份" and not can_promote_to_rank(game_state, step.get("target", "")):
                promotion_message = f"⚠️ {target_label} 人数已满，暂无法晋升。"
            elif step and step["type"] == "四妃封号" and not step.get("target"):
                promotion_message = "⚠️ 四妃（淑德贤宸）封号已满，暂无空缺。"
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
                if current_rank == "妃":
                    # 妃位内封号晋升（无号→普通→四妃→贵妃），统一走 promote_npc_one_step
                    stage_ok = True
                    if npc.get("nobletitle") and is_four_consort_title(npc.get("nobletitle")):
                        # 四妃封号 → 贵妃，需名额与母凭子贵
                        stage_ok = can_promote_to_rank(game_state, "贵妃") and npc_meets_rank_requirements(npc, "贵妃")
                    elif npc.get("nobletitle"):
                        # 普通封号 → 四妃封号，需空缺与母凭子贵
                        stage_ok = bool(pick_available_four_consort_title(game_state)) and npc_meets_rank_requirements(npc, "四妃封号")
                    if stage_ok and random.random() < 0.25:
                        next_label = promote_npc_one_step(game_state, npc)
                        if next_label:
                            npc["attributes"]["宠爱"] = min(100, favor + random.randint(5, 12))
                            npc["attributes"]["威望"] = min(100, prestige + random.randint(5, 10))
                            other_promotions.append(f"✨ {name} 晋封为 {next_label}！")
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

    # ---- 选秀：开选与放榜（三方共决流程见 start_draft / process_draft） ----
    new_concubine = None
    draft_events = []
    if game_state.year % 3 == 0 and game_state.month == 1 and game_state.day <= 10:
        if random.random() < 0.8 and not getattr(game_state, "draft", None):
            draft_events.extend(start_draft(game_state, "大选"))
    elif game_state.month % 6 == 0 and game_state.day <= 10 and random.random() < 0.3:
        if not getattr(game_state, "draft", None):
            draft_events.extend(start_draft(game_state, "小选"))
    _draft_msgs, _draft_new = process_draft(game_state)
    draft_events.extend(_draft_msgs)
    new_concubine = _draft_new
    tick_recommendations(game_state)  # 妃嫔举荐冷却递减


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
                    swap_rec = (getattr(game_state, "secret_relationships", {}) or {}).get("swap") or {}
                    if str(swap_rec.get("child_uid") or "") == str(heir_child.get("uid") or "") \
                            and swap_rec.get("phase") == "executed" and not swap_rec.get("案发"):
                        # 狸猫继位（§3.4 阶段六）：换来的孩子登基
                        if swap_rec.get("揭穿"):
                            ending = trigger_ending(game_state, "狸猫之祸",
                                "新帝登基当日，你当众道破了狸猫真相")
                        else:
                            ending = trigger_ending(game_state, "狸猫天子",
                                "新帝登基，龙椅上坐着的，是你换来的孩子")
                        game_state.add_memory("👑 新帝登基——只有你知道龙袍之下藏着什么")
                    elif heir_mother == game_state.name:
                        # 你的子嗣继位 → 太后结局；太子若已长歪，改判不正经结局
                        ending_key, absurd_reason = resolve_heir_succession_ending(game_state)
                        reason = absurd_reason or (
                            f"皇帝驾崩，你的子嗣{heir_child.get('name','皇嗣')}继位为帝，尊你为太后")
                        ending = trigger_ending(game_state, ending_key, reason)
                        if ending_key == "母仪天下":
                            intelligence.append("👑 新帝登基，尊你为太后，母仪天下！")
                            # 太后线：幼帝冲龄践祚则转入垂帘听政续章（非终局）
                            if int(float(heir_child.get("age", 20) or 20)) < DOWAGER_REGENCY_MAX_AGE:
                                ok_d, msg_d = enter_dowager_mode(game_state, heir_child)
                                if ok_d:
                                    intelligence.append(msg_d)
                        else:
                            headline = (ENDINGS.get(ending_key) or {}).get("headline", ending_key)
                            intelligence.append(f"👑 新帝登基，尊你为太后——只是这位新君，{headline}。")
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
        "key_events": classify_key_events(intelligence),
        "avatars": avatar_payload(game_state),
        "dowager_mode": is_dowager_active(game_state),
        "player_render": build_player_render(game_state),
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
        "chonghua_events": chonghua_events,
        "draft_events": draft_events,
        "draft_panel": draft_panel_payload(game_state),
        "chonghua": chonghua_state(game_state),
        "death_events": death_events,
        "intrigue": summarize_intrigue(game_state),
        "intrigue_events": intrigue_events,
        "ai_events_used": ai_events_used,
        "ai_events_fallback": ai_fallback,
        "ending": ending,
        "game_over": bool(ending),
        "ending_warnings": ending_warnings,
        "heir_status": game_state.heir_status,
        "heir_panel": heir_panel_payload(game_state),
        "palaces": PALACE_LIST,
        "emperor": game_state.emperor,
        "heir_race": normalize_heir_race(getattr(game_state, "heir_race", None)),
        "child_event_queue": getattr(game_state, "child_event_queue", []),
        "governance_events": getattr(game_state, "governance_events", []),
        "governance_history": getattr(game_state, "governance_history", [])[-10:],
        "relationship_log": (getattr(game_state, "relationship_log", []) or [])[:5],
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

    # 前朝关联：按开局家世生成玩家家族，并补全 NPC 母族及与玩家家族的初始关系
    # （须在 npcs 生成之后；旧档由 process_clan_period 兜底补全）
    game_state.player_clan = generate_player_clan(extract_surname(player_name) or "沈", game_state.family_meta or {})
    ensure_clans(game_state)
    
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
    game_state._promotion_done = False
    sessions[player_id] = game_state
    user_configs[player_id] = {"custom_prompt": "", "romance_mode": False, "api_base": api_config.get('api_base', 'https://cn.jixiangai.xyz/v1'), "api_key": api_config.get('api_key', ''), "api_model": api_config.get('api_model', '')}
    npc_names = list(game_state.npcs.keys())
    story = generate_story(game_state, "入宫选秀，开启了后宫生涯", npc_names, api_config.get('api_key'), api_config.get('api_base'), api_config.get('api_model'))
    # 宫中有皇后则由皇后设立重华宫（六宫公器，无需主控手动奏请，亦不卡威望/银两）
    _queen = get_queen_name(game_state, include_player=True)
    if _queen:
        _ch = chonghua_state(game_state)
        if not _ch.get('founded'):
            _ch['founded'] = True
            _ch['level'] = 1
            _ch['arrears'] = 0
            chonghua_add_log(game_state, _ch, f'皇后{_queen}设立重华宫')
            game_state.add_memory(f'🏛️ 皇后{_queen}设立重华宫，皇嗣共育之所自此立起')
    
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
    return jsonify({"player_id": player_id, "rank": game_state.rank.name, "nobletitle": game_state.nobletitle, "display_rank": game_state.get_display_rank(), "attributes": game_state.attributes, "attr_max": game_state.ATTR_MAX, "relationships": game_state.relationships, "story_flags": game_state.story_flags, "storyline": game_state.storyline.value, "emperor": game_state.emperor, "dowager": dowager_data, "day": game_state.day, "month": game_state.month, "year": game_state.year, "calendar_str": game_state.get_calendar_str(), "silver": game_state.silver, "family_background": game_state.family_background, "npcs": npcs_with_children, "narration": story.get("narration","宫中岁月静好。"), "choices": story.get("choices",["继续","查看状态","保存游戏"]), "effects": story.get("effects",{}), "ai_warning": story.get("ai_warning"), "rivalry_event": rivalry_event, "event_triggered": story.get("event_triggered"), "memories": game_state.get_recent_memories(3), "is_pregnant": game_state.is_pregnant, "pregnancy_month": game_state.pregnancy_month, "children": game_state.children, "has_children": game_state.has_children, "rivalries": game_state.rivalries, "alliances": game_state.alliances, "intrigue": summarize_intrigue(game_state), "intrigue_events": [], "attr_change_log": game_state.attr_change_log[-5:], "servants": [s.to_dict() for s in game_state.get_active_servants()], "romance_mode": game_state.romance_mode, "player_name": game_state.name, "age": game_state.age, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions, "empress_status": get_empress_requirement_status(game_state), **confidant_payload(game_state)})

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
        return jsonify({"rank": game_state.rank.name, "nobletitle": game_state.nobletitle, "display_rank": game_state.get_display_rank(), "rank_periods": get_rank_periods(game_state), "rank_tenure_required": get_min_tenure(game_state.rank.name), "special_favor": is_special_favor(game_state), "empress_status": get_empress_requirement_status(game_state), "name": game_state.name, "age": game_state.age, "family_background": game_state.family_background, "attributes": game_state.attributes, "attr_max": game_state.ATTR_MAX, "relationships": game_state.relationships, "current_time": game_state.current_time, "day": game_state.day, "month": game_state.month, "year": game_state.year, "calendar_str": game_state.get_calendar_str(), "silver": game_state.silver, "story_flags": game_state.story_flags, "storyline": game_state.storyline.value, "emperor": game_state.emperor, "dowager": dowager_data, "memories": game_state.get_recent_memories(5), "inventory": game_state.inventory, "npcs": npcs_with_children, "is_pregnant": game_state.is_pregnant, "pregnancy_month": game_state.pregnancy_month, "children": game_state.children, "has_children": game_state.has_children, "rivalries": game_state.rivalries, "alliances": game_state.alliances, "intrigue": summarize_intrigue(game_state), "intrigue_events": [], "attr_change_log": game_state.attr_change_log[-10:], "servants": [s.to_dict() for s in game_state.get_active_servants()], "romance_mode": game_state.romance_mode, "player_name": game_state.name, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions, "appearance": getattr(game_state,'appearance',''), "talent": getattr(game_state,'talent',''), "personality": getattr(game_state,'personality',''), "traits": getattr(game_state,'traits',[]), "custom_story": getattr(game_state,'custom_story',''), "player_render": build_player_render(game_state), "ending": ending_payload(game_state), "game_over": is_game_over(game_state), "neglect_periods": getattr(game_state, "neglect_periods", 0), "restored_from_save": need_restore, "dowager_mode": is_dowager_active(game_state), "avatars": avatar_payload(game_state), "heir_status": game_state.heir_status, "palaces": PALACE_LIST, "chonghua": chonghua_state(game_state), "chonghua_capacity": chonghua_capacity(chonghua_state(game_state)), "chonghua_permission": chonghua_permission(game_state), "court_faction_favor": normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None)), "heir_race": normalize_heir_race(getattr(game_state, "heir_race", None)), "heir_panel": heir_panel_payload(game_state), "draft_panel": draft_panel_payload(game_state), "child_event_queue": getattr(game_state, "child_event_queue", []), "governance_events": getattr(game_state, "governance_events", []), "governance_history": getattr(game_state, "governance_history", [])[-10:], "family_event_queue": getattr(game_state, "family_event_queue", []), "family_event_history": (getattr(game_state, "family_event_history", []) or [])[-10:], "relationship_log": (getattr(game_state, "relationship_log", []) or [])[:5], **confidant_payload(game_state)})
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
        tmp_path = filename + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, filename)  # 原子替换：写入中断不再产生截断存档
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

@app.route('/api/child_event/respond', methods=['POST'])
def child_event_respond():
    """处理子嗣标签事件：提交选项索引，结算并移除该事件。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    queue = getattr(game_state, 'child_event_queue', None)
    if not isinstance(queue, list):
        queue = []
        game_state.child_event_queue = queue
    ev_id = data.get('event_id')
    ev = next((e for e in queue if e.get('id') == ev_id), None)
    if ev is None:
        return jsonify({"error": "事件不存在或已了结"}), 404
    idx = int(data.get('choice_index', 0) or 0)
    choices = ev.get('choices') or []
    if idx < 0 or idx >= len(choices):
        return jsonify({"error": "选项无效"}), 400
    result = apply_child_tag_choice(game_state, ev, choices[idx])
    game_state.child_event_queue = [e for e in queue if e.get('id') != ev_id]
    return jsonify({"success": True, **result, "child_event_queue": game_state.child_event_queue,
                    "children": game_state.children})


@app.route('/api/governance/respond', methods=['POST'])
def governance_respond():
    """处理协理六宫事件：提交选项索引，结算并移除该事件（消耗 1 行动点）。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    queue = getattr(game_state, 'governance_events', None)
    if not isinstance(queue, list):
        queue = []
        game_state.governance_events = queue
    ev_id = data.get('event_id')
    ev = next((e for e in queue if e.get('id') == ev_id), None)
    if ev is None:
        return jsonify({"error": "事件不存在或已了结"}), 404
    ok, gerr = guard_action(game_state)
    if not ok:
        return gerr
    idx = int(data.get('choice_index', 0) or 0)
    choices = ev.get('choices') or []
    if idx < 0 or idx >= len(choices):
        return jsonify({"error": "选项无效"}), 400
    result = apply_governance_choice(game_state, ev, choices[idx])
    game_state.governance_events = [e for e in queue if e.get('id') != ev_id]
    return jsonify({"success": True, **result,
                    "governance_events": game_state.governance_events,
                    "governance_history": game_state.governance_history[-10:],
                    "silver": game_state.silver,
                    "attributes": game_state.attributes,
                    "remaining_actions": game_state.remaining_actions})


@app.route('/api/family/respond', methods=['POST'])
def family_respond():
    """处理家族事件：提交选项索引，结算并移除该事件（家事不耗行动点）。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    queue = getattr(game_state, 'family_event_queue', None)
    if not isinstance(queue, list):
        queue = []
        game_state.family_event_queue = queue
    ev_id = data.get('event_id')
    ev = next((e for e in queue if e.get('id') == ev_id), None)
    if ev is None:
        return jsonify({"error": "事件不存在或已了结"}), 404
    idx = int(data.get('choice_index', 0) or 0)
    choices = ev.get('choices') or []
    if idx < 0 or idx >= len(choices):
        return jsonify({"error": "选项无效"}), 400
    result = apply_family_choice(game_state, ev, choices[idx])
    game_state.family_event_queue = [e for e in queue if e.get('id') != ev_id]
    return jsonify({"success": True, **result,
                    "family_event_queue": game_state.family_event_queue,
                    "family_event_history": game_state.family_event_history[-10:],
                    "player_clan": game_state.player_clan,
                    "court_faction_favor": normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None)),
                    "silver": game_state.silver,
                    "attributes": game_state.attributes})


@app.route('/api/court/overview', methods=['GET'])
def court_overview():
    """前朝总览：玩家家族 + 朝堂派系好感 + 各妃嫔母族（缺失的家族结构就地补全）。"""
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    clan = ensure_clans(game_state)
    npc_clans = []
    for name, npc in (game_state.npcs or {}).items():
        if not isinstance(npc, dict) or name == "太后" or not npc.get("alive", True):
            continue
        c = npc.get("clan")
        if not isinstance(c, dict):
            continue
        rel = c.get("与玩家家族关系") or {}
        father = c.get("father") or {}
        npc_clans.append({
            "name": name, "rank": npc.get("rank", "答应"),
            "faction": c.get("政治倾向", ""),
            "prestige": int(c.get("家族威望", 40) or 0),
            "father": f'{father.get("官职", "")}{father.get("name", "")}',
            "relation": rel.get("关系", "中立"), "favor": int(rel.get("好感", 0) or 0),
        })
    npc_clans.sort(key=lambda x: -x["favor"])
    return jsonify({
        "player_clan": clan,
        "factions": normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None)),
        "npc_clans": npc_clans,
        "period": game_state.get_calendar_str(),
    })


# ---- 宗室系统（royal_clan.py / ROYAL_CLAN.md） ----

@app.route('/api/royal/overview', methods=['GET'])
def royal_overview_api():
    """宗室势力总览：男性两翼分列 + 待办 + 动态。"""
    game_state, err = session_or_404(request.args.get('player_id'))
    if err:
        return err
    return jsonify(royal_overview_payload(game_state))


@app.route('/api/royal/action', methods=['POST'])
def royal_action_api():
    """宗室成员玩法接口（男：结盟/献计/求援/举报/联姻；女：结交/拉拢/情报/推荐/联姻/手帕交）。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    rc = seed_royal_clan(game_state)
    name = data.get('name')
    kind = data.get('kind')
    action = data.get('action')
    if kind == "male":
        member = rc["males"].get(name)
        if not member or not member.get("alive"):
            return jsonify({"error": "宗室名册查无此人"}), 404
        ok, msg = royal_male_action(game_state, rc, member, action)
    elif kind == "female":
        member = rc["females"].get(name)
        if not member or not member.get("alive"):
            return jsonify({"error": "宗室名册查无此人"}), 404
        ok, msg = royal_female_action(game_state, rc, member, action)
    else:
        return jsonify({"error": "无效的成员类型"}), 400
    if not ok:
        if isinstance(msg, tuple):
            return msg[0], msg[1]
        return jsonify({"error": str(msg)}), 400
    return jsonify({"success": True, "narration": msg, "overview": royal_overview_payload(game_state),
                    "silver": game_state.silver,
                    "attributes": game_state.attributes,
                    "remaining_actions": game_state.remaining_actions,
                    "max_actions": game_state.max_actions})


@app.route('/api/royal/pending', methods=['POST'])
def royal_pending_api():
    """宗室待办事件响应（郡主入宫/长辈争执/郡王议亲）。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    rc = seed_royal_clan(game_state)
    ok, msg = respond_royal_pending(game_state, rc, data.get('event_id'), data.get('choice_index'))
    if ok is None:
        return jsonify({"error": msg}), 404
    return jsonify({"success": True, "narration": msg, "overview": royal_overview_payload(game_state),
                    "attributes": game_state.attributes,
                    "relationships": game_state.relationships})


# ---- 冷宫系统（cold_palace.py / COLD_PALACE.md） ----

@app.route('/api/coldpalace/overview', methods=['GET'])
def coldpalace_overview_api():
    game_state, err = session_or_404(request.args.get('player_id'))
    if err:
        return err
    return jsonify(cold_overview_payload(game_state))


@app.route('/api/coldpalace/interact', methods=['POST'])
def coldpalace_interact_api():
    """与冷宫妃嫔互动：探视/递送/求情/利用秘密/太医/买通看守。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    ok, msg = interact_inmate(game_state, data.get('name'), data.get('action'))
    if ok is None:
        return jsonify({"error": msg}), 404
    if not ok:
        if isinstance(msg, tuple):
            return msg[0], msg[1]
        return jsonify({"error": str(msg)}), 400
    return jsonify({"success": True, "narration": msg,
                    "overview": cold_overview_payload(game_state),
                    "silver": game_state.silver,
                    "attributes": game_state.attributes,
                    "intrigue": summarize_intrigue(game_state),
                    "remaining_actions": game_state.remaining_actions,
                    "max_actions": game_state.max_actions})


@app.route('/api/coldpalace/manage', methods=['POST'])
def coldpalace_manage_api():
    """冷宫管理（需协理权限）：改善条件/特赦/搜查/裁决入冷宫。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    ok, msg = cold_manage(game_state, data.get('action'), data.get('name'))
    if ok is None:
        return jsonify({"error": msg}), 400
    if not ok:
        if isinstance(msg, tuple):
            return msg[0], msg[1]
        return jsonify({"error": str(msg)}), 400
    return jsonify({"success": True, "narration": msg,
                    "overview": cold_overview_payload(game_state),
                    "silver": game_state.silver,
                    "attributes": game_state.attributes,
                    "npcs": {n: {"rank": c.get("rank", "答应"), "alive": c.get("alive", True)}
                             for n, c in (game_state.npcs or {}).items()}})


@app.route('/api/coldpalace/self', methods=['POST'])
def coldpalace_self_api():
    """玩家冷宫生存动作与翻身尝试。action ∈ SELF_ACTIONS 或 release:<方式>。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    action = data.get('action') or ''
    if action.startswith('release:'):
        ok, msg = player_release_attempt(game_state, action.split(':', 1)[1])
    else:
        ok, msg = player_self_action(game_state, action)
    if ok is None:
        return jsonify({"error": msg}), 400
    if not ok:
        if isinstance(msg, tuple):
            return msg[0], msg[1]
        return jsonify({"error": str(msg)}), 400
    resp = {"success": True, "narration": msg,
            "overview": cold_overview_payload(game_state),
            "attributes": game_state.attributes,
            "remaining_actions": game_state.remaining_actions,
            "max_actions": game_state.max_actions}
    if is_game_over(game_state):
        resp["game_over"] = True
        resp["ending"] = ending_payload(game_state)
    return jsonify(resp)


@app.route('/api/coldpalace/enter', methods=['POST'])
def coldpalace_enter_api():
    """玩家主动避居冷宫（§二：主动途径）。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    ok, msg = enter_cold_palace(game_state, (data.get('reason') or '主动避居，静思己过'))
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"success": True, "narration": msg,
                    "overview": cold_overview_payload(game_state),
                    "silver": game_state.silver,
                    "attributes": game_state.attributes})


# ---- 出轨/私通 + 狸猫换子（affair_system.py / AFFAIR_SYSTEM.md） ----

@app.route('/api/affair/overview', methods=['GET'])
def affair_overview_api():
    game_state, err = session_or_404(request.args.get('player_id'))
    if err:
        return err
    return jsonify(affair_overview_payload(game_state))


@app.route('/api/affair/action', methods=['POST'])
def affair_action_api():
    """私通/处置统一动作分发。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    action = data.get('action')
    if action == 'develop':
        ok, msg = develop_affair(game_state, data.get('target_type'), data.get('way'), data.get('name'))
    elif action == 'use':
        ok, msg = use_affair_perk(game_state, data.get('name'))
    elif action == 'mitigate':
        ok, msg = mitigate_risk(game_state, data.get('name'), data.get('way'))
    elif action == 'probe':
        ok, msg = probe_npc_affair(game_state)
    elif action == 'dispose':
        ok, msg = dispose_npc_affair(game_state, data.get('name'), data.get('op'))
    else:
        return jsonify({"error": "无效的动作"}), 400
    if ok is None:
        return jsonify({"error": msg}), 400
    if not ok:
        if isinstance(msg, tuple):
            return msg[0], msg[1]
        return jsonify({"error": str(msg)}), 400
    return jsonify({"success": True, "narration": msg,
                    "overview": affair_overview_payload(game_state),
                    "silver": game_state.silver,
                    "attributes": game_state.attributes,
                    "remaining_actions": game_state.remaining_actions,
                    "max_actions": game_state.max_actions,
                    "game_over": is_game_over(game_state)})


@app.route('/api/swap/action', methods=['POST'])
def swap_action_api():
    """狸猫换子：密谋/执行/善后/案发应对。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    action = data.get('action')
    if action == 'eligibility':
        return jsonify(swap_eligibility(game_state))
    if action == 'plan':
        ok, msg = swap_start_plan(game_state, data.get('insider'))
    elif action == 'execute':
        ok, msg = swap_execute(game_state)
    elif action.startswith('aftercare:'):
        ok, msg = swap_aftercare(game_state, action.split(':', 1)[1])
    elif action.startswith('case:'):
        ok, msg = swap_case_respond(game_state, action.split(':', 1)[1])
    elif action == 'reveal_at_crown':
        sr = get_affairs(game_state)
        if sr["swap"].get("phase") != "executed":
            return jsonify({"error": "尚无狸猫之局"}), 400
        sr["swap"]["揭穿"] = True
        return jsonify({"success": True, "narration": "你把那个秘密封存心底——或随时揭开。（已设：登基之日自揭真相）"})
    else:
        return jsonify({"error": "无效的动作"}), 400
    if ok is None:
        return jsonify({"error": msg}), 400
    if not ok:
        return jsonify({"error": str(msg)}), 400
    resp = {"success": True, "narration": msg,
            "overview": affair_overview_payload(game_state),
            "silver": game_state.silver,
            "attributes": game_state.attributes,
            "remaining_actions": game_state.remaining_actions,
            "max_actions": game_state.max_actions}
    if is_game_over(game_state):
        resp["game_over"] = True
        resp["ending"] = ending_payload(game_state)
    return jsonify(resp)


@app.route('/api/relationships', methods=['GET'])
def relationship_net():
    """后宫关系网数据（含类型/图标/颜色）+ 最近变化日志。"""
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    return jsonify({
        "net": npc_relationships_payload(game_state),
        "log": (getattr(game_state, "relationship_log", []) or [])[:20],
        "pending": (getattr(game_state, "relationship_events", []) or [])[-5:],
    })


@app.route('/api/child/given_chars', methods=['GET'])
def list_child_given_chars():
    return jsonify({"categories": CHILD_GIVEN_NAME_CATEGORIES, "chars": CHILD_GIVEN_CHARS})

@app.route('/api/child/interact', methods=['POST'])
def child_interact():
    data = request.get_json()
    player_id = data.get('player_id')
    action = data.get('action')
    child_index = data.get('child_index', 0)
    child_uid = data.get('child_uid')
    mother_name = data.get('mother_name')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err

    # 夺嫡造势/打压可作用于任意皇子（含非玩家亲子），优先按 child_uid 定位
    if child_uid is not None and action in ("boost_heir", "undermine_heir"):
        child, resolved_mother = _find_prince_by_uid(game_state, child_uid)
        if child is None:
            return jsonify({"error": "子嗣不存在", "success": False}), 404
        if mother_name is None:
            mother_name = resolved_mother
    else:
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
    elif action == "boost_heir":
        # 为某皇子造势：消耗银两50 + 行动点1（行动点已由 guard_action 扣除）
        if child.get("gender") != "皇子":
            return jsonify({"error": "只可为皇子造势", "success": False}), 400
        if not child.get("alive", True):
            return jsonify({"error": "此子已不在人世", "success": False}), 400
        if game_state.silver < 50:
            return jsonify({"error": "银两不足，造势需50两", "success": False}), 400
        race = getattr(game_state, "heir_race", None)
        if not (isinstance(race, dict) and race.get("active")):
            return jsonify({"error": "当前并非夺嫡之期，无从造势", "success": False}), 400
        uid = ensure_child_uid(game_state, child)
        if uid not in (race.get("candidates") or []):
            return jsonify({"error": "此皇子尚未参与夺嫡（须年满8岁）", "success": False}), 400
        game_state.silver -= 50
        momentum = race.setdefault("momentum", {})
        momentum[uid] = max(0, min(100, momentum.get(uid, 0) + 5))
        effects = {"silver": -50, "momentum": 5}
        # 造势者非其生母/养母时，被其生母记恨
        target_mother = child.get("adoptive_mother") or child.get("birth_mother") or mother_name or ""
        narration = f"你为皇子{child_name}暗中造势，其夺嫡势头+5"
        if target_mother and target_mother != game_state.name:
            game_state.rivalries[target_mother] = game_state.rivalries.get(target_mother, 0) + 15
            if target_mother in game_state.relationships:
                game_state.relationships[target_mother]["好感"] = max(-100, game_state.relationships[target_mother].get("好感", 0) - 8)
            narration += f"。{target_mother}察觉你插手其子储位，心生记恨（摩擦+15）"
            effects["rivalry"] = 15
    elif action == "undermine_heir":
        # 打压某皇子：消耗银两30 + 行动点1，需心计≥50
        if child.get("gender") != "皇子":
            return jsonify({"error": "只可打压皇子", "success": False}), 400
        if not child.get("alive", True):
            return jsonify({"error": "此子已不在人世", "success": False}), 400
        if game_state.attributes.get("心计", 0) < 50:
            return jsonify({"error": "心计不足（需≥50），暗中构陷力有不逮", "success": False}), 400
        if game_state.silver < 30:
            return jsonify({"error": "银两不足，打压需30两", "success": False}), 400
        race = getattr(game_state, "heir_race", None)
        if not (isinstance(race, dict) and race.get("active")):
            return jsonify({"error": "当前并非夺嫡之期，无从打压", "success": False}), 400
        uid = ensure_child_uid(game_state, child)
        if uid not in (race.get("candidates") or []):
            return jsonify({"error": "此皇子尚未参与夺嫡（须年满8岁）", "success": False}), 400
        game_state.silver -= 30
        momentum = race.setdefault("momentum", {})
        if random.random() < 0.30:
            # 阴谋败露
            game_state.attributes["威望"] = max(0, game_state.attributes.get("威望", 0) - 10)
            game_state.attributes["宠爱"] = max(0, game_state.attributes.get("宠爱", 0) - 5)
            effects = {"silver": -30, "威望": -10, "宠爱": -5}
            narration = f"你暗中打压皇子{child_name}，不料阴谋败露！威望-10，宠爱-5"
        else:
            momentum[uid] = max(0, min(100, momentum.get(uid, 0) - 4))
            effects = {"silver": -30, "momentum": -4}
            narration = f"你暗中构陷皇子{child_name}，其夺嫡势头-4，无人察觉"
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
        "heir_race": normalize_heir_race(getattr(game_state, "heir_race", None)),
        "rivalries": game_state.rivalries,
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
        # 共用资格校验（模块三统一归属管理）：年龄/名额/转继次数/位份/皇嗣特权
        verr = validate_ownership_transfer(game_state, child, my_rank_idx, is_orphan=is_orphan)
        if verr:
            return jsonify({"error": verr, "success": False}), 400
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
        # 费用（遗孤减半）
        base_cost = ADOPT_IN_COST_PRINCE if gender == "皇子" else ADOPT_IN_COST
        cost = max(10, base_cost // 2) if is_orphan else base_cost
        if game_state.silver < cost:
            return jsonify({"error": f"银两不足，过继仪式需{cost}两", "success": False}), 400

        # 执行过继（共用归属变更机制，模块三）
        apply_child_ownership_transfer(game_state, child, source_npc=npc, source_index=pos,
                                       mode_label="收养", cost=cost, cost_note=f"过继仪式{cost}两",
                                       from_name=mother_name if not is_orphan else f"遗孤·{mother_name}")

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
        prev = heir_state(game_state)
        deposed = list(prev.get("deposed", []))
        if old and old.get("name"):
            deposed.append({
                "name": old.get("name"),
                "period": heir_period_label(game_state),
                "merit": prev.get("regency_merit", 0),
            })
        game_state.heir_status = normalize_heir_status({"deposed": deposed})
        game_state.heir_consorts = default_heir_consorts()
        message = "📜 皇帝降旨废储，储君之位悬空。" if old else "储君之位本为空悬，无需废立。"
        if old:
            game_state.add_memory(f"📜 {old.get('name','皇子')}被废黜储君之位")
            for c in game_state.children:
                if c.get("name") == old.get("name"):
                    c["mood"] = "低落"
                    c["is_heir"] = False
        return jsonify({
            "success": True,
            "narration": message,
            "heir_status": game_state.heir_status,
            "heir_panel": heir_panel_payload(game_state),
        })

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
    prev_hs = heir_state(game_state)
    hs = normalize_heir_status({
        "deposed": prev_hs.get("deposed", []),
        "heir_id": child_uid_str,
        "heir_name": child.get("name", "皇子"),
        "heir_mother": child.get("birth_mother") or child_mother,
        "established_at": f"建元{game_state.year}年{game_state.month}月",
        "last_event": "册立太子",
    })
    game_state.heir_status = hs
    game_state.heir_consorts = default_heir_consorts()
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
    # 立储即尝试激活监国（未及岁数则只给提示）
    regency_msgs = heir_activate_regency(game_state, reason="册立太子")
    narration = message
    if regency_msgs:
        narration += "\n" + "\n".join(regency_msgs)
    return jsonify({
        "success": True,
        "narration": narration,
        "heir_status": game_state.heir_status,
        "heir_panel": heir_panel_payload(game_state),
        "regency_messages": regency_msgs,
        "child": child,
        "attributes": game_state.attributes,
    })

# ============================================================
#  太子系统 API：储君面板 / 监国进言 / 事件处置 / 微服私访 / 选妃
# ============================================================

@app.route('/api/heir/state', methods=['GET'])
def heir_state_api():
    """只读查询储君面板（监国 / 成长 / 内宅）。"""
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    return jsonify({"success": True, **heir_panel_payload(game_state)})


@app.route('/api/heir/regency', methods=['POST'])
def heir_regency_advise():
    """向监国太子进言。choice: 'A' / 'B'。

    进言成功率 = 50% 基线
        + 20%（宠爱 ≥ 60）
        + 10%（威望 ≥ 60）
        + 5%（心计 ≥ 60）
        + 10%（太子亲近 ≥ 70）
    成功则按你选的项落定，失败则太子仍按自己的倾向批红。每旬限一次。
    """
    data = request.get_json() or {}
    player_id = data.get('player_id')
    choice_key = (data.get('choice') or '').strip().upper()
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)

    hs = heir_state(game_state)
    if not hs.get("heir_id"):
        return jsonify({"success": False, "error": "储君之位空悬，无从进言"}), 400
    if not hs.get("regency_active"):
        return jsonify({"success": False, "error": "太子尚未监国听政"}), 400
    event = hs.get("pending_regency_event")
    if not isinstance(event, dict):
        return jsonify({"success": False, "error": "东宫本旬并无待议政务"}), 400
    choices = event.get("choices") or {}
    if choice_key not in choices:
        return jsonify({"success": False, "error": "请择定一项进言"}), 400

    period_now = chonghua_period_key(game_state)
    if hs.get("last_regency_input") == period_now:
        return jsonify({"success": False, "error": "本旬你已进言一次，政事不可反复"}), 400

    attrs = game_state.attributes
    rate = 0.50
    breakdown = ["基线50%"]
    if attrs.get("宠爱", 0) >= 60:
        rate += 0.20
        breakdown.append("圣宠+20%")
    if attrs.get("威望", 0) >= 60:
        rate += 0.10
        breakdown.append("威望+10%")
    if attrs.get("心计", 0) >= 60:
        rate += 0.05
        breakdown.append("心计+5%")
    try:
        affection = int(hs.get("heir_affection", 50) or 50)
    except (TypeError, ValueError):
        affection = 50
    if affection >= 70:
        rate += 0.10
        breakdown.append("母子亲厚+10%")
    rate = min(0.95, rate)

    accepted = random.random() < rate
    hs["last_regency_input"] = period_now
    hs["pending_regency_event"] = None
    heir_name = hs.get("heir_name") or "太子"

    if accepted:
        final_key = choice_key
        final_choice = dict(choices[choice_key])
        # 进言被采纳，母子亲近略增
        final_choice["affection"] = int(final_choice.get("affection", 0) or 0) + 3
        lead = f"🖋️ {heir_name}听罢沉吟片刻，依你所言批了红：「{choices[choice_key].get('text','')}」"
    else:
        final_key, auto_choice = heir_auto_decide(game_state, event)
        final_choice = dict(auto_choice) if auto_choice else None
        if final_choice:
            # 逆你之意，亲近略降
            final_choice["affection"] = int(final_choice.get("affection", 0) or 0) - 2
        lead = (f"🖋️ {heir_name}听完只道「儿臣自有主张」，仍按己意批红："
                f"「{(final_choice or {}).get('text','')}」")

    if not final_choice:
        return jsonify({"success": False, "error": "政务选项异常"}), 400

    notes, summary = heir_apply_choice(game_state, final_choice)
    narration = lead
    if notes:
        narration += "（" + "，".join(notes) + "）"
    game_state.add_memory(narration)
    heir_log_push(hs, "regency_events", {
        "period": heir_period_label(game_state),
        "event_id": event.get("id"),
        "title": event.get("category", "政务"),
        "decided_by": "从谏" if accepted else "太子自决",
        "choice": final_choice.get("text", ""),
        "detail": narration,
    })
    autosave_session(player_id)
    return jsonify({
        "success": True,
        "accepted": accepted,
        "rate": round(rate, 3),
        "rate_breakdown": breakdown,
        "choice_key": final_key,
        "narration": narration,
        "changes": notes,
        "summary": summary,
        "attributes": game_state.attributes,
        **heir_panel_payload(game_state),
    })


@app.route('/api/heir/event', methods=['POST'])
def heir_event_resolve():
    """处置太子叛逆 / 危机 / 不孝事件。choice: 'A' / 'B'。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    choice_key = (data.get('choice') or '').strip().upper()
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)

    hs = heir_state(game_state)
    event = hs.get("pending_heir_event")
    if not isinstance(event, dict):
        return jsonify({"success": False, "error": "东宫眼下并无待处置之事"}), 400
    choices = event.get("choices") or {}
    if choice_key not in choices:
        return jsonify({"success": False, "error": "请择定一项处置"}), 400

    choice = choices[choice_key]
    hs["pending_heir_event"] = None
    notes, summary = heir_apply_choice(game_state, choice)
    narration = f"「{event.get('name', '东宫之事')}」你选择了：{choice.get('text', '')}。{choice.get('detail', '')}"
    if notes:
        narration += "（" + "，".join(notes) + "）"
    game_state.add_memory(narration)
    heir_log_push(hs, "heir_event_log", {
        "period": heir_period_label(game_state),
        "event_id": event.get("id"),
        "kind": event.get("kind", ""),
        "title": event.get("name", ""),
        "decided_by": "你",
        "choice": choice.get("text", ""),
        "detail": narration,
    })
    if event.get("kind") == "defiance":
        heir_log_push(hs, "defiance_log", {
            "period": heir_period_label(game_state),
            "stage": event.get("stage"),
            "title": event.get("name", ""),
            "choice": choice.get("text", ""),
            "detail": narration,
        })
    autosave_session(player_id)
    return jsonify({
        "success": True,
        "narration": narration,
        "changes": notes,
        "summary": summary,
        "attributes": game_state.attributes,
        **heir_panel_payload(game_state),
    })

@app.route('/api/progeny/urge', methods=['POST'])
def progeny_urge():
    """催皇嗣生子：耗银 + 行动点，提升指定婚配对象当旬受孕概率。
    scope: heir(东宫内宅，需 target=成员名) / prince / princess。
    """
    data = request.get_json() or {}
    player_id = data.get('player_id')
    scope = (data.get('scope') or '').strip()
    child_uid = data.get('child_uid')
    target = (data.get('target') or '').strip()
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)
    if game_state.silver < PROGENY_URGE_COST:
        return jsonify({"success": False, "error": f"银两不足，催生需{PROGENY_URGE_COST}两"}), 400

    holder = None
    parent_name = ""
    consort_name = ""
    child = None
    if scope == 'heir':
        hs = heir_state(game_state)
        if not hs.get("heir_id"):
            return jsonify({"success": False, "error": "储君之位空悬，无东宫可催"}), 400
        heir_child = get_heir_child(game_state)
        parent_name = hs.get("heir_name") or (heir_child.get("name") if heir_child else "太子")
        if not target:
            return jsonify({"success": False, "error": "请指定东宫内宅成员"}), 400
        for m in heir_consort_members(game_state):
            if m.get("name") == target:
                holder = m
                break
        if holder is None:
            return jsonify({"success": False, "error": "东宫内宅并无此人"}), 400
        consort_name = holder.get("name", "内眷")
    else:
        if scope == 'prince':
            _idx, c = find_player_prince(game_state, child_uid)
            if c is None or c.get("marriage_status") not in ("已婚", "已娶"):
                return jsonify({"success": False, "error": "未找到已大婚的皇子"}), 404
            parent_name = c.get("name", "皇子")
            consort_name = (c.get("consort") or {}).get("name", "正妃")
        elif scope == 'princess':
            _idx, c = find_player_princess(game_state, child_uid)
            if c is None or c.get("marriage_status") not in ("已嫁", "和亲"):
                return jsonify({"success": False, "error": "未找到已出降的公主"}), 404
            parent_name = c.get("name", "公主")
            consort_name = (c.get("consort") or {}).get("name", "驸马")
        else:
            return jsonify({"success": False, "error": "未知的催生对象"}), 400
        child = c
        ensure_child_fields(c)
        consort = ensure_offspring_fields(c.get("consort"))
        if not isinstance(consort, dict):
            return jsonify({"success": False, "error": "该婚配对象状态异常"}), 400
        holder = consort

    # 校验：已怀孕 / 产后休养 / 本旬已催 则不可催
    if holder.get("is_pregnant"):
        return jsonify({"success": False, "error": f"{consort_name}已有身孕，不必催生"}), 400
    if int(holder.get("postpartum_cooldown", 0) or 0):
        return jsonify({"success": False, "error": f"{consort_name}产后尚需静养，不宜催生"}), 400
    if int(holder.get("conceive_boost", 0) or 0):
        return jsonify({"success": False, "error": "本旬已为此人催生，且待下旬"}), 400

    game_state.silver -= PROGENY_URGE_COST
    holder["conceive_boost"] = 1
    holder["urged_this_period"] = True
    if "favor" in holder:
        try:
            holder["favor"] = min(100, int(holder.get("favor", 50) or 50) + random.randint(1, 3))
        except (TypeError, ValueError):
            holder["favor"] = 52
    narration = (f"🍼 你赐下补品、遣太医诊脉，着人尽心照拂，{parent_name}之"
                 f"{consort_name}承雨露之恩，本旬有望受孕")
    game_state.add_memory(narration)

    if scope == 'heir':
        heir_log_push(hs, "consort_events", {
            "period": heir_period_label(game_state),
            "title": "催皇嗣生",
            "choice": consort_name,
            "detail": narration,
        }, limit=10)
        autosave_session(player_id)
        return jsonify({"success": True, "message": narration,
                        "silver": game_state.silver,
                        **heir_panel_payload(game_state)})
    # prince / princess
    c.setdefault("marriage_events", []).insert(0, narration)
    add_child_event(c, narration)
    autosave_session(player_id)
    return jsonify({
        "success": True, "message": narration,
        "silver": game_state.silver,
        "consort": serialize_offspring_holder(holder),
        "prince": prince_serialize(game_state, c) if scope == 'prince' else None,
        "princess": princess_serialize(game_state, c) if scope == 'princess' else None,
        **heir_panel_payload(game_state),
    })


@app.route('/api/heir/incognito', methods=['POST'])
def heir_incognito():
    """陪太子微服私访。耗银 30 两 + 1 行动点，必定触发一条市井奇遇。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)

    hs = heir_state(game_state)
    if not hs.get("heir_id"):
        return jsonify({"success": False, "error": "储君之位空悬，无人可陪你出宫"}), 400
    child = get_heir_child(game_state)
    if not child or not child.get("alive", True):
        return jsonify({"success": False, "error": "太子不在，无法出宫"}), 400
    ensure_child_fields(child)
    try:
        age = float(child.get("age", 0) or 0)
    except (TypeError, ValueError):
        age = 0
    if age < HEIR_REBELLION_MIN_AGE:
        return jsonify({"success": False, "error": f"太子年方{int(age)}，尚不宜出宫涉险"}), 400
    if game_state.silver < HEIR_INCOGNITO_COST:
        return jsonify({"success": False, "error": f"银两不足，出宫打点需{HEIR_INCOGNITO_COST}两"}), 400
    if game_state.remaining_actions < HEIR_INCOGNITO_ACTION:
        return jsonify({"success": False, "error": "本旬行动点不足"}), 400

    game_state.silver -= HEIR_INCOGNITO_COST
    game_state.remaining_actions -= HEIR_INCOGNITO_ACTION

    event = generate_incognito_adventure()
    notes, summary = heir_apply_choice(game_state, event)
    narration = (f"🏮 你与{hs.get('heir_name') or '太子'}换了便装出宫，遇上「{event.get('name')}」。"
                 f"{event.get('description', '')}{event.get('result', '')}")
    detail = f"出宫打点耗银{HEIR_INCOGNITO_COST}两"
    if notes:
        detail += "，" + "，".join(notes)
    narration += f"（{detail}）"
    game_state.add_memory(narration)
    heir_log_push(hs, "heir_event_log", {
        "period": heir_period_label(game_state),
        "event_id": event.get("id"),
        "kind": "incognito",
        "title": event.get("name", ""),
        "decided_by": "你",
        "detail": narration,
    })
    autosave_session(player_id)
    return jsonify({
        "success": True,
        "event": event,
        "narration": narration,
        "changes": notes,
        "summary": summary,
        "silver": game_state.silver,
        "attributes": game_state.attributes,
        **heir_panel_payload(game_state),
    })


@app.route('/api/heir/consort', methods=['POST'])
def heir_consort_api():
    """东宫内宅操作。

    action:
        'select'  —— 择定太子妃（candidate 传姓名）
        'resolve' —— 处置内宅事件（choice 传 'A' / 'B'）
        'fill'    —— 依例添置侧室（count 可选，默认 1-2 人）
    """
    data = request.get_json() or {}
    player_id = data.get('player_id')
    action = (data.get('action') or 'select').strip()
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not ok:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)

    hs = heir_state(game_state)
    if not hs.get("heir_id"):
        return jsonify({"success": False, "error": "储君之位空悬，东宫无内宅可言"}), 400
    hc = heir_consorts_state(game_state)

    # ---- 择定太子妃 ----
    if action == 'select':
        selection = hs.get("consort_selection")
        if not isinstance(selection, dict):
            return jsonify({"success": False, "error": "眼下并无待选名册"}), 400
        if isinstance(hc.get("太子妃"), dict):
            return jsonify({"success": False, "error": "太子妃已册，不可轻易更立"}), 400
        cand_name = (data.get('candidate') or '').strip()
        candidate = find_consort_candidate(cand_name)
        if not candidate:
            return jsonify({"success": False, "error": "名册上并无此人"}), 400

        member = heir_consort_add(
            game_state, "太子妃",
            name=candidate.get("name"),
            family=candidate.get("family", ""),
            personality=candidate.get("personality", ""),
            favor=70,
            faction=candidate.get("faction", ""),
            fun_tag=candidate.get("fun_tag", ""),
            talent=candidate.get("talent"),
            looks=candidate.get("looks"),
            ruling_style=candidate.get("ruling_style"),
        )
        if not member:
            return jsonify({"success": False, "error": "册立未成，内宅编制有异"}), 400

        hs["consort_selection"] = None
        hs["heir_consort"] = member.get("name")
        # 太子妃出身定调治国倾向
        style = candidate.get("ruling_style")
        if style:
            hs["heir_ruling_style"] = style
        # 贤明与和睦起手加成
        heir_clamp_merit(hs, int(candidate.get("style_bonus", 0) or 0))
        heir_clamp_harmony(hs, 5)
        # 朝堂派系好感联动
        favor_map = normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None))
        for faction, delta in (candidate.get("faction_bonus") or {}).items():
            if faction in favor_map:
                favor_map[faction] = max(0, min(100, int(favor_map[faction]) + int(delta)))
        game_state.court_faction_favor = favor_map
        # 首批侧室随册入宫
        added = heir_consort_fill(game_state, count=random.randint(1, 3))

        narration = (f"💐 你为{hs.get('heir_name') or '太子'}择定{member['name']}为太子妃"
                     f"（{candidate.get('faction', '')}·{candidate.get('ruling_style', '')}）。"
                     f"{candidate.get('flavor', '')}")
        if added:
            narration += "礼部随即依例添置内眷：" + "、".join(f"{m['name']}（{m['rank']}）" for m in added) + "。"
        game_state.add_memory(narration)
        heir_log_push(hs, "consort_events", {
            "period": heir_period_label(game_state),
            "title": "册立太子妃",
            "choice": member["name"],
            "detail": narration,
        }, limit=10)
        autosave_session(player_id)
        return jsonify({
            "success": True,
            "narration": narration,
            "consort": member,
            "new_members": added,
            "court_faction_favor": favor_map,
            **heir_panel_payload(game_state),
        })

    # ---- 处置内宅事件 ----
    if action == 'resolve':
        event = hs.get("pending_consort_event")
        if not isinstance(event, dict):
            return jsonify({"success": False, "error": "内宅眼下并无待决之事"}), 400
        options = event.get("options") or event.get("choices") or {}
        choice_key = (data.get('choice') or '').strip().upper()
        if choice_key not in options:
            return jsonify({"success": False, "error": "请择定一项处置"}), 400
        choice = options[choice_key]
        hs["pending_consort_event"] = None
        notes, summary = heir_apply_choice(game_state, choice)
        # 部分趣味事件会带来新成员（如宫女晋为奉仪）
        new_member = None
        if choice.get("new_member") in HEIR_CONSORT_RANKS:
            new_member = heir_consort_add(game_state, choice["new_member"])
        narration = f"🏮 「{event.get('name', '内宅之事')}」你选择了：{choice.get('text', '')}。{choice.get('detail', '')}"
        if new_member:
            narration += f"（{new_member['name']}自此列入{new_member['rank']}）"
        if notes:
            narration += "（" + "，".join(notes) + "）"
        game_state.add_memory(narration)
        heir_log_push(hs, "consort_events", {
            "period": heir_period_label(game_state),
            "event_id": event.get("id"),
            "title": event.get("name", ""),
            "decided_by": "你",
            "choice": choice.get("text", ""),
            "detail": narration,
        }, limit=10)
        autosave_session(player_id)
        return jsonify({
            "success": True,
            "narration": narration,
            "changes": notes,
            "summary": summary,
            "new_member": new_member,
            "attributes": game_state.attributes,
            **heir_panel_payload(game_state),
        })

    # ---- 依例添置侧室 ----
    if action == 'fill':
        if not isinstance(hc.get("太子妃"), dict):
            return jsonify({"success": False, "error": "太子妃未册，侧室不得先入东宫"}), 400
        if heir_consort_total(game_state) >= HEIR_CONSORT_MAX_TOTAL:
            return jsonify({"success": False, "error": f"东宫内宅已满{HEIR_CONSORT_MAX_TOTAL}人，不宜再添"}), 400
        try:
            count = max(1, min(3, int(data.get('count') or random.randint(1, 2))))
        except (TypeError, ValueError):
            count = 1
        added = heir_consort_fill(game_state, count=count)
        if not added:
            return jsonify({"success": False, "error": "各位份均已满编，无从添置"}), 400
        narration = "🎐 东宫依例添置内眷：" + "、".join(f"{m['name']}（{m['rank']}）" for m in added)
        autosave_session(player_id)
        return jsonify({
            "success": True,
            "narration": narration,
            "new_members": added,
            **heir_panel_payload(game_state),
        })

    return jsonify({"success": False, "error": "未知的内宅操作"}), 400


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
# ============================================================
#  重华宫（皇嗣共育之所）
# ============================================================

CHONGHUA_PALACE_NAME = '重华宫'
# 统管全宫（可处置他人皇嗣）：皇后本人或受命协理六宫者。
# 贵妃/皇贵妃只可「查阅」全宫名册，不可处置他人皇嗣（见 chonghua_permission）。
CHONGHUA_MANAGE_RANKS = ['皇后']
CHONGHUA_VIEW_MIN_RANK = '贵妃'
CHONGHUA_MIN_PRESTIGE = 80
CHONGHUA_FOUND_COST = 200
CHONGHUA_UPGRADE_BASE = 300
CHONGHUA_MAX_LEVEL = 5
CHONGHUA_PER_LEVEL_CAPACITY = 3
CHONGHUA_AUTO_ADMIT_AGE = 3        # ≤此岁的皇嗣转旬时自动入馆
CHONGHUA_GRADUATE_AGE = 15         # ≥此岁的皇嗣转旬时学成出馆
CHONGHUA_UPKEEP_PER_CHILD = 8      # 每名在馆皇嗣每旬用度
CHONGHUA_TUTOR_COST = 20           # 授业束脩基数（按已授次数递增）
CHONGHUA_TUTOR_MIN_AGE = 4         # 可受业最低年龄
CHONGHUA_TUTOR_MAX_LEVEL = 10      # 授业上限
CHONGHUA_ADOPT_PRESTIGE = 10       # 首次亲养他人皇嗣的威望奖赏


def chonghua_state(game_state):
    """获取并归一化重华宫状态，保证字段齐全。"""
    ch = getattr(game_state, 'chonghua', None)
    if not isinstance(ch, dict):
        ch = {}
    ch.setdefault('founded', False)
    ch.setdefault('level', 1)
    ch.setdefault('budget', 0)
    ch.setdefault('stipend', 0)        # 皇帝每月固定拨发的用度（主控自行填写）
    ch.setdefault('stipend_period', None)  # 上次发放月俸的「年-月」标记，防同月重复发放
    ch.setdefault('children', [])
    ch.setdefault('log', [])
    ch.setdefault('events', [])
    ch.setdefault('arrears', 0)        # 累计欠用度旬数
    ch.setdefault('tutored', {})       # {uid: 本旬已授业的旬标记}
    # 兼容旧存档：children 曾保存子嗣字典，统一收敛为 uid 字符串列表
    normalized = []
    for item in ch.get('children') or []:
        uid = item.get('uid') if isinstance(item, dict) else item
        if uid is None or uid == '':
            continue
        uid = str(uid)
        if uid not in normalized:
            normalized.append(uid)
    ch['children'] = normalized
    # 兼容旧存档：log 曾保存纯字符串
    ch['log'] = [x if isinstance(x, dict) else {'msg': str(x), 'time': 0}
                 for x in (ch.get('log') or [])]
    game_state.chonghua = ch
    return ch


def chonghua_add_log(game_state, ch, msg):
    ch.setdefault('log', []).append({'msg': msg, 'time': getattr(game_state, 'day', 0)})
    if len(ch['log']) > 50:
        ch['log'] = ch['log'][-50:]


def chonghua_rank_name(game_state):
    try:
        return game_state.rank.name if hasattr(game_state.rank, 'name') else str(game_state.rank)
    except Exception:
        return ''


def chonghua_permission(game_state):
    """重华宫权限分级。

    'full' —— 皇后本人或受命协理六宫者：可查阅并处置全宫皇嗣（收容/亲养/授业/迁出）。
    'view' —— 贵妃及以上：可查阅全宫在馆名册，但只可处置自己膝下皇嗣。
    'own'  —— 其余位份：只见自己的皇嗣。
    """
    if get_queen_name(game_state, include_player=True) == game_state.name:
        return 'full'
    if _get_six_palace_assistant(game_state) == game_state.name:
        return 'full'
    rank_name = chonghua_rank_name(game_state)
    if rank_name in CHONGHUA_MANAGE_RANKS:
        return 'full'
    if getattr(game_state, 'manage_six_palaces', False):
        return 'full'
    if RANK_LEVELS.get(rank_name, -1) >= RANK_LEVELS.get(CHONGHUA_VIEW_MIN_RANK, 99):
        return 'view'
    return 'own'


def chonghua_can_manage_all(game_state):
    """是否可处置他人皇嗣（仅 'full' 权限）。"""
    return chonghua_permission(game_state) == 'full'


def chonghua_can_see_all(game_state, perm=None):
    """是否可查阅全宫皇嗣名册（'full' 与 'view' 均可）。"""
    return (perm or chonghua_permission(game_state)) in ('full', 'view')


def chonghua_is_inside(child):
    return bool(child.get('in_chonghua')) or child.get('palace') == CHONGHUA_PALACE_NAME


def chonghua_collect_children(game_state, can_see_all):
    """汇总可见的存活子嗣。返回 [(owner_name, owner_type, index, child), ...]"""
    entries = []
    for idx, c in enumerate(getattr(game_state, 'children', []) or []):
        if not isinstance(c, dict) or not c.get('alive', True):
            continue
        entries.append((game_state.name, 'player', idx, c))
    if can_see_all:
        for name, npc in (getattr(game_state, 'npcs', {}) or {}).items():
            if not isinstance(npc, dict) or name == game_state.name or name == '太后':
                continue
            for idx, c in enumerate(npc.get('children', []) or []):
                if not isinstance(c, dict) or not c.get('alive', True):
                    continue
                entries.append((name, 'npc', idx, c))
    return entries


def chonghua_collect_all_children(game_state):
    """无视权限，汇总全宫存活子嗣——用于容量与用度等全局结算。"""
    entries = []
    for idx, c in enumerate(getattr(game_state, 'children', []) or []):
        if isinstance(c, dict) and c.get('alive', True):
            entries.append((game_state.name, 'player', idx, c))
    for name, npc in (getattr(game_state, 'npcs', {}) or {}).items():
        if not isinstance(npc, dict) or name == game_state.name or name == '太后':
            continue
        for idx, c in enumerate(npc.get('children', []) or []):
            if isinstance(c, dict) and c.get('alive', True):
                entries.append((name, 'npc', idx, c))
    return entries


def chonghua_capacity(ch):
    try:
        level = int(ch.get('level', 1) or 1)
    except (TypeError, ValueError):
        level = 1
    return max(1, min(CHONGHUA_MAX_LEVEL, level)) * CHONGHUA_PER_LEVEL_CAPACITY


def chonghua_upgrade_cost(ch):
    try:
        level = int(ch.get('level', 1) or 1)
    except (TypeError, ValueError):
        level = 1
    return CHONGHUA_UPGRADE_BASE * max(1, level)


def chonghua_period_key(game_state):
    """一旬的唯一标记，用于「每旬限一次」类限制。"""
    return f'{getattr(game_state, "year", 0)}-{getattr(game_state, "month", 0)}-{getattr(game_state, "day", 0)}'


def chonghua_since_label(game_state):
    return f'{getattr(game_state, "year", 0)}年{getattr(game_state, "month", 0)}月'


def chonghua_upkeep_due(game_state, ch=None):
    """本旬应付用度 = 在馆人数 × 每人用度。"""
    inside = sum(1 for _o, _t, _i, c in chonghua_collect_all_children(game_state)
                 if chonghua_is_inside(c))
    return inside * CHONGHUA_UPKEEP_PER_CHILD


def chonghua_admit_child(game_state, ch, child, reason='入馆'):
    """将子嗣置入在馆状态并登记名册。调用方负责校验容量与权限。"""
    child['in_chonghua'] = True
    child['palace'] = CHONGHUA_PALACE_NAME
    child['chonghua_since'] = chonghua_since_label(game_state)
    uid = ensure_child_uid(game_state, child)
    if uid not in ch['children']:
        ch['children'].append(uid)
    chonghua_add_log(game_state, ch, f'{child.get("name") or "皇嗣"}{reason}')
    return uid


def chonghua_remove_child(game_state, ch, child):
    """解除在馆状态并从名册摘除。"""
    uid = ensure_child_uid(game_state, child)
    child['in_chonghua'] = False
    if child.get('palace') == CHONGHUA_PALACE_NAME:
        child['palace'] = ''
    child.pop('chonghua_since', None)
    if uid in ch['children']:
        ch['children'].remove(uid)
    (ch.get('tutored') or {}).pop(uid, None)
    return uid


def chonghua_sync_roster(game_state, ch):
    """按全宫（非仅可见）在馆子嗣重建名册，避免低权限查询把名册截断。"""
    roster = []
    for _owner, _otype, _idx, c in chonghua_collect_all_children(game_state):
        if chonghua_is_inside(c):
            uid = ensure_child_uid(game_state, c)
            if uid not in roster:
                roster.append(uid)
    ch['children'] = roster
    tutored = ch.get('tutored')
    if isinstance(tutored, dict):
        ch['tutored'] = {k: v for k, v in tutored.items() if k in roster}
    return roster


def chonghua_period_tick(game_state):
    """转旬结算：学成出馆 → 自动收容 → 用度支给 → 在馆教养收益。

    返回可播报的消息列表。仅在重华宫已开设时产生效果。
    """
    ch = chonghua_state(game_state)
    if not ch.get('founded'):
        chonghua_sync_roster(game_state, ch)
        return []

    msgs = []
    ch['tutored'] = {}
    entries = chonghua_collect_all_children(game_state)

    # 0) 用度已与内务府合并：重华宫不再设独立预算，月俸（皇帝拨用度）已取消，
    #    每旬在馆抚养费统一由下方第3节从内务府库银自动扣取。

    # 1) 学成出馆：年满则迁出，交回生母/养母
    for owner, _otype, _idx, c in entries:
        if not chonghua_is_inside(c):
            continue
        try:
            age = float(c.get('age', 0) or 0)
        except (TypeError, ValueError):
            age = 0
        if age >= CHONGHUA_GRADUATE_AGE:
            name = c.get('name') or '皇嗣'
            chonghua_remove_child(game_state, ch, c)
            if not c.get('guardian'):
                c['guardian'] = c.get('adoptive_mother') or c.get('birth_mother') or owner
            msg = f'🎓 {name}年已{int(age)}，自重华宫学成出馆'
            msgs.append(msg)
            chonghua_add_log(game_state, ch, f'{name}学成出馆')

    # 2) 自动收容：嫔位以下且无监护人的年幼皇嗣（≤CHONGHUA_AUTO_ADMIT_AGE）入馆
    capacity = chonghua_capacity(ch)
    inside = sum(1 for _o, _t, _i, c in entries if chonghua_is_inside(c))
    for owner, _otype, _idx, c in entries:
        if inside >= capacity:
            break
        if chonghua_is_inside(c) or c.get('guardian'):
            continue
        try:
            age = float(c.get('age', 0) or 0)
        except (TypeError, ValueError):
            age = 0
        if age > CHONGHUA_AUTO_ADMIT_AGE:
            continue
        # 仅嫔位以下生母所出才自动送入
        mother_name = c.get('birth_mother') or owner
        mother_rank = ''
        if mother_name == game_state.name:
            mother_rank = chonghua_rank_name(game_state)
        else:
            npc = (game_state.npcs or {}).get(mother_name)
            if isinstance(npc, dict):
                mother_rank = normalize_rank_name(npc.get('rank', ''))
        if RANK_LEVELS.get(mother_rank, 99) >= RANK_LEVELS.get('嫔', 0):
            continue
        chonghua_admit_child(game_state, ch, c, '自动入馆')
        msgs.append(f'🏛️ {c.get("name") or "皇嗣"}生母位卑，已入重华宫共育')
        inside += 1

    # 3) 用度支给：用度已与内务府合并，每旬在馆抚养费直接从内务府库银扣取；
    #    库银不足则欠饷，连欠三旬有皇嗣被生母领回
    due = inside * CHONGHUA_UPKEEP_PER_CHILD
    if due > 0:
        ip_d = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
        game_state.inner_palace = ip_d
        ip_budget = int(ip_d.get('budget', 0) or 0)
        if ip_budget >= due:
            ip_d['budget'] = ip_budget - due
            ch['arrears'] = 0
            chonghua_add_log(game_state, ch, f'本旬俸给{due}两（内务府划拨）')
            # 记录内务府记事
            try:
                from inner_palace_system import _ip_log
                _ip_log(ip_d, f'拨重华宫用度{due}两')
            except Exception:
                pass
        else:
            short = due - ip_budget
            ip_d['budget'] = 0
            ch['arrears'] = int(ch.get('arrears', 0) or 0) + 1
            msgs.append(f'💸 重华宫用度短缺{short}两，膳食减半，皇嗣颇有怨言（已欠{ch["arrears"]}旬）')
            chonghua_add_log(game_state, ch, f'用度短缺{short}两')
            for _owner, _otype, _idx, c in entries:
                if not chonghua_is_inside(c):
                    continue
                c['health'] = max(20, int(c.get('health', 70) or 70) - random.randint(1, 3))
                c['affection'] = max(5, int(c.get('affection', 30) or 30) - random.randint(1, 2))
            if ch['arrears'] >= 3:
                pool = [(o, c) for o, _t, _i, c in entries if chonghua_is_inside(c)]
                if pool:
                    owner, c = random.choice(pool)
                    name = c.get('name') or '皇嗣'
                    chonghua_remove_child(game_state, ch, c)
                    c['guardian'] = c.get('adoptive_mother') or c.get('birth_mother') or owner
                    ch['arrears'] = 0
                    msg = f'🕯️ 重华宫久欠用度，{name}被{c["guardian"]}领回自养，宫中物议'
                    msgs.append(msg)
                    chonghua_add_log(game_state, ch, f'{name}因欠用度被领回')
                    game_state.attributes['威望'] = max(0, game_state.attributes.get('威望', 0) - 3)
    else:
        ch['arrears'] = 0

    # 4) 在馆教养收益 & 五岁以上自动开蒙
    level = max(1, min(CHONGHUA_MAX_LEVEL, int(ch.get('level', 1) or 1)))
    if not ch.get('arrears'):
        for _owner, _otype, _idx, c in entries:
            if not chonghua_is_inside(c):
                continue
            try:
                age = float(c.get('age', 0) or 0)
            except (TypeError, ValueError):
                age = 0
            # 五岁以上自动安排开蒙（tutor_level 至少为1）
            if age >= 5 and int(c.get('tutor_level', 0) or 0) < 1:
                c['tutor_level'] = 1
                name = c.get('name') or '皇嗣'
                msgs.append(f'📖 {name}年满五岁，已安排开蒙授业')
                chonghua_add_log(game_state, ch, f'{name}开蒙')
            c['talent'] = min(100, int(c.get('talent', 50) or 50) + random.randint(0, level))
            c['wit'] = min(100, int(c.get('wit', 40) or 40) + random.randint(0, max(1, level - 1)))
            c['health'] = min(100, int(c.get('health', 70) or 70) + random.randint(0, 1))

    # 5) 宫中轶事：偶发一条在馆动态
    if inside > 0 and random.random() < 0.35:
        pool = [c for _o, _t, _i, c in entries if chonghua_is_inside(c)]
        c = random.choice(pool)
        name = c.get('name') or '皇嗣'
        flavor = random.choice([
            f'📖 重华宫师傅称{name}读书用心，字有筋骨',
            f'🎋 {name}在重华宫庭中习射，颇得众师称许',
            f'🍬 {name}与馆中同侪争一枚蜜饯，闹作一团，被师傅罚抄书',
            f'🌙 {name}夜里想念母妃，抱着枕头哭了半宿',
        ])
        msgs.append(flavor)
        events = ch.setdefault('events', [])
        events.insert(0, {'msg': flavor, 'time': getattr(game_state, 'day', 0)})
        ch['events'] = events[:20]

    chonghua_sync_roster(game_state, ch)
    return msgs


def chonghua_serialize_child(game_state, owner, owner_type, index, child, perm='own'):
    ensure_child_fields(child)
    uid = ensure_child_uid(game_state, child)
    is_own = owner_type == 'player'
    try:
        age = float(child.get('age', 0) or 0)
    except (TypeError, ValueError):
        age = 0
    heir_id = (getattr(game_state, 'heir_status', None) or {}).get('heir_id')
    return {
        'uid': uid,
        'name': child.get('name') or '未命名',
        'age': child.get('age', 0),
        'gender': child.get('gender', ''),
        'in_chonghua': chonghua_is_inside(child),
        'palace': child.get('palace', ''),
        'guardian': child.get('guardian', '') or child.get('adoptive_mother', '') or '',
        'birth_mother': child.get('birth_mother', '') or owner,
        'tutor_level': child.get('tutor_level', 0),
        'talent': child.get('talent', 0),
        'wit': child.get('wit', 0),
        'health': child.get('health', 0),
        'affection': child.get('affection', 0),
        'mood': child.get('mood', ''),
        'is_heir': bool(child.get('is_heir')) or (heir_id and str(heir_id) == uid),
        'since': child.get('chonghua_since', ''),
        'tutored_this_period': uid in (getattr(game_state, 'chonghua', {}) or {}).get('tutored', {}),
        # 可操作性：自己的皇嗣任何位份皆可处置；他人皇嗣仅 full 权限可动
        'can_act': is_own or perm == 'full',
        'can_tutor': (is_own or perm == 'full') and age >= CHONGHUA_TUTOR_MIN_AGE,
        '_mother': owner,
        '_owner_type': owner_type,
        '_index': index,
    }


@app.route('/api/chonghua', methods=['GET'])
def get_chonghua():
    """只读查询：不改动任何状态（自动收容等已移入转旬结算）。"""
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ch = chonghua_state(game_state)
    perm = chonghua_permission(game_state)
    can_manage_all = perm == 'full'
    can_see_all = chonghua_can_see_all(game_state, perm)
    entries = chonghua_collect_children(game_state, can_see_all)

    inside_list = []
    candidate_list = []
    for owner, owner_type, idx, c in entries:
        payload = chonghua_serialize_child(game_state, owner, owner_type, idx, c, perm)
        if payload['in_chonghua']:
            inside_list.append(payload)
        else:
            candidate_list.append(payload)

    # 名册按全宫在馆情况重建（低权限查询不得截断名册）
    chonghua_sync_roster(game_state, ch)
    total_inside = len(ch['children'])

    rank_name = chonghua_rank_name(game_state)
    # 用度已并入内务府：重华宫不再有独立预算，前端显示内务府库银
    ip_snapshot = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
    inner_budget = int(ip_snapshot.get('budget', 0) or 0)
    info = {
        'manage_ranks': CHONGHUA_MANAGE_RANKS,
        'view_min_rank': CHONGHUA_VIEW_MIN_RANK,
        'min_prestige': CHONGHUA_MIN_PRESTIGE,
        'found_cost': CHONGHUA_FOUND_COST,
        'upgrade_cost': chonghua_upgrade_cost(ch),
        'max_level': CHONGHUA_MAX_LEVEL,
        'tutor_cost': CHONGHUA_TUTOR_COST,
        'tutor_min_age': CHONGHUA_TUTOR_MIN_AGE,
        'graduate_age': CHONGHUA_GRADUATE_AGE,
        'auto_admit_age': CHONGHUA_AUTO_ADMIT_AGE,
        'upkeep_per_child': CHONGHUA_UPKEEP_PER_CHILD,
        'upkeep_due': total_inside * CHONGHUA_UPKEEP_PER_CHILD,
        'inner_budget': inner_budget,
        'arrears': int(ch.get('arrears', 0) or 0),
        'permission': perm,
        'has_permission': can_manage_all,
        'rank_name': rank_name,
        'prestige': game_state.attributes.get('威望', 0),
    }
    return jsonify({
        'chonghua': dict(ch),
        'children': inside_list,
        'candidates': candidate_list,
        'capacity': chonghua_capacity(ch),
        'total_inside': total_inside,
        'permission': perm,
        'can_manage_all': can_manage_all,
        'can_see_all': can_see_all,
        'player_name': game_state.name,
        'silver': getattr(game_state, 'silver', 0),
        'inner_budget': inner_budget,
        'inner_palace': ip_snapshot,
        'info': info,
    })

def chonghua_find_child(game_state, uid, can_see_all):
    """按 uid（兼容按名字）查找子嗣，返回 (owner, owner_type, index, child)。"""
    if uid is None or uid == '':
        return None, None, -1, None
    target = str(uid)
    for owner, owner_type, idx, c in chonghua_collect_children(game_state, can_see_all):
        if str(c.get('uid')) == target or c.get('name') == target:
            return owner, owner_type, idx, c
    return None, None, -1, None


def chonghua_count_inside(game_state):
    """全宫在馆人数（容量校验必须用全局值，否则低权限可越过上限）。"""
    return sum(1 for _o, _t, _i, c in chonghua_collect_all_children(game_state)
               if chonghua_is_inside(c))


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
    ensure_ending_fields(game_state)
    if is_game_over(game_state):
        return game_over_response(game_state)
    # 重华宫事务属宫务打理，不消耗行动点
    ch = chonghua_state(game_state)
    perm = chonghua_permission(game_state)
    can_manage_all = perm == 'full'
    can_see_all = chonghua_can_see_all(game_state, perm)

    def add_log(msg):
        chonghua_add_log(game_state, ch, msg)

    def ok(message, extra=None):
        chonghua_sync_roster(game_state, ch)
        autosave_session(player_id)
        payload = {
            'success': True,
            'message': message,
            'chonghua': ch,
            'silver': getattr(game_state, 'silver', 0),
            'attributes': game_state.attributes,
            'capacity': chonghua_capacity(ch),
            'total_inside': len(ch['children']),
            'permission': perm,
        }
        if extra:
            payload.update(extra)
        return jsonify(payload)

    if action == 'found':
        if ch.get('founded'):
            return jsonify({'success': False, 'error': '重华宫已开设'}), 400
        # 只要宫中有皇后即可开设（不要求主控本人是皇后），仍需协理权限或皇后身份主持
        queen_name = get_queen_name(game_state, include_player=True)
        if not queen_name:
            return jsonify({'success': False, 'error': '宫中尚无皇后，无法开设重华宫'}), 400
        if not can_manage_all:
            return jsonify({'success': False, 'error': '重华宫为六宫公器，须皇后或协理六宫者方可开设'}), 403
        if game_state.attributes.get('威望', 0) < CHONGHUA_MIN_PRESTIGE:
            return jsonify({'success': False, 'error': f'威望不足（需≥{CHONGHUA_MIN_PRESTIGE}）'}), 400
        if game_state.silver < CHONGHUA_FOUND_COST:
            return jsonify({'success': False, 'error': f'银两不足（需{CHONGHUA_FOUND_COST}两）'}), 400
        game_state.silver -= CHONGHUA_FOUND_COST
        ch['founded'] = True
        ch['level'] = 1
        ch['budget'] = 0
        ch['arrears'] = 0
        add_log('重华宫开设成功')
        game_state.add_memory('🏛️ 你奏请开设重华宫，皇嗣共育之所自此立起')
        return ok(f'重华宫开设成功，耗费{CHONGHUA_FOUND_COST}两')

    if action == 'upgrade':
        if not ch.get('founded'):
            return jsonify({'success': False, 'error': '重华宫尚未开设'}), 400
        if not can_manage_all:
            return jsonify({'success': False, 'error': '扩建须皇后或协理六宫者主持'}), 403
        level = max(1, int(ch.get('level', 1) or 1))
        if level >= CHONGHUA_MAX_LEVEL:
            return jsonify({'success': False, 'error': f'重华宫已达最高等级（{CHONGHUA_MAX_LEVEL}级）'}), 400
        cost = chonghua_upgrade_cost(ch)
        # 用度已并入内务府，扩建费用直接从内务府库银扣取
        ip_d = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
        game_state.inner_palace = ip_d
        ip_budget = int(ip_d.get('budget', 0) or 0)
        if ip_budget < cost:
            return jsonify({'success': False, 'error': f'内务府库银不足（现存{ip_budget}两，扩建需{cost}两），请先充实内帑'}), 400
        ip_d['budget'] = ip_budget - cost
        ch['level'] = level + 1
        add_log(f'重华宫扩建至等级{ch["level"]}')
        return ok(f'扩建成功，等级提升至{ch["level"]}（容量{chonghua_capacity(ch)}人），从内务府库银扣除{cost}两，余{ip_d["budget"]}两')

    if action == 'patronize' or action == 'set_stipend':
        # 用度已与内务府合并，手动拨用度/定月俸交互已取消
        return jsonify({'success': False, 'error': '重华宫用度已并入内务府，每旬自动从内务府库银划拨，无需手动拨用度'}), 400

    if action not in ('admit', 'tutor', 'adopt', 'release'):
        return jsonify({'success': False, 'error': '未知操作'}), 400

    if not ch.get('founded'):
        return jsonify({'success': False, 'error': '重华宫尚未开设'}), 400

    owner, owner_type, idx, child = chonghua_find_child(game_state, uid, can_see_all)
    if not child:
        return jsonify({'success': False, 'error': '子嗣不存在'}), 404
    ensure_child_fields(child)
    child_uid = ensure_child_uid(game_state, child)
    child_name = child.get('name') or '未命名'
    is_own = (owner_type == 'player')
    if not is_own and not can_manage_all:
        return jsonify({'success': False, 'error': f'你只可查阅名册，处置{owner}的皇嗣须皇后或协理六宫者出面'}), 403
    try:
        child_age = float(child.get('age', 0) or 0)
    except (TypeError, ValueError):
        child_age = 0

    if action == 'admit':
        if chonghua_is_inside(child):
            return jsonify({'success': False, 'error': f'{child_name}已在馆'}), 400
        if child_age >= CHONGHUA_GRADUATE_AGE:
            return jsonify({'success': False, 'error': f'{child_name}已{int(child_age)}岁，年长不必再入馆共育'}), 400
        capacity = chonghua_capacity(ch)
        if chonghua_count_inside(game_state) >= capacity:
            return jsonify({'success': False, 'error': f'重华宫容量已满（{capacity}人），请先扩建'}), 400
        guardian = child.get('guardian') or ''
        if guardian and guardian != game_state.name and not can_manage_all:
            return jsonify({'success': False, 'error': f'{child_name}由{guardian}亲养，不便代为送入'}), 400
        chonghua_admit_child(game_state, ch, child)
        if guardian:
            child['guardian'] = ''
        return ok(f'{child_name}已收容至重华宫')

    if action == 'release':
        if not chonghua_is_inside(child):
            return jsonify({'success': False, 'error': f'{child_name}不在馆'}), 400
        chonghua_remove_child(game_state, ch, child)
        if not child.get('guardian'):
            child['guardian'] = child.get('adoptive_mother') or child.get('birth_mother') or owner
        add_log(f'{child_name}迁出重华宫')
        return ok(f'{child_name}已迁出重华宫，交由{child["guardian"]}抚养')

    if action == 'tutor':
        if not chonghua_is_inside(child):
            return jsonify({'success': False, 'error': f'{child_name}不在馆'}), 400
        if child_age < CHONGHUA_TUTOR_MIN_AGE:
            return jsonify({'success': False, 'error': f'{child_name}年纪尚幼（需满{CHONGHUA_TUTOR_MIN_AGE}岁）'}), 400
        tutor_level = int(child.get('tutor_level', 0) or 0)
        if tutor_level >= CHONGHUA_TUTOR_MAX_LEVEL:
            return jsonify({'success': False, 'error': f'{child_name}已学至{tutor_level}级，师傅无可再教'}), 400
        tutored = ch.setdefault('tutored', {})
        period = chonghua_period_key(game_state)
        if tutored.get(child_uid) == period:
            return jsonify({'success': False, 'error': f'{child_name}本旬已授业，且待下旬'}), 400
        cost = CHONGHUA_TUTOR_COST + tutor_level * 5
        # 用度已并入内务府：束脩优先从内务府库银抵扣，不足再自掏银两
        ip_d = normalize_inner_palace(getattr(game_state, 'inner_palace', None))
        game_state.inner_palace = ip_d
        from_budget = min(int(ip_d.get('budget', 0) or 0), cost)
        need_silver = cost - from_budget
        if game_state.silver < need_silver:
            return jsonify({'success': False, 'error': f'束脩需{cost}两（内务府库银可抵{from_budget}两），银两不足'}), 400
        ip_d['budget'] = int(ip_d.get('budget', 0) or 0) - from_budget
        game_state.silver -= need_silver
        tutored[child_uid] = period
        child['tutor_level'] = tutor_level + 1
        talent_gain = random.randint(2, 5)
        wit_gain = random.randint(1, 4)
        child['talent'] = min(100, int(child.get('talent', 50) or 50) + talent_gain)
        child['wit'] = min(100, int(child.get('wit', 40) or 40) + wit_gain)
        child['emperor_favor'] = min(100, int(child.get('emperor_favor', 30) or 30) + random.randint(0, 2))
        add_child_event(child, f'📖 在重华宫延师授业，才情+{talent_gain}、机敏+{wit_gain}')
        add_log(f'{child_name}授业（束脩{cost}两）')
        source = f'用度支{from_budget}两' + (f'、自付{need_silver}两' if need_silver else '')
        return ok(f'为{child_name}延师授业，才情+{talent_gain}、机敏+{wit_gain}（{source}）',
                  {'child': chonghua_serialize_child(game_state, owner, owner_type, idx, child, perm)})

    # action == 'adopt'：将在馆皇嗣收作己出，交由自己抚养
    if not chonghua_is_inside(child):
        return jsonify({'success': False, 'error': f'{child_name}不在重华宫，无法亲养'}), 400
    existing_guardian = child.get('guardian') or ''
    if existing_guardian and existing_guardian != game_state.name:
        return jsonify({'success': False, 'error': f'{child_name}已由{existing_guardian}抚养'}), 400
    my_rank_idx = RANK_LEVELS.get(chonghua_rank_name(game_state), 0)
    cost = 0
    if not is_own:
        # 亲养他人皇嗣，等同过继：沿用宗人府那套规矩，仅仪银减半（宫中共育，礼从简）
        birth_mother_npc = (getattr(game_state, 'npcs', {}) or {}).get(owner)
        is_orphan = isinstance(birth_mother_npc, dict) and not birth_mother_npc.get('alive', True)
        # 共用资格校验（模块三统一归属管理）：年龄/名额/转继次数/位份/皇嗣特权
        verr = validate_ownership_transfer(game_state, child, my_rank_idx, is_orphan=is_orphan)
        if verr:
            return jsonify({'success': False, 'error': verr}), 400
        # 生母在世且情分浅薄时，未必愿意割舍
        if isinstance(birth_mother_npc, dict) and birth_mother_npc.get('alive', True):
            willingness = adoption_willingness(game_state, birth_mother_npc, child)
            if willingness < 35:
                return jsonify({'success': False, 'error': f'{owner}割舍不下亲子{child_name}，亲养未成'}), 400
        base_cost = ADOPT_IN_COST_PRINCE if child.get('gender') == '皇子' else ADOPT_IN_COST
        cost = max(10, base_cost // 2)
        if is_orphan:
            cost = max(10, cost // 2)
        if game_state.silver < cost:
            return jsonify({'success': False, 'error': f'银两不足，亲养仪需{cost}两'}), 400
        # 共用归属变更机制（模块三；重华宫亲养不调整亲密——共育情分另计）
        apply_child_ownership_transfer(game_state, child, source_npc=birth_mother_npc, source_index=idx,
                                       mode_label='重华宫亲养', cost=cost, cost_note='重华宫共育',
                                       from_name=owner, adjust_affection=False)
        if owner in game_state.relationships:
            game_state.relationships[owner]['好感'] = max(-100, game_state.relationships[owner].get('好感', 0) - random.randint(3, 10))
    chonghua_remove_child(game_state, ch, child)
    child['guardian'] = game_state.name
    gain = CHONGHUA_ADOPT_PRESTIGE if not is_own else 3
    game_state.attributes['威望'] = min(game_state.get_attr_max('威望'),
                                      game_state.attributes.get('威望', 0) + gain)
    add_log(f'{game_state.name}亲养{child_name}')
    verb = '亲养' if is_own else f'自{owner}处亲养'
    game_state.add_memory(f'👶 你{verb}{child_name}，自重华宫接回宫中抚养')
    tail = f'，仪银{cost}两' if cost else ''
    return ok(f'{child_name}已归你抚养，威望+{gain}{tail}')


# ============================================================
#  公主择婿与省亲 · API 路由
# ============================================================

def princess_serialize(game_state, child):
    """公主择婿/婚姻状态序列化，供前端渲染。"""
    ensure_child_fields(child)
    suitors = child.get("suitors") or []
    suitor_views = []
    for s in suitors:
        v = suitor_public_view(s)
        v["court_favor"] = suitor_court_favor_score(game_state, child, s)
        suitor_views.append(v)
    mother_name = child.get("adoptive_mother") or child.get("birth_mother") or ""
    is_own = mother_name == getattr(game_state, "name", "") or child in (getattr(game_state, "children", []) or [])
    decider = princess_marriage_decider(game_state, child)
    return {
        "uid": child.get("uid"),
        "name": child.get("name"),
        "age": int(child.get("age", 0)),
        "marriage_status": child.get("marriage_status", "未议"),
        "preference": child.get("preference"),
        "marriage_authority": child.get("marriage_authority"),
        "marriage_decider": decider,
        "decision_type": emperor_decision_type(game_state, child),
        "suitors": suitor_views,
        "consort": serialize_offspring_holder(child.get("consort")),
        "mansion": child.get("mansion"),
        "marriage_events": (child.get("marriage_events") or [])[:8],
        "prestige_tier": princess_prestige_tier(game_state, child),
        "mother": mother_name,
        "is_own": bool(is_own),
        "must_marry": int(child.get("age", 0)) >= PRINCESS_FORCE_MARRY_AGE and child.get("marriage_status") not in ("已嫁", "和亲"),
        "force_marry_age": PRINCESS_FORCE_MARRY_AGE,
    }



@app.route('/api/princess/list', methods=['GET'])
def princess_list():
    """列出玩家名下所有公主的婚姻信息。"""
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    princesses = []
    seen = set()
    for owner, otype, idx, c in iter_all_princesses(game_state):
        ensure_child_fields(c)
        uid = ensure_child_uid(game_state, c)
        if uid in seen:
            continue
        seen.add(uid)
        princesses.append(princess_serialize(game_state, c))
    return jsonify({
        "princesses": princesses,
        "marry_min_age": PRINCESS_MARRY_MIN_AGE,
        "betroth_cost": BETROTH_COST,
        "marry_cost": MARRY_COST,
        "court_faction_favor": normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None)),
        "factions": COURT_FACTIONS,
    })


@app.route('/api/princess/suitors', methods=['POST'])
def princess_suitors():
    """生成/返回候选驸马（每旬缓存一次，重复请求返回缓存）。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    child_uid = data.get('child_uid')
    refresh = bool(data.get('refresh'))
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)
    idx, child = find_player_princess(game_state, child_uid)
    if child is None:
        return jsonify({"success": False, "error": "未找到该公主"}), 404
    if int(child.get("age", 0)) < PRINCESS_MARRY_MIN_AGE:
        return jsonify({"success": False, "error": f"公主尚未及笄（需满{PRINCESS_MARRY_MIN_AGE}岁）"}), 400
    if child.get("marriage_status") in ("已定", "已嫁", "和亲"):
        return jsonify({"success": False, "error": "公主婚事已定，不必再相看"}), 400
    stamp = period_stamp(game_state)
    if refresh or not child.get("suitors") or child.get("suitors_period") != stamp:
        child["suitors"] = generate_suitors(game_state, child)
        child["suitors_period"] = stamp
    if child.get("marriage_status") == "未议":
        child["marriage_status"] = "议婚中"
    autosave_session(player_id)
    return jsonify({"success": True, "princess": princess_serialize(game_state, child)})

# @@PRINCESS_ROUTES_ANCHOR@@


@app.route('/api/princess/inspect', methods=['POST'])
def princess_inspect():
    """细察某候选驸马，花行动点揭示其野心与隐藏标签。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    child_uid = data.get('child_uid')
    suitor_uid = data.get('suitor_uid')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)
    idx, child = find_player_princess(game_state, child_uid)
    if child is None:
        return jsonify({"success": False, "error": "未找到该公主"}), 404
    suitor = next((s for s in (child.get("suitors") or []) if str(s.get("uid")) == str(suitor_uid)), None)
    if not suitor:
        return jsonify({"success": False, "error": "候选人不存在或已更替"}), 404
    if suitor.get("inspected"):
        return jsonify({"success": True, "message": "已细察过此人", "princess": princess_serialize(game_state, child)})
    if game_state.remaining_actions <= 0:
        return jsonify({"success": False, "error": "行动点不足，请先转旬"}), 400
    game_state.consume_action()
    suitor["inspected"] = True
    autosave_session(player_id)
    return jsonify({
        "success": True,
        "message": f"细察{suitor.get('name')}，其底细已然明了",
        "remaining_actions": game_state.remaining_actions,
        "princess": princess_serialize(game_state, child),
    })


@app.route('/api/princess/authority', methods=['POST'])
def princess_authority():
    """皇帝将某公主的婚事决策权下放给生母/皇后（依宠爱而定）。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    child_uid = data.get('child_uid')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)
    idx, child = find_player_princess(game_state, child_uid)
    if child is None:
        return jsonify({"success": False, "error": "未找到该公主"}), 404
    if child.get("marriage_status") in ("已定", "已嫁", "和亲"):
        return jsonify({"success": False, "error": "婚事已定，无需再请旨"}), 400
    if child.get("marriage_authority"):
        return jsonify({"success": False, "error": "婚事决策权已在你手中"}), 400
    favor = game_state.attributes.get("宠爱", 0)
    if favor < 60:
        return jsonify({"success": False, "error": f"圣宠未浓（需宠爱≥60，当前{favor}），皇帝不愿假手于人"}), 400
    child["marriage_authority"] = game_state.name
    game_state.add_memory(f"👑 皇帝念你宠冠六宫，特许你亲裁{child.get('name')}的婚事")
    autosave_session(player_id)
    return jsonify({
        "success": True,
        "message": f"皇帝已将{child.get('name')}的婚事交由你定夺",
        "princess": princess_serialize(game_state, child),
    })


@app.route('/api/princess/betroth', methods=['POST'])
def princess_betroth():
    """定亲：选定一名候选驸马，写入 consort，marriage_status→已定。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    child_uid = data.get('child_uid')
    suitor_uid = data.get('suitor_uid')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)
    idx, child = find_player_princess(game_state, child_uid)
    if child is None:
        return jsonify({"success": False, "error": "未找到该公主"}), 404
    if int(child.get("age", 0)) < PRINCESS_MARRY_MIN_AGE:
        return jsonify({"success": False, "error": f"公主尚未及笄（需满{PRINCESS_MARRY_MIN_AGE}岁）"}), 400
    if child.get("marriage_status") in ("已定", "已嫁", "和亲"):
        return jsonify({"success": False, "error": "公主婚事已定"}), 400
    suitor = next((s for s in (child.get("suitors") or []) if str(s.get("uid")) == str(suitor_uid)), None)
    if not suitor:
        return jsonify({"success": False, "error": "候选人不存在或已更替"}), 404
    if game_state.silver < BETROTH_COST:
        return jsonify({"success": False, "error": f"银两不足，纳采需{BETROTH_COST}两"}), 400
    game_state.silver -= BETROTH_COST
    child["consort"] = dict(suitor)
    child["marriage_status"] = "已定"
    child["suitors"] = []
    child["suitors_period"] = None
    match = preference_match_score(child, suitor)
    if match < 40:
        child["affection"] = max(0, child.get("affection", 30) - random.randint(2, 6))
        child["mood"] = "闷闷不乐"
    msg = f"💐 你为{child.get('name')}定下驸马{suitor.get('name')}（{suitor.get('faction')}·{suitor.get('father_title')}之子），纳采礼成，耗银{BETROTH_COST}两"
    game_state.add_memory(msg)
    add_child_event(child, msg)
    autosave_session(player_id)
    return jsonify({
        "success": True,
        "message": msg,
        "silver": game_state.silver,
        "princess": princess_serialize(game_state, child),
    })

# @@PRINCESS_ROUTES_ANCHOR2@@


@app.route('/api/princess/marry', methods=['POST'])
def princess_marry():
    """出降：下赐婚圣旨，建立公主府，触发朝堂联动。mode=='和亲' 走番邦和亲分支。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    child_uid = data.get('child_uid')
    mode = data.get('mode', '出降')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)
    idx, child = find_player_princess(game_state, child_uid)
    if child is None:
        return jsonify({"success": False, "error": "未找到该公主"}), 404
    if game_state.silver < MARRY_COST:
        return jsonify({"success": False, "error": f"银两不足，大典需{MARRY_COST}两"}), 400

    if mode == '和亲':
        if child.get("marriage_status") in ("已嫁", "和亲"):
            return jsonify({"success": False, "error": "公主已经出嫁"}), 400
        if int(child.get("age", 0)) < PRINCESS_MARRY_MIN_AGE:
            return jsonify({"success": False, "error": f"公主尚未及笄（需满{PRINCESS_MARRY_MIN_AGE}岁）"}), 400
        game_state.silver -= MARRY_COST
        realm = random.choice(["北狄", "西凉", "南诏", "东瀛", "吐蕃"])
        child["consort"] = {
            "name": f"{realm}王子",
            "faction": "宗室党",
            "father_title": f"{realm}可汗",
            "family_score": random.randint(60, 85),
            "hidden_tags": [],
            "talent": random.randint(40, 80),
            "looks": random.randint(40, 80),
            "age": random.randint(18, 30),
            "ambition": random.randint(40, 90),
        }
        child["marriage_status"] = "和亲"
        child["mansion"] = None
        child["suitors"] = []
        child["suitors_period"] = None
        game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + random.randint(10, 18))
        child["affection"] = max(0, child.get("affection", 30) - random.randint(5, 12))
        child["mood"] = "思念"
        msg = f"🕊️ {child.get('name')}远嫁{realm}和亲，销烟止戈，社稷得安，然骨肉天各一方（威望大增）"
        game_state.add_memory(msg)
        add_child_event(child, msg)
        child.setdefault("marriage_events", []).insert(0, msg)
        autosave_session(player_id)
        return jsonify({
            "success": True, "message": msg,
            "silver": game_state.silver,
            "princess": princess_serialize(game_state, child),
        })

    if child.get("marriage_status") != "已定" or not child.get("consort"):
        return jsonify({"success": False, "error": "尚未定亲，不能下赐婚圣旨"}), 400
    game_state.silver -= MARRY_COST
    child["marriage_status"] = "已嫁"
    child["mansion"] = default_mansion()
    consort = child.get("consort") or {}
    court_notes = apply_marriage_court_effect(game_state, child)
    game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + random.randint(5, 10))
    msg = f"🎊 赐婚圣旨已下，{child.get('name')}出降驸马{consort.get('name')}，凤冠霞帔，十里红妆，耗银{MARRY_COST}两"
    game_state.add_memory(msg)
    add_child_event(child, msg)
    child.setdefault("marriage_events", []).insert(0, msg)
    for note in court_notes:
        game_state.add_memory(note)
    sub = subsidize_princess_mother(game_state, child, occasion="出降")
    if sub:
        game_state.add_memory(sub)
    autosave_session(player_id)
    return jsonify({
        "success": True, "message": msg,
        "court_notes": court_notes,
        "subsidy": sub,
        "silver": game_state.silver,
        "princess": princess_serialize(game_state, child),
    })


@app.route('/api/mansion/descendants', methods=['GET'])
def mansion_descendants_api():
    """王府/公主府后代列表（折叠面板数据源）。后代存于皇嗣婚配对象的 offspring，就地派生。"""
    player_id = request.args.get('player_id')
    child_uid = request.args.get('child_uid')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    child = next((c for c in (getattr(game_state, "children", []) or [])
                  if str(c.get("uid")) == str(child_uid)), None)
    if child is None:
        return jsonify({"error": "未找到该皇嗣"}), 404
    return jsonify({
        "descendants": mansion_descendants_payload(game_state, child),
        "can_manage": chonghua_permission(game_state) == "full",
    })


@app.route('/api/mansion/descendant/admit', methods=['POST'])
def mansion_descendant_admit():
    """把在府孙辈接入重华宫（安置标记；需协理权限，年龄≤12，容量与银两校验）。"""
    data = request.get_json() or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    child = next((c for c in (getattr(game_state, "children", []) or [])
                  if str(c.get("uid")) == str(data.get('child_uid'))), None)
    if child is None:
        return jsonify({"error": "未找到该皇嗣"}), 404
    if chonghua_permission(game_state) != "full":
        return jsonify({"error": "接入重华宫需皇后亲裁或协理六宫权限"}), 403
    gc = next((g for g in get_descendants(game_state, child)
               if str(g.get("uid")) == str(data.get('descendant_uid'))), None)
    if gc is None:
        return jsonify({"error": "未找到该后代"}), 404
    ensure_descendant_fields(game_state, gc, (child.get("mansion") or {}).get("name", ""))
    if gc.get("安置状态") == "已入重华宫":
        return jsonify({"error": "该后代已在重华宫"}), 400
    age = float(gc.get("age", 0) or 0)
    if age > CHONGHUA_GRADUATE_AGE:
        return jsonify({"error": f"已{int(age)}岁，不宜再入重华宫教养"}), 400
    ch = chonghua_state(game_state)
    if chonghua_count_inside(game_state) >= chonghua_capacity(ch):
        return jsonify({"error": "重华宫已满，先迁出一些皇嗣再接入"}), 400
    if game_state.silver < CHONGHUA_UPKEEP_PER_CHILD:
        return jsonify({"error": f"银两不足，接入用度需{CHONGHUA_UPKEEP_PER_CHILD}两"}), 400
    game_state.silver -= CHONGHUA_UPKEEP_PER_CHILD
    gc["in_chonghua"] = True
    gc["palace"] = CHONGHUA_PALACE_NAME
    gc["安置状态"] = "已入重华宫"
    gc["安置地"] = "重华宫"
    chonghua_add_log(game_state, ch, f'孙辈{gc.get("name", "")}自府邸接入')
    msg = f"🏛️ {child.get('name', '')}之子{gc.get('name', '')}接入重华宫，由你亲自教养（-{CHONGHUA_UPKEEP_PER_CHILD}两）"
    game_state.add_memory(msg)
    return jsonify({"success": True, "narration": msg,
                    "descendants": mansion_descendants_payload(game_state, child),
                    "silver": game_state.silver})


@app.route('/api/princess/mansion', methods=['POST'])
def princess_mansion():
    """公主府经营：扩建府邸（数值经营）。op=='upgrade'。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    child_uid = data.get('child_uid')
    op = data.get('op', 'upgrade')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)
    idx, child = find_player_princess(game_state, child_uid)
    if child is None:
        return jsonify({"success": False, "error": "未找到该公主"}), 404
    if child.get("marriage_status") != "已嫁":
        return jsonify({"success": False, "error": "公主尚未出降，未立府邸"}), 400
    mansion = child.get("mansion") or default_mansion()
    child["mansion"] = mansion
    if op == 'upgrade':
        level = int(mansion.get("level", 1) or 1)
        if level >= MANSION_MAX_LEVEL:
            return jsonify({"success": False, "error": f"公主府已达最高规模（{MANSION_MAX_LEVEL}进）"}), 400
        cost = MANSION_UPGRADE_BASE * level
        if game_state.silver < cost:
            return jsonify({"success": False, "error": f"银两不足，扩建需{cost}两"}), 400
        game_state.silver -= cost
        mansion["level"] = level + 1
        mansion["income"] = int(mansion.get("income", 0) or 0) + random.randint(5, 12)
        mansion["reputation"] = min(100, int(mansion.get("reputation", 50) or 50) + random.randint(4, 8))
        msg = f"🏗️ {child.get('name')}公主府扩建至第{mansion['level']}进，进项与声望俱增，耗银{cost}两"
        mansion.setdefault("log", []).insert(0, msg)
        game_state.add_memory(msg)
        autosave_session(player_id)
        return jsonify({
            "success": True, "message": msg,
            "silver": game_state.silver,
            "princess": princess_serialize(game_state, child),
        })
    return jsonify({"success": False, "error": "未知的公主府操作"}), 400


# ============================================================
#  皇子择妃 · API 路由
# ============================================================

@app.route('/api/prince/list', methods=['GET'])
def prince_list():
    """列出玩家名下所有皇子的婚姻信息。"""
    player_id = request.args.get('player_id')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    princes = []
    seen = set()
    for uid, child, mother_name, is_player in _iter_all_princes(game_state):
        if not is_player:
            continue
        ensure_child_fields(child)
        if uid in seen:
            continue
        seen.add(uid)
        # 仅展示已成年（开府）的皇子
        if child.get("eighteen_years") or int(child.get("age", 0)) >= PRINCE_MARRY_MIN_AGE:
            princes.append(prince_serialize(game_state, child))
    return jsonify({
        "princes": princes,
        "marry_min_age": PRINCE_MARRY_MIN_AGE,
        "betroth_cost": PRINCE_BETROTH_COST,
        "marry_cost": PRINCE_MARRY_COST,
        "court_faction_favor": normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None)),
        "factions": COURT_FACTIONS,
    })


@app.route('/api/prince/suitors', methods=['POST'])
def prince_suitors():
    """生成/返回皇子妃候选人（每旬缓存一次）。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    child_uid = data.get('child_uid')
    refresh = bool(data.get('refresh'))
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)
    idx, child = find_player_prince(game_state, child_uid)
    if child is None:
        return jsonify({"success": False, "error": "未找到该皇子"}), 404
    if int(child.get("age", 0)) < PRINCE_MARRY_MIN_AGE:
        return jsonify({"success": False, "error": f"皇子尚未成年（需满{PRINCE_MARRY_MIN_AGE}岁）"}), 400
    if child.get("marriage_status") in ("已定", "已婚"):
        return jsonify({"success": False, "error": "皇子婚事已定，不必再相看"}), 400
    stamp = period_stamp(game_state)
    if refresh or not child.get("suitors") or child.get("suitors_period") != stamp:
        child["suitors"] = generate_prince_suitors(game_state, child)
        child["suitors_period"] = stamp
    if child.get("marriage_status") == "未议":
        child["marriage_status"] = "议婚中"
    autosave_session(player_id)
    return jsonify({"success": True, "prince": prince_serialize(game_state, child)})


@app.route('/api/prince/inspect', methods=['POST'])
def prince_inspect():
    """细察某皇子妃候选人，花行动点揭示其野心与隐藏标签。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    child_uid = data.get('child_uid')
    suitor_uid = data.get('suitor_uid')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)
    idx, child = find_player_prince(game_state, child_uid)
    if child is None:
        return jsonify({"success": False, "error": "未找到该皇子"}), 404
    suitor = next((s for s in (child.get("suitors") or []) if str(s.get("uid")) == str(suitor_uid)), None)
    if not suitor:
        return jsonify({"success": False, "error": "候选人不存在或已更替"}), 404
    if suitor.get("inspected"):
        return jsonify({"success": True, "message": "已细察过此人", "prince": prince_serialize(game_state, child)})
    if game_state.remaining_actions <= 0:
        return jsonify({"success": False, "error": "行动点不足，请先转旬"}), 400
    game_state.consume_action()
    suitor["inspected"] = True
    autosave_session(player_id)
    return jsonify({
        "success": True,
        "message": f"细察{suitor.get('name')}完毕，揭示其野心与隐情",
        "prince": prince_serialize(game_state, child),
    })


@app.route('/api/prince/betroth', methods=['POST'])
def prince_betroth():
    """定亲：选定一名候选正妃，写入 consort，marriage_status→已定。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    child_uid = data.get('child_uid')
    suitor_uid = data.get('suitor_uid')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)
    idx, child = find_player_prince(game_state, child_uid)
    if child is None:
        return jsonify({"success": False, "error": "未找到该皇子"}), 404
    if int(child.get("age", 0)) < PRINCE_MARRY_MIN_AGE:
        return jsonify({"success": False, "error": f"皇子尚未成年（需满{PRINCE_MARRY_MIN_AGE}岁）"}), 400
    if child.get("marriage_status") in ("已定", "已婚"):
        return jsonify({"success": False, "error": "皇子婚事已定"}), 400
    suitor = next((s for s in (child.get("suitors") or []) if str(s.get("uid")) == str(suitor_uid)), None)
    if not suitor:
        return jsonify({"success": False, "error": "候选人不存在或已更替"}), 404
    if game_state.silver < PRINCE_BETROTH_COST:
        return jsonify({"success": False, "error": f"银两不足，纳采需{PRINCE_BETROTH_COST}两"}), 400
    game_state.silver -= PRINCE_BETROTH_COST
    child["consort"] = dict(suitor)
    child["marriage_status"] = "已定"
    child["suitors"] = []
    child["suitors_period"] = None
    msg = f"💐 你为{child.get('title', '皇子')}{child.get('name')}定下正妃{suitor.get('name')}（{suitor.get('faction')}·{suitor.get('father_title')}之女），纳采礼成，耗银{PRINCE_BETROTH_COST}两"
    game_state.add_memory(msg)
    add_child_event(child, msg)
    autosave_session(player_id)
    return jsonify({
        "success": True,
        "message": msg,
        "silver": game_state.silver,
        "prince": prince_serialize(game_state, child),
    })


@app.route('/api/prince/marry', methods=['POST'])
def prince_marry():
    """大婚：下赐婚圣旨，迎娶正妃，触发朝堂联动。"""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    child_uid = data.get('child_uid')
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if is_game_over(game_state):
        return game_over_response(game_state)
    idx, child = find_player_prince(game_state, child_uid)
    if child is None:
        return jsonify({"success": False, "error": "未找到该皇子"}), 404
    if game_state.silver < PRINCE_MARRY_COST:
        return jsonify({"success": False, "error": f"银两不足，大典需{PRINCE_MARRY_COST}两"}), 400
    if child.get("marriage_status") != "已定" or not child.get("consort"):
        return jsonify({"success": False, "error": "尚未定亲，不能举行大婚"}), 400
    game_state.silver -= PRINCE_MARRY_COST
    child["marriage_status"] = "已婚"
    consort = child.get("consort") or {}
    favor = normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None))
    faction = consort.get("faction")
    court_notes = []
    if faction in favor:
        gain = random.randint(5, 12)
        favor[faction] = min(100, favor[faction] + gain)
        court_notes.append(f"{faction}因联姻之喜，好感+{gain}")
    game_state.court_faction_favor = favor
    game_state.attributes["威望"] = min(game_state.get_attr_max("威望"), game_state.attributes.get("威望", 0) + random.randint(6, 12))
    title = child.get("title", "皇子")
    name = child.get("name", "")
    msg = f"🎊 赐婚圣旨已下，{title}{name}迎娶正妃{consort.get('name')}，六礼既成，百官朝贺，耗银{PRINCE_MARRY_COST}两"
    game_state.add_memory(msg)
    add_child_event(child, msg)
    child.setdefault("marriage_events", []).insert(0, msg)
    for note in court_notes:
        game_state.add_memory(note)
    autosave_session(player_id)
    return jsonify({
        "success": True, "message": msg,
        "court_notes": court_notes,
        "silver": game_state.silver,
        "prince": prince_serialize(game_state, child),
    })


# ---- 太后垂帘听政（dowager_system.py / DOWAGER_SYSTEM.md） ----

@app.route('/api/dowager/overview', methods=['GET'])
def dowager_overview_api():
    game_state, err = session_or_404(request.args.get('player_id'))
    if err:
        return err
    return jsonify(dowager_payload(game_state))


@app.route('/api/dowager/affair', methods=['POST'])
def dowager_affair_api():
    """裁决一件朝会奏事。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    ok, msg = respond_court_affair(game_state, data.get('affair_id'), data.get('choice_index'))
    if ok is None:
        return jsonify({"error": msg}), 404
    if not ok:
        return jsonify({"error": str(msg)}), 400
    return jsonify({"success": True, "narration": msg,
                    "overview": dowager_payload(game_state),
                    "attributes": game_state.attributes})


@app.route('/api/dowager/action', methods=['POST'])
def dowager_action_api():
    """太后主动施为：亲授帝学/赏赐朝臣/整肃朝纲/施粥赈灾/召见宗亲。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    ok, msg = dowager_action(game_state, data.get('action'))
    if ok is None:
        return jsonify({"error": msg}), 400
    if not ok:
        if isinstance(msg, tuple):
            return msg[0], msg[1]
        return jsonify({"error": str(msg)}), 400
    return jsonify({"success": True, "narration": msg,
                    "overview": dowager_payload(game_state),
                    "silver": game_state.silver,
                    "remaining_actions": game_state.remaining_actions,
                    "max_actions": game_state.max_actions})


@app.route('/api/dowager/harem', methods=['POST'])
def dowager_harem_api():
    """太后掌新帝后宫：mode=<亲掌/共治/放权> 切换治理之法；action=<...> 施为。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    if data.get('mode'):
        ok, msg = set_harem_mode(game_state, data.get('mode'))
    elif data.get('action'):
        ok, msg = harem_action(game_state, data.get('action'))
    else:
        return jsonify({"error": "须指定 mode 或 action"}), 400
    if ok is None:
        return jsonify({"error": msg}), 400
    if not ok:
        if isinstance(msg, tuple):
            return msg[0], msg[1]
        return jsonify({"error": str(msg)}), 400
    return jsonify({"success": True, "narration": msg,
                    "overview": dowager_payload(game_state),
                    "silver": game_state.silver,
                    "remaining_actions": game_state.remaining_actions,
                    "max_actions": game_state.max_actions})


@app.route('/api/dowager/meddle', methods=['POST'])
def dowager_meddle_api():
    """裁决外戚/宗室/权臣的干政请托。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    ok, msg = respond_meddle(game_state, data.get('meddle_id'), data.get('choice_index'))
    if ok is None:
        return jsonify({"error": msg}), 404
    if not ok:
        return jsonify({"error": str(msg)}), 400
    return jsonify({"success": True, "narration": msg, "overview": dowager_payload(game_state),
                    "attributes": game_state.attributes})


@app.route('/api/dowager/consort', methods=['POST'])
def dowager_consort_api():
    """处置新帝妃嫔：promote/demote/dismiss/comfort。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    ok, msg = consort_action(game_state, data.get('name'), data.get('action'))
    if ok is None:
        return jsonify({"error": msg}), 404
    if not ok:
        if isinstance(msg, tuple):
            return msg[0], msg[1]
        return jsonify({"error": str(msg)}), 400
    return jsonify({"success": True, "narration": msg, "overview": dowager_payload(game_state),
                    "silver": game_state.silver,
                    "remaining_actions": game_state.remaining_actions,
                    "max_actions": game_state.max_actions})


@app.route('/api/reign/action', methods=['POST'])
def reign_action_api():
    """女帝称制期：agenda=裁决国是 / abdicate=传位。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    if data.get('agenda_id'):
        ok, msg = respond_reign_agenda(game_state, data.get('agenda_id'), data.get('choice_index'))
    elif data.get('action') == 'abdicate':
        ok, msg = reign_abdicate(game_state)
    else:
        return jsonify({"error": "须指定 agenda_id 或 action=abdicate"}), 400
    if ok is None:
        return jsonify({"error": msg}), 400
    if not ok:
        return jsonify({"error": str(msg)}), 400
    resp = {"success": True, "narration": msg, "overview": dowager_payload(game_state)}
    if is_game_over(game_state):
        resp["game_over"] = True
        resp["ending"] = ending_payload(game_state)
    return jsonify(resp)


@app.route('/api/dowager/power', methods=['POST'])
def dowager_power_api():
    """还政抉择：yield=归政 / refuse=继续垂帘 / regnant=临朝称制。"""
    data = request.get_json(silent=True) or {}
    game_state, err = session_or_404(data.get('player_id'))
    if err:
        return err
    ok, msg = return_power(game_state, data.get('mode'))
    if ok is None:
        return jsonify({"error": msg}), 400
    if not ok:
        return jsonify({"error": str(msg)}), 400
    resp = {"success": True, "narration": msg, "overview": dowager_payload(game_state)}
    if is_game_over(game_state):
        resp["game_over"] = True
        resp["ending"] = ending_payload(game_state)
    return jsonify(resp)


@app.route('/')
def serve_index():
    resp = send_file('index.html')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/<path:filename>', methods=['GET'])
def serve_static(filename):
    if filename.startswith('api/'):
        return jsonify({"error": "接口不存在，请确认游戏后端已启动"}), 404
    return send_from_directory('.', filename)

# ============================================================
#  自定义头像系统
# ============================================================
AVATAR_DIR = "avatars"
os.makedirs(AVATAR_DIR, exist_ok=True)


@app.route('/api/avatar/reroll', methods=['POST'])
def avatar_reroll():
    """🎲 随机换一张：对指定角色递换取图 salt，重新分配（保留上传的自定义头像则先清除）。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    key = (data.get('key') or '').strip()
    game_state, err = session_or_404(player_id)
    if err:
        return err
    if not key:
        return jsonify({"error": "缺少 key"}), 400
    if key == "player" and getattr(game_state, "avatar", None):
        game_state.avatar = ""  # 想换掉上传的头像时允许直接掷
    rerolls = getattr(game_state, "avatar_rerolls", None)
    if not isinstance(rerolls, dict):
        rerolls = {}
        game_state.avatar_rerolls = rerolls
    rerolls[key] = int(rerolls.get(key, 0)) + 1
    _set_avatar_field(player_id, key, "")
    _pack_assign_all(game_state)
    autosave_session(player_id)
    payload = avatar_payload(game_state)
    return jsonify({"success": True, "key": key, "url": payload.get(key, ""),
                    "avatars": payload})


@app.route('/api/avatar/upload', methods=['POST'])
def avatar_upload():
    """上传自定义头像（前端已缩至 128×128 的 base64 JPEG）。"""
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    b64 = data.get('avatar') or ''
    key = (data.get('key') or '').strip()
    if not key or not b64:
        return jsonify({"error": "缺少 avatar 或 key"}), 400
    if not b64.startswith("data:image/"):
        return jsonify({"error": "仅支持图片格式"}), 400
    import base64 as _b64
    try:
        raw = _b64.b64decode(b64.split(",", 1)[-1])
    except Exception:
        return jsonify({"error": "图片解码失败"}), 400
    if len(raw) > 200 * 1024:
        return jsonify({"error": "图片过大（上限200KB），请换小图"}), 400
    import hashlib
    fname = hashlib.md5(key.encode()).hexdigest() + ".jpg"
    path = os.path.join(AVATAR_DIR, fname)
    with open(path, "wb") as f:
        f.write(raw)
    _set_avatar_field(player_id, key, f"/avatars/{fname}")
    return jsonify({"success": True, "url": f"/avatars/{fname}", "key": key})


@app.route('/api/avatar/remove', methods=['POST'])
def avatar_remove():
    data = request.get_json(silent=True) or {}
    key = (data.get('key') or '').strip()
    if not key:
        return jsonify({"error": "缺少 key"}), 400
    import hashlib
    fname = hashlib.md5(key.encode()).hexdigest() + ".jpg"
    path = os.path.join(AVATAR_DIR, fname)
    if os.path.exists(path):
        os.remove(path)
    _set_avatar_field(data.get('player_id'), key, "")
    return jsonify({"success": True})


@app.route('/avatars/<path:fname>')
def serve_avatar(fname):
    return send_from_directory(AVATAR_DIR, fname)


INBOX_DIR = os.path.join(AVATAR_DIR, "_inbox")
UI_ASSET_DIR = os.path.join(AVATAR_DIR, "ui")


@app.route('/avatars/inbox/<path:fname>')
def serve_inbox_avatar(fname):
    """分类后的立绘图库（avatars/_inbox，文件名可能含 #/@ 等特殊字符）。"""
    return send_from_directory(INBOX_DIR, fname)


@app.route('/avatars/ui/<path:fname>')
def serve_ui_asset(fname):
    """UI 装饰用场景图（avatars/ui）。"""
    return send_from_directory(UI_ASSET_DIR, fname)


# ===== 按身份分桶的头像分配（avatars/pool/ 由 tools/build_avatar_pool.py 压缩生成并入库） =====
AVATAR_POOL_DIR = os.path.join(AVATAR_DIR, "pool")
AVATAR_POOL_CACHE = {"mtime": None, "pools": None}
# 角色 → 桶优先级（依次回退，全空则回退旧 pack 逻辑）
BUCKET_ALIASES = {
    "player":  ["妃嫔", "公主"],
    "npc":     ["妃嫔", "公主"],
    "npc_太后": ["太后", "妃嫔"],
    "npc_皇后": ["妃嫔"],
    "child_m": ["皇子", "名臣", "驸马"],
    "child_f": ["公主", "妃嫔"],
    "servant_宫女": ["宫女", "女官", "妃嫔"],
    "servant_太监": ["侍卫", "男仆", "名臣"],
    "royal_m": ["皇子", "名臣", "驸马"],
    "royal_f": ["公主", "妃嫔"],
    "consort": ["妃嫔", "公主"],
    "cold":    ["妃嫔"],
}


def _load_bucket_pools():
    """扫描 avatars/pool/<桶>/ 目录（git 跟踪，clone 即用）。返回 {桶: [文件名...]}。"""
    if not os.path.isdir(AVATAR_POOL_DIR):
        return {}
    try:
        mt = os.path.getmtime(AVATAR_POOL_DIR)
        if AVATAR_POOL_CACHE["pools"] is None or mt != AVATAR_POOL_CACHE["mtime"]:
            pools = {}
            for d in os.listdir(AVATAR_POOL_DIR):
                pdir = os.path.join(AVATAR_POOL_DIR, d)
                if os.path.isdir(pdir):
                    pools[d] = sorted(f for f in os.listdir(pdir) if f.endswith(".jpg"))
            AVATAR_POOL_CACHE["pools"] = pools
            AVATAR_POOL_CACHE["mtime"] = mt
        return AVATAR_POOL_CACHE["pools"]
    except Exception as e:
        print(f"[warn] avatar pool load: {e}")
        return {}


def _bucket_pick(pools, buckets, seed_key, salt=0):
    """按桶优先级取一张确定性头像 URL；salt 非零时换血（🎲 随机按钮）。"""
    import hashlib, urllib.parse
    seed = f"{seed_key}#{salt}" if salt else seed_key
    for b in buckets:
        files = pools.get(b) or []
        if not files:
            continue
        idx = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(files)
        return f"/avatars/pool/{urllib.parse.quote(b)}/{files[idx]}"
    return None


def _pack_assign_all(game_state):
    """给所有无头像的角色批量分配头像：优先按身份桶取 pool 图库，回退旧 pack。"""
    import hashlib
    pack_dir = os.path.join(AVATAR_DIR, "pack")
    pack_files = sorted([f for f in os.listdir(pack_dir)
                         if f.endswith((".jpg", ".png"))]) if os.path.isdir(pack_dir) else []
    pools = _load_bucket_pools()
    rerolls = getattr(game_state, "avatar_rerolls", {}) or {}

    def _assign(key, url):
        if url:
            _set_avatar_field(game_state.player_id, key, url)
        elif pack_files:
            idx = int(hashlib.md5(f"{key}#{rerolls.get(key, 0)}".encode()).hexdigest(), 16) % len(pack_files)
            _set_avatar_field(game_state.player_id, key, f"/avatars/pack/{pack_files[idx]}")

    def _pick(key, alias):
        return _bucket_pick(pools, BUCKET_ALIASES[alias], key, rerolls.get(key, 0))

    # 主控
    if not getattr(game_state, "avatar", None):
        _assign("player", _pick("player", "player"))
    # NPC
    for name, npc in (game_state.npcs or {}).items():
        if isinstance(npc, dict) and not npc.get("avatar"):
            alias = f"npc_{name}" if name in ("太后", "皇后") else "npc"
            _assign(f"npc:{name}", _pick(f"npc:{name}", alias))
    # 子嗣（按性别分桶）
    for c in (game_state.children or []):
        if isinstance(c, dict) and not c.get("avatar"):
            uid = str(c.get("uid", ""))
            if not uid:
                continue
            key = f"child:{uid}"
            alias = "child_m" if c.get("gender") == "皇子" else "child_f"
            _assign(key, _pick(key, alias))
    # 宫人
    for s in (game_state.servants or []):
        if getattr(s, "avatar", None) is None:
            key = f"servant:{s.name}"
            alias = "servant_宫女" if s.type == "宫女" else "servant_太监"
            _assign(key, _pick(key, alias))
    # 宗室
    rc = getattr(game_state, "royal_clan", None)
    if isinstance(rc, dict):
        for pool, alias in (("males", "royal_m"), ("females", "royal_f")):
            for name, m in (rc.get(pool) or {}).items():
                if isinstance(m, dict) and not m.get("avatar"):
                    key = f"royal:{name}"
                    _assign(key, _pick(key, alias))
    # 太后线妃嫔
    ds = getattr(game_state, "dowager_state", None)
    if isinstance(ds, dict):
        for c in (ds.get("consorts") or []):
            if isinstance(c, dict) and not c.get("avatar"):
                key = f"consort:{c['name']}"
                _assign(key, _pick(key, "consort"))
        # 冷宫
        for name, inm in (ds.get("inmates") or {}).items():
            if isinstance(inm, dict) and not inm.get("avatar"):
                key = f"cold:{name}"
                _assign(key, _pick(key, "cold"))


def _set_avatar_field(player_id, key, url):
    """根据 key 把头像 URL 写入对应角色的 avatar 字段。"""
    try:
        game_state = sessions.get(player_id)
        if not game_state:
            return
        if key == "player":
            game_state.avatar = url
        elif key.startswith("npc:"):
            npc = (game_state.npcs or {}).get(key[4:])
            if isinstance(npc, dict):
                npc["avatar"] = url
        elif key.startswith("child:"):
            uid = key[6:]
            for c in (game_state.children or []):
                if str(c.get("uid")) == uid:
                    c["avatar"] = url
                    break
        elif key.startswith("servant:"):
            sn = key[8:]
            for s in (game_state.servants or []):
                if s.name == sn:
                    s.avatar = url
                    break
        elif key.startswith("royal:"):
            rc = getattr(game_state, "royal_clan", None)
            if isinstance(rc, dict):
                for pool in ("males", "females"):
                    if key[6:] in (rc.get(pool) or {}):
                        rc[pool][key[6:]]["avatar"] = url
                        break
        elif key.startswith("consort:"):
            ds = getattr(game_state, "dowager_state", None)
            if isinstance(ds, dict):
                for c in (ds.get("consorts") or []):
                    if c.get("name") == key[8:]:
                        c["avatar"] = url
                        break
        elif key.startswith("cold:"):
            ds = getattr(game_state, "cold_palace", None)
            if isinstance(ds, dict) and key[5:] in (ds.get("inmates") or {}):
                ds["inmates"][key[5:]]["avatar"] = url
    except Exception as e:
        print(f"[warn] avatar set {key}: {e}")


def _pack_assign(game_state, key, seed):
    """角色无自定义头像时，从图包中确定性分配一张。"""
    if getattr(game_state, "avatar", None) and key == "player":
        return  # 玩家有自定义头像
    pack_dir = os.path.join(AVATAR_DIR, "pack")
    if not os.path.isdir(pack_dir):
        return
    files = sorted([f for f in os.listdir(pack_dir) if f.endswith((".jpg", ".png"))])
    if not files:
        return
    import hashlib
    idx = int(hashlib.md5(key.encode()).hexdigest(), 16) % len(files)
    url = f"/avatars/pack/{files[idx]}"
    _set_avatar_field(player_id=game_state.player_id, key=key, url=url)


def build_player_render(game_state):
    """主控状态页所需：立绘 + 外观描写 + 才艺对五维的加成。"""
    appearance = (getattr(game_state, "appearance", "") or "").strip()
    talent = (getattr(game_state, "talent", "") or "").strip()
    personality = (getattr(game_state, "personality", "") or "").strip()
    # 固定外观描写（缺省时给一段古风模板）
    if not appearance:
        age = max(15, int(getattr(game_state, "age", 18) or 18))
        appearance = "云鬓如墨，肤若凝脂，眉目间一派婉约，端的是温婉贤淑之姿。"
    # 才艺对五维的加成：每位才艺最多 3 条修饰（属性 + 数值）
    bonus_map = {
        "琴艺": [("宠爱", 2), ("才情", 4), ("魅力", 2)],
        "棋艺": [("谋略", 4), ("心计", 2), ("才情", 1)],
        "书画": [("才情", 5), ("福运", 1), ("魅力", 1)],
        "诗词": [("才情", 5), ("威望", 1), ("魅力", 1)],
        "歌舞": [("宠爱", 3), ("魅力", 4), ("福运", 1)],
        "刺绣": [("才艺", 5), ("福运", 1), ("才情", 1)],
        "厨艺": [("宠爱", 2), ("福运", 2), ("健康", 1)],
        "医理": [("健康", 2), ("福运", 3), ("才情", 1)],
        "音律": [("才情", 3), ("魅力", 2), ("宠爱", 1)],
        "花艺": [("福运", 3), ("魅力", 2), ("才情", 1)],
    }
    talent_bonus = []
    for k in re.split(r"[、，,\s]+", talent):
        k = k.strip()
        if not k:
            continue
        if k in bonus_map:
            for attr, val in bonus_map[k]:
                talent_bonus.append({"attr": attr, "value": val, "src": k})
    return {
        "avatar": getattr(game_state, "avatar", None) or "",
        "appearance": appearance,
        "talent": talent or "—",
        "personality": personality or "—",
        "traits": list(getattr(game_state, "traits", []) or []),
        "talent_bonus": talent_bonus,
    }


# ===== 主控互动对话：手势/语气/动作 三选拼装 + NPC 状态轴改动 =====
INTERACT_STYLES = {
    "soft":   {"label": "温柔",   "emoji": "🌸", "tone": "低声软语，含笑带怯"},
    "cool":   {"label": "冷淡",   "emoji": "❄️", "tone": "神色淡漠，不假辞色"},
    "sharp":  {"label": "锋利",   "emoji": "🗡️", "tone": "言辞如刀，寸步不让"},
    "warm":   {"label": "热情",   "emoji": "☀️", "tone": "笑意盈盈，言语间尽是亲近"},
    "crafty": {"label": "城府",   "emoji": "🦊", "tone": "语带机锋，话外有话"},
}
NPC_FACES = {
    "joy": "😊", "shy": "😳", "anger": "😠", "fear": "😨",
    "cold": "😐", "puzzled": "🤔", "satisfied": "😌", "amazed": "😲",
}

def _pick_npc_face(npc, axes):
    """根据 NPC 当前状态轴（好感/信任/畏惧/爱慕）选择表情。"""
    if axes is None:
        return NPC_FACES["puzzled"]
    trust = axes.get("信任", 30)
    fear = axes.get("畏惧", 0)
    favor = axes.get("好感", 30)
    love = axes.get("爱慕", 0)
    if fear >= 60: return NPC_FACES["fear"]
    if love >= 50: return NPC_FACES["shy"]
    if trust >= 70: return NPC_FACES["joy"]
    if favor >= 60: return NPC_FACES["satisfied"]
    if favor <= 20 or axes.get("敌意", 0) >= 50: return NPC_FACES["anger"]
    if trust <= 20: return NPC_FACES["cold"]
    return NPC_FACES["puzzled"]


def _ensure_npc_axes(npc):
    """保证 NPC 有 4 维状态轴（态度/信任/畏惧/爱慕），旧数据兼容。"""
    if not isinstance(npc, dict):
        return
    npc.setdefault("attitude", {})
    axes = npc["attitude"]
    axes.setdefault("好感", 30)
    axes.setdefault("信任", 30)
    axes.setdefault("畏惧", 0)
    axes.setdefault("爱慕", 0)
    axes.setdefault("敌意", 0)


def _compute_interact_effects(style_key, npc_axes):
    """根据 5 种风格计算对 NPC 四轴的影响（好感/信任/畏惧/爱慕）。"""
    table = {
        "soft":   {"好感": 4, "信任": 3, "畏惧": -2, "爱慕": 2, "敌意": -1},
        "cool":   {"好感": -1, "信任": 1, "畏惧": 3, "爱慕": 0, "敌意": 1},
        "sharp":  {"好感": -3, "信任": -2, "畏惧": 6, "爱慕": -1, "敌意": 4},
        "warm":   {"好感": 5, "信任": 4, "畏惧": -1, "爱慕": 3, "敌意": -2},
        "crafty": {"好感": 0, "信任": 2, "畏惧": 4, "爱慕": 1, "敌意": 0},
    }
    base = dict(table.get(style_key, table["soft"]))
    # 主控的才情/心计对结果有微调
    return base


def build_interact_line(player_name, style_key, action, target_name):
    """根据风格 + 动作拼出一句主控台词。"""
    s = INTERACT_STYLES.get(style_key, INTERACT_STYLES["soft"])
    templates = {
        "soft":   ["{p}朝{t}盈盈一福，轻声道：「{act}。」", "{p}低眉浅笑，对{t}柔声道：「{act}。」"],
        "cool":   ["{p}瞥了{t}一眼，淡声道：「{act}。」", "{p}负手而立，对{t}冷冷道：「{act}。」"],
        "sharp":  ["{p}目光微凛，对{t}冷笑道：「{act}。」", "{p}一字一顿，对{t}道：「{act}！」"],
        "warm":   ["{p}挽住{t}的臂膀，爽朗笑道：「{act}！」", "{p}满脸堆欢，对{t}道：「{act}。」"],
        "crafty": ["{p}轻轻一笑，对{t}意味深长道：「{act}？」", "{p}端起茶盏，对{t}悠悠道：「{act}。」"],
    }
    pool = templates.get(style_key, templates["soft"])
    line = random.choice(pool)
    return line.format(p=player_name or "我", t=target_name or "对方", act=action or "今日倒有闲心")


def player_interact_npc(game_state, npc_name, style_key, action_text):
    """主控主动与 NPC 互动：三选拼装 + 状态轴改动 + 表情反应。"""
    if npc_name not in game_state.npcs:
        return None, "NPC不存在"
    npc = game_state.npcs[npc_name]
    if isinstance(npc, dict) and not npc.get("alive", True):
        return None, "该妃嫔已不在后宫"
    _ensure_npc_axes(npc)
    axes = npc["attitude"]
    style = INTERACT_STYLES.get(style_key)
    if not style:
        return None, "未知风格"
    effects = _compute_interact_effects(style_key, axes)
    for k, v in effects.items():
        axes[k] = max(0, min(100, int(axes.get(k, 30)) + int(v)))
    # 同步主控关系的「好感」（影响宫斗/举荐）
    if "好感" in axes:
        cur = game_state.relationships.get(npc_name, {}).get("好感", 0)
        delta = effects["好感"] // 2
        if delta != 0:
            game_state.relationships.setdefault(npc_name, {"好感": 0, "印象": "初识"})
            game_state.relationships[npc_name]["好感"] = max(-100, min(100, cur + delta))
    # 主角台词 + NPC 表情 + 内心活动
    line = build_interact_line(getattr(game_state, "name", ""), style_key, action_text, npc_name)
    face = _pick_npc_face(npc, axes)
    inner = ""
    if axes.get("畏惧", 0) >= 60:
        inner = f"{npc_name}心头一凛，不敢直视。"
    elif axes.get("爱慕", 0) >= 50:
        inner = f"{npc_name}粉面微红，垂下了眼睫。"
    elif axes.get("敌意", 0) >= 50:
        inner = f"{npc_name}眉峰一挑，拂袖欲去。"
    elif axes.get("信任", 0) >= 70:
        inner = f"{npc_name}会心一笑，点了点头。"
    else:
        inner = f"{npc_name}神色不动，似在揣度来意。"
    # 落账
    game_state.add_attr_change(
        {"心计": (1 if style_key in ("crafty", "sharp") else 0) - (1 if style_key == "soft" else 0)},
        f"与{npc_name}互动：{style['label']}姿态"
    )
    game_state.add_memory(f"以{style['label']}姿态对{npc_name}：{action_text}")
    return {
        "line": line,
        "face": face,
        "inner": inner,
        "effects": effects,
        "axes": dict(axes),
        "style": style["label"],
        "npc_name": npc_name,
    }, None


@app.route('/api/player/interact', methods=['POST'])
def api_player_interact():
    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    npc_name = data.get('npc_name')
    style_key = data.get('style', 'soft')
    action_text = (data.get('action') or '').strip() or "今日天气正好"
    game_state, err = session_or_404(player_id)
    if err:
        return err
    ok, err = guard_action(game_state)
    if not err and not ok:
        return err
    payload, err_msg = player_interact_npc(game_state, npc_name, style_key, action_text)
    if err_msg:
        return jsonify({"error": err_msg}), 400
    autosave_session(player_id)
    return jsonify({**payload, "remaining_actions": game_state.remaining_actions, "max_actions": game_state.max_actions})


def avatar_payload(game_state):
    """收集所有已设置头像的 key→URL 映射，供前端批量挂载。

    首次调用时自动为无头像角色从图包确定性分配。
    """
    _pack_assign_all(game_state)
    out = {}
    if getattr(game_state, "avatar", None):
        out["player"] = game_state.avatar
    for name, npc in (game_state.npcs or {}).items():
        if isinstance(npc, dict) and npc.get("avatar"):
            out[f"npc:{name}"] = npc["avatar"]
    for c in (game_state.children or []):
        if isinstance(c, dict) and c.get("avatar"):
            out[f"child:{c.get('uid', '')}"] = c["avatar"]
    for s in (game_state.servants or []):
        if getattr(s, "avatar", None):
            out[f"servant:{s.name}"] = s.avatar
    rc = getattr(game_state, "royal_clan", None)
    if isinstance(rc, dict):
        for pool in ("males", "females"):
            for name, m in (rc.get(pool) or {}).items():
                if isinstance(m, dict) and m.get("avatar"):
                    out[f"royal:{name}"] = m["avatar"]
    ds = getattr(game_state, "dowager_state", None)
    if isinstance(ds, dict):
        for c in (ds.get("consorts") or []):
            if isinstance(c, dict) and c.get("avatar"):
                out[f"consort:{c['name']}"] = c["avatar"]
    return out

# 存档预热放后台线程：817+ 存档同步加载会阻塞 gunicorn worker 启动，
# 导致容器健康检查超时；未预热到的会话由 get_or_restore_session 按需恢复。
import threading
threading.Thread(target=restore_sessions_on_startup, daemon=True,
                 name="session-restore").start()

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