# models.py
from enum import Enum
import random
from datetime import datetime

# 位份顺序（低→高），供 app/scenarios 等模块统一引用
RANK_ORDER = ["宫女", "更衣", "官女子", "秀女", "答应", "常在", "贵人", "才人", "美人", "婕妤", "嫔", "妃", "贵妃", "皇贵妃", "皇后"]
# 方案 B：四妃改为「妃」位份下的专属封号（各限 1 人），不再是独立位份。
FOUR_CONSORT_TITLES = ["淑", "德", "贤", "宸"]
# 旧存档兼容：把旧的四妃「位份」迁移为 妃 + 对应封号。
_LEGACY_FOUR_CONSORT_RANKS = {"淑妃": "淑", "德妃": "德", "贤妃": "贤", "宸妃": "宸"}
TITLED_CONSORT_POWER = 12   # 妃 + 普通封号（位份仍为妃）
FOUR_CONSORT_POWER = 13     # 妃 + 四妃封号（正牌四妃：淑/德/贤/宸）

RANK_POWER = {
    "宫女": 0, "更衣": 1, "官女子": 2, "秀女": 3, "答应": 4, "常在": 5,
    "贵人": 6, "才人": 7, "美人": 8, "婕妤": 9, "嫔": 10, "妃": 11,
    "贵妃": 17, "皇贵妃": 18, "皇后": 19,
}

# ---- 公主择婿 · 三大朝堂势力 ----
# 复用现有「母家 / 官阶」观念，抽象为三派。驸马家族所属派系会影响朝堂好感度。
COURT_FACTIONS = {
    "文官党": {"desc": "科举清流、内阁六部，重礼法名分", "weight_attr": "才情"},
    "武官党": {"desc": "边镇将门、京营勋卫，重军功实力", "weight_attr": "威望"},
    "宗室党": {"desc": "亲王郡王、宗人府，重血脉正统", "weight_attr": "福运"},
}


# 内务府总管派系
IP_CHIEF_FACTIONS = ["皇后派", "太后派", "皇帝派", "中立"]


def default_inner_palace():
    """内务府默认状态。"""
    return {
        "budget": 5000,
        "storehouse": {"布匹": 30, "药材": 15, "香料": 10, "木材": 20, "食材": 40},
        "chief": {"name": "苏培盛", "loyalty": 60, "corruption": 25, "skill": 70,
                  "faction": "中立", "tenure": 0, "performance": 0,
                  "appointed_by": "祖传", "dismissed": 0},
        "market": {"布匹": 5, "药材": 10, "香料": 15, "木材": 8, "食材": 3},
        "monthly_stipend": {
            "皇后": 100, "皇贵妃": 80, "贵妃": 70, "妃": 60, "嫔": 50,
            "贵人": 35, "常在": 25, "答应": 15, "官女子": 10
        },
        "logs": [],
        "corruption_evidence": 0,
        # ---- 奏请内帑拨款：同旬一次限制 ----
        "last_funding_period": None,
        "audited_this_period": False,
        # ---- 权谋操作：克扣份例 / 额外赏赐（逐旬结算）----
        "stipend_cuts": {},
        "bonus_gifts": {},
        # ---- 宫宴承办 ----
        "banquet": None,
        "banquet_history": [],
        # ---- 私库（公银转私银）----
        "private_purse": {"enabled": False, "total_transferred": 0,
                          "last_transfer_period": 0, "transfer_logs": []},
        # ---- 季度考绩（每 30 旬一次）----
        "performance_reviews": {"last_review": 0, "score": 0, "grade": "",
                                "next_review": 30, "history": []},
        # ---- 产业投资（长线经营）----
        "projects": {
            "皇庄": {"level": 0, "invested": 0, "income_per_period": 0, "status": "正常", "status_periods": 0},
            "织造局": {"level": 0, "invested": 0, "income_per_period": 0, "status": "正常", "status_periods": 0},
            "茶庄": {"level": 0, "invested": 0, "income_per_period": 0, "status": "正常", "status_periods": 0},
        },
    }


def _ip_int(data, key, default):
    """取整数字段：键存在且可转 int 则用之（含 0），否则回落默认。"""
    try:
        if data is not None and key in data:
            return int(data[key])
    except (TypeError, ValueError):
        pass
    return default


