# dowager_system.py — 太后垂帘听政线（新帝登基后的续章）
# 上朝奏事裁决 · 摄政权威/朝堂控制 · 新帝成长与母子博弈 · 归政/称制/失势三条出路
import random

from names import random_given, EMPEROR_GIVEN

COURT_LOG_MAX = 20
EMPEROR_ADULT_AGE = 16          # 新帝请求亲政的年龄
RETURN_POWER_GRACE = 3          # 亲政请求后可周旋的旬数
REGENCY_CRISIS_AUTH = 25        # 摄政权威跌破此值触发失势危机
EMPRESS_REGNANT_AUTH = 90       # 临朝称制（女帝）所需权威
EMPRESS_REGNANT_COURT = 85      # 临朝称制所需朝堂控制力

# 后宫治理模式（太后如何对待新帝的后宫）
HAREM_MODES = {
    "亲掌": {"name": "太后亲掌", "desc": "六宫事无大小皆决于慈宁宫；权威+，帝心-，新后怨望",
              "authority": 2, "emperor_affection": -2, "queen_favor": -3},
    "共治": {"name": "与后共治", "desc": "大事由你，细务归新后；平稳持中",
              "authority": 1, "emperor_affection": 0, "queen_favor": 1},
    "放权": {"name": "全付新后", "desc": "撤手不问，颐养天年；帝心+，新后感念，权威-",
              "authority": -2, "emperor_affection": 3, "queen_favor": 4},
}
HAREM_MODE_DEFAULT = "共治"

# 新帝性格（登基时按幼时养育定型，影响奉事反应/亲政时机/母子博弈/结局叙事）
EMPEROR_PERSONALITIES = {
    "仁厚": {
        "desc": "宽和纳谏，敬重母后",
        "affection_drift": 1,      # 每旬母子亲近自然变化
        "majesty_drift": 0,
        "authority_drift": 0,
        "adult_offset": 2,         # 请亲政的年龄偏移（+ 表示更晚）
        "seize_risk": 0.0,         # 逾期未决时提前夺权的额外概率
        "obedient": True,          # 训诫/催促时反弹更小
        "flavor": "他听你的话，哪怕心里未必情愿。",
    },
    "多疑": {
        "desc": "猜忌深重，忌母后干政",
        "affection_drift": -1,
        "majesty_drift": 1,
        "authority_drift": -1,
        "adult_offset": -2,        # 更早要亲政
        "seize_risk": 0.25,
        "obedient": False,
        "flavor": "他看你的眼神里，总藏着一层试探。",
    },
    "暴戾": {
        "desc": "刚烈嗜杀，动辄雷霆",
        "affection_drift": -1,
        "majesty_drift": 2,
        "authority_drift": -1,
        "adult_offset": -1,
        "seize_risk": 0.35,
        "obedient": False,
        "flavor": "他发怒时，殿上没有人敢抬头——包括你。",
    },
    "庸懒": {
        "desc": "疏懒惮政，乐得撒手",
        "affection_drift": 0,
        "majesty_drift": -1,
        "authority_drift": 1,
        "adult_offset": 4,         # 很晚才提亲政
        "seize_risk": 0.0,
        "obedient": True,
        "flavor": "他乐得把奏本推给你，自己去听戏。",
    },
}


def derive_emperor_personality(heir_child):
    """由子嗣五维/标签推导新帝性格（无数据时按仁厚）。"""
    c = heir_child or {}
    tags = c.get("tags") or []
    stats = c.get("stats") or {}
    xin = int(stats.get("心性", c.get("wit", 40)) or 40)
    wu = int(stats.get("武略", 40) or 40)
    wen = int(stats.get("文治", c.get("talent", 40)) or 40)
    if "孤僻" in tags or xin <= 30:
        return "多疑"
    if "尚武" in tags or wu >= 75:
        return "暴戾"
    if "娇纵" in tags or (wen <= 35 and xin <= 45):
        return "庸懒"
    return "仁厚"


def emperor_personality_spec(d):
    return EMPEROR_PERSONALITIES.get(
        (d.get("emperor") or {}).get("personality") or "仁厚",
        EMPEROR_PERSONALITIES["仁厚"],
    )


def emperor_adult_age(d):
    """该性格的新帝请求亲政的实际年龄。"""
    return max(12, EMPEROR_ADULT_AGE + int(emperor_personality_spec(d).get("adult_offset", 0)))

# 上朝奏事模板：每条三选，效果键 权威/朝堂/国库/帝心/民心/派系_x
COURT_AFFAIRS = [
    {
        "id": "border_raid", "type": "军情", "icon": "⚔️",
        "title": "北境告急",
        "desc": "北境边镇急报：胡骑犯边，掠去牛马千头。兵部请旨发兵，户部却道国库支绌。",
        "choices": [
            {"text": "发禁军三万北征", "icon": "⚔️", "effects": {"权威": 6, "国库": -300, "派系_武官党": 6, "民心": -3}},
            {"text": "遣使议和，岁赐安边", "icon": "🕊️", "effects": {"权威": -3, "国库": -120, "派系_文官党": 5, "民心": 4}},
            {"text": "命边将自守，不予增援", "icon": "🛡️", "effects": {"权威": -5, "派系_武官党": -8, "民心": -5}},
        ],
    },
    {
        "id": "tax_flood", "type": "赋税", "icon": "🌊",
        "title": "江南水患",
        "desc": "江南三州大水，田庐尽没。地方请免赋三年，户部言若允，国库将亏空过半。",
        "choices": [
            {"text": "免赋三年，开仓赈济", "icon": "🌾", "effects": {"国库": -400, "民心": 12, "权威": 4, "派系_文官党": 4}},
            {"text": "免赋一年，余者缓征", "icon": "⚖️", "effects": {"国库": -150, "民心": 5, "权威": 2}},
            {"text": "照例征收，不可开例", "icon": "📜", "effects": {"国库": 120, "民心": -12, "权威": -4}},
        ],
    },
    {
        "id": "corrupt_case", "type": "吏治", "icon": "⚖️",
        "title": "封疆大吏贪墨案",
        "desc": "御史弹劾两江总督贪墨河工银二十万两。此人是先帝旧臣，门生故吏遍布朝野。",
        "choices": [
            {"text": "下诏严办，抄没家产", "icon": "🗡️", "effects": {"权威": 8, "国库": 250, "朝堂": -6, "民心": 8}},
            {"text": "夺官留命，令其还银", "icon": "⚖️", "effects": {"权威": 3, "国库": 120, "朝堂": 2}},
            {"text": "留中不发，暗示其自请致仕", "icon": "🤫", "effects": {"权威": -4, "朝堂": 6, "民心": -6}},
        ],
    },
    {
        "id": "exam_reform", "type": "科举", "icon": "📚",
        "title": "科场舞弊",
        "desc": "本届春闱有权贵子弟夹带,已成众矢之的。士林哗然，宗室却为其请托。",
        "choices": [
            {"text": "彻查重考，褫夺功名", "icon": "📚", "effects": {"权威": 6, "派系_文官党": 8, "派系_宗室党": -8, "民心": 8}},
            {"text": "只黜首恶，余者不问", "icon": "⚖️", "effects": {"权威": 2, "派系_文官党": 3, "朝堂": 2}},
            {"text": "压下此事，安抚宗室", "icon": "🏵️", "effects": {"权威": -5, "派系_宗室党": 8, "派系_文官党": -8, "民心": -8}},
        ],
    },
    {
        "id": "clan_title", "type": "宗室", "icon": "🏵️",
        "title": "宗室请封",
        "desc": "数位宗室联名上表，请为新帝叔伯加封亲王、增食邑，言此乃「皇室体面」。",
        "choices": [
            {"text": "择贤者一人加封", "icon": "🏵️", "effects": {"权威": 3, "国库": -100, "派系_宗室党": 6, "朝堂": 3}},
            {"text": "一概驳回，宗室不可骄纵", "icon": "🚫", "effects": {"权威": 5, "派系_宗室党": -10, "朝堂": -4}},
            {"text": "尽数准奏，广施恩泽", "icon": "🎁", "effects": {"权威": -4, "国库": -350, "派系_宗室党": 12}},
        ],
    },
    {
        "id": "emperor_study", "type": "帝学", "icon": "📖",
        "title": "新帝课业",
        "desc": "太傅奏称新帝近来懈于经史，常以「母后自会料理」为辞推诿。",
        "choices": [
            {"text": "严词训诲，加课加责", "icon": "📖", "effects": {"帝心": -6, "帝威": 6, "权威": 3}},
            {"text": "温言劝勉，寓教于游", "icon": "🌿", "effects": {"帝心": 8, "帝威": 2}},
            {"text": "由他去罢，朝政有我", "icon": "🫱", "effects": {"帝心": 3, "帝威": -8, "权威": 5}},
        ],
    },
    {
        "id": "eunuch_power", "type": "内廷", "icon": "🕯️",
        "title": "内侍干政",
        "desc": "司礼监掌印以传旨为名擅改票拟，外朝已有怨言，然此人是你垂帘之初的心腹。",
        "choices": [
            {"text": "杖毙以正朝纲", "icon": "🗡️", "effects": {"权威": 4, "朝堂": 8, "民心": 4}},
            {"text": "调外任职，体面收权", "icon": "📜", "effects": {"权威": 2, "朝堂": 4}},
            {"text": "留用如故，正需其耳目", "icon": "🕯️", "effects": {"权威": 3, "朝堂": -8, "民心": -5}},
        ],
    },
    {
        "id": "return_power_hint", "type": "朝议", "icon": "👑",
        "title": "还政之议",
        "desc": "有大臣于朝会试探：「陛下渐长，太后垂帘辛劳，可否择日还政？」满殿寂然，都在看你脸色。",
        "choices": [
            {"text": "允议，着礼部拟还政仪注", "icon": "👑", "effects": {"权威": -8, "帝心": 12, "朝堂": 6, "民心": 6}},
            {"text": "斥其妄言，帘幕不动", "icon": "🚫", "effects": {"权威": 6, "帝心": -8, "朝堂": -6}},
            {"text": "含糊其辞，容后再议", "icon": "🤫", "effects": {"权威": 1, "帝心": -2}},
        ],
    },
]

