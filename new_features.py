# -*- coding: utf-8 -*-
"""新玩法模块：节令宴饮 / 太医网络 / 宫廷市集。

设计原则（与 affair_system / recommend_system 等同级模块一致）：
- 状态挂在 GameState 的 banquet / medical / market 三个 dict 上，旧存档缺字段时由
  models.from_dict 兜底默认值，本模块所有函数对缺失键做防御读取。
- 不引入外部服务、不新增数据库；全部为纯内存 + JSON 存档。
- 与已有系统联动：宴饮吃宠爱/威望/党争好感；太医挂钩怀孕/中毒/健康；市集吃银两并
  向关系/属性/太医供弹药（礼物、药材）。
"""
import random

# ============================================================
#  一、节令宴饮
# ============================================================
# 每月至多一场；attended 记录 {节令key: 已办年份}，实现"每年一届"。
BANQUETS = {
    "shangyuan": {
        "name": "上元灯会", "month": 1, "icon": "🏮",
        "desc": "上元佳节，宫城张灯。皇帝携妃嫔登午楼观灯，命妇随侍，御前争彩之时。",
        "choices": [
            {"text": "🎆 献花灯争彩头（银两80）", "cost_silver": 80,
             "check": None,
             "success": {"宠爱": (6, 12), "威望": (2, 5)}, "fail": {},
             "narrate": "你的花灯压过宫制巧匠，皇帝驻足良久，赐彩绢两匹。"},
            {"text": "✍️ 即席赋诗（才情判定）", "cost_silver": 0,
             "check": {"attr": "才情", "dc": 55},
             "success": {"宠爱": (4, 8), "才情": (1, 3), "威望": (3, 6)},
             "fail": {"宠爱": (-3, -1)},
             "narrate_ok": "一句『火树银花合星桥』满座称奇，皇帝亲赐御酒。",
             "narrate_no": "诗句撞了前人之作，御前失仪，只得讪讪退下。"},
            {"text": "🍡 安坐陪宴，与邻座妃嫔闲话", "cost_silver": 0,
             "check": None, "success": {"福运": (1, 3)}, "fail": {},
             "bond": {"favor": 6},
             "narrate": "你与邻座妃嫔说得投契，灯影里结了一份香火情。"},
        ],
    },
    "huachao": {
        "name": "花朝赏红", "month": 2, "icon": "🌸",
        "desc": "二月花朝，剪彩为花、系枝为红。后宫例设赏红宴，斗草簪花，最见巧思。",
        "choices": [
            {"text": "🌷 献绣品赏红（才艺判定）", "cost_silver": 30,
             "check": {"attr": "才艺", "dc": 50},
             "success": {"宠爱": (4, 8), "威望": (2, 5)}, "fail": {"银两": 0},
             "narrate_ok": "你的并蒂芍药绣片艳压群芳，皇后特赐宫缎一匹。",
             "narrate_no": "绣色被雨水洇了，未能尽展巧思，只落了个参与。"},
            {"text": "🌿 斗草赌戏（福运判定，押银50）", "cost_silver": 50,
             "check": {"attr": "福运", "dc": 45},
             "success": {"宠爱": (2, 5)}, "fail": {},
             "narrate_ok": "草茎不断，你笑纳众妃押注，银两翻倍。",
             "narrate_no": "一折即断，愿赌服输，众妃笑作一团。"},
            {"text": "🍵 素手调香，侍奉太后", "cost_silver": 0,
             "check": None, "success": {"威望": (2, 4), "福运": (1, 2)}, "fail": {},
             "narrate": "太后闻香而喜，夸你稳重知礼，孝名暗传六宫。"},
        ],
    },
    "duanwu": {
        "name": "端午宫宴", "month": 5, "icon": "🐉",
        "desc": "端午龙舟，赐扇系缕。校场龙舟竞渡，后宫设宴临水观之。",
        "choices": [
            {"text": "🚣 押注夺冠龙舟（银两100）", "cost_silver": 100,
             "check": {"attr": "福运", "dc": 50},
             "success": {"宠爱": (3, 6)}, "fail": {},
             "narrate_ok": "你所押龙舟夺标，赔注颇丰，皇帝隔水遥遥一举金杯。",
             "narrate_no": "龙舟中途折桨，百两银钱打了水漂。"},
            {"text": "🎐 献艾虎香囊于御前", "cost_silver": 20,
             "check": None, "success": {"宠爱": (3, 6), "健康": (1, 3)}, "fail": {},
             "narrate": "香囊精巧，皇帝佩于身侧三日，六宫仿效成风。"},
            {"text": "🏹 校场射柳（谋略判定）", "cost_silver": 0,
             "check": {"attr": "谋略", "dc": 55},
             "success": {"威望": (4, 8)}, "fail": {"威望": (-2, -1)},
             "narrate_ok": "一箭断柳，武名藉甚，宗室王公遥遥颔首。",
             "narrate_no": "三箭虚发，沦为校场笑谈。"},
        ],
    },
    "qixi": {
        "name": "七夕乞巧", "month": 7, "icon": "🪡",
        "desc": "七夕夜，穿针乞巧、拜牛女。是夜宫禁稍弛，最宜传情。",
        "choices": [
            {"text": " 穿针乞巧比速（才艺判定）", "cost_silver": 0,
             "check": {"attr": "才艺", "dc": 45},
             "success": {"宠爱": (3, 6), "才情": (1, 2)}, "fail": {},
             "narrate_ok": "九孔皆通，巧名传遍六宫，皇帝笑唤你『巧姐』。",
             "narrate_no": "线头散乱，只落得与姊妹们笑作一处。"},
            {"text": "🌌 月下与皇帝私语", "cost_silver": 0,
             "check": {"attr": "魅力", "dc": 50},
             "success": {"宠爱": (6, 12)}, "fail": {"宠爱": (0, 2)},
             "narrate_ok": "星河为证，帝妃执手，翌日宫中皆传圣眷。",
             "narrate_no": "皇帝心不在焉，你讨了个没趣。"},
            {"text": "🎋 结彩楼祀牛女，为宫中生民祈福", "cost_silver": 40,
             "check": None, "success": {"威望": (3, 6), "福运": (2, 4)}, "fail": {},
             "narrate": "彩楼高结，宫人皆称你贤德，善名远播。"},
        ],
    },
    "zhongqiu": {
        "name": "中秋月宴", "month": 8, "icon": "🌕",
        "desc": "中秋夜，登月华门赏月，分咏月饼。团圆之宴，暗流亦多。",
        "choices": [
            {"text": "🥮 精制月饼分赠诸妃（银两60）", "cost_silver": 60,
             "check": None, "success": {"宠爱": (1, 3)}, "fail": {},
             "bond_all": {"favor": 5},
             "narrate": "月饼甜而不腻，诸妃回礼络绎，你在后宫的人情簿又厚了一页。"},
            {"text": "📜 月华门联诗（才情判定）", "cost_silver": 0,
             "check": {"attr": "才情", "dc": 60},
             "success": {"宠爱": (4, 8), "威望": (4, 8)}, "fail": {"才情": (0, 1)},
             "narrate_ok": "你的句子被翰林写入《月赋》，文名远达宗室。",
             "narrate_no": "联句迟滞，皇帝转与他妃联咏，你默默饮尽一杯。"},
            {"text": "🍂 称病早退，静观席间暗流", "cost_silver": 0,
             "check": {"attr": "心计", "dc": 45},
             "success": {"心计": (1, 3)}, "fail": {"宠爱": (-2, -1)},
             "narrate_ok": "早退反叫你窥见席后私语，一条要紧消息入手。",
             "narrate_no": "称病被识破，皇帝怪你失礼，宠爱稍减。"},
        ],
    },
    "dongzhi": {
        "name": "冬至大祀", "month": 11, "icon": "🕯️",
        "desc": "冬至郊祀，礼部主祭，后宫从祀坤宁殿。一年将尽，福祸皆要清算。",
        "choices": [
            {"text": "📿 斋戒三日，代天子祈国祚（威望判定）", "cost_silver": 50,
             "check": {"attr": "威望", "dc": 60},
             "success": {"威望": (6, 12), "宠爱": (2, 5)}, "fail": {"威望": (1, 3)},
             "narrate_ok": "祈文被礼部存档，宗人府记你首功，朝野侧目。",
             "narrate_no": "仪程生疏，礼官暗皱眉头，好在无过即是功。"},
            {"text": "🧧 广施宫人炭米（银两120）", "cost_silver": 120,
             "check": None, "success": {"福运": (2, 5), "威望": (2, 4)}, "fail": {},
             "bond_all": {"favor": 4},
             "narrate": "炭米送到各宫下人手里，颂声载道，连冷宫都念你的好。"},
            {"text": "🏮 守岁宴上敬酒拉拢（魅力判定）", "cost_silver": 0,
             "check": {"attr": "魅力", "dc": 50},
             "success": {"宠爱": (3, 6)}, "fail": {},
             "bond": {"favor": 8},
             "narrate_ok": "三杯两盏，你与那位素来中立的妃嫔成了互访之交。",
             "narrate_no": "酒过三巡失言，对方笑而不语，交情未进分毫。"},
        ],
    },
}