def normalize_inner_palace(data):
    """归一化内务府数据，兼容旧存档缺失字段。"""
    base = default_inner_palace()
    if not isinstance(data, dict):
        return base
    # budget
    base["budget"] = _ip_int(data, "budget", base["budget"])
    # storehouse
    sh = data.get("storehouse")
    if isinstance(sh, dict):
        for k in base["storehouse"]:
            base["storehouse"][k] = _ip_int(sh, k, base["storehouse"][k])
    # chief
    ch = data.get("chief")
    if isinstance(ch, dict):
        nm = ch.get("name")
        if isinstance(nm, str) and nm.strip():
            base["chief"]["name"] = nm.strip()
        for attr in ("loyalty", "corruption", "skill"):
            v = _ip_int(ch, attr, None)
            if v is not None:
                base["chief"][attr] = max(0, min(100, v))
        faction = ch.get("faction")
        if faction in IP_CHIEF_FACTIONS:
            base["chief"]["faction"] = faction
        for attr in ("tenure", "dismissed"):
            v = _ip_int(ch, attr, None)
            if v is not None:
                base["chief"][attr] = max(0, v)
        perf = _ip_int(ch, "performance", None)
        if perf is not None:
            base["chief"]["performance"] = max(-100, min(100, perf))
        ab = ch.get("appointed_by")
        if isinstance(ab, str) and ab.strip():
            base["chief"]["appointed_by"] = ab.strip()
    # market
    mk = data.get("market")
    if isinstance(mk, dict):
        for k in base["market"]:
            v = _ip_int(mk, k, None)
            if v is not None:
                base["market"][k] = max(2, v)
    # monthly_stipend
    ms = data.get("monthly_stipend")
    if isinstance(ms, dict):
        for k in base["monthly_stipend"]:
            base["monthly_stipend"][k] = _ip_int(ms, k, base["monthly_stipend"][k])
    # logs（按旬归档：新结构为 {'p': 旬, 't': 文本}，兼容旧字符串）
    logs = data.get("logs")
    if isinstance(logs, list):
        clean_logs = []
        for x in logs[-80:]:
            if isinstance(x, dict):
                p = _ip_int(x, "p", 0)
                t = x.get("t")
                if isinstance(t, str) and t.strip():
                    clean_logs.append({"p": p, "t": t.strip()})
            elif isinstance(x, str) and x.strip():
                # 兼容旧存档：剥离形如 [MM-DD HH:MM] 的本地时间前缀
                import re as _re
                t = _re.sub(r'^\[\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2}\]\s*', '', x.strip())
                clean_logs.append({"p": 0, "t": t})
        base["logs"] = clean_logs
    # corruption_evidence
    try:
        base["corruption_evidence"] = max(0, int(data.get("corruption_evidence", 0) or 0))
    except (TypeError, ValueError):
        pass
    # audited_this_period
    base["audited_this_period"] = bool(data.get("audited_this_period", False))
    # stipend_cuts / bonus_gifts（逐旬权谋）
    for key in ("stipend_cuts", "bonus_gifts"):
        raw = data.get(key)
        clean = {}
        if isinstance(raw, dict):
            for tgt, v in raw.items():
                if not isinstance(v, dict):
                    continue
                pct = _ip_int(v, "amount", 0)
                periods = _ip_int(v, "periods", 0)
                if periods <= 0:
                    continue
                if key == "stipend_cuts":
                    pct = max(10, min(50, pct))
                    clean[str(tgt)] = {"amount": pct, "periods": min(30, periods),
                                       "start_period": _ip_int(v, "start_period", 0)}
                else:
                    clean[str(tgt)] = {"amount": max(0, min(100, pct)),
                                       "periods": min(30, periods),
                                       "start_period": _ip_int(v, "start_period", 0)}
        base[key] = clean
    # banquet / banquet_history
    bq = data.get("banquet")
    base["banquet"] = bq if isinstance(bq, dict) else None
    bh = data.get("banquet_history")
    if isinstance(bh, list):
        base["banquet_history"] = [x for x in bh if isinstance(x, dict)][:20]
    # private_purse
    pp = data.get("private_purse")
    if isinstance(pp, dict):
        base["private_purse"] = {
            "enabled": bool(pp.get("enabled", False)),
            "total_transferred": max(0, _ip_int(pp, "total_transferred", 0)),
            "last_transfer_period": max(0, _ip_int(pp, "last_transfer_period", 0)),
            "transfer_logs": [str(x) for x in pp.get("transfer_logs", [])[-30:]]
            if isinstance(pp.get("transfer_logs"), list) else [],
        }
    # performance_reviews
    pr = data.get("performance_reviews")
    if isinstance(pr, dict):
        history = [x for x in pr.get("history", []) if isinstance(x, dict)][:12] \
            if isinstance(pr.get("history"), list) else []
        base["performance_reviews"] = {
            "last_review": max(0, _ip_int(pr, "last_review", 0)),
            "score": _ip_int(pr, "score", 0),
            "grade": str(pr.get("grade", "")),
            "next_review": max(0, _ip_int(pr, "next_review", 30)),
            "history": history,
        }
    # projects
    pj = data.get("projects")
    if isinstance(pj, dict):
        for name in base["projects"]:
            src = pj.get(name)
            if not isinstance(src, dict):
                continue
            dst = base["projects"][name]
            for attr in ("level", "invested", "income_per_period", "status_periods"):
                dst[attr] = max(0, _ip_int(src, attr, 0))
            dst["level"] = min(5, dst["level"])
            status = src.get("status")
            if status in ("正常", "丰收", "灾荒", "贪墨"):
                dst["status"] = status
    # last_funding_period（奏请内帑同旬限制）
    base["last_funding_period"] = data.get("last_funding_period")
    return base


def default_court_faction_favor():
    """三派好感默认各 50。"""
    return {name: 50 for name in COURT_FACTIONS}


def normalize_court_faction_favor(data):
    """归一化朝堂好感度字典，缺失的派系补 50，非法值裁剪到 0–100。"""
    base = default_court_faction_favor()
    if isinstance(data, dict):
        for name in COURT_FACTIONS:
            try:
                base[name] = max(0, min(100, int(data.get(name, 50))))
            except (TypeError, ValueError):
                base[name] = 50
    return base


def normalize_rank_name(rank_name):
    """把旧的四妃「位份」名归一化为「妃」（方案 B：四妃改为妃的封号）。"""
    if rank_name in _LEGACY_FOUR_CONSORT_RANKS:
        return "妃"
    return rank_name

def legacy_four_consort_title(rank_name):
    """旧四妃位份名 → 对应封号字（用于存档迁移）。非四妃返回 None。"""
    return _LEGACY_FOUR_CONSORT_RANKS.get(rank_name)

def is_four_consort_title(nobletitle):
    """封号是否为四妃专属封号（淑/德/贤/宸）。"""
    return nobletitle in FOUR_CONSORT_TITLES

def get_rank_power(rank_name, nobletitle=None):
    """位份实力：妃 < 带普通封号的妃 < 四妃封号的妃（淑/德/贤/宸）。"""
    rank_name = normalize_rank_name(rank_name)
    if rank_name == "妃" and nobletitle:
        return FOUR_CONSORT_POWER if is_four_consort_title(nobletitle) else TITLED_CONSORT_POWER
    return RANK_POWER.get(rank_name, 0)

def is_titled_consort(rank_name, nobletitle=None):
    return rank_name == "妃" and nobletitle

class Rank(Enum):
    宫女 = 0
    更衣 = 1
    官女子 = 2
    秀女 = 3
    答应 = 4
    常在 = 5
    贵人 = 6
    才人 = 7
    美人 = 8
    婕妤 = 9
    嫔 = 10
    妃 = 11
    贵妃 = 12
    皇贵妃 = 13
    皇后 = 14