# 垂帘期三方势力干政（外戚=你的家族 / 宗室=royal_clan / 权臣=朝堂重臣）
MEDDLE_KINDS = {
    "外戚": {"icon": "🏠", "who": "母家"},
    "宗室": {"icon": "🏵️", "who": "宗室"},
    "权臣": {"icon": "⚖️", "who": "权臣"},
}
MINISTER_NAMES = ["张", "李", "王", "沈", "崔", "裴", "杨", "韩"]
MINISTER_TITLES = ["内阁首辅", "吏部尚书", "兵部尚书", "都察院左都御史", "户部尚书"]
# ===== 女帝称制期 =====
REGNANT_YEARS_TO_LEGACY = 12      # 称制满此旬数可从容传位（善终）
REGNANT_STABILITY_CRISIS = 25     # 朝局稳固跌破此值则有倾覆之危

REGNANT_AGENDA = [
    {
        "id": "change_name", "title": "改制易号",
        "desc": "礼部请旨：既已称制，宜改国号、易衣冠、定新历，以正天命。",
        "choices": [
            {"text": "大改国号，另立新朝", "effects": {"稳固": -8, "威权": 10, "民心": -5, "青史": 8}},
            {"text": "仍用旧号，只改年号", "effects": {"稳固": 4, "威权": 3, "民心": 2, "青史": 2}},
            {"text": "一切照旧，不事更张", "effects": {"稳固": 6, "威权": -3, "民心": 3}},
        ],
    },
    {
        "id": "female_officials", "title": "开女科",
        "desc": "有臣上疏：既有女主，何妨开女科取士，使天下才女得列朝班。",
        "choices": [
            {"text": "准开女科，破千年例", "effects": {"稳固": -6, "威权": 6, "民心": 6, "青史": 12}},
            {"text": "只设内学，教而不仕", "effects": {"稳固": 2, "民心": 3, "青史": 4}},
            {"text": "驳回，恐骇物听", "effects": {"稳固": 5, "威权": -2, "青史": -3}},
        ],
    },
    {
        "id": "old_emperor", "title": "旧帝安置",
        "desc": "被你取而代之的那位——你亲手抚养大的孩子——如今幽居别宫。朝臣问：何以处之？",
        "choices": [
            {"text": "尊为太上，优礼奉养", "effects": {"稳固": 6, "民心": 8, "青史": 6, "威权": -2}},
            {"text": "废为亲王，迁出京师", "effects": {"稳固": 3, "威权": 4, "民心": -4, "青史": -4}},
            {"text": "一杯酒了结此事", "effects": {"稳固": -4, "威权": 8, "民心": -12, "青史": -15}},
        ],
    },
    {
        "id": "regnant_consort", "title": "内廷侍奉",
        "desc": "内侍省奏请：女主临朝，内廷侍奉之制当有定例——是否遴选年少俊秀入侍？",
        "choices": [
            {"text": "依前朝故事，设内侍之班", "effects": {"稳固": -5, "威权": 5, "民心": -6, "青史": -5}},
            {"text": "只置女官，不设男侍", "effects": {"稳固": 4, "民心": 4, "青史": 3}},
            {"text": "内廷从简，专心政事", "effects": {"稳固": 5, "威权": 2, "青史": 5}},
        ],
    },
    {
        "id": "regnant_heir", "title": "立储之议",
        "desc": "你已称制，储位空悬。是立自己的血脉，还是从宗室择贤？此一步定百年。",
        "choices": [
            {"text": "立己出（或己养）之嗣", "effects": {"稳固": 6, "威权": 4, "青史": 4}},
            {"text": "从宗室择贤而立", "effects": {"稳固": 8, "威权": -4, "民心": 4, "青史": 2}},
            {"text": "储位仍悬，待我百年", "effects": {"稳固": -8, "威权": 6, "青史": -6}},
        ],
    },
    {
        "id": "rebellion", "title": "宗室举兵",
        "desc": "宗室某王以「复辟」为名举兵，檄文传至京师，斥你「以妇人窃神器」。",
        "choices": [
            {"text": "御驾亲征，以雷霆扫之", "effects": {"稳固": 8, "威权": 12, "民心": -4, "青史": 6}},
            {"text": "遣将讨之，坐镇京师", "effects": {"稳固": 4, "威权": 3, "青史": 2}},
            {"text": "遣使许以封地，罢兵息事", "effects": {"稳固": -6, "威权": -8, "民心": 4, "青史": -4}},
        ],
    },
]

NEW_HAREM_RANKS = ["答应", "常在", "贵人", "嫔", "妃", "贵妃", "皇后"]
NEW_HAREM_MAX = 8
COURT_SESSION_INTERVAL = 3       # 每 3 旬一次大朝会
MEDDLE_QUEUE_MAX = 2
MINISTER_SEIZE_POWER = 85        # 权臣势力达此值则挟制朝政

# 干政事件模板：三选一，效果键同 _apply_effects，另有 外戚势/宗室势/权臣势
MEDDLE_EVENTS = [
    {
        "id": "clan_office", "kind": "外戚", "title": "母家请官",
        "desc": "你的兄弟递来密笺：如今太后垂帘，正该为母家在六部谋一实缺。",
        "choices": [
            {"text": "破格擢用，母家为援", "effects": {"外戚势": 10, "权威": 3, "朝堂": -5, "民心": -4}},
            {"text": "循资叙用，不徇私情", "effects": {"外戚势": 3, "朝堂": 3, "民心": 3}},
            {"text": "严词斥回，以塞人口", "effects": {"外戚势": -8, "权威": 2, "朝堂": 5}},
        ],
    },
    {
        "id": "clan_greed", "kind": "外戚", "title": "母家骄纵",
        "desc": "母家子弟仗着太后势，在京中强买民田，御史已具折待发。",
        "choices": [
            {"text": "压下折子，保住体面", "effects": {"外戚势": 5, "朝堂": -6, "民心": -8, "权威": -2}},
            {"text": "责令退田，罚俸示众", "effects": {"外戚势": -6, "民心": 8, "朝堂": 4, "权威": 3}},
            {"text": "交宗人府议处，避亲避嫌", "effects": {"外戚势": -10, "民心": 10, "权威": 5, "帝心": 3}},
        ],
    },
    {
        "id": "royal_regent", "kind": "宗室", "title": "宗室请与摄政",
        "desc": "几位亲王联名上表：幼帝在位，宜由宗室长者共参机务，以安社稷。",
        "choices": [
            {"text": "允其共参，分权求安", "effects": {"宗室势": 12, "权威": -6, "朝堂": 5}},
            {"text": "只许议政不许决事", "effects": {"宗室势": 4, "权威": 1, "朝堂": 2}},
            {"text": "断然驳回，帘政独任", "effects": {"宗室势": -8, "权威": 6, "朝堂": -6}},
        ],
    },
    {
        "id": "royal_heir_push", "kind": "宗室", "title": "宗室议储",
        "desc": "宗室私下议论：万一幼帝有恙，当从某亲王之子中择贤。此言已传入慈宁宫。",
        "choices": [
            {"text": "彻查散布者，以正名分", "effects": {"宗室势": -10, "权威": 5, "朝堂": -4, "帝心": 5}},
            {"text": "召其入宫，温言抚慰", "effects": {"宗室势": 3, "朝堂": 3}},
            {"text": "听之任之，留作后手", "effects": {"宗室势": 8, "权威": -3, "帝心": -4}},
        ],
    },
    {
        "id": "minister_faction", "kind": "权臣", "title": "权臣结党",
        "desc": "{minister}门生故吏遍布台省，票拟未上先定，朝议几成虚设。",
        "choices": [
            {"text": "夺其票拟之权", "effects": {"权臣势": -12, "权威": 5, "朝堂": -6}},
            {"text": "引另一党相制", "effects": {"权臣势": -5, "朝堂": 4, "权威": 2}},
            {"text": "倚其办事，暂且相安", "effects": {"权臣势": 10, "朝堂": 6, "权威": -4}},
        ],
    },
    {
        "id": "minister_impeach", "kind": "权臣", "title": "权臣劾帘",
        "desc": "{minister}上疏：太后久居帘后，非社稷长计，请早还大政。满朝观望。",
        "choices": [
            {"text": "廷杖之，以立威", "effects": {"权臣势": -8, "权威": 6, "朝堂": -8, "民心": -4}},
            {"text": "留中不发，冷处理", "effects": {"权臣势": 4, "权威": -2}},
            {"text": "优诏褒答，示我大度", "effects": {"权臣势": 2, "朝堂": 6, "民心": 5, "权威": -3}},
        ],
    },
]


# 太后可主动施为（每旬各一次）
DOWAGER_ACTIONS = {
    "instruct": {"name": "亲授帝学", "cost": {"actions": 1}, "desc": "亲课新帝经史，帝心与帝威俱进"},
    "grant": {"name": "赏赐朝臣", "cost": {"silver": 150}, "desc": "以私帑赏赐重臣，朝堂控制+"},
    "purge": {"name": "整肃朝纲", "cost": {"actions": 2}, "desc": "罢黜异己，权威+但朝堂震动"},
    "almsgiving": {"name": "施粥赈灾", "cost": {"silver": 200}, "desc": "以国库行仁政，民心+"},
    "audience": {"name": "召见宗亲", "cost": {"actions": 1}, "desc": "抚循宗室，宗室党好感+"},
}