def _clamp_attr(game_state, attr, val):
    if attr == "银两":
        return val
    mx = game_state.get_attr_max(attr)
    return max(0, min(mx, game_state.attributes.get(attr, 0) + val))


def ensure_banquet_state(game_state):
    b = getattr(game_state, "banquet", None)
    if not isinstance(b, dict):
        b = {"pending": None, "attended": {}, "log": []}
        game_state.banquet = b
    b.setdefault("pending", None)
    if not isinstance(b.get("attended"), dict):
        b["attended"] = {}
    if not isinstance(b.get("log"), list):
        b["log"] = []
    return b


def generate_banquet(game_state):
    """转旬月初调用：本月有节令且今年未办 → 生成待赴宴饮。返回提示消息或 None。"""
    b = ensure_banquet_state(game_state)
    if b.get("pending"):
        return None
    if game_state.day > 10:  # 只在每月上旬发出请柬
        return None
    for key, cfg in BANQUETS.items():
        if cfg["month"] != game_state.month:
            continue
        if b["attended"].get(key) == game_state.year:
            continue
        b["pending"] = {
            "key": key, "name": cfg["name"], "icon": cfg["icon"],
            "desc": cfg["desc"], "year": game_state.year,
            "choices": [{"text": c["text"]} for c in cfg["choices"]],
        }
        return f"🏮 节令帖到：{cfg['icon']} {cfg['name']}设于本旬，请择席面应对。"
    return None