class EmperorPersonality(Enum):
    明君 = "明君"
    昏君 = "昏君"
    痴情 = "痴情"
    多疑 = "多疑"

class Storyline(Enum):
    主线 = "主线"
    爱情线 = "爱情线"
    权谋线 = "权谋线"
    自由线 = "自由线"

NOBLETITLES = [
    "贤", "淑", "德", "容", "华", "仪", "婉", "柔", "娴", "静",
    "惠", "康", "庄", "和", "顺", "慈", "宁", "昭", "敬", "端",
    "良", "懿", "敏", "慧", "安", "宁", "禧", "纯", "瑾", "瑜"
]

# 普通封号池（排除四妃专属封号：淑/德/贤/宸），供「妃 + 普通封号」阶段随机取用。
ORDINARY_NOBLETITLES = [t for t in NOBLETITLES if t not in FOUR_CONSORT_TITLES]


def default_heir_status():
    return {
        "heir_id": None,
        "heir_name": "",
        "heir_mother": "",
        "regent": "",
        "regent_title": "",
        "established_at": "",
        "last_event": "",
        "deposed": [],
        "regent_active": False,
        # ---- 监国政务 ----
        "regency_active": False,        # 是否已激活监国
        "regency_merit": 0,             # 贤明值 -100 ~ 100
        "regency_events": [],           # 历次政务决策流水（最多留 20 条）
        "pending_regency_event": None,  # 当前待决政务事件
        "last_regency_input": None,     # 上次玩家进言的旬标记
        # ---- 太子成长 ----
        "heir_traits": [],              # 太子特质标签（贤明/圣君/昏聩/暴虐/爱兽…）
        "heir_affection": 50,           # 太子对玩家的亲近 0-100
        "heir_consort": None,           # 太子妃对象
        "heir_ruling_style": None,      # 治国倾向：儒家/法家/道家
        # ---- 趣味与危机事件 ----
        "heir_counters": {},            # 计数器：truancy/pets/incognito/cooking/beast…
        "pending_heir_event": None,     # 当前待决的叛逆/特殊/内宅事件
        "heir_event_log": [],           # 趣味事件流水（最多留 20 条）
        "last_special_period": None,    # 上次特殊事件的旬序号
        # ---- 不孝 / 逼宫事件链 ----
        "defiance_stage": 0,            # 0 未启动，1 冷落，2 顶撞，3 私建府邸，4 密谋逼宫
        "defiance_log": [],
        # ---- 内宅 ----
        "consort_selection": None,      # 选妃事件（候选人列表）
        "consort_harmony": 60,          # 内宅和睦度 0-100
        "consort_events": [],           # 内宅事件日志（最多留 10 条）
        "pending_consort_event": None,  # 当前待决的内宅宫斗/趣味事件
    }


def default_heir_consorts():
    """太子内宅：太子妃 1 位（dict 或 None），其余位份各为列表。"""
    return {
        "太子妃": None,
        "良娣": [],
        "良媛": [],
        "承徽": [],
        "昭训": [],
        "奉仪": [],
    }


def default_heir_consort_member(name, family="", personality="", favor=50, rank="奉仪"):
    """内宅成员标准结构。"""
    return {
        "name": name,
        "rank": rank,
        "family": family,
        "personality": personality,
        "favor": max(0, min(100, int(favor))),
        "alive": True,
        "children": [],       # 子嗣 uid 列表
        "is_pregnant": False,
        "pregnancy_period": 0,
        "faction": "",
        "fun_tag": "",
        "talent": 50,
        "looks": 50,
        "entered_at": "",
    }


def normalize_heir_consorts(data):
    """归一化内宅字典，兼容旧存档缺字段 / 结构错乱。"""
    base = default_heir_consorts()
    if not isinstance(data, dict):
        return base

    def clean_member(raw, rank):
        if not isinstance(raw, dict):
            return None
        member = default_heir_consort_member(str(raw.get("name") or "无名"), rank=rank)
        member.update({k: v for k, v in raw.items() if k in member})
        member["rank"] = rank
        try:
            member["favor"] = max(0, min(100, int(raw.get("favor", 50))))
        except (TypeError, ValueError):
            member["favor"] = 50
        member["alive"] = bool(raw.get("alive", True))
        member["children"] = [str(x) for x in raw.get("children", [])] if isinstance(raw.get("children"), list) else []
        member["is_pregnant"] = bool(raw.get("is_pregnant", False))
        try:
            member["pregnancy_period"] = max(0, int(raw.get("pregnancy_period", 0) or 0))
        except (TypeError, ValueError):
            member["pregnancy_period"] = 0
        return member

    consort = clean_member(data.get("太子妃"), "太子妃")
    base["太子妃"] = consort
    for rank in ("良娣", "良媛", "承徽", "昭训", "奉仪"):
        raw_list = data.get(rank, [])
        if not isinstance(raw_list, list):
            raw_list = []
        cleaned = []
        for raw in raw_list:
            member = clean_member(raw, rank)
            if member:
                cleaned.append(member)
        base[rank] = cleaned
    return base


def normalize_heir_status(data):
    """归一化储君状态，缺失字段一律补默认值（旧存档兼容）。"""
    base = default_heir_status()
    if isinstance(data, dict):
        base.update({k: v for k, v in data.items() if k in base})
    # 列表 / 字典型字段防御
    for key in ("deposed", "regency_events", "heir_traits", "heir_event_log",
                "defiance_log", "consort_events"):
        if not isinstance(base.get(key), list):
            base[key] = []
    if not isinstance(base.get("heir_counters"), dict):
        base["heir_counters"] = {}
    for key, lo, hi, default in (
        ("regency_merit", -100, 100, 0),
        ("heir_affection", 0, 100, 50),
        ("consort_harmony", 0, 100, 60),
        ("defiance_stage", 0, 4, 0),
    ):
        try:
            base[key] = max(lo, min(hi, int(base.get(key, default))))
        except (TypeError, ValueError):
            base[key] = default
    base["regency_active"] = bool(base.get("regency_active", False))
    if base.get("heir_ruling_style") not in ("儒家", "法家", "道家", None):
        base["heir_ruling_style"] = None
    return base