def default_dowager():
    return {
        "active": False,
        "authority": 60,        # 摄政权威
        "court": 50,            # 朝堂控制力
        "treasury": 2000,       # 国库
        "people": 60,           # 民心
        "emperor": {"name": "", "age": 6, "affection": 60, "majesty": 30, "alive": True},
        "periods": 0,
        "pending": [],          # 待裁奏事
        "history": [],
        "log": [],
        "return_requested": 0,  # 亲政请求后已过旬数（0=未请求）
        "used_period": "",      # 本旬已施为记录
        "used_actions": [],
        # ---- 新帝后宫（太后仍可插手的那一半） ----
        "harem_mode": HAREM_MODE_DEFAULT,   # 亲掌 / 共治 / 放权
        "new_queen": "",                    # 新后名（新帝的皇后）
        "queen_favor": 50,                  # 新后对你的敬顺度 0-100
        "harem_log": [],
        # ---- 三方势力干政 ----
        "clan_power": 30,                   # 外戚（母家）势力
        "royal_power": 40,                  # 宗室势力
        "minister_power": 45,               # 权臣势力
        "minister": "",                     # 当朝权臣名号
        "meddle": [],                       # 待决干政事件
        "meddle_log": [],
        # ---- 大朝会与百官班次 ----
        "ministers": [],                    # 三位党派领袖 [{name,faction,power,attitude}]
        "sessions_held": 0,                 # 已历大朝会次数
        "last_session": "",                 # 上次出席方式
        # ---- 新帝妃嫔名册 ----
        "consorts": [],                     # [{name, rank, favor(帝宠), respect(对你敬顺), pregnant, children}]
        "consort_log": [],
        # ---- 女帝称制期 ----
        "regnant": False,                   # 是否已称制（进入女帝朝政循环）
        "reign_name": "",                   # 年号
        "reign_periods": 0,                 # 称制已历旬数
        "stability": 55,                    # 朝局稳固
        "sovereignty": 70,                  # 威权
        "legacy": 40,                       # 青史（史笔评价）
        "agenda": [],                       # 待决国是
        "reign_log": [],
    }


def get_dowager(game_state):
    d = getattr(game_state, "dowager_state", None)
    if not isinstance(d, dict):
        d = default_dowager()
        game_state.dowager_state = d
    for k, v in default_dowager().items():
        d.setdefault(k, v)
    for k, v in default_dowager()["emperor"].items():
        d["emperor"].setdefault(k, v)
    return d


def is_dowager_active(game_state):
    d = getattr(game_state, "dowager_state", None)
    return isinstance(d, dict) and bool(d.get("active"))


def _log(d, text):
    d["log"].insert(0, text)
    del d["log"][COURT_LOG_MAX:]


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, int(v)))


def enter_dowager_mode(game_state, heir_child):
    """新帝登基：由「母仪天下」转入垂帘听政续章，而非直接终局。"""
    d = get_dowager(game_state)
    if d.get("active"):
        return False, "你已在垂帘听政"
    d["active"] = True
    prestige = int(game_state.attributes.get("威望", 0) or 0)
    d["authority"] = _clamp(45 + prestige // 20)
    d["court"] = _clamp(40 + int(game_state.attributes.get("心计", 40) or 0) // 4)
    d["treasury"] = 2000
    d["people"] = 60
    d["emperor"] = {
        "name": (heir_child or {}).get("name", "新帝"),
        "age": int(float((heir_child or {}).get("age", 8) or 8)),
        "affection": int((heir_child or {}).get("affection", 60) or 60),
        "majesty": _clamp(20 + int((heir_child or {}).get("emperor_favor", 30) or 30) // 3),
        "alive": True,
        "personality": derive_emperor_personality(heir_child),
    }
    d["periods"] = 0
    game_state.dowager_mode = True
    game_state.regency_authority = d["authority"]
    game_state.court_power = d["court"]
    game_state.ending = None          # 续章：清掉「母仪天下」的终局落定
    game_state.game_over = False
    _log(d, f"{d['emperor']['name']}登基，你于养心殿后垂帘听政")
    game_state.add_memory(f"👑 你以太后之尊垂帘听政，辅幼帝{d['emperor']['name']}")
    p = d["emperor"]["personality"]
    pspec = EMPEROR_PERSONALITIES[p]
    return True, (f"👑 新帝{d['emperor']['name']}年方{d['emperor']['age']}，冲龄践祚。"
                  f"珠帘之后，你第一次听见满殿朝臣向帘幕行礼。\n"
                  f"这孩子性子{p}——{pspec['desc']}。{pspec['flavor']}\n"
                  f"摄政权威{d['authority']} · 朝堂控制{d['court']} · 国库{d['treasury']}万 · 民心{d['people']}")


def _apply_effects(game_state, d, effects):
    applied = {}
    for k, v in (effects or {}).items():
        v = int(v)
        if k == "权威":
            d["authority"] = _clamp(d["authority"] + v)
            applied["摄政权威"] = v
        elif k == "朝堂":
            d["court"] = _clamp(d["court"] + v)
            applied["朝堂控制"] = v
        elif k == "国库":
            d["treasury"] = max(0, int(d["treasury"]) + v)
            applied["国库"] = v
        elif k == "民心":
            d["people"] = _clamp(d["people"] + v)
            applied["民心"] = v
        elif k == "帝心":
            d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] + v)
            applied["帝心"] = v
        elif k == "帝威":
            d["emperor"]["majesty"] = _clamp(d["emperor"]["majesty"] + v)
            applied["新帝威仪"] = v
        elif k.startswith("派系_"):
            faction = k.split("_", 1)[1]
            favor = {"文官党": 50, "武官党": 50, "宗室党": 50}
            favor.update(getattr(game_state, "court_faction_favor", None) or {})
            if faction in favor:
                favor[faction] = _clamp(int(favor[faction] or 0) + v)
                game_state.court_faction_favor = favor
                applied[faction] = v
    game_state.regency_authority = d["authority"]
    game_state.court_power = d["court"]
    return applied


def generate_court_affairs(game_state):
    """转旬：生成 1~2 件待裁奏事（队列上限 3）。"""
    d = get_dowager(game_state)
    if not d.get("active"):
        return []
    msgs = []
    if len(d["pending"]) >= 3:
        return ["📜 通政司积压的奏本已堆到三件，朝臣都在等太后裁断"]
    for _ in range(random.choice([1, 1, 2])):
        if len(d["pending"]) >= 3:
            break
        tpl = random.choice(COURT_AFFAIRS)
        if tpl["id"] == "return_power_hint" and d["emperor"]["age"] < EMPEROR_ADULT_AGE - 2:
            continue
        if any(p.get("tpl") == tpl["id"] for p in d["pending"]):
            continue
        d["pending"].append({
            "id": f"ca{len(d['history']) + len(d['pending']) + 1}_{random.randint(100, 999)}",
            "tpl": tpl["id"], "type": tpl["type"], "icon": tpl["icon"],
            "title": tpl["title"], "desc": tpl["desc"],
            "choices": [{"text": c["text"], "icon": c.get("icon", ""), "effects": c["effects"]}
                        for c in tpl["choices"]],
            "period": f"{game_state.year}年{game_state.month}月",
        })
        msgs.append(f"{tpl['icon']} 朝会奏事：{tpl['title']}——满殿都在等帘后一言")
    return msgs


def respond_court_affair(game_state, affair_id, choice_index):
    """裁决一件奏事。"""
    d = get_dowager(game_state)
    if not d.get("active"):
        return None, "你不在垂帘听政"
    ev = next((p for p in d["pending"] if p.get("id") == affair_id), None)
    if not ev:
        return None, "此奏本已批过或不存在"
    choices = ev.get("choices") or []
    idx = int(choice_index or 0)
    if not (0 <= idx < len(choices)):
        return False, "无此选项"
    choice = choices[idx]
    if ev.get("tpl") == "grand_session":
        way = (choice.get("effects") or {}).get("way", "curtain")
        applied, session_msgs = _resolve_court_session(game_state, d, way)
        d["pending"] = [p for p in d["pending"] if p.get("id") != affair_id]
        d["history"].insert(0, {"title": "大朝会", "choice": choice["text"], "period": ev.get("period")})
        del d["history"][30:]
        narr = f"👑 大朝会 · {choice['text']}。\n" + "\n".join(session_msgs)
        game_state.add_memory(f"大朝会：{choice['text']}")
        return True, narr
    applied = _apply_effects(game_state, d, choice.get("effects"))
    d["pending"] = [p for p in d["pending"] if p.get("id") != affair_id]
    d["history"].insert(0, {"title": ev["title"], "choice": choice["text"], "period": ev.get("period")})
    del d["history"][30:]
    # 还政之议特判
    if ev.get("tpl") == "return_power_hint" and idx == 0:
        d["return_requested"] = max(1, d["return_requested"])
    parts = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in applied.items() if v]
    narr = f"「{ev['title']}」你于帘后裁断：{choice['text']}。"
    if parts:
        narr += "（" + "、".join(parts) + "）"
    _log(d, f"{ev['title']}：{choice['text']}")
    game_state.add_memory(f"垂帘裁断：{ev['title']}—{choice['text']}")
    return True, narr


