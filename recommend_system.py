# recommend_system.py — 妃嫔举荐秀女入宫系统
# 设计文档：RECOMMEND_SYSTEM.md（v1.0）
# 挂接：选秀（start_draft / process_draft / draft_panel_payload）、皇帝好感（relationships["皇帝"]）、
#       家族（player_clan / npc["clan"]）、协理（queen_authority）、NPC 关系网
import random

# ===== 常量 =====
RECOMMEND_PRIVATE_COST = 30       # 私荐打点银两（§二）
RECOMMEND_RETRY_COST = 50         # 失败后再次举荐银两（§8.3）
RECOMMEND_RETRY_PENALTY = 10      # 再次举荐成功率罚减
RECOMMEND_MEET_BONUS = 10         # 安排偶遇：下次举荐加成（§8.3）
RECOMMEND_DOWAGER_BONUS = 10      # 太后说情：本届后续举荐加成（§8.3）
RECOMMEND_COMPETITION_PENALTY = 15  # 竞争举荐罚减（§9.2）
RECOMMEND_COOLDOWN_PERIODS = 3    # 举荐冷却（旬，§8.2；同届重试不受限）
NPC_INTERCEPT_COST = 50           # 截留举荐信银两（§6.3）

# 位份加成与限次（§3.1；RANK_LEVELS: 贵人6 婕妤9 嫔10 妃11 贵妃12 皇贵妃13 皇后14）
RANK_BONUS_STEPS = [(14, 50), (13, 40), (12, 30), (11, 20), (9, 10)]
RANK_MAX_USES_STEPS = [(14, 3), (11, 2)]   # 其余（贵人~婕妤）1 次

# NPC 举荐概率 / 被采纳基础率（§6.1）
NPC_REC_CHANCE = {"嫔": 0.20, "妃": 0.35, "贵妃": 0.50, "皇贵妃": 0.60, "皇后": 0.70}
NPC_REC_BASE_RATE = {"嫔": 0.30, "妃": 0.40, "贵妃": 0.55, "皇贵妃": 0.65, "皇后": 0.75}

# 结果档位（§4.1）：掷骰定成败，成功率区间定恩宠程度与效果幅度
SUCCESS_TIERS = [
    (80, "圣心大悦", 5, 8, 30, ["常在", "贵人"]),
    (50, "欣然应允", 3, 5, 20, ["常在", "答应"]),
    (0, "勉强同意", 1, 2, 10, ["答应", "官女子"]),
]
FAIL_TIERS = [
    (10, "沉吟不语", -3, -5, -10),
    (0, "龙颜不悦", -8, -10, -20),
]

METHODS = {
    "private": {"name": "私下举荐", "icon": "🌙", "actions": 1, "silver": RECOMMEND_PRIVATE_COST, "bonus": 8,
                "min_rank": "贵人", "desc": "消耗1行动点与30两打点宫人传递消息"},
    "public": {"name": "当众进言", "icon": "🏛️", "actions": 1, "silver": 0, "bonus": 0,
               "min_rank": "嫔", "desc": "消耗1行动点，需位份≥嫔；成功则秀女得「贤名」"},
    "phoenix": {"name": "凤印圈定", "icon": "👑", "actions": 2, "silver": 0, "bonus": 25,
                "min_rank": "贵人", "desc": "消耗2行动点，需皇后亲裁或协理六宫权限；成功保底「常在」"},
}


def default_recommendations():
    return {
        "player_used": 0,             # 本届已举荐次数
        "player_max": 2,              # 本届最大举荐次数（由位份决定，开举时刷新）
        "edition": None,              # 本届选秀标识（draft.started_key）
        "cooldown_left": 0,           # 举荐冷却剩余旬数（§8.2）
        "npc_recommendations": [],    # NPC 的举荐请求（待处理，§6）
        "recommendation_history": [], # 历届举荐记录（§7.1）
        "dowager_plea_edition": None, # 太后说情本届一次
    }


def get_recommendations(game_state):
    rec = getattr(game_state, "recommendations", None)
    if not isinstance(rec, dict):
        rec = default_recommendations()
        game_state.recommendations = rec
    for k, v in default_recommendations().items():
        rec.setdefault(k, v)
    return rec


def _rank_index(rank_name):
    from app import RANK_LEVELS
    return RANK_LEVELS.get(rank_name, 0)