def resolve_banquet(game_state, choice_index):
    """玩家择选应对。返回 (ok, msg, effects_summary)。"""
    b = ensure_banquet_state(game_state)
    pending = b.get("pending")
    if not pending:
        return False, "本旬并无节令宴饮", None
    cfg = BANQUETS.get(pending["key"])
    if not cfg:
        b["pending"] = None
        return False, "宴饮已散", None
    idx = int(choice_index or 0)
    if idx < 0 or idx >= len(cfg["choices"]):
        return False, "无效的应对", None
    ch = cfg["choices"][idx]
    cost = int(ch.get("cost_silver", 0) or 0)
    if cost and game_state.silver < cost:
        return False, f"银两不足，此应对需{cost}两", None
    if cost:
        game_state.silver -= cost
    # 属性判定
    ok = True
    check = ch.get("check")
    if check:
        dc = int(check.get("dc", 50))
        roll = game_state.attributes.get(check["attr"], 0) + random.randint(-15, 15)
        ok = roll >= dc
    effects = ch.get("success") if ok else ch.get("fail")
    applied = {}
    for attr, rng in (effects or {}).items():
        if attr == "银两":
            continue
        lo, hi = rng if isinstance(rng, (list, tuple)) else (rng, rng)
        delta = random.randint(int(lo), int(hi))
        if delta:
            game_state.attributes[attr] = _clamp_attr(game_state, attr, delta)
            applied[attr] = delta
    # 宴饮人缘：bond 指定邻座一人 / bond_all 普涨
    bond = ch.get("bond") or ch.get("bond_all")
    if bond:
        gain = int(bond.get("favor", 5))
        pool = [n for n, npc in (game_state.npcs or {}).items()
                if n not in ("太后",) and npc.get("alive", True)]
        if ch.get("bond_all"):
            for n in pool[:8]:
                rel = game_state.relationships.setdefault(n, {"好感": 0})
                rel["好感"] = max(-100, min(100, rel.get("好感", 0) + gain))
            applied["诸妃好感"] = gain
        elif pool:
            n = random.choice(pool)
            rel = game_state.relationships.setdefault(n, {"好感": 0})
            rel["好感"] = max(-100, min(100, rel.get("好感", 0) + gain))
            applied[f"与{n}好感"] = gain
    narrate = ch.get("narrate") or (ch.get("narrate_ok") if ok else ch.get("narrate_no")) or ""
    eff_txt = "、".join(f"{k}{v:+d}" if isinstance(v, int) else f"{k}+{v}" for k, v in applied.items())
    msg = f"{cfg['icon']} {cfg['name']}：{narrate}" + (f"（{eff_txt}）" if eff_txt else "")
    b["attended"][pending["key"]] = game_state.year
    b["pending"] = None
    b["log"].append(f"{game_state.get_calendar_str()} {cfg['name']}·{ch['text']}")
    b["log"] = b["log"][-20:]
    game_state.add_memory(f"赴{cfg['name']}，择「{ch['text']}」")
    return True, msg, applied