def dowager_action(game_state, action):
    """太后主动施为（每旬每项一次）。"""
    from app import guard_action, check_and_consume_action
    d = get_dowager(game_state)
    if not d.get("active"):
        return None, "你不在垂帘听政"
    spec = DOWAGER_ACTIONS.get(action)
    if not spec:
        return None, "无此举措"
    period_key = f"{game_state.year}-{game_state.month}-{game_state.day}"
    if d.get("used_period") != period_key:
        d["used_period"] = period_key
        d["used_actions"] = []
    if action in d["used_actions"]:
        return False, f"本旬已{spec['name']}，不宜再行"
    if "silver" in spec["cost"]:
        need = spec["cost"]["silver"]
        if action == "almsgiving":
            if d["treasury"] < need:
                return False, f"国库不足（需{need}万）"
            d["treasury"] -= need
        else:
            if game_state.silver < need:
                return False, f"私帑不足（需{need}两）"
            game_state.silver -= need
    if "actions" in spec["cost"]:
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
        for _ in range(spec["cost"]["actions"] - 1):
            check_and_consume_action(game_state)
    d["used_actions"].append(action)
    if action == "instruct":
        eff = {"帝心": random.randint(3, 7), "帝威": random.randint(2, 5), "权威": 1}
        applied = _apply_effects(game_state, d, eff)
        msg = f"📖 你亲执朱笔为{d['emperor']['name']}讲《贞观政要》，他听得入神"
    elif action == "grant":
        applied = _apply_effects(game_state, d, {"朝堂": random.randint(5, 9), "权威": 1})
        msg = "🎁 你以私帑厚赏几位老臣，朝上的风向和缓了些"
    elif action == "purge":
        applied = _apply_effects(game_state, d, {"权威": random.randint(6, 10),
                                                 "朝堂": -random.randint(3, 6),
                                                 "民心": -random.randint(0, 3)})
        msg = "🗡️ 你借考功之名罢黜数名异议之臣，朝堂一时噤声"
    elif action == "almsgiving":
        applied = _apply_effects(game_state, d, {"民心": random.randint(6, 11), "权威": 2})
        msg = "🌾 京畿设粥棚三十处，百姓称颂太后仁德"
    else:  # audience
        applied = _apply_effects(game_state, d, {"派系_宗室党": random.randint(4, 8), "朝堂": 2})
        msg = "🏵️ 你于慈宁宫召见宗亲，赐茶叙话，宗室感念"
    parts = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in applied.items() if v]
    if parts:
        msg += "（" + "、".join(parts) + "）"
    _log(d, spec["name"])
    return True, msg


def return_power(game_state, mode):
    """还政抉择：yield=归政新帝（结局）；refuse=继续垂帘（权威消耗）。"""
    from app import trigger_ending
    d = get_dowager(game_state)
    if not d.get("active"):
        return None, "你不在垂帘听政"
    adult_at = emperor_adult_age(d)
    if d["emperor"]["age"] < adult_at and mode == "yield":
        return False, f"新帝尚未及{adult_at}岁，此时归政恐社稷动摇"
    if mode == "yield":
        d["active"] = False
        game_state.dowager_mode = False
        affection = d["emperor"]["affection"]
        pname = d["emperor"].get("personality", "仁厚")
        if pname == "暴戾" and affection < 50:
            trigger_ending(game_state, "还政归养",
                           f"{d['emperor']['name']}性暴戾，你趁其未及发难先行撤帘")
            return True, ("🍂 你抢在他开口之前撤了帘。这不是让贤，是保命——"
                          "他接玺时脸上那点意外，是你这十年最后一次胜过他。（终局：还政归养）")
        if pname == "庸懒" and affection >= 50:
            trigger_ending(game_state, "还政归养",
                           f"{d['emperor']['name']}疏懒，你撤帘后他仍事事来问")
            return True, ("🌤️ 你撤了帘，可他仍旧三天两头往慈宁宫跑，"
                          "拿着奏本问「母后你看这个怎么办」。你笑着替他看了——最后一次。（终局：还政归养）")
        if affection >= 60 and d["people"] >= 50:
            trigger_ending(game_state, "还政归养",
                           f"{d['emperor']['name']}既冠,你撤帘还政，母慈子孝")
            return True, ("🌤️ 撤帘那日，新帝亲扶你出殿。你把批红的朱笔交回他手里，"
                          "从此只在慈宁宫看花——这江山，你替他守住了。（终局：还政归养）")
        trigger_ending(game_state, "还政归养",
                       f"{d['emperor']['name']}亲政，你交还权柄，母子间终究隔了一层")
        return True, ("🍂 你撤了帘。新帝受玺时没有看你。此后慈宁宫的门槛，他一年也难得踏过一次。"
                      "（终局：还政归养）")
    if mode == "refuse":
        d["return_requested"] = 0
        applied = _apply_effects(game_state, d, {"权威": -6, "帝心": -10, "朝堂": -4})
        _log(d, "拒还政")
        return True, ("🚫 你只说了一句「皇帝还小」。帘外一片沉默，新帝的手在袖中攥紧了。"
                      f"（{'、'.join(f'{k}{v}' for k, v in applied.items())}）")
    if mode == "regnant":
        if d["authority"] < EMPRESS_REGNANT_AUTH or d["court"] < EMPRESS_REGNANT_COURT:
            return False, (f"临朝称制需摄政权威≥{EMPRESS_REGNANT_AUTH}、朝堂控制≥{EMPRESS_REGNANT_COURT}"
                           f"（现{d['authority']}/{d['court']}）")
        # 称制后进入女帝朝政循环（不再直接终局）
        d["regnant"] = True
        d["reign_name"] = random.choice(["天授", "神龙", "正元", "开成", "永昌", "承光"])
        d["reign_periods"] = 0
        d["stability"] = _clamp(30 + d["court"] // 2)
        d["sovereignty"] = _clamp(50 + d["authority"] // 3)
        d["legacy"] = 40
        d["agenda"] = []
        _reign_log(d, f"去帘临朝，改元{d['reign_name']}")
        game_state.add_memory(f"👑 你临朝称制，改元{d['reign_name']}")
        return True, ("👑 那道珠帘被撤了下来——不是还政，是不必再隔着帘子。\n"
                      f"你着帝服受百官朝贺，改元{d['reign_name']}。\n"
                      f"朝局稳固{d['stability']} · 威权{d['sovereignty']} · 青史{d['legacy']}\n"
                      "从今往后，这天下的事，你自己拿主意。")
    return None, "无效的抉择"


# ===== 新帝后宫：太后仍可插手的那一半 =====
HAREM_ACTIONS = {
    "select_draft": {"name": "为帝选秀", "cost": {"actions": 1}, "min_mode": ("亲掌", "共治"),
                     "desc": "为新帝钦定秀女入宫，充实子嗣（新后敬顺-）"},
    "instruct_queen": {"name": "训诫新后", "cost": {"actions": 1}, "min_mode": ("亲掌", "共治"),
                       "desc": "以太后之尊教诲新后宫务（权威+，敬顺-）"},
    "bless_consort": {"name": "抚循妃嫔", "cost": {"silver": 100}, "min_mode": ("亲掌", "共治", "放权"),
                      "desc": "赏赐新帝妃嫔，广植恩德（民心+，敬顺+）"},
    "urge_heir": {"name": "催促皇嗣", "cost": {"actions": 1}, "min_mode": ("亲掌", "共治"),
                  "desc": "催新帝早绵子嗣（帝心-，皇孙有望）"},
    "arbitrate": {"name": "裁断宫争", "cost": {"actions": 1}, "min_mode": ("亲掌", "共治"),
                  "desc": "亲裁新帝后宫的争端（权威+，或招怨）"},
}


def _harem_log(d, text):
    d.setdefault("harem_log", []).insert(0, text)
    del d["harem_log"][12:]


def ensure_new_queen(game_state, d):
    """新帝立后：从名册中挑一位（或凭空生成）作为新后。"""
    if d.get("new_queen"):
        return d["new_queen"]
    if d["emperor"]["age"] < 14:
        return ""
    from names import generate_female_name
    try:
        name = generate_female_name()
    except Exception:
        name = "新后"
    d["new_queen"] = name
    d["queen_favor"] = random.randint(40, 60)
    _harem_log(d, f"{d['emperor']['name']}册立{name}为后")
    game_state.add_memory(f"👑 新帝册立{name}为后")
    return name


def set_harem_mode(game_state, mode):
    """选择后宫治理模式：亲掌 / 共治 / 放权。"""
    d = get_dowager(game_state)
    if not d.get("active"):
        return None, "你不在垂帘听政"
    if mode not in HAREM_MODES:
        return None, "无此治理之法"
    if d.get("harem_mode") == mode:
        return False, f"你已行「{HAREM_MODES[mode]['name']}」之法"
    old = d.get("harem_mode", HAREM_MODE_DEFAULT)
    d["harem_mode"] = mode
    spec = HAREM_MODES[mode]
    # 转换代价：亲掌需权威，放权则失权威但得帝心
    if mode == "亲掌":
        d["authority"] = _clamp(d["authority"] + 3)
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) - 8)
        d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] - 4)
        narr = ("🏛️ 你传下话去：六宫事无大小，皆先报慈宁宫。"
                "新后垂手立在阶下，一句话也没有说。（权威+3，帝心-4，新后敬顺-8）")
    elif mode == "放权":
        d["authority"] = _clamp(d["authority"] - 4)
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) + 10)
        d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] + 6)
        narr = ("🌿 你把六宫的册子交回新后手里：「往后这些，你自己拿主意。」"
                "她跪下谢恩时，眼里是真的松了口气。（权威-4，帝心+6，新后敬顺+10）")
    else:
        d["authority"] = _clamp(d["authority"] + 1)
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) + 3)
        narr = ("⚖️ 你划下界线：大事你断，细务归她。"
                "这样最省心，也最容易长久。（权威+1，新后敬顺+3）")
    _harem_log(d, f"治理之法：{old}→{mode}")
    game_state.add_memory(f"后宫治理改为「{spec['name']}」")
    return True, narr