def _rank_bonus(rank_name):
    idx = _rank_index(rank_name)
    for step, b in RANK_BONUS_STEPS:
        if idx >= step:
            return b
    return 0


def rank_recommend_max(rank_name):
    idx = _rank_index(rank_name)
    for step, n in RANK_MAX_USES_STEPS:
        if idx >= step:
            return n
    return 1


def _emperor_favor(game_state):
    rel = (game_state.relationships or {}).get("皇帝") or {}
    try:
        return int(rel.get("好感", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _player_clan_surname(game_state):
    clan = getattr(game_state, "player_clan", None)
    return clan.get("surname") if isinstance(clan, dict) else None


def _rival_clan_surnames(game_state):
    surnames = set()
    for name in (getattr(game_state, "rivalries", None) or {}):
        npc = (game_state.npcs or {}).get(name)
        if isinstance(npc, dict) and isinstance(npc.get("clan"), dict):
            surnames.add(npc["clan"].get("surname"))
    surnames.discard(None)
    return surnames


def _cand_surname(cand):
    meta = cand.get("family_meta") or {}
    return meta.get("surname") or (cand.get("name") or "")[:1]


def eligibility_blockers(game_state, cand, allow_retry=False):
    """返回不可举荐的原因列表（空列表 = 可举荐）；cand 为 None 时只做全局校验。

    allow_retry：§8.3「再次举荐」明确允许对本届举荐未成的秀女重试（自带 -10% 罚），
    故重试时豁免「已举荐未成」与冷却拦截。
    """
    sync_edition(game_state)
    blockers = []
    d = getattr(game_state, "draft", None)
    if not isinstance(d, dict) or not d.get("active"):
        blockers.append("当前没有进行中的选秀")
        return blockers
    if cand is not None and not allow_retry:
        if cand.get("rec_failed") or cand.get("player_rejected"):
            blockers.append("此女已被你举荐过且未成，不宜再荐（可安排补救）")
        if cand.get("guaranteed_admit"):
            blockers.append("此女已获圣意留用")
    rank_name = game_state.rank.name
    if _rank_index(rank_name) < _rank_index("贵人"):
        blockers.append("位份不足：举荐需位份≥贵人")
    if _emperor_favor(game_state) < 40:
        blockers.append("皇帝好感不足40，不愿听你说话")
    if int(game_state.attributes.get("威望", 0) or 0) < 30:
        blockers.append("威望不足30，人微言轻")
    rec = get_recommendations(game_state)
    quota_max = rank_recommend_max(rank_name)
    if rec["player_used"] >= quota_max:
        blockers.append(f"本届举荐次数已用尽（{quota_max}次）")
    if rec["cooldown_left"] > 0 and not (cand is not None and cand.get("rec_failed")):
        blockers.append(f"举荐冷却中（还差{rec['cooldown_left']}旬）")
    return blockers


def compute_rate(game_state, cand, method_key, retry=False):
    """按 §4 公式计算成功率（%）。

    适配说明：设计中「皇帝心情≤30」无现成心情系统，以皇帝性格近似——昏君-10%、多疑-5%。
    """
    favor = _emperor_favor(game_state)
    rate = 40 + random.randint(-10, 10)
    rate += (favor - 40) * 0.5
    rate += _rank_bonus(game_state.rank.name)
    rate += int(game_state.attributes.get("宠爱", 0) or 0) * 0.1
    rate += int(game_state.attributes.get("威望", 0) or 0) * 0.05
    rate += METHODS[method_key]["bonus"]
    if _cand_surname(cand) == _player_clan_surname(game_state):
        rate += 10  # 举贤不避亲（§4）
    if _cand_surname(cand) in _rival_clan_surnames(game_state):
        rate -= 10  # 仇敌族女（§4）
    if cand.get("rec_failed"):
        rate -= 15  # 皇帝已见过她且印象差（§4）
    if cand.get("npc_rec_pending"):
        rate -= RECOMMEND_COMPETITION_PENALTY  # 竞争举荐（§9.2）
    if retry:
        rate -= RECOMMEND_RETRY_PENALTY
    rate += int(cand.get("impression_bonus", 0) or 0)  # 安排偶遇（§8.3）
    rec = get_recommendations(game_state)
    if rec.get("dowager_plea_edition") and rec.get("dowager_plea_edition") == rec.get("edition"):
        rate += RECOMMEND_DOWAGER_BONUS  # 太后说情（§8.3）
    emp = game_state.emperor or {}
    if emp.get("personality") == "昏君":
        rate -= 10
    elif emp.get("personality") == "多疑":
        rate -= 5
    return int(max(5, min(95, rate)))


def _apply_attr(game_state, attr, delta):
    old = int(game_state.attributes.get(attr, 0) or 0)
    game_state.attributes[attr] = int(max(0, min(game_state.get_attr_max(attr), old + delta)))


def _apply_emp_favor(game_state, delta):
    rel = game_state.relationships.setdefault("皇帝", {"好感": 10, "印象": "初识", "互动次数": 0})
    rel["好感"] = int(max(0, min(100, int(rel.get("好感", 0) or 0) + delta)))


def _npc_rel_change(npc, delta):
    rel = npc.setdefault("relationship", {"好感": 0, "印象": "陌生", "互动次数": 0})
    rel["好感"] = int(max(-100, min(100, int(rel.get("好感", 0) or 0) + delta)))


def _add_history(rec, **entry):
    entry["id"] = f"rec_{len(rec['recommendation_history']) + 1:03d}"
    rec["recommendation_history"].insert(0, entry)
    del rec["recommendation_history"][40:]


def _period_key(game_state):
    return f"{game_state.year}-{game_state.month}-{game_state.day}"


def player_recommend(game_state, cand_name, method_key, retry=False):
    """玩家举荐（§二/§四/§五）。返回 dict；校验失败返回 {"error": ...}。"""
    d = getattr(game_state, "draft", None)
    if not isinstance(d, dict) or not d.get("active"):
        return {"error": "当前没有进行中的选秀"}
    cand = next((c for c in d.get("candidates", []) if c.get("name") == cand_name), None)
    if cand is None:
        return {"error": "名册上查无此人"}
    blockers = eligibility_blockers(game_state, cand, allow_retry=retry)
    if blockers:
        return {"error": blockers[0]}
    method = METHODS.get(method_key)
    if not method:
        return {"error": "无效的举荐方式"}
    if _rank_index(game_state.rank.name) < _rank_index(method["min_rank"]):
        return {"error": f"{method['name']}需位份≥{method['min_rank']}"}
    if method_key == "phoenix":
        from app import queen_authority
        qa = queen_authority(game_state)
        if game_state.rank.name != "皇后" and not qa.get("can_assist_six_palaces"):
            return {"error": "凤印圈定需皇后亲裁或持有协理六宫权限"}
    if retry:
        if game_state.silver < RECOMMEND_RETRY_COST:
            return {"error": f"银两不足，再次举荐需{RECOMMEND_RETRY_COST}两"}
        game_state.silver -= RECOMMEND_RETRY_COST
    elif method["silver"]:
        if game_state.silver < method["silver"]:
            return {"error": f"银两不足，{method['name']}需{method['silver']}两"}
        game_state.silver -= method["silver"]

    from app import guard_action, check_and_consume_action
    ok, err = guard_action(game_state)
    if not ok:
        return err if isinstance(err, dict) else {"error": "行动点不足"}
    for _ in range(method["actions"] - 1):
        ok2, _left = check_and_consume_action(game_state)
        if not ok2:
            break

    rec = get_recommendations(game_state)
    rec["player_max"] = rank_recommend_max(game_state.rank.name)
    rate = compute_rate(game_state, cand, method_key, retry=retry)
    roll = random.randint(1, 100)
    success = roll <= rate
    if success:
        tier = next(t for t in SUCCESS_TIERS if rate >= t[0])
        _name, prestige_d, favor_d, cand_favor_d, pool = tier[1], tier[2], tier[3], tier[4], tier[5]
    else:
        tier = next(t for t in FAIL_TIERS if rate >= t[0])
        _name, prestige_d, favor_d, cand_favor_d = tier[1], tier[2], tier[3], tier[4]
        pool = None

    effects = {}
    _apply_attr(game_state, "威望", prestige_d)
    _apply_emp_favor(game_state, favor_d)
    effects["威望"] = prestige_d
    effects["皇帝好感"] = favor_d

    if success:
        cand["guaranteed_admit"] = True
        cand["guaranteed_pool"] = list(pool) if pool else ["答应"]
        if method_key == "phoenix" and "常在" not in cand["guaranteed_pool"]:
            cand["guaranteed_pool"] = ["常在"] + cand["guaranteed_pool"]  # 保底常在（§5.2）
        if method_key == "public":
            cand["virtue_tag"] = True  # 贤名（§5.2）
        cand["favor_offset"] = cand.get("favor_offset", 0) + cand_favor_d
        effects["秀女好感"] = cand_favor_d
        if _cand_surname(cand) == _player_clan_surname(game_state):
            clan = game_state.player_clan
            clan["家族威望"] = max(10, min(95, int(clan.get("家族威望", 40) or 0) + 5))
            effects["家族威望"] = 5
    else:
        cand["rec_failed"] = True
        cand["favor_offset"] = cand.get("favor_offset", 0) + cand_favor_d
        effects["秀女好感"] = cand_favor_d
        if tier[1] == "龙颜不悦":
            rivals = [c for c in (game_state.npcs or {}).values()
                      if isinstance(c, dict) and c.get("alive", True)
                      and _rank_index(c.get("rank", "")) >= _rank_index("妃")]
            if rivals and random.random() < 0.3:
                r = random.choice(rivals)
                _npc_rel_change(r, -5)
                effects[f"{r['name']}记恨"] = -5

    if cand.get("npc_rec_pending") and success:
        # 竞争举荐获胜：对手恼怒（§9.2）
        rival_npc = (game_state.npcs or {}).get(cand["npc_rec_pending"])
        if isinstance(rival_npc, dict):
            _npc_rel_change(rival_npc, -5)
            effects[f"{cand['npc_rec_pending']}恼怒"] = -5

    rec["player_used"] = int(rec["player_used"]) + 1
    rec["cooldown_left"] = RECOMMEND_COOLDOWN_PERIODS
    _add_history(rec, recommender="player", candidate=cand_name,
                 candidate_clan=_cand_surname(cand), method=method["name"],
                 result="成功" if success else "失败", tier=tier[1],
                 rate=rate, selected_rank=None, period=_period_key(game_state),
                 edition=rec.get("edition"), competition=bool(cand.get("npc_rec_pending")))
    cand["player_recommended"] = True
    game_state.add_memory(f"举荐{cand_name}（{method['name']}）：{tier[1]}")
    return {"success": success, "tier": tier[1], "rate": rate, "roll": roll,
            "method": method["name"], "effects": effects, "candidate": cand_name,
            "retry": retry}


# ===== NPC 举荐竞争（§6） =====
def attach_npc_recommendations(game_state, msgs):
    """开选时：位份≥嫔且名册上有同姓族女的 NPC 概率举荐（待处理，留一旬干扰窗口）。"""
    rec = get_recommendations(game_state)
    d = getattr(game_state, "draft", None)
    if not isinstance(d, dict) or not d.get("active"):
        return
    rec["npc_recommendations"] = []
    cands = d.get("candidates", [])
    for name, npc in (game_state.npcs or {}).items():
        if not isinstance(npc, dict) or not npc.get("alive", True) or name == game_state.name:
            continue
        chance = NPC_REC_CHANCE.get(npc.get("rank", ""))
        if not chance or random.random() >= chance:
            continue
        clan = npc.get("clan") or {}
        surname = clan.get("surname") or name[:1]
        own = [c for c in cands if _cand_surname(c) == surname
               and not c.get("npc_rec_pending") and not c.get("guaranteed_admit")]
        if not own:
            continue
        pick = max(own, key=lambda c: (c.get("family_meta") or {}).get("score", 50))
        pick["npc_rec_pending"] = name
        rec["npc_recommendations"].append({
            "npc": name, "candidate": pick["name"], "base_rate": NPC_REC_BASE_RATE.get(npc.get("rank", ""), 0.3),
            "rate_mod": 0, "period": _period_key(game_state),
        })
        msgs.append(f"🏷️ {name}属意其族女{pick['name']}，似有举荐之意。")
        if len(rec["npc_recommendations"]) >= 2:
            break


def resolve_npc_recommendations(game_state):
    """放榜前结算 NPC 举荐（§6.2）：成功者保送入宫并结盟。返回消息列表。"""
    rec = get_recommendations(game_state)
    msgs = []
    pendings = rec.get("npc_recommendations") or []
    rec["npc_recommendations"] = []
    d = getattr(game_state, "draft", None)
    for p in pendings:
        npc = (game_state.npcs or {}).get(p["npc"])
        cand = next((c for c in (d.get("candidates", []) if isinstance(d, dict) else [])
                     if c.get("name") == p["candidate"]), None)
        if not isinstance(npc, dict) or not npc.get("alive", True) or cand is None:
            continue
        rate = max(0.05, min(0.95, p["base_rate"] + p.get("rate_mod", 0) / 100.0))
        success = random.random() < rate
        if success:
            cand["guaranteed_admit"] = True
            cand["guaranteed_pool"] = ["答应", "常在"]
            cand["npc_endorsed"] = p["npc"]
            attrs = npc.setdefault("attributes", {})
            attrs["宠爱"] = min(100, int(attrs.get("宠爱", 30) or 0) + 3)
            if isinstance(npc.get("clan"), dict):
                npc["clan"]["家族威望"] = max(10, min(95, int(npc["clan"].get("家族威望", 40) or 0) + 5))
            _npc_rel_change(npc, -2)  # 此消彼长（§6.2）
            msgs.append(f"🏛️ {p['npc']}向皇帝举荐了其族女{p['candidate']}，皇帝颇为满意，已留用。")
            game_state.add_memory(f"{p['npc']}举荐族女{p['candidate']}成功")
        else:
            attrs = npc.setdefault("attributes", {})
            attrs["宠爱"] = max(0, int(attrs.get("宠爱", 30) or 0) - 1)
            msgs.append(f"🏛️ {p['npc']}为其族女{p['candidate']}进言，皇帝未置可否，此事作罢。")
            if p.get("rate_mod", 0) < 0:
                _npc_rel_change(npc, -15)
                msgs.append(f"⚠️ {p['npc']}疑心有人从中作梗，暗中记恨。")
        _add_history(rec, recommender=p["npc"], candidate=p["candidate"], method="族荐",
                     result="成功" if success else "失败", period=_period_key(game_state),
                     edition=rec.get("edition"))
    return msgs


def interfere_npc_rec(game_state, npc_name, way):
    """玩家干扰 NPC 举荐（§6.3）。way: whisper | intercept | warn。"""
    rec = get_recommendations(game_state)
    pending = next((p for p in rec.get("npc_recommendations", []) if p.get("npc") == npc_name), None)
    if not pending:
        return {"error": "该妃嫔当前没有待转呈的举荐"}
    if way == "whisper":
        pending["rate_mod"] = pending.get("rate_mod", 0) - 30
        game_state.add_memory(f"向皇帝进谗言，贬损{npc_name}所荐之人")
        return {"narration": f"你在御前不经意提了一句「{pending['candidate']}姿色平平、门第亦一般」，皇帝眉头微皱。"}
    if way == "intercept":
        if game_state.silver < NPC_INTERCEPT_COST:
            return {"error": f"银两不足，截留需{NPC_INTERCEPT_COST}两"}
        game_state.silver -= NPC_INTERCEPT_COST
        rec["npc_recommendations"] = [p for p in rec["npc_recommendations"] if p is not pending]
        d = getattr(game_state, "draft", None)
        if isinstance(d, dict):
            cand = next((c for c in d.get("candidates", []) if c.get("name") == pending["candidate"]), None)
            if cand:
                cand.pop("npc_rec_pending", None)
                cand["rec_delayed"] = True
        discovered = random.random() < 0.5
        msg = f"你截下了{npc_name}递往御前的举荐信，只推说名册有误、须下届再议。（-{NPC_INTERCEPT_COST}两）"
        if discovered:
            npc = (game_state.npcs or {}).get(npc_name)
            if isinstance(npc, dict):
                _npc_rel_change(npc, -25)
                msg += f"可惜纸包不住火，{npc_name}察觉了信使的蹊跷，对你生了嫌隙。（好感-25）"
        game_state.add_memory(f"截留{npc_name}的举荐信")
        _add_history(rec, recommender=npc_name, candidate=pending["candidate"], method="族荐",
                     result="延迟", period=_period_key(game_state), edition=rec.get("edition"))
        return {"narration": msg}
    if way == "warn":
        d = getattr(game_state, "draft", None)
        if isinstance(d, dict):
            d["candidates"] = [c for c in d.get("candidates", []) if c.get("name") != pending["candidate"]]
        rec["npc_recommendations"] = [p for p in rec["npc_recommendations"] if p is not pending]
        npc = (game_state.npcs or {}).get(npc_name)
        if isinstance(npc, dict):
            _npc_rel_change(npc, -20)
        game_state.add_memory(f"私下警告{pending['candidate']}，其退出选秀")
        _add_history(rec, recommender=npc_name, candidate=pending["candidate"], method="族荐",
                     result="劝退", period=_period_key(game_state), edition=rec.get("edition"))
        return {"narration": f"你托人给{pending['candidate']}递了句话。次日，她便称病退出采选，{npc_name}虽无凭据，心下已然生疑。（好感-20）"}
    return {"error": "无效的干扰方式"}


# ===== 补救措施（§8.3） =====
def remedy(game_state, kind, cand_name=None):
    if kind == "retry":
        return player_recommend(game_state, cand_name, "private", retry=True)
    if kind == "meet":
        d = getattr(game_state, "draft", None)
        cand = None
        if isinstance(d, dict) and cand_name:
            cand = next((c for c in d.get("candidates", []) if c.get("name") == cand_name), None)
        if cand is None:
            return {"error": "名册上查无此人"}
        from app import queen_authority
        qa = queen_authority(game_state)
        if game_state.rank.name != "皇后" and not qa.get("can_assist_six_palaces"):
            return {"error": "安排偶遇需协理六宫权限"}
        from app import guard_action
        ok, err = guard_action(game_state)
        if not ok:
            return err if isinstance(err, dict) else {"error": "行动点不足"}
        cand["impression_bonus"] = int(cand.get("impression_bonus", 0) or 0) + RECOMMEND_MEET_BONUS
        game_state.add_memory(f"安排{cand_name}与皇帝「偶遇」")
        return {"narration": f"你借协理之便，让{cand_name}「恰巧」在御花园遇见圣驾。皇帝多看了她两眼，下次举荐时更说得动话。（举荐成功率+{RECOMMEND_MEET_BONUS}%）"}
    if kind == "dowager":
        rec = get_recommendations(game_state)
        if rec.get("dowager_plea_edition") and rec.get("dowager_plea_edition") == rec.get("edition"):
            return {"error": "本届已请太后说情，不宜再扰"}
        taihou = (game_state.relationships or {}).get("太后") or {}
        if int(taihou.get("好感", 0) or 0) < 50:
            return {"error": "太后好感不足50，不便开口"}
        _apply_emp_favor(game_state, 5)
        rec["dowager_plea_edition"] = rec.get("edition")
        game_state.add_memory("请太后代为说情")
        return {"narration": f"你陪太后用了盏茶，提起选秀之事。太后笑道：「你们小夫妻的事，哀家自会提点。」皇帝好感+5，本届后续举荐成功率+{RECOMMEND_DOWAGER_BONUS}%。"}
    return {"error": "无效的补救方式"}


def tick_recommendations(game_state):
    """转旬：冷却递减。"""
    rec = get_recommendations(game_state)
    if rec["cooldown_left"] > 0:
        rec["cooldown_left"] -= 1


def sync_edition(game_state):
    """届次切换时重置本届计数。"""
    d = getattr(game_state, "draft", None)
    rec = get_recommendations(game_state)
    edition = d.get("started_key") if isinstance(d, dict) and d.get("active") else None
    if rec.get("edition") != edition:
        rec["edition"] = edition
        rec["player_used"] = 0
        rec["dowager_plea_edition"] = None


def recommend_payload(game_state):
    """draft_panel 的举荐面板数据。"""
    sync_edition(game_state)
    rec = get_recommendations(game_state)
    taihou = (game_state.relationships or {}).get("太后") or {}
    return {
        "used": int(rec["player_used"]),
        "max": rank_recommend_max(game_state.rank.name),
        "cooldown_left": int(rec["cooldown_left"]),
        "global_blockers": eligibility_blockers(game_state, None),
        "dowager_plea_available": (rec.get("dowager_plea_edition") != rec.get("edition")
                                   and int(taihou.get("好感", 0) or 0) >= 50),
        "npc_pending": [{"npc": p["npc"], "candidate": p["candidate"]}
                        for p in rec.get("npc_recommendations", [])],
        "history": list(rec.get("recommendation_history", []))[:8],
    }