def default_heir_race():
    """夺嫡暗流默认状态：未激活、无候选、无势头。"""
    return {
        "active": False,
        "candidates": [],
        "momentum": {},
        "events": [],
        "outcome": None,
    }


def normalize_heir_race(data):
    """归一化夺嫡状态字典，兼容旧存档缺字段。"""
    base = default_heir_race()
    if isinstance(data, dict):
        base["active"] = bool(data.get("active", False))
        cand = data.get("candidates", [])
        base["candidates"] = [str(x) for x in cand] if isinstance(cand, list) else []
        mo = data.get("momentum", {})
        if isinstance(mo, dict):
            clean = {}
            for k, v in mo.items():
                try:
                    clean[str(k)] = max(0, min(100, int(v)))
                except (TypeError, ValueError):
                    continue
            base["momentum"] = clean
        ev = data.get("events", [])
        base["events"] = list(ev) if isinstance(ev, list) else []
        outcome = data.get("outcome")
        base["outcome"] = outcome if outcome in (None, "settled") else None
    return base


class Servant:
    def __init__(self, name, type_, loyalty=50, skill=30, age=None):
        self.name = name
        self.type = type_
        self.loyalty = loyalty
        self.skill = skill
        self.age = age if age is not None else random.randint(16, 28)
        self.is_active = True
        self.hire_day = 0
        # 心腹系统：是否具备立为心腹的潜质（默认 True，个别宫人可禁用）
        self.has_confidant_potential = True
    def to_dict(self):
        return {"name": self.name, "type": self.type, "loyalty": self.loyalty, "skill": self.skill, "age": self.age, "is_active": self.is_active, "hire_day": self.hire_day, "has_confidant_potential": getattr(self, "has_confidant_potential", True)}
    @classmethod
    def from_dict(cls, data):
        s = cls(data["name"], data["type"], data["loyalty"], data["skill"], data.get("age"))
        s.is_active = data.get("is_active", True)
        s.hire_day = data.get("hire_day", 0)
        s.has_confidant_potential = data.get("has_confidant_potential", True)
        return s