def harem_action(game_state, action):
    """太后对新帝后宫的施为（受治理模式限制）。"""
    from app import guard_action
    d = get_dowager(game_state)
    if not d.get("active"):
        return None, "你不在垂帘听政"
    spec = HAREM_ACTIONS.get(action)
    if not spec:
        return None, "无此举措"
    mode = d.get("harem_mode", HAREM_MODE_DEFAULT)
    if mode not in spec["min_mode"]:
        return False, f"你已行「{HAREM_MODES[mode]['name']}」，此事不宜再由慈宁宫过问"
    period_key = f"{game_state.year}-{game_state.month}-{game_state.day}"
    key = "harem_" + action
    if d.get("used_period") != period_key:
        d["used_period"] = period_key
        d["used_actions"] = []
    if key in d["used_actions"]:
        return False, f"本旬已{spec['name']}"
    if "silver" in spec["cost"]:
        if game_state.silver < spec["cost"]["silver"]:
            return False, f"私帑不足（需{spec['cost']['silver']}两）"
        game_state.silver -= spec["cost"]["silver"]
    if "actions" in spec["cost"]:
        ok, err = guard_action(game_state)
        if not ok:
            return False, err
    d["used_actions"].append(key)
    queen = ensure_new_queen(game_state, d)

    if action == "select_draft":
        applied = _apply_effects(game_state, d, {"权威": 2, "帝心": -2})
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) - 5)
        d.setdefault("grandchild_chance", 0)
        d["grandchild_chance"] = min(60, int(d.get("grandchild_chance", 0)) + 15)
        msg = (f"📜 你为{d['emperor']['name']}钦定了两名秀女入宫。"
               f"{'新后' + queen + '闻讯，指尖掐进了掌心。' if queen else ''}"
               f"（权威+2，帝心-2，新后敬顺-5，皇孙可期）")
    elif action == "instruct_queen":
        if not queen:
            return False, "新帝尚未立后，无人可训"
        applied = _apply_effects(game_state, d, {"权威": 3})
        backlash = 4 if emperor_personality_spec(d).get("obedient") else 8
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) - backlash)
        msg = (f"📖 你召{queen}至慈宁宫，从晨昏定省讲到内帑出入，讲了一个时辰。"
               f"她跪谢受教，膝下的砖被跪出了印子。（权威+3，新后敬顺-6）")
    elif action == "bless_consort":
        applied = _apply_effects(game_state, d, {"民心": 3, "朝堂": 2})
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) + 6)
        msg = ("🎁 你以私帑赏赐新帝的妃嫔，人人有份，厚薄得宜。"
               "宫里都说太后慈厚。（民心+3，朝堂+2，新后敬顺+6）")
    elif action == "urge_heir":
        heart = -2 if emperor_personality_spec(d).get("obedient") else -5
        applied = _apply_effects(game_state, d, {"帝心": heart, "权威": 1})
        d["grandchild_chance"] = min(70, int(d.get("grandchild_chance", 0)) + 20)
        msg = (f"🍼 你当着朝臣的面问{d['emperor']['name']}：「皇嗣之事，可有消息了？」"
               f"他脸上一红，答不上话。（帝心-3，权威+1，皇孙可期）")
    else:  # arbitrate
        good = random.random() < 0.6
        if good:
            applied = _apply_effects(game_state, d, {"权威": 4, "朝堂": 2})
            d["queen_favor"] = _clamp(d.get("queen_favor", 50) + 2)
            msg = ("⚖️ 新帝后宫两位娘娘争一处宫室，闹到慈宁宫来。"
                   "你三言两语断得公道，两边都谢了恩。（权威+4，朝堂+2）")
        else:
            applied = _apply_effects(game_state, d, {"权威": 1, "民心": -2})
            d["queen_favor"] = _clamp(d.get("queen_favor", 50) - 5)
            msg = ("⚖️ 你裁断了那桩争执，可落败的那位是新后的亲表妹。"
                   "从此新后见你，礼数越发周全了。（权威+1，民心-2，新后敬顺-5）")
    parts = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in (applied or {}).items() if v]
    _harem_log(d, spec["name"])
    return True, msg


# ===== 三方势力干政 =====
def ensure_minister(game_state, d):
    if d.get("minister"):
        return d["minister"]
    d["minister"] = f"{random.choice(MINISTER_TITLES)}{random.choice(MINISTER_NAMES)}{random_given(EMPEROR_GIVEN, 0.5)}"
    return d["minister"]


def _meddle_log(d, text):
    d.setdefault("meddle_log", []).insert(0, text)
    del d["meddle_log"][12:]


def _apply_meddle_effects(game_state, d, effects):
    """在 _apply_effects 之上追加三方势力键。"""
    core = {k: v for k, v in (effects or {}).items()
            if k not in ("外戚势", "宗室势", "权臣势")}
    applied = _apply_effects(game_state, d, core)
    mapping = {"外戚势": "clan_power", "宗室势": "royal_power", "权臣势": "minister_power"}
    for k, field in mapping.items():
        if k in (effects or {}):
            v = int(effects[k])
            d[field] = _clamp(int(d.get(field, 40) or 0) + v)
            applied[k] = v
    return applied


def generate_meddle_events(game_state):
    """转旬按势力高低生成干政事件（队列上限 2）。"""
    d = get_dowager(game_state)
    if not d.get("active"):
        return []
    msgs = []
    if len(d.get("meddle") or []) >= MEDDLE_QUEUE_MAX:
        return msgs
    # 势力越高越容易生事
    weights = {
        "外戚": max(1, int(d.get("clan_power", 30)) // 10),
        "宗室": max(1, int(d.get("royal_power", 40)) // 10),
        "权臣": max(1, int(d.get("minister_power", 45)) // 10),
    }
    if random.random() >= 0.45:
        return msgs
    kind = random.choices(list(weights), weights=list(weights.values()))[0]
    pool = [e for e in MEDDLE_EVENTS if e["kind"] == kind
            and not any(p.get("tpl") == e["id"] for p in (d.get("meddle") or []))]
    if not pool:
        return msgs
    tpl = random.choice(pool)
    minister = ensure_minister(game_state, d)
    desc = tpl["desc"].replace("{minister}", minister)
    d.setdefault("meddle", []).append({
        "id": f"md{random.randint(1000, 9999)}",
        "tpl": tpl["id"], "kind": kind, "icon": MEDDLE_KINDS[kind]["icon"],
        "title": tpl["title"], "desc": desc,
        "choices": [{"text": c["text"], "effects": c["effects"]} for c in tpl["choices"]],
        "period": f"{game_state.year}年{game_state.month}月",
    })
    msgs.append(f"{MEDDLE_KINDS[kind]['icon']} {MEDDLE_KINDS[kind]['who']}有动静：{tpl['title']}")
    return msgs


def respond_meddle(game_state, meddle_id, choice_index):
    """裁决一件干政事件。"""
    d = get_dowager(game_state)
    if not d.get("active"):
        return None, "你不在垂帘听政"
    ev = next((p for p in (d.get("meddle") or []) if p.get("id") == meddle_id), None)
    if not ev:
        return None, "此事已了或不存在"
    idx = int(choice_index or 0)
    choices = ev.get("choices") or []
    if not (0 <= idx < len(choices)):
        return False, "无此选项"
    choice = choices[idx]
    applied = _apply_meddle_effects(game_state, d, choice.get("effects"))
    d["meddle"] = [p for p in d["meddle"] if p.get("id") != meddle_id]
    parts = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in applied.items() if v]
    narr = f"「{ev['title']}」你于帘后处置：{choice['text']}。"
    if parts:
        narr += "（" + "、".join(parts) + "）"
    _meddle_log(d, f"{ev['title']}：{choice['text']}")
    game_state.add_memory(f"垂帘处置{ev['kind']}：{ev['title']}")
    return True, narr


def _sync_external_powers(game_state, d):
    """与既有家族/宗室/朝堂系统对齐（单向读取，避免双轨）。"""
    clan = getattr(game_state, "player_clan", None)
    if isinstance(clan, dict):
        d["clan_power"] = _clamp(int(clan.get("家族威望", 40) or 40))
    rc = getattr(game_state, "royal_clan", None)
    if isinstance(rc, dict) and rc.get("males"):
        alive = [m for m in rc["males"].values() if isinstance(m, dict) and m.get("alive")]
        if alive:
            d["royal_power"] = _clamp(int(sum(int(m.get("实力", 30) or 30) for m in alive) / len(alive)))


# ===== 新帝妃嫔名册 =====
def _consort_log(d, text):
    d.setdefault("consort_log", []).insert(0, text)
    del d["consort_log"][12:]


def _new_consort(game_state, rank="常在"):
    from names import generate_female_name
    try:
        name = generate_female_name()
    except Exception:
        name = "新人"
    return {"name": name, "rank": rank,
            "favor": random.randint(20, 55), "respect": random.randint(35, 65),
            "pregnant": False, "children": 0, "alive": True}


def ensure_new_harem(game_state, d, count=None):
    """新帝立后前后自动铺开后宫名册。"""
    roster = d.setdefault("consorts", [])
    if roster:
        return roster
    if d["emperor"]["age"] < 13:
        return roster
    n = count if count is not None else random.randint(3, 5)
    used = set()
    for _ in range(n):
        c = _new_consort(game_state, random.choice(["答应", "常在", "贵人", "嫔"]))
        if c["name"] in used:
            continue
        used.add(c["name"])
        roster.append(c)
    _consort_log(d, f"新帝后宫初立，共{len(roster)}人")
    return roster


def find_consort(d, name):
    for c in d.get("consorts") or []:
        if c.get("name") == name and c.get("alive", True):
            return c
    return None


def consort_action(game_state, name, action):
    """太后处置新帝妃嫔：提拔 / 贬黜 / 赐婚（出宫）/ 抚慰。"""
    from app import guard_action
    d = get_dowager(game_state)
    if not d.get("active"):
        return None, "你不在垂帘听政"
    mode = d.get("harem_mode", HAREM_MODE_DEFAULT)
    if mode == "放权" and action in ("promote", "demote", "dismiss"):
        return False, "你已全付新后，妃嫔位份升降不再经慈宁宫"
    c = find_consort(d, name)
    if not c:
        return None, "名册上查无此人"
    ok, err = guard_action(game_state)
    if not ok:
        return False, err
    if action == "promote":
        idx = NEW_HAREM_RANKS.index(c["rank"]) if c["rank"] in NEW_HAREM_RANKS else 1
        if idx >= NEW_HAREM_RANKS.index("贵妃"):
            return False, f"{name}已至{c['rank']}，再进便是中宫，非你可专断"
        old_rank = c["rank"]
        c["rank"] = NEW_HAREM_RANKS[idx + 1]
        c["respect"] = _clamp(c["respect"] + 15)
        c["favor"] = _clamp(c["favor"] + 5)
        applied = _apply_effects(game_state, d, {"权威": 2})
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) - 3)
        _consort_log(d, f"{name}{old_rank}→{c['rank']}")
        return True, (f"📜 你一句话把{name}由{old_rank}擢为{c['rank']}。"
                      f"她伏地谢恩，从此这条命是你给的。（她敬顺+15，权威+2，新后敬顺-3）")
    if action == "demote":
        idx = NEW_HAREM_RANKS.index(c["rank"]) if c["rank"] in NEW_HAREM_RANKS else 1
        if idx <= 0:
            return False, f"{name}已是末位，再降便当出宫"
        old_rank = c["rank"]
        c["rank"] = NEW_HAREM_RANKS[idx - 1]
        c["respect"] = _clamp(c["respect"] - 20)
        c["favor"] = _clamp(c["favor"] - 8)
        applied = _apply_effects(game_state, d, {"权威": 3, "帝心": -2})
        _consort_log(d, f"{name}{old_rank}→{c['rank']}（贬）")
        return True, (f"⚖️ 你以「不谨」为由将{name}由{old_rank}降为{c['rank']}。"
                      f"六宫看在眼里，谁还敢在慈宁宫前失仪。（权威+3，帝心-2）")
    if action == "dismiss":
        if int(c.get("children", 0) or 0) > 0:
            return False, f"{name}已有子嗣，出宫之议不合宗法"
        c["alive"] = False
        applied = _apply_effects(game_state, d, {"权威": 2, "帝心": -4})
        d["queen_favor"] = _clamp(d.get("queen_favor", 50) + 4)
        _consort_log(d, f"{name}出宫")
        return True, (f"🚪 你赐{name}归家，另择良配。轿子出宫那日，"
                      f"新帝在殿上坐了很久没说话。（权威+2，帝心-4，新后敬顺+4）")
    if action == "comfort":
        if game_state.silver < 60:
            return False, "私帑不足（需60两）"
        game_state.silver -= 60
        c["respect"] = _clamp(c["respect"] + 12)
        applied = _apply_effects(game_state, d, {"民心": 1})
        _consort_log(d, f"抚慰{name}")
        return True, f"🎁 你赏了{name}一副头面，又叫太医替她诊了脉。她记着这份恩（敬顺+12）"
    return None, "无效的处置"