# ============================================================
#  二、太医网络
# ============================================================
MEDICIAN_DEFAULT = {"name": "沈修", "favor": 20, "skill": 55}
# 病症：每旬扣健康，可医治
CONDITIONS = {
    "风寒": {"decay": 2, "cure_cost": 20, "desc": "偶感风寒，咳嗽不止"},
    "旧疾": {"decay": 3, "cure_cost": 40, "desc": "旧疾复发，缠绵榻上"},
    "产后亏虚": {"decay": 2, "cure_cost": 30, "desc": "生产伤了元气，需慢慢将养"},
    "郁结": {"decay": 2, "cure_cost": 25, "desc": "心绪郁结，夜不能寐"},
}
HERBS = {"安胎药": 40, "解毒散": 50, "养身丸": 30}


def ensure_medical_state(game_state):
    m = getattr(game_state, "medical", None)
    if not isinstance(m, dict):
        m = {"physician": dict(MEDICIAN_DEFAULT), "conditions": [], "herbs": {}, "log": []}
        game_state.medical = m
    if not isinstance(m.get("physician"), dict):
        m["physician"] = dict(MEDICIAN_DEFAULT)
    if not isinstance(m.get("conditions"), list):
        m["conditions"] = []
    if not isinstance(m.get("herbs"), dict):
        m["herbs"] = {}
    if not isinstance(m.get("log"), list):
        m["log"] = []
    return m