class GameState:
    # 属性上限配置
    ATTR_MAX = {
        "容貌": 100,
        "才情": 100,
        "心计": 100,
        "宠爱": 999,
        "威望": 3000,
        "健康": 100,
        "才艺": 100,
        "谋略": 100,
        "魅力": 100,
        "福运": 100,
        "倾向": 100
    }

    def __init__(self, player_id, start_rank=Rank.秀女):
        self.player_id = player_id
        self.rank = start_rank
        self.nobletitle = None
        self.name = "未命名"
        self.family_background = "未知"
        self.family_meta = {}
        self.appearance = ""
        self.talent = ""
        self.personality = ""
        self.background_desc = ""
        self.traits = []
        self.custom_story = ""
        self.age = 16
        self.current_time = "辰时"
        # 日历
        self.day = 1
        self.month = 1
        self.year = 1
        # 行动点
        self.max_actions = 7
        self.remaining_actions = 7

        # 属性初始化
        self.attributes = {
            "容貌": 60,
            "才情": 50,
            "心计": 40,
            "宠爱": 30,
            "威望": 20,
            "健康": 80,
            "才艺": 40,
            "谋略": 35,
            "魅力": 45,
            "福运": 30,
            "倾向": 35
        }
        self.silver = 100
        self.servants = []
        self.max_servants = 6 + self.rank.value // 2
        self.relationships = {}
        self.story_flags = []
        self.main_story_progress = 0
        self.storyline = Storyline.主线
        self.ending_unlocked = None
        self.ending = None  # 结局落定后为字典，见 endings.py
        self.neglect_periods = 0  # 连续失宠旬数，达阈值打入冷宫
        self.inventory = []
        self.important_memories = []
        self.history = []
        self.attr_change_log = []
        self.romance_mode = False
        self.custom_prompt = ""
        self.is_pregnant = False
        self.pregnancy_month = 0
        self.monthly_intimacy = 0
        self.children = []
        self.has_children = False
        self.rivalries = {}
        self.alliances = {}
        self.intrigue = {"heat": 0, "rumors": [], "dirt": {}, "last_action": None}
        # 皇后协理六宫：每旬独立计数，旧存档缺字段时由后端按默认值兼容。
        self.queen_authority_period = None
        self.queen_authority_uses = 0
        self.queen_assistance_count = 0
        self.six_palace_assistant = None
        self.honorary_title = None
        self.child_uid_seq = 1
        self.heir_status = default_heir_status()
        # 选秀系统：None 或 {"active","scale","started_key","candidates","player_influenced"}
        self.draft = None
        # 妃嫔举荐秀女系统（见 recommend_system.py / RECOMMEND_SYSTEM.md）
        self.recommendations = {
            "player_used": 0, "player_max": 2, "edition": None, "cooldown_left": 0,
            "npc_recommendations": [], "recommendation_history": [], "dowager_plea_edition": None,
        }
        # 宗室系统（见 royal_clan.py / ROYAL_CLAN.md）
        self.royal_clan = {"seeded": False}
        # 冷宫系统（见 cold_palace.py / COLD_PALACE.md）
        self.cold_palace = {"inmates": {}, "events": [],
                            "environment": {"条件": "恶劣", "看守类型": "严厉", "银两储备": 0},
                            "player": None, "log": []}
        # 出轨/私通 + 狸猫换子（见 affair_system.py / AFFAIR_SYSTEM.md）
        self.secret_relationships = {
            "player": [], "npc": {}, "hidden_npc": {},
            "swap": {"phase": None, "内应": "", "孕旬": 0, "child_uid": "", "真实父母": {},
                     "知情者": [], "风险值": 0, "案发": False, "揭穿": False},
            "risk_log": [],
        }
        # 东宫内宅（太子妃 + 五级侧室）
        self.heir_consorts = default_heir_consorts()
        # 心腹系统：心腹宫人名字 + 心腹关键事件（最多20条）
        self.confidant = None
        self.confidant_memory = []
        # 重华宫与陷害系统新属性
        # chonghua.children 保存在馆子嗣的 uid 列表；log/events 为流水记录
        self.chonghua = {"founded": False, "level": 1, "budget": 0, "children": [], "log": [], "events": []}
        self.frameups = {"seq": 1, "cases": [], "log": []}
        # 公主择婿——三大朝堂势力好感度（默认各 50）
        self.court_faction_favor = default_court_faction_favor()
        # 夺嫡暗流——储君空悬时的多方博弈
        self.heir_race = default_heir_race()
        # 子嗣标签事件队列 + 协理六宫事件（每旬 1~2 件，队列 max2）
        self.child_event_queue = []
        self.governance_events = []
        self.governance_history = []
        self.governance_cooldown = 0
        self.governance_handled_streak = 0
        # 前朝关联系统：玩家家族 + 前朝总览（NPC 家族挂在 npcs[name]["clan"]）
        self.player_clan = None
        self.family_event_queue = []    # 待处理的家族事件（弹窗）
        self.family_event_history = []  # 已处置的家族事件历史（最多20条）
        # NPC 妃嫔关系网：{A: {B: {好感, 印象, 关系类型, 历史事件, 最后互动旬}}}
        self.npc_relationships = {}
        self.relationship_events = []   # 待推送的关系变化事件
        self.relationship_log = []      # 关系变化历史日志（最多40条）
        # 内务府自治系统
        self.inner_palace = default_inner_palace()
        # 内务府总管派系（顶层冗余，便于其他系统直接读取）
        self.chief_faction = "中立"
        self.emperor = {
            "name": "萧景琰",
            "personality": random.choice([p.value for p in EmperorPersonality]),
            "age": random.randint(25, 55),
            "health": random.randint(76, 94),
            "succession_pressure": 0,
            "illness_stage": "安康",
            "stats": {"威严": random.randint(40, 90), "仁德": random.randint(30, 85), "勤政": random.randint(30, 85), "好色": random.randint(10, 80)},
            "favor_factors": {"明君": {"容貌": 0.2, "才情": 0.5, "心计": 0.3}, "昏君": {"容貌": 0.8, "才情": 0.1, "心计": 0.1}, "痴情": {"容貌": 0.3, "才情": 0.3, "心计": 0.4}, "多疑": {"容貌": 0.2, "才情": 0.2, "心计": 0.6}}
        }
        self.npcs = {}
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        # 本旬晋升标志（晋升已改为自动触发，无选择事件）
        self._promotion_done = False
        self.scandal_strikes = 0  # 宫斗丑闻累积，满则更易降位
        self.rank_periods = 0  # 现任位份已历旬数（资历）
        self.last_duel_period = None
        self._active_duel = None
        self.client_id = None
        # 太后掌权线
        self.dowager_mode = False          # 是否进入太后模式
        self.regency_authority = 0         # 摄政权威 0-100
        self.court_power = 50              # 朝堂控制力 0-100
        self.dowager_periods = 0           # 太后掌权已历旬数
        self.new_emperor = {               # 新帝（你的子嗣）
            "name": "",
            "age": 1,
            "personality": "仁厚",
            "health": 80,
            "stats": {"威严": 40, "仁德": 60, "勤政": 50, "好色": 20},
            "alive": True,
        }
        self.last_court_event = ""
        self.dowager_ending_triggered = False

    def get_attr_max(self, attr_name):
        return self.ATTR_MAX.get(attr_name, 100)

    def get_attr_percentage(self, attr_name):
        val = self.attributes.get(attr_name, 0)
        max_val = self.get_attr_max(attr_name)
        return min(100, int((val / max_val) * 100)) if max_val > 0 else 0

    # 日历方法：每次推进 10 天（一旬）
    def advance_calendar(self):
        self.day += 10
        while self.day > 30:
            self.day -= 30
            self.month += 1
            if self.month > 12:
                self.month = 1
                self.year += 1

    def get_calendar_str(self):
        if self.day <= 10:
            period = "上旬"
        elif self.day <= 20:
            period = "中旬"
        else:
            period = "下旬"
        return f"建元{self.year}年{self.month}月{period}"

    def get_full_date_str(self):
        return f"建元{self.year}年{self.month}月{self.day}日"

    # 行动点方法
    def reset_actions(self):
        self.remaining_actions = self.max_actions

    def can_act(self):
        return self.remaining_actions > 0

    def consume_action(self):
        if self.remaining_actions <= 0:
            return False
        self.remaining_actions -= 1
        return True

    # 其他方法
    def get_emperor_factor(self):
        personality = self.emperor["personality"]
        return self.emperor["favor_factors"].get(personality, self.emperor["favor_factors"]["明君"])

    def get_display_rank(self):
        if getattr(self, "honorary_title", None):
            return self.honorary_title
        if self.nobletitle:
            return f"{self.nobletitle}{self.rank.name}"
        return self.rank.name

    def grant_nobletitle(self):
        favor = self.attributes.get("宠爱", 0)
        prestige = self.attributes.get("威望", 0)
        rank_order = [
            "宫女", "更衣", "官女子", "秀女", "答应", "常在", "贵人", "才人", "美人", "婕妤",
            "嫔", "妃", "贵妃", "皇贵妃", "皇后",
        ]
        current_idx = rank_order.index(self.rank.name) if self.rank.name in rank_order else 0
        if current_idx >= rank_order.index("贵人") and favor >= 65 and prestige >= 55:
            if self.rank.name != "妃":
                return None
            if self.nobletitle:
                if random.random() < 0.2:
                    new_title = random.choice(NOBLETITLES)
                    while new_title == self.nobletitle:
                        new_title = random.choice(NOBLETITLES)
                    old_title = self.nobletitle
                    self.nobletitle = new_title
                    return f"封号更换：『{old_title}』→『{new_title}』"
                return None
            else:
                self.nobletitle = random.choice(NOBLETITLES)
                return f"皇帝赐封号：『{self.nobletitle}』"
        return None

    def add_servant(self, servant):
        if len(self.servants) >= self.max_servants:
            return False, "已有太多宫女太监，需先遣散一些。"
        servant.hire_day = self.day
        self.servants.append(servant)
        return True, f"招募了{servant.name}（{servant.type}）"

    def remove_servant(self, name):
        for i, s in enumerate(self.servants):
            if s.name == name and s.is_active:
                s.is_active = False
                self.servants.pop(i)
                return True, f"遣散了{name}"
        return False, "未找到该宫女/太监"

    def get_active_servants(self):
        return [s for s in self.servants if s.is_active]

    def add_attr_change(self, changes, reason=""):
        self.attr_change_log.append({"day": self.day, "time": self.current_time, "changes": changes.copy(), "reason": reason})
        if len(self.attr_change_log) > 50:
            self.attr_change_log.pop(0)

    def add_memory(self, event):
        self.important_memories.append(f"[第{self.day}天] {event}")
        if len(self.important_memories) > 20:
            self.important_memories.pop(0)

    def get_recent_memories(self, count=3):
        return self.important_memories[-count:] if self.important_memories else []

    def to_dict(self):
        return {
            "player_id": self.player_id,
            "rank": self.rank.name,
            "nobletitle": self.nobletitle,
            "honorary_title": getattr(self, "honorary_title", None),
            "display_rank": self.get_display_rank(),
            "name": self.name,
            "family_background": self.family_background,
            "family_meta": getattr(self, "family_meta", {}),
            "appearance": getattr(self, "appearance", ""),
            "talent": getattr(self, "talent", ""),
            "personality": getattr(self, "personality", ""),
            "background_desc": getattr(self, "background_desc", ""),
            "traits": getattr(self, "traits", []),
            "custom_story": getattr(self, "custom_story", ""),
            "age": max(12, min(80, int(getattr(self, "age", 16) or 16))),
            "current_time": self.current_time,
            "day": self.day,
            "month": self.month,
            "year": self.year,
            "calendar_str": self.get_calendar_str(),
            "max_actions": self.max_actions,
            "remaining_actions": self.remaining_actions,
            "attributes": self.attributes,
            "attr_max": self.ATTR_MAX,
            "relationships": self.relationships,
            "story_flags": self.story_flags,
            "main_story_progress": self.main_story_progress,
            "storyline": self.storyline.value,
            "ending": getattr(self, "ending", None),
            "ending_unlocked": getattr(self, "ending_unlocked", None),
            "neglect_periods": getattr(self, "neglect_periods", 0),
            "inventory": self.inventory,
            "silver": self.silver,
            "important_memories": self.important_memories,
            "history": self.history[-50:],
            "emperor": self.emperor,
            "npcs": self.npcs,
            "servants": [s.to_dict() for s in self.get_active_servants()],
            "is_pregnant": self.is_pregnant,
            "pregnancy_month": self.pregnancy_month,
            "monthly_intimacy": getattr(self, "monthly_intimacy", 0),
            "children": self.children,
            "has_children": self.has_children,
            "rivalries": self.rivalries,
            "alliances": self.alliances,
            "intrigue": getattr(self, "intrigue", {"heat": 0, "rumors": [], "dirt": {}, "last_action": None}),
            "queen_authority_period": getattr(self, "queen_authority_period", None),
            "queen_authority_uses": getattr(self, "queen_authority_uses", 0),
            "queen_assistance_count": getattr(self, "queen_assistance_count", 0),
            "six_palace_assistant": getattr(self, "six_palace_assistant", None),
            "child_uid_seq": getattr(self, "child_uid_seq", 1),
            "heir_status": normalize_heir_status(getattr(self, "heir_status", None)),
            "draft": getattr(self, "draft", None),
            "recommendations": getattr(self, "recommendations", {}),
            "royal_clan": getattr(self, "royal_clan", {}),
            "cold_palace": getattr(self, "cold_palace", {}),
            "secret_relationships": getattr(self, "secret_relationships", {}),
            "heir_consorts": normalize_heir_consorts(getattr(self, "heir_consorts", None)),
            "chonghua": getattr(self, "chonghua", {"founded": False, "level": 1, "budget": 0, "children": [], "log": [], "events": []}),
            "frameups": getattr(self, "frameups", {"seq": 1, "cases": [], "log": []}),
            "court_faction_favor": normalize_court_faction_favor(getattr(self, "court_faction_favor", None)),
            "heir_race": normalize_heir_race(getattr(self, "heir_race", None)),
            "child_event_queue": getattr(self, "child_event_queue", []),
            "governance_events": getattr(self, "governance_events", []),
            "governance_history": getattr(self, "governance_history", [])[-30:],
            "governance_cooldown": getattr(self, "governance_cooldown", 0),
            "governance_handled_streak": getattr(self, "governance_handled_streak", 0),
            "family_event_queue": getattr(self, "family_event_queue", []),
            "family_event_history": getattr(self, "family_event_history", [])[-20:],
            "npc_relationships": getattr(self, "npc_relationships", {}),
            "relationship_events": getattr(self, "relationship_events", []),
            "relationship_log": getattr(self, "relationship_log", [])[-40:],
            "inner_palace": normalize_inner_palace(getattr(self, "inner_palace", None)),
            "chief_faction": getattr(self, "chief_faction", "中立"),
            "confidant": getattr(self, "confidant", None),
            "confidant_memory": getattr(self, "confidant_memory", [])[-20:],
            "player_clan": getattr(self, "player_clan", None),
            "attr_change_log": self.attr_change_log[-20:],
            "romance_mode": self.romance_mode,
            "custom_prompt": self.custom_prompt,
            "last_duel_period": getattr(self, "last_duel_period", None),
            "scandal_strikes": getattr(self, "scandal_strikes", 0),
            "rank_periods": getattr(self, "rank_periods", 0),
            "client_id": getattr(self, "client_id", None),
            "dowager_mode": getattr(self, "dowager_mode", False),
            "regency_authority": getattr(self, "regency_authority", 0),
            "court_power": getattr(self, "court_power", 50),
            "dowager_periods": getattr(self, "dowager_periods", 0),
            "new_emperor": getattr(self, "new_emperor", None),
            "last_court_event": getattr(self, "last_court_event", ""),
            "dowager_ending_triggered": getattr(self, "dowager_ending_triggered", False),
            "created_at": self.created_at,
            "updated_at": datetime.now().isoformat()
        }

    def to_save_data(self):
        return {"version": "1.5", "save_time": datetime.now().isoformat(), "game_state": self.to_dict()}

    @classmethod
    def from_save_data(cls, save_data):
        try:
            data = save_data.get("game_state", save_data)
            raw_rank_name = data.get("rank", "秀女")
            # 方案 B 迁移：旧四妃「位份」→ 妃 + 对应封号
            migrated_four_title = legacy_four_consort_title(raw_rank_name)
            rank_name = normalize_rank_name(raw_rank_name)
            try:
                rank = Rank[rank_name]
            except KeyError:
                rank = Rank.秀女
            player_id = data.get("player_id", "unknown")
            game_state = cls(player_id, rank)
            game_state.name = data.get("name", "未命名")
            game_state.family_background = data.get("family_background", "未知")
            game_state.family_meta = data.get("family_meta", {})
            game_state.appearance = data.get("appearance", "")
            game_state.talent = data.get("talent", "")
            game_state.personality = data.get("personality", "")
            game_state.background_desc = data.get("background_desc", "")
            game_state.traits = data.get("traits", [])
            game_state.custom_story = data.get("custom_story", "")
            try:
                game_state.age = int(data.get("age", 16) or 16)
            except (TypeError, ValueError):
                game_state.age = 16
            game_state.age = max(12, min(80, game_state.age))
            game_state.current_time = data.get("current_time", "辰时")
            game_state.day = data.get("day", 1)
            game_state.month = data.get("month", 1)
            game_state.year = data.get("year", 1)
            game_state.nobletitle = data.get("nobletitle")
            # 方案 B 迁移：旧四妃位份的玩家，其封号改为对应四妃封号
            if migrated_four_title:
                game_state.nobletitle = migrated_four_title
            game_state.honorary_title = data.get("honorary_title")
            game_state.romance_mode = data.get("romance_mode", False)
            game_state.custom_prompt = data.get("custom_prompt", "")
            saved_attrs = data.get("attributes", {})
            default_attrs = {"容貌": 60, "才情": 50, "心计": 40, "宠爱": 30, "威望": 20, "健康": 80, "才艺": 40, "谋略": 35, "魅力": 45, "福运": 30, "倾向": 35}
            for key, default_val in default_attrs.items():
                game_state.attributes[key] = saved_attrs.get(key, default_val)
            game_state.silver = data.get("silver", 100)
            game_state.relationships = data.get("relationships", {})
            game_state.story_flags = data.get("story_flags", [])
            game_state.main_story_progress = data.get("main_story_progress", 0)
            game_state.inventory = data.get("inventory", [])
            game_state.important_memories = data.get("important_memories", [])
            game_state.history = data.get("history", [])
            game_state.attr_change_log = data.get("attr_change_log", [])
            game_state.emperor = data.get("emperor", {"name": "萧景琰", "personality": "明君", "age": 35, "stats": {"威严": 60, "仁德": 50, "勤政": 50, "好色": 40}, "favor_factors": {"明君": {"容貌": 0.2, "才情": 0.5, "心计": 0.3}, "昏君": {"容貌": 0.8, "才情": 0.1, "心计": 0.1}, "痴情": {"容貌": 0.3, "才情": 0.3, "心计": 0.4}, "多疑": {"容貌": 0.2, "才情": 0.2, "心计": 0.6}}})
            game_state.npcs = data.get("npcs", {})
            for npc in game_state.npcs.values():
                if "rank" in npc:
                    # 方案 B 迁移：旧四妃位份的 NPC → 妃 + 对应封号
                    _legacy_title = legacy_four_consort_title(npc["rank"])
                    if _legacy_title and not npc.get("nobletitle"):
                        npc["nobletitle"] = _legacy_title
                    npc["rank"] = normalize_rank_name(npc["rank"])
            servants_data = data.get("servants", [])
            game_state.servants = []
            for sd in servants_data:
                s = Servant.from_dict(sd)
                game_state.servants.append(s)
            # 心腹系统：还原心腹指向（旧存档可能缺失字段；若心腹已不在则清空）
            saved_confidant = data.get("confidant")
            game_state.confidant = None
            if saved_confidant:
                for _cs in game_state.servants:
                    if _cs.name == saved_confidant and _cs.is_active:
                        game_state.confidant = saved_confidant
                        break
            cm = data.get("confidant_memory", [])
            game_state.confidant_memory = [str(x) for x in cm][-20:] if isinstance(cm, list) else []
            # 前朝关联系统：还原玩家家族与前朝总览（旧存档缺失时置空，由 app 层兜底生成）
            game_state.player_clan = data.get("player_clan") if isinstance(data.get("player_clan"), dict) else None
            game_state.max_servants = 6 + game_state.rank.value // 2
            game_state.is_pregnant = data.get("is_pregnant", False)
            game_state.pregnancy_month = data.get("pregnancy_month", 0)
            game_state.monthly_intimacy = data.get("monthly_intimacy", 0)
            game_state.children = data.get("children", [])
            game_state.has_children = data.get("has_children", False)
            game_state.rivalries = data.get("rivalries", {})
            game_state.alliances = data.get("alliances", {})
            intrigue = data.get("intrigue", {}) or {}
            game_state.intrigue = {
                "heat": int(intrigue.get("heat", 0) or 0),
                "rumors": intrigue.get("rumors", []) if isinstance(intrigue.get("rumors", []), list) else [],
                "dirt": intrigue.get("dirt", {}) if isinstance(intrigue.get("dirt", {}), dict) else {},
                "last_action": intrigue.get("last_action"),
            }
            game_state.queen_authority_period = data.get("queen_authority_period")
            game_state.queen_authority_uses = data.get("queen_authority_uses", 0)
            game_state.queen_assistance_count = data.get("queen_assistance_count", 0)
            game_state.six_palace_assistant = data.get("six_palace_assistant")
            game_state.chonghua = data.get("chonghua", {"founded": False, "level": 1, "budget": 0, "children": [], "log": [], "events": []})
            game_state.frameups = data.get("frameups", {"seq": 1, "cases": [], "log": []})
            game_state.court_faction_favor = normalize_court_faction_favor(data.get("court_faction_favor"))
            game_state.heir_race = normalize_heir_race(data.get("heir_race"))
            ceq = data.get("child_event_queue")
            game_state.child_event_queue = ceq if isinstance(ceq, list) else []
            ge = data.get("governance_events")
            game_state.governance_events = ge if isinstance(ge, list) else []
            gh = data.get("governance_history")
            game_state.governance_history = gh[-30:] if isinstance(gh, list) else []
            try:
                game_state.governance_cooldown = int(data.get("governance_cooldown", 0) or 0)
            except (TypeError, ValueError):
                game_state.governance_cooldown = 0
            try:
                game_state.governance_handled_streak = int(data.get("governance_handled_streak", 0) or 0)
            except (TypeError, ValueError):
                game_state.governance_handled_streak = 0
            feq = data.get("family_event_queue")
            game_state.family_event_queue = feq if isinstance(feq, list) else []
            feh = data.get("family_event_history")
            game_state.family_event_history = feh[-20:] if isinstance(feh, list) else []
            nrel = data.get("npc_relationships")
            game_state.npc_relationships = nrel if isinstance(nrel, dict) else {}
            rel_ev = data.get("relationship_events")
            game_state.relationship_events = rel_ev if isinstance(rel_ev, list) else []
            rel_log = data.get("relationship_log")
            game_state.relationship_log = rel_log[-40:] if isinstance(rel_log, list) else []
            game_state.inner_palace = normalize_inner_palace(data.get("inner_palace"))
            game_state.chief_faction = data.get("chief_faction") if data.get("chief_faction") in (
                "皇后派", "太后派", "皇帝派", "中立") else "中立"
            try:
                game_state.child_uid_seq = max(1, int(data.get("child_uid_seq", 1) or 1))
            except (TypeError, ValueError):
                game_state.child_uid_seq = 1
            heir_status = data.get("heir_status") if isinstance(data.get("heir_status"), dict) else default_heir_status()
            draft = data.get("draft")
            game_state.draft = draft if isinstance(draft, dict) else None
            recs = data.get("recommendations")
            game_state.recommendations = recs if isinstance(recs, dict) else {
                "player_used": 0, "player_max": 2, "edition": None, "cooldown_left": 0,
                "npc_recommendations": [], "recommendation_history": [], "dowager_plea_edition": None,
            }
            rc_data = data.get("royal_clan")
            game_state.royal_clan = rc_data if isinstance(rc_data, dict) else {"seeded": False}
            cp_data = data.get("cold_palace")
            game_state.cold_palace = cp_data if isinstance(cp_data, dict) else {
                "inmates": {}, "events": [], "environment": {"条件": "恶劣", "看守类型": "严厉", "银两储备": 0},
                "player": None, "log": []}
            sr_data = data.get("secret_relationships")
            game_state.secret_relationships = sr_data if isinstance(sr_data, dict) else {
                "player": [], "npc": {}, "hidden_npc": {},
                "swap": {"phase": None, "内应": "", "孕旬": 0, "child_uid": "", "真实父母": {},
                         "知情者": [], "风险值": 0, "案发": False, "揭穿": False},
                "risk_log": [],
            }
            game_state.heir_status = normalize_heir_status(heir_status)
            game_state.heir_consorts = normalize_heir_consorts(data.get("heir_consorts"))
            game_state.created_at = data.get("created_at", datetime.now().isoformat())
            game_state.updated_at = datetime.now().isoformat()
            game_state.max_actions = data.get("max_actions", 7)
            game_state.remaining_actions = data.get("remaining_actions", 7)
            game_state.last_duel_period = data.get("last_duel_period")
            game_state._promotion_done = data.get("_promotion_done", False)
            game_state.scandal_strikes = data.get("scandal_strikes", 0)
            game_state.rank_periods = data.get("rank_periods", 0)
            game_state.dowager_mode = bool(data.get("dowager_mode", False))
            game_state.regency_authority = int(data.get("regency_authority", 0) or 0)
            game_state.court_power = int(data.get("court_power", 50) or 50)
            game_state.dowager_periods = int(data.get("dowager_periods", 0) or 0)
            game_state.new_emperor = data.get("new_emperor") if isinstance(data.get("new_emperor"), dict) else {
                "name": "", "age": 1, "personality": "仁厚", "health": 80,
                "stats": {"威严": 40, "仁德": 60, "勤政": 50, "好色": 20}, "alive": True
            }
            game_state.last_court_event = str(data.get("last_court_event", ""))
            game_state.dowager_ending_triggered = bool(data.get("dowager_ending_triggered", False))
            ending = data.get("ending")
            game_state.ending = ending if isinstance(ending, dict) else None
            game_state.ending_unlocked = data.get("ending_unlocked")
            try:
                game_state.neglect_periods = int(data.get("neglect_periods", 0) or 0)
            except (TypeError, ValueError):
                game_state.neglect_periods = 0
            game_state.client_id = data.get("client_id")
            storyline_value = data.get("storyline", "主线")
            for sl in Storyline:
                if sl.value == storyline_value:
                    game_state.storyline = sl
                    break
            return game_state
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise ValueError(f"恢复存档失败: {str(e)}")