def dowager_harem_roster(d):
    return [{k: c.get(k) for k in ("name", "rank", "favor", "respect", "pregnant", "children")}
            for c in (d.get("consorts") or []) if c.get("alive", True)]


# ===== 女帝称制期 =====
def is_regnant(game_state):
    d = getattr(game_state, "dowager_state", None)
    return isinstance(d, dict) and bool(d.get("regnant"))


def _reign_log(d, text):
    d.setdefault("reign_log", []).insert(0, text)
    del d["reign_log"][COURT_LOG_MAX:]


def _apply_reign_effects(game_state, d, effects):
    applied = {}
    mapping = {"稳固": "stability", "威权": "sovereignty", "青史": "legacy"}
    for k, v in (effects or {}).items():
        v = int(v)
        if k in mapping:
            d[mapping[k]] = _clamp(int(d.get(mapping[k], 50) or 0) + v)
            applied[k] = v
        elif k == "民心":
            d["people"] = _clamp(d["people"] + v)
            applied["民心"] = v
    return applied


def generate_reign_agenda(game_state):
    """称制期每旬按概率生成国是（队列上限 2）。"""
    d = get_dowager(game_state)
    if not d.get("regnant"):
        return []
    if len(d.get("agenda") or []) >= 2:
        d["stability"] = _clamp(d["stability"] - 2)
        return ["📜 国是悬而未决，六部无所适从（朝局稳固-2）"]
    if random.random() >= 0.5:
        return []
    pool = [a for a in REGNANT_AGENDA
            if not any(x.get("tpl") == a["id"] for x in (d.get("agenda") or []))]
    if not pool:
        return []
    tpl = random.choice(pool)
    d.setdefault("agenda", []).append({
        "id": f"rg{random.randint(1000, 9999)}", "tpl": tpl["id"],
        "title": tpl["title"], "desc": tpl["desc"],
        "choices": [{"text": c["text"], "effects": c["effects"]} for c in tpl["choices"]],
        "period": f"{d['reign_name']}{game_state.year}年",
    })
    return [f"📜 国是待决：{tpl['title']}"]


def respond_reign_agenda(game_state, agenda_id, choice_index):
    d = get_dowager(game_state)
    if not d.get("regnant"):
        return None, "你尚未称制"
    ev = next((a for a in (d.get("agenda") or []) if a.get("id") == agenda_id), None)
    if not ev:
        return None, "此国是已决或不存在"
    idx = int(choice_index or 0)
    choices = ev.get("choices") or []
    if not (0 <= idx < len(choices)):
        return False, "无此选项"
    choice = choices[idx]
    applied = _apply_reign_effects(game_state, d, choice.get("effects"))
    d["agenda"] = [a for a in d["agenda"] if a.get("id") != agenda_id]
    parts = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in applied.items() if v]
    narr = f"「{ev['title']}」你降旨：{choice['text']}。"
    if parts:
        narr += "（" + "、".join(parts) + "）"
    _reign_log(d, f"{ev['title']}：{choice['text']}")
    game_state.add_memory(f"称制降旨：{ev['title']}")
    return True, narr


def reign_abdicate(game_state):
    """女帝传位：按青史/稳固落定三种终局。"""
    from app import trigger_ending
    d = get_dowager(game_state)
    if not d.get("regnant"):
        return None, "你尚未称制"
    if d.get("reign_periods", 0) < 4:
        return False, "改元未久，此时传位则新政尽废"
    d["regnant"] = False
    d["active"] = False
    game_state.dowager_mode = False
    legacy = int(d.get("legacy", 40) or 40)
    stability = int(d.get("stability", 50) or 50)
    if legacy >= 70 and stability >= 55:
        trigger_ending(game_state, "女帝功成",
                       f"改元{d['reign_name']}凡{d['reign_periods']}旬，功成传位，史称贤主")
        return True, ("👑 你在生前把玉玺交了出去，这是历代女主都没做到的事。\n"
                      "新君奉你为太上，年号仍用你的。史官落笔时手是稳的——"
                      f"「{d['reign_name']}之政，海内称治」。（终局：女帝功成）")
    if stability <= 30:
        trigger_ending(game_state, "神器倾覆",
                       f"改元{d['reign_name']}后朝局崩坏，神器旁落")
        return True, ("🔥 你终究没有守住。玄武门的火光照到了含元殿的檐角，"
                      "他们冲进来时你还坐在御座上——你没有起身。（终局：神器倾覆）")
    trigger_ending(game_state, "女帝功成",
                   f"改元{d['reign_name']}凡{d['reign_periods']}旬，倦而传位")
    return True, ("🍂 你把玉玺交了出去，没有人挽留。史书上给你留了一卷，"
                  "褒贬各半——「以妇人而有天下，亦异数也」。（终局：女帝功成）")


def reign_period_tick(game_state):
    """称制期转旬：国是、稳固消长、倾覆危机、传位时机。"""
    d = get_dowager(game_state)
    if not d.get("regnant"):
        return []
    msgs = []
    d["reign_periods"] = int(d.get("reign_periods", 0) or 0) + 1
    # 女帝每 3 旬御门听政，亲裁大计
    if d["reign_periods"] % COURT_SESSION_INTERVAL == 0:
        gain = random.randint(2, 5)
        d["sovereignty"] = _clamp(d["sovereignty"] + gain)
        d["legacy"] = _clamp(d["legacy"] + 1)
        msgs.append(f"👑 你御门听政，亲裁大计三件（威权+{gain}，青史+1）")
    # 威权高则稳固缓升，民心低则稳固下滑
    drift = 1 if d["sovereignty"] >= 60 else -1
    if d["people"] < 40:
        drift -= 2
    d["stability"] = _clamp(d["stability"] + drift)
    if d["stability"] <= REGNANT_STABILITY_CRISIS:
        if random.random() < 0.35:
            from app import trigger_ending
            d["regnant"] = False
            d["active"] = False
            game_state.dowager_mode = False
            trigger_ending(game_state, "神器倾覆", "朝局崩坏，宗室与外朝合力复辟")
            msgs.append("🔥 复辟的兵马已进了朱雀门——这一次，没有帘子可以躲。（终局：神器倾覆）")
            return msgs
        msgs.append("⚠️ 朝局已危：州郡观望，京中流言四起（朝局稳固<25）")
    if d["reign_periods"] == REGNANT_YEARS_TO_LEGACY:
        msgs.append(f"👑 改元{d['reign_name']}已{d['reign_periods']}旬，你可从容议传位之事（青史{d['legacy']}）")
    msgs.extend(generate_reign_agenda(game_state))
    return msgs