def medical_period_tick(game_state):
    """转旬结算：病症衰减/新发、孕期胎象。返回消息列表。"""
    msgs = []
    m = ensure_medical_state(game_state)
    phys = m["physician"]
    favor = int(phys.get("favor", 20) or 0)
    # 1) 已有病症：每旬扣健康；高好感太医自动调理减半
    for cond in list(m["conditions"]):
        name = cond.get("name")
        spec = CONDITIONS.get(name)
        if not spec:
            m["conditions"].remove(cond)
            continue
        decay = int(spec["decay"])
        if favor >= 60:
            decay = max(1, decay // 2)
        game_state.attributes["健康"] = max(0, game_state.attributes.get("健康", 60) - decay)
        cond["months"] = int(cond.get("months", 0)) + 1
        msgs.append(f"🌿 {spec['desc']}，健康-{decay}{'（太医调理中，损耗减半）' if favor >= 60 else ''}")
        # 郁结/旧疾拖久了会加重
        if cond["months"] >= 4 and name == "风寒":
            cond["name"] = "旧疾"
            cond["months"] = 0
            msgs.append("⚠️ 风寒迁延不愈，竟成了旧疾。")
    # 2) 新发疾病：低健康概率病倒；失宠概率郁结
    hp = game_state.attributes.get("健康", 60)
    have = {c.get("name") for c in m["conditions"]}
    if hp < 35 and "风寒" not in have and random.random() < 0.25:
        m["conditions"].append({"name": "风寒", "months": 0})
        msgs.append("🤒 你身子虚弱，染了风寒。可去太医处诊治。")
    if game_state.attributes.get("宠爱", 0) < 15 and "郁结" not in have and random.random() < 0.12:
        m["conditions"].append({"name": "郁结", "months": 0})
        msgs.append("💔 深宫夜长，忧思成疾，你添了郁结之症。")
    # 3) 孕期胎象：12% 不稳；有安胎药或太医好感≥50 可化解
    if game_state.is_pregnant and random.random() < 0.12:
        herbs = m.get("herbs") or {}
        if int(herbs.get("安胎药", 0) or 0) > 0:
            herbs["安胎药"] = int(herbs["安胎药"]) - 1
            msgs.append("🫖 胎象微动，幸而你早备下安胎药，服后安然。")
        elif favor >= 50:
            msgs.append("🩺 胎象微动，太医{0}及时请脉安胎，有惊无险。".format(phys.get("name", "太医")))
        else:
            game_state.attributes["健康"] = max(0, game_state.attributes.get("健康", 60) - 5)
            msgs.append("⚠️ 胎象不稳，太医署无人用心，健康-5。宜备安胎药或结交太医。")
    m["log"].extend(msgs)
    m["log"] = m["log"][-20:]
    return msgs


def poison_screen(game_state):
    """玩家遭下毒时的太医拦截钩子（app.py 冲突结算调用）。
    返回 (mitigated, herb_used, rumor)：mitigated=True 表示毒性已被化解一半。"""
    m = ensure_medical_state(game_state)
    phys = m["physician"]
    herbs = m.get("herbs") or {}
    if int(herbs.get("解毒散", 0) or 0) > 0:
        herbs["解毒散"] = int(herbs["解毒散"]) - 1
        return True, True, "你素日备下的解毒散派了用场，毒性大减。"
    if int(phys.get("favor", 0) or 0) >= 50 and random.random() < 0.45:
        return True, False, f"太医{phys.get('name', '')}察觉汤色有异，及时换盏，毒性大减。"
    return False, False, ""


def medical_action(game_state, action, target=""):
    """太医网络玩家动作。返回 (ok, msg)。"""
    m = ensure_medical_state(game_state)
    phys = m["physician"]
    if action == "consult":
        if game_state.silver < 10:
            return False, "银两不足，请脉需10两"
        game_state.silver -= 10
        phys["favor"] = min(100, int(phys.get("favor", 20)) + 2)
        conds = m.get("conditions") or []
        if conds:
            lines = "；".join(f"{c.get('name')}（已缠{int(c.get('months', 0)) + 1}旬）" for c in conds)
            return True, f"🩺 太医{phys['name']}切脉良久：{lines}。太医好感+2。"
        return True, f"🩺 太医{phys['name']}道脉象平稳，并无大碍。太医好感+2。"
    if action == "treat":
        conds = m.get("conditions") or []
        cond = next((c for c in conds if c.get("name") == target), None) if target else (conds[0] if conds else None)
        if not cond:
            return False, "身上并无病症可医"
        spec = CONDITIONS.get(cond.get("name"))
        if not spec:
            m["conditions"].remove(cond)
            return False, "病症已消"
        cost = int(spec["cure_cost"])
        if game_state.silver < cost:
            return False, f"银两不足，医「{cond['name']}」需{cost}两"
        game_state.silver -= cost
        m["conditions"].remove(cond)
        heal = random.randint(4, 8)
        game_state.attributes["健康"] = min(game_state.get_attr_max("健康"), game_state.attributes.get("健康", 60) + heal)
        phys["favor"] = min(100, int(phys.get("favor", 20)) + 1)
        return True, f"💊 太医{phys['name']}开方施治，{cond['name']}已愈，健康+{heal}（-{cost}两）。"
    if action == "gift":
        if game_state.silver < 20:
            return False, "银两不足，打点太医需20两"
        game_state.silver -= 20
        gain = random.randint(3, 6)
        phys["favor"] = min(100, int(phys.get("favor", 20)) + gain)
        return True, f"🎁 你遣人给太医{phys['name']}送了份节礼，太医好感+{gain}。"
    return False, "无效的太医动作"


# ============================================================
#  三、宫廷市集
# ============================================================
MARKET_CATALOG = [
    {"id": "gift_shujin", "name": "蜀锦一匹", "price": 60, "icon": "🧣", "kind": "gift", "favor": 8,
     "desc": "赠礼诸妃，好感+8"},
    {"id": "gift_pearl", "name": "南珠一盒", "price": 120, "icon": "🦪", "kind": "gift", "favor": 16,
     "desc": "赠礼诸妃，好感+16"},
    {"id": "book_rare", "name": "诗赋孤本", "price": 80, "icon": "📖", "kind": "attr", "attr": "才情", "gain": 3,
     "desc": "研读一旬，才情+3"},
    {"id": "jewel_pin", "name": "点翠头面", "price": 100, "icon": "💎", "kind": "attr", "attr": "容貌", "gain": 2,
     "desc": "御前增色，容貌+2"},
    {"id": "bribe_case", "name": "打点刑名", "price": 150, "icon": "🕴️", "kind": "bribe",
     "desc": "压下嫌疑：任一在办案件嫌疑-20"},
    {"id": "herb_taian", "name": "安胎药", "price": 40, "icon": "🫖", "kind": "herb", "herb": "安胎药",
     "desc": "入药匣，胎象不稳时自动服用"},
    {"id": "herb_jiedu", "name": "解毒散", "price": 50, "icon": "🧪", "kind": "herb", "herb": "解毒散",
     "desc": "入药匣，遭下毒时自动化解半数毒性"},
    {"id": "pill_yangshen", "name": "养身丸", "price": 30, "icon": "🍯", "kind": "instant", "attr": "健康", "gain": 10,
     "desc": "即服，健康+10"},
]


def ensure_market_state(game_state):
    mk = getattr(game_state, "market", None)
    if not isinstance(mk, dict):
        mk = {"stock": [], "refreshed": ""}
        game_state.market = mk
    if not isinstance(mk.get("stock"), list):
        mk["stock"] = []
    mk.setdefault("refreshed", "")
    return mk


def market_refresh(game_state, force=False):
    """每月自动轮换货架（随机 5-6 件）。返回是否刷新。"""
    mk = ensure_market_state(game_state)
    key = f"{game_state.year}-{game_state.month}"
    if not force and mk.get("refreshed") == key:
        return False
    picks = random.sample(MARKET_CATALOG, k=min(len(MARKET_CATALOG), random.randint(5, 6)))
    mk["stock"] = [{"id": p["id"], "stock": random.randint(1, 3)} for p in picks]
    mk["refreshed"] = key
    return True


def market_buy(game_state, item_id, target=""):
    """购买市集货物。返回 (ok, msg)。"""
    mk = ensure_market_state(game_state)
    entry = next((s for s in mk.get("stock") or [] if s.get("id") == item_id), None)
    if not entry:
        return False, "本月市集未售此货，待下月再观"
    if int(entry.get("stock", 0) or 0) <= 0:
        return False, "此货已售罄，待下月市集"
    spec = next((c for c in MARKET_CATALOG if c["id"] == item_id), None)
    if not spec:
        return False, "无此货物"
    price = int(spec["price"])
    if game_state.silver < price:
        return False, f"银两不足，{spec['name']}需{price}两"
    kind = spec.get("kind")
    # 礼物需要指定受赠妃嫔
    if kind == "gift":
        if not target or target not in game_state.npcs or not game_state.npcs[target].get("alive", True):
            names = "、".join(list(game_state.npcs.keys())[:6])
            return False, f"请指定一位在世妃嫔为受赠人（如：{names}…）"
    if kind == "bribe":
        cases = (getattr(game_state, "frameups", None) or {}).get("cases") or []
        if not cases:
            return False, "眼下并无在办案件，打点无处着力"
    game_state.silver -= price
    entry["stock"] = int(entry["stock"]) - 1
    if kind == "gift":
        rel = game_state.relationships.setdefault(target, {"好感": 0})
        rel["好感"] = max(-100, min(100, rel.get("好感", 0) + int(spec["favor"])))
        game_state.add_memory(f"以{spec['name']}赠{target}")
        return True, f" 你遣人将{spec['name']}送入{target}宫中，{target}回赠笑言，好感+{spec['favor']}（-{price}两）。"
    if kind == "attr":
        game_state.attributes[spec["attr"]] = _clamp_attr(game_state, spec["attr"], int(spec["gain"]))
        return True, f"{spec['icon']} 购得{spec['name']}，{spec['attr']}+{spec['gain']}（-{price}两）。"
    if kind == "instant":
        game_state.attributes[spec["attr"]] = _clamp_attr(game_state, spec["attr"], int(spec["gain"]))
        return True, f"{spec['icon']} 服下{spec['name']}，{spec['attr']}+{spec['gain']}（-{price}两）。"
    if kind == "herb":
        m = ensure_medical_state(game_state)
        herbs = m.setdefault("herbs", {})
        herbs[spec["herb"]] = int(herbs.get(spec["herb"], 0) or 0) + 1
        return True, f"{spec['icon']} {spec['name']}已入药匣（现有{herbs[spec['herb']]}份，-{price}两）。"
    if kind == "bribe":
        cases = (getattr(game_state, "frameups", None) or {}).get("cases") or []
        c = cases[0]
        c["嫌疑"] = max(0, int(c.get("嫌疑", 0)) - 20)
        game_state.add_memory(f"重金打点刑名，「{c.get('罪名', '案件')}」嫌疑-20")
        return True, f"🕴️ 你遣人打点刑房，「{c.get('罪名', '案件')}」嫌疑-20（-{price}两）。"
    return False, "未知货物"


def market_payload(game_state):
    """给前端的市集快照。"""
    mk = ensure_market_state(game_state)
    stock = []
    for s in mk.get("stock") or []:
        spec = next((c for c in MARKET_CATALOG if c["id"] == s.get("id")), None)
        if not spec:
            continue
        stock.append({"id": spec["id"], "name": spec["name"], "icon": spec["icon"], "price": spec["price"],
                      "desc": spec["desc"], "kind": spec.get("kind", ""), "stock": int(s.get("stock", 0) or 0)})
    return {"stock": stock, "refreshed": mk.get("refreshed", "")}


def medical_payload(game_state):
    m = ensure_medical_state(game_state)
    return {
        "physician": {"name": m["physician"].get("name", "太医"), "favor": int(m["physician"].get("favor", 20) or 0),
                      "skill": int(m["physician"].get("skill", 55) or 55)},
        "conditions": [{"name": c.get("name"), "months": int(c.get("months", 0) or 0),
                        "desc": (CONDITIONS.get(c.get("name")) or {}).get("desc", "")} for c in m.get("conditions") or []],
        "herbs": dict(m.get("herbs") or {}),
    }


def banquet_payload(game_state):
    b = ensure_banquet_state(game_state)
    return {"pending": b.get("pending"), "log": (b.get("log") or [])[-6:]}