def reign_payload(d):
    return {
        "regnant": bool(d.get("regnant")),
        "reign_name": d.get("reign_name", ""),
        "reign_periods": int(d.get("reign_periods", 0) or 0),
        "stability": int(d.get("stability", 55) or 0),
        "sovereignty": int(d.get("sovereignty", 70) or 0),
        "legacy": int(d.get("legacy", 40) or 0),
        "agenda": list(d.get("agenda") or []),
        "reign_log": list(d.get("reign_log") or [])[:6],
        "can_abdicate": int(d.get("reign_periods", 0) or 0) >= 4,
        "legacy_gate": REGNANT_YEARS_TO_LEGACY,
    }


# ===== 大朝会与百官班次 =====
def ensure_court_ministers(game_state, d):
    """三位党派领袖入班（文官/武官/宗室各一），势力随派系好感。"""
    ms = d.setdefault("ministers", [])
    favor = {"文官党": 50, "武官党": 50, "宗室党": 50}
    favor.update(getattr(game_state, "court_faction_favor", None) or {})
    have = {m.get("faction") for m in ms}
    for faction in ("文官党", "武官党", "宗室党"):
        if faction in have:
            continue
        ms.append({
            "name": f"{random.choice(MINISTER_TITLES)}{random.choice(MINISTER_NAMES)}{random_given(EMPEROR_GIVEN, 0.5)}",
            "faction": faction,
            "power": _clamp(int(favor.get(faction, 50)) + random.randint(-8, 8)),
            "attitude": random.randint(25, 55),   # 对太后的顺从度
            "alive": True,
        })
    return ms


def _ministers_attitude_shift(d, delta_by_faction):
    """按派系调整领袖态度。"""
    for m in d.get("ministers") or []:
        delta = delta_by_faction.get(m.get("faction"), 0)
        if delta:
            m["attitude"] = _clamp(int(m.get("attitude", 40) or 0) + delta)


def open_court_session(game_state):
    """大朝会开场：入待裁队列，须选择出席方式。"""
    d = get_dowager(game_state)
    if not d.get("active") or d.get("regnant"):
        return []
    if any(p.get("tpl") == "grand_session" for p in (d.get("pending") or [])):
        return []
    ministers = ensure_court_ministers(game_state, d)
    roster = "、".join(f"{m['faction']}{m['name']}" for m in ministers)
    emp = d["emperor"]
    pname = emp.get("personality", "仁厚")
    scene = {
        "仁厚": f"{emp['name']}端坐御座，先向帘后望了一眼，才命百官奏事。",
        "多疑": f"{emp['name']}坐得很直，每道奏本读完，都先看你一眼再看群臣。",
        "暴戾": f"{emp['name']}今日面色不佳，方才已斥退一名奏事含糊的给事中。",
        "庸懒": f"{emp['name']}来得比百官晚，落座没多久就开始揉眼睛。",
    }.get(pname, "")
    d["pending"].append({
        "id": f"cs{random.randint(1000, 9999)}",
        "tpl": "grand_session", "type": "大朝会", "icon": "👑",
        "title": "大朝会 · 百官入朝",
        "desc": (f"朔日大朝，百官入朝班列如仪——{roster}。{scene}\n"
                 f"今日要议的奏本已有三匣，满殿都在看太后如何临朝。"),
        "choices": [
            {"text": "亲临主裁——撤帘御外朝，当殿裁断", "effects": {"way": "preside"}},
            {"text": "垂帘静观——如例垂帘，静听后再断", "effects": {"way": "curtain"}},
            {"text": "称疾不朝——命协理代听", "effects": {"way": "absent"}},
        ],
        "period": f"{game_state.year}年{game_state.month}月",
    })
    return ["👑 朔日大朝会，百官入朝班列——须定临朝之仪"]


def _resolve_court_session(game_state, d, way):
    """大朝会结算：出席方式 × 新帝性格 × 百官态度。"""
    emp = d["emperor"]
    pname = emp.get("personality", "仁厚")
    pspec = emperor_personality_spec(d)
    msgs = []
    ministers = ensure_court_ministers(game_state, d)
    if way == "preside":
        applied = _apply_effects(game_state, d, {"权威": 8, "朝堂": -4, "民心": -2, "帝心": -3})
        _ministers_attitude_shift(d, {"文官党": -4, "武官党": 2, "宗室党": -2})
        flavor = {"仁厚": "他始终垂手立在你侧，诸事都以你断为准。",
                  "多疑": "你每裁一事，他的目光就在你脸上停一瞬。",
                  "暴戾": "有两议他当殿驳了你的口谕，殿上霎时死寂。",
                  "庸懒": "他乐得躲在你身后，连「请太后圣裁」都说得顺口。"}.get(pname, "")
        msgs.append(f"👑 你亲御外朝，当殿连裁三匣奏本。{flavor}（权威+8，朝堂-4）")
    elif way == "curtain":
        applied = _apply_effects(game_state, d, {"权威": 2, "朝堂": 5, "帝心": 2})
        _ministers_attitude_shift(d, {"文官党": 3, "武官党": 1, "宗室党": 2})
        flavor = {"仁厚": "散朝后他绕到帘后，把今日的争论讲给你听。",
                  "多疑": "帘外争论正酣，帘后能听见他几次压着嗓子与近侍耳语。",
                  "暴戾": "他今日难得耐性，照你的意思把该驳的驳了。",
                  "庸懒": "他在御座上险些睡着，全靠你在帘后提词。"}.get(pname, "")
        msgs.append(f"🎚️ 你如例垂帘，听百官争了半日才落朱批。{flavor}（权威+2，朝堂+5）")
    else:
        applied = _apply_effects(game_state, d, {"权威": -6, "朝堂": -3, "帝心": 4})
        _ministers_attitude_shift(d, {"文官党": -5, "武官党": -4, "宗室党": -4})
        if pname == "庸懒":
            applied = _apply_effects(game_state, d, {"帝心": 3})
            msgs.append("🛌 你称疾不朝。他倒高兴——终于能自己说了算了（帝心+3，权威-6）")
        else:
            msgs.append(f"🛌 你称疾不朝，朝会草草而散。散朝时百官交换眼色的样子，你虽不在，也想得到。（权威-6，朝堂-3）")
    # 势力联动：领袖态度随派系好感、派系好感随出席方式微调
    favor = {"文官党": 50, "武官党": 50, "宗室党": 50}
    favor.update(getattr(game_state, "court_faction_favor", None) or {})
    for m in ministers:
        favor[m["faction"]] = _clamp(int(favor.get(m["faction"], 50)) +
                                     (-2 if way == "preside" else 2 if way == "curtain" else -2))
    game_state.court_faction_favor = favor
    d["sessions_held"] = int(d.get("sessions_held", 0) or 0) + 1
    d["last_session"] = {"preside": "亲临", "curtain": "垂帘", "absent": "称疾"}[way]
    _log(d, f"大朝会：{d['last_session']}")
    return applied, msgs



def dowager_period_tick(game_state):
    """转旬：奏事生成、国库民心自然变动、新帝成长、亲政请求与失势危机。

    已称制则转入女帝朝政循环（reign_period_tick）。
    """
    d = get_dowager(game_state)
    if d.get("regnant"):
        return reign_period_tick(game_state)
    if not d.get("active"):
        return []
    msgs = []
    d["periods"] += 1
    # 财政与民心
    income = 120 + d["people"] // 2 + d["court"] // 3
    d["treasury"] = max(0, d["treasury"] + income - 100)
    if d["treasury"] <= 0:
        d["people"] = _clamp(d["people"] - 5)
        msgs.append("💸 国库空虚，京畿米价飞涨，民怨渐起（民心-5）")
    # 积压奏本消磨权威
    if len(d["pending"]) >= 3:
        d["authority"] = _clamp(d["authority"] - 3)
        msgs.append("📜 奏本积压不批，朝臣私议太后倦政（摄政权威-3）")
    # 新帝性格的每旬漂移
    pspec = emperor_personality_spec(d)
    d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] + int(pspec.get("affection_drift", 0)))
    d["emperor"]["majesty"] = _clamp(d["emperor"]["majesty"] + int(pspec.get("majesty_drift", 0)))
    d["authority"] = _clamp(d["authority"] + int(pspec.get("authority_drift", 0)))
    # 后宫治理模式的每旬效应
    mode = d.get("harem_mode", HAREM_MODE_DEFAULT)
    spec = HAREM_MODES.get(mode) or {}
    d["authority"] = _clamp(d["authority"] + int(spec.get("authority", 0)))
    d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] + int(spec.get("emperor_affection", 0)))
    d["queen_favor"] = _clamp(d.get("queen_favor", 50) + int(spec.get("queen_favor", 0)))
    # 新帝立后
    if not d.get("new_queen") and d["emperor"]["age"] >= 14:
        q = ensure_new_queen(game_state, d)
        if q:
            msgs.append(f"👑 {d['emperor']['name']}册立{q}为后，六宫有主")
    # 新后敬顺过低 → 联手新帝抗命
    if d.get("new_queen") and d.get("queen_favor", 50) <= 20 and random.random() < 0.3:
        d["authority"] = _clamp(d["authority"] - 4)
        d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] - 3)
        msgs.append(f"🕸️ {d['new_queen']}在御前哭诉太后严苛，新帝默然听了很久（权威-4，帝心-3）")
    # 皇孙诞生
    gc = int(d.get("grandchild_chance", 0) or 0)
    if gc > 0 and random.random() < gc / 100.0:
        d["grandchild_chance"] = 0
        d["authority"] = _clamp(d["authority"] + 3)
        d["people"] = _clamp(d["people"] + 4)
        d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] + 5)
        msgs.append(f"👶 {d['emperor']['name']}得了皇长子，宗庙有继——你成了太皇太后的辈分（权威+3，民心+4，帝心+5）")
        game_state.add_memory("👶 皇孙诞生，宗庙有继")
    # 新帝成长
    if d["periods"] % 3 == 0:
        d["emperor"]["age"] += 1
        d["emperor"]["majesty"] = _clamp(d["emperor"]["majesty"] + random.randint(0, 2))
        adult_at = emperor_adult_age(d)
        if d["emperor"]["age"] == adult_at:
            d["return_requested"] = 1
            pname = d["emperor"].get("personality", "仁厚")
            hint = {"多疑": "他等这一日已久", "暴戾": "他说这话时手按在剑柄上",
                    "庸懒": "倒是朝臣比他还急", "仁厚": "他先向你行了礼才开口"}.get(pname, "")
            msgs.append(f"👑 {d['emperor']['name']}已及{adult_at}岁，行冠礼，朝野皆言当亲政——{hint}（可归政或拒还）")
        else:
            msgs.append(f"👦 {d['emperor']['name']}又长一岁（{d['emperor']['age']}岁，威仪{d['emperor']['majesty']}）")
    # 亲政请求逾期未决
    if d["return_requested"]:
        d["return_requested"] += 1
        if d["return_requested"] > RETURN_POWER_GRACE:
            from app import trigger_ending
            seize = float(pspec.get("seize_risk", 0.0) or 0.0)
            if seize > 0 and random.random() < seize:
                d["active"] = False
                game_state.dowager_mode = False
                pname = d["emperor"].get("personality", "多疑")
                why = "疑你久握权柄，先下手为强" if pname == "多疑" else "一怒之下命禁军围了慈宁宫"
                trigger_ending(game_state, "幽居慈宁",
                               f"{d['emperor']['name']}性{pname}，{why}")
                msgs.append(f"⛓️ {d['emperor']['name']}{why}——这一次他没有再问你的意思。（终局：幽居慈宁）")
                return msgs
            if d["emperor"]["majesty"] >= 60 and d["emperor"]["affection"] < 40:
                d["active"] = False
                game_state.dowager_mode = False
                trigger_ending(game_state, "幽居慈宁",
                               f"{d['emperor']['name']}羽翼已成，恨你久握权柄，奉你于慈宁宫「养尊」")
                msgs.append("⛓️ 新帝终究动了手——慈宁宫的门从外面锁上了。（终局：幽居慈宁）")
                return msgs
            d["authority"] = _clamp(d["authority"] - 5)
            d["emperor"]["affection"] = _clamp(d["emperor"]["affection"] - 5)
            msgs.append("⏳ 还政之事悬而未决，朝野议论纷纷（摄政权威-5，帝心-5）")
    # 失势危机
    if d["authority"] <= REGENCY_CRISIS_AUTH:
        from app import trigger_ending
        if random.random() < 0.4:
            d["active"] = False
            game_state.dowager_mode = False
            trigger_ending(game_state, "幽居慈宁", "摄政权威扫地，为群臣所弃")
            msgs.append("⛓️ 朝臣联名请太后「颐养天年」。这一次，没有人再向帘幕行礼。（终局：幽居慈宁）")
            return msgs
        msgs.append("⚠️ 帘外的礼数越来越薄了——摄政权威已危（<25）")
    # 新帝后宫名册：铺开 / 生育 / 请安
    if d["emperor"]["age"] >= 13:
        roster = ensure_new_harem(game_state, d)
        if roster and random.random() < 0.12:
            c = random.choice(roster)
            if not c.get("pregnant") and int(c.get("children", 0) or 0) < 3:
                c["pregnant"] = True
                msgs.append(f"🤰 {c['rank']}{c['name']}传出有孕，慈宁宫先得了消息")
        for c in roster:
            if c.get("pregnant") and random.random() < 0.35:
                c["pregnant"] = False
                c["children"] = int(c.get("children", 0) or 0) + 1
                d["authority"] = _clamp(d["authority"] + 2)
                d["people"] = _clamp(d["people"] + 2)
                msgs.append(f"👶 {c['rank']}{c['name']}诞下皇嗣，宗庙又添一枝（权威+2，民心+2）")
                break
        low = [c for c in roster if int(c.get("respect", 50) or 50) <= 15]
        if low and random.random() < 0.2:
            c = random.choice(low)
            d["authority"] = _clamp(d["authority"] - 2)
            msgs.append(f"🕸️ {c['rank']}{c['name']}称病不来慈宁宫问安，宫里都在看（权威-2）")
    # 三方势力：与既有系统对齐 + 自然消长 + 干政事件
    _sync_external_powers(game_state, d)
    d["minister_power"] = _clamp(int(d.get("minister_power", 45)) + random.choice([-1, 0, 1, 1]))
    if len(d.get("meddle") or []) >= MEDDLE_QUEUE_MAX:
        d["authority"] = _clamp(d["authority"] - 2)
        msgs.append("🕸️ 外朝内廷的请托积压不理，人人都在看太后能不能压住场（摄政权威-2）")
    if int(d.get("minister_power", 45)) >= MINISTER_SEIZE_POWER:
        d["authority"] = _clamp(d["authority"] - 4)
        d["court"] = _clamp(d["court"] - 3)
        msgs.append(f"⚖️ {ensure_minister(game_state, d)}权势已成，票拟不复经帘（摄政权威-4，朝堂-3）")
    if int(d.get("clan_power", 30)) >= 80:
        d["people"] = _clamp(d["people"] - 3)
        msgs.append("🏠 母家势盛，京中已有「一门两国舅」的讥议（民心-3）")
    msgs.extend(generate_meddle_events(game_state))
    # 百官班次：领袖态度过低的会出班发难
    ensure_court_ministers(game_state, d)
    trouble = [m for m in (d.get("ministers") or []) if int(m.get("attitude", 40) or 0) <= 18]
    if trouble:
        m = random.choice(trouble)
        d["minister_power"] = _clamp(int(d.get("minister_power", 45) or 0) + 4)
        msgs.append(f"🕸️ {m['faction']}{m['name']}出班发难，语多讥刺帘政（其势+4）")
    # 大朝会：到期开场（称制期在 reign_period_tick 内御门听政）
    if d["periods"] % COURT_SESSION_INTERVAL == 0 and not d.get("regnant"):
        msgs.extend(open_court_session(game_state))
    # 领袖态度向派系好感回归
    favor = {"文官党": 50, "武官党": 50, "宗室党": 50}
    favor.update(getattr(game_state, "court_faction_favor", None) or {})
    for m in d.get("ministers") or []:
        target = _clamp(int(favor.get(m["faction"], 50) or 50))
        cur = int(m.get("attitude", 40) or 0)
        m["attitude"] = _clamp(cur + (1 if cur < target else -1 if cur > target else 0))
    # 生成新奏事
    msgs.extend(generate_court_affairs(game_state))
    return msgs


def dowager_payload(game_state):
    d = get_dowager(game_state)
    from app import normalize_court_faction_favor
    return {
        "active": bool(d.get("active")),
        "authority": d["authority"], "court": d["court"],
        "treasury": d["treasury"], "people": d["people"],
        "emperor": dict(d["emperor"]),
        "emperor_personality": {
            "name": (d.get("emperor") or {}).get("personality", "仁厚"),
            **{k: v for k, v in emperor_personality_spec(d).items() if k in ("desc", "flavor")},
        },
        "adult_age_actual": emperor_adult_age(d),
        "periods": d["periods"],
        "pending": list(d["pending"]),
        "history": list(d["history"])[:6],
        "log": list(d["log"])[:8],
        "return_requested": d["return_requested"],
        "adult_age": EMPEROR_ADULT_AGE,
        "regnant_req": {"authority": EMPRESS_REGNANT_AUTH, "court": EMPRESS_REGNANT_COURT},
        "factions": normalize_court_faction_favor(getattr(game_state, "court_faction_favor", None)),
        "actions": [{"key": k, "name": v["name"], "desc": v["desc"],
                     "used": k in (d.get("used_actions") or [])}
                    for k, v in DOWAGER_ACTIONS.items()],
        "harem_mode": d.get("harem_mode", HAREM_MODE_DEFAULT),
        "harem_modes": [{"key": k, "name": v["name"], "desc": v["desc"]} for k, v in HAREM_MODES.items()],
        "new_queen": d.get("new_queen", ""),
        "queen_favor": d.get("queen_favor", 50),
        "grandchild_chance": int(d.get("grandchild_chance", 0) or 0),
        "harem_actions": [{"key": k, "name": v["name"], "desc": v["desc"],
                           "allowed": d.get("harem_mode", HAREM_MODE_DEFAULT) in v["min_mode"],
                           "used": ("harem_" + k) in (d.get("used_actions") or [])}
                          for k, v in HAREM_ACTIONS.items()],
        "harem_log": list(d.get("harem_log") or [])[:5],
        "clan_power": int(d.get("clan_power", 30) or 0),
        "royal_power": int(d.get("royal_power", 40) or 0),
        "minister_power": int(d.get("minister_power", 45) or 0),
        "minister": d.get("minister", ""),
        "meddle": list(d.get("meddle") or []),
        "ministers": [{k: m.get(k) for k in ("name", "faction", "power", "attitude")}
                      for m in (d.get("ministers") or [])],
        "sessions_held": int(d.get("sessions_held", 0) or 0),
        "last_session": d.get("last_session", ""),
        "session_due": (not d.get("regnant")) and d.get("periods", 0) % COURT_SESSION_INTERVAL == COURT_SESSION_INTERVAL - 1,
        "meddle_log": list(d.get("meddle_log") or [])[:5],
        "consorts": dowager_harem_roster(d),
        "consort_log": list(d.get("consort_log") or [])[:5],
        "consort_ranks": list(NEW_HAREM_RANKS),
        **reign_payload(d),
    }
