# inner_palace_system.py
import random
from datetime import datetime as _dt

def _ip_log(ip, text):
    logs = ip.setdefault('logs', [])
    if not isinstance(logs, list):
        ip['logs'] = []
        logs = ip['logs']
    ts = _dt.now().strftime('%m-%d %H:%M')
    logs.append(f'[{ts}] {text}')
    if len(logs) > 50:
        ip['logs'] = logs[-50:]


def inner_palace_period_tick(game_state, normalize_inner_palace, RANK_POWER, chonghua_count_inside=None, CHONGHUA_UPKEEP_PER_CHILD=10):
    from models import normalize_rank_name
    ip = getattr(game_state, 'inner_palace', None)
    if not isinstance(ip, dict):
        game_state.inner_palace = normalize_inner_palace(None)
        ip = game_state.inner_palace
    msgs = []
    stipend_table = ip.get('monthly_stipend', {})
    budget = int(ip.get('budget', 0) or 0)
    quarter_start_budget = budget  # 考绩用：本季度开局库银
    # ---- 生效中的克扣 / 赏赐（Phase 1 权谋操作）----
    cuts_raw = ip.get('stipend_cuts') or {}
    gifts_raw = ip.get('bonus_gifts') or {}
    if not isinstance(cuts_raw, dict):
        cuts_raw = {}
    if not isinstance(gifts_raw, dict):
        gifts_raw = {}
    cut_amt = {}
    for tgt, v in cuts_raw.items():
        if not isinstance(v, dict):
            continue
        npc = (game_state.npcs or {}).get(tgt)
        if not isinstance(npc, dict) or not npc.get('alive', True):
            continue
        pct = max(0, min(50, int(v.get('amount', 0) or 0)))
        if pct > 0:
            cut_amt[str(tgt)] = pct
    gift_amt = {}
    for tgt, v in gifts_raw.items():
        if not isinstance(v, dict):
            continue
        npc = (game_state.npcs or {}).get(tgt)
        if not isinstance(npc, dict) or not npc.get('alive', True):
            continue
        amt = max(0, min(100, int(v.get('amount', 0) or 0)))
        if amt > 0:
            gift_amt[str(tgt)] = amt
    total_due = 0
    payouts = []
    player_rank = normalize_rank_name(getattr(game_state.rank, 'name', '秀女'))
    player_amt = int(stipend_table.get(player_rank, 0))
    if player_amt > 0:
        payouts.append(('__player__', player_amt, player_rank, True))
        total_due += player_amt
    for npc_name, npc in (game_state.npcs or {}).items():
        if not npc.get('alive', True): continue
        r = normalize_rank_name(npc.get('rank', ''))
        if r == '太后': continue
        amt = int(stipend_table.get(r, 0))
        if npc_name in cut_amt:
            amt = max(0, amt - int(stipend_table.get(r, 0)) * cut_amt[npc_name] // 100)
        if npc_name in gift_amt:
            amt += gift_amt[npc_name]
        if amt > 0:
            payouts.append((npc_name, amt, r, False))
            total_due += amt
    deficit = False
    if total_due > budget:
        deficit = True
        payouts_sorted = sorted(payouts, key=lambda x: RANK_POWER.get(x[2], 0))
        remaining = budget
        final_payouts = {}
        for target, amt, rank, is_p in payouts_sorted:
            if remaining <= 0: final_payouts[target] = 0
            else:
                pay = min(amt, remaining)
                final_payouts[target] = pay
                remaining -= pay
        actual_total = sum(final_payouts.values())
        for target, amt, rank, is_p in payouts:
            pay = final_payouts.get(target, 0)
            if is_p: game_state.silver = int(getattr(game_state, 'silver', 0) or 0) + pay
            else:
                npc = game_state.npcs.get(target)
                if isinstance(npc, dict): npc['silver'] = int(npc.get('silver', 0) or 0) + pay
        ip['budget'] = 0
        msgs.append('⚠️ 内务府亏空，宫中怨声载道')
        game_state.attributes['威望'] = max(0, int(game_state.attributes.get('威望', 0) or 0) - 3)
        _ip_log(ip, f'月例亏空{total_due - actual_total}两，威望-3')
    else:
        for target, amt, rank, is_p in payouts:
            if is_p: game_state.silver = int(getattr(game_state, 'silver', 0) or 0) + amt
            else:
                npc = game_state.npcs.get(target)
                if isinstance(npc, dict): npc['silver'] = int(npc.get('silver', 0) or 0) + amt
        ip['budget'] = budget - total_due
        _ip_log(ip, f'月例发放{total_due}两')


    # ---------- 2. 库存消耗 ----------
    storehouse = ip.setdefault('storehouse', {'布匹': 0, '药材': 0, '香料': 0, '木材': 0, '食材': 0})
    consume = {
        '食材': random.randint(1, 3),
        '木材': random.randint(0, 2),
        '布匹': random.randint(0, 1),
    }
    for k, v in consume.items():
        cur = int(storehouse.get(k, 0) or 0)
        new_val = max(0, cur - v)
        storehouse[k] = new_val
        if new_val == 0 and cur > 0:
            msgs.append(f'📦 {k}短缺，宫人私下抱怨')
            _ip_log(ip, f'{k}库存归零')
            alive_npcs = [n for n, d in (game_state.npcs or {}).items() if d.get('alive', True)]
            if alive_npcs:
                victim = random.choice(alive_npcs)
                npc = game_state.npcs[victim]
                loss = random.randint(1, 3)
                npc['health'] = max(0, int(npc.get('health', 80) or 80) - loss)
                msgs.append(f'💔 {victim}因{k}短缺身体不适，健康-{loss}')

    # ---------- 3. 物价波动 ----------
    market = ip.setdefault('market', {'布匹': 5, '药材': 10, '香料': 15, '木材': 8, '食材': 3})
    for k in list(market.keys()):
        delta = random.randint(-2, 3)
        market[k] = max(2, int(market.get(k, 5) or 5) + delta)


    # ---------- 4. 总管 AI 行为 ----------
    chief = ip.setdefault('chief', {'name': '苏培盛', 'loyalty': 60, 'corruption': 25, 'skill': 70})
    corruption = int(chief.get('corruption', 0) or 0)
    loyalty = int(chief.get('loyalty', 0) or 0)
    skill = int(chief.get('skill', 0) or 0)
    evidence = int(ip.get('corruption_evidence', 0) or 0)
    if corruption > 60 and loyalty < 50 and random.random() < 0.35:
        stolen = random.randint(5, 20)
        ip['budget'] = max(0, int(ip.get('budget', 0) or 0) - stolen)
        ev_add = random.randint(1, 3)
        ip['corruption_evidence'] = evidence + ev_add
        msgs.append(f'🐀 内务府总管暗中漂没库银{stolen}两')
        _ip_log(ip, f'总管漂没{stolen}两，罪证+{ev_add}')
    if loyalty > 70 and random.random() < 0.20:
        reduce = random.randint(1, 3)
        chief['corruption'] = max(0, corruption - reduce)
        _ip_log(ip, f'总管自省，贪腐-{reduce}')
    if skill > 70:
        saving = random.randint(1, 3)
        ip['budget'] = int(ip.get('budget', 0) or 0) + saving
        _ip_log(ip, f'总管精打细算，节省{saving}两')
    audited = bool(ip.get('audited_this_period', False))
    if evidence > 30 and not audited and random.random() < 0.25:
        accusers = [n for n, d in (game_state.npcs or {}).items() if d.get('alive', True)]
        if accusers:
            accuser = random.choice(accusers)
            msgs.append(f'📢 {accuser}向皇帝揭发内务府贪腐！')
            _ip_log(ip, f'{accuser}告发内务府贪腐')
            if int(game_state.attributes.get('威望', 0) or 0) < 60:
                game_state.attributes['威望'] = max(0, int(game_state.attributes.get('威望', 0) or 0) - 5)
                msgs.append('😰 你威望不足，此事令你声望受损，威望-5')


    # ---------- 5. NPC 讨要份例 ----------
    beg_candidates = [n for n, d in (game_state.npcs or {}).items()
                      if d.get('alive', True) and normalize_rank_name(d.get('rank', '')) != '太后']
    if beg_candidates:
        beggar = random.choice(beg_candidates)
        beg_npc = game_state.npcs[beggar]
        cur_budget = int(ip.get('budget', 0) or 0)
        if cur_budget > 50:
            cost = random.randint(10, 20)
            ip['budget'] = cur_budget - cost
            favor_gain = random.randint(3, 6)
            beg_npc['favor'] = min(100, int(beg_npc.get('favor', 50) or 50) + favor_gain)
            msgs.append(f'🎁 {beggar}向内务府讨要额外份例，已拨给{cost}两，好感+{favor_gain}')
            _ip_log(ip, f'{beggar}讨要份例{cost}两，好感+{favor_gain}')
        else:
            favor_loss = random.randint(3, 8)
            beg_npc['favor'] = max(0, int(beg_npc.get('favor', 50) or 50) - favor_loss)
            msgs.append(f'😤 {beggar}向内务府讨要份例被拒，好感-{favor_loss}')
            _ip_log(ip, f'{beggar}讨要被拒，好感-{favor_loss}')
            if random.random() < 0.20:
                game_state.attributes['威望'] = max(0, int(game_state.attributes.get('威望', 0) or 0) - 3)
                msgs.append(f'👑 {beggar}向皇帝/太后告状，你威望-3')
                _ip_log(ip, f'{beggar}告状，威望-3')


    # ---------- 6. 重华宫用度联动 ----------
    ch = getattr(game_state, 'chonghua', {})
    if isinstance(ch, dict) and ch.get('founded'):
        inside_count = 0
        try:
            if callable(chonghua_count_inside):
                inside_count = chonghua_count_inside(game_state)
            else:
                inside_count = len([c for c in ch.get('children', []) if isinstance(c, dict)])
        except Exception:
            inside_count = len([c for c in ch.get('children', []) if isinstance(c, dict)])
        upkeep_per = CHONGHUA_UPKEEP_PER_CHILD
        due_ch = inside_count * upkeep_per
        if due_ch > 0:
            cur_b = int(ip.get('budget', 0) or 0)
            if cur_b >= due_ch:
                ip['budget'] = cur_b - due_ch
                ch['arrears'] = 0
                _ip_log(ip, f'划拨重华宫用度{due_ch}两')
            else:
                short = due_ch - cur_b
                ip['budget'] = 0
                ch['arrears'] = int(ch.get('arrears', 0) or 0) + 1
                msgs.append(f'💸 内务府无力全额拨付重华宫用度，欠饷{short}两')
                _ip_log(ip, f'重华宫用度不足，欠饷{short}两')

    # ---------- 7. 克扣份例：到期递减 + 总管揭发 + 副作用 ----------
    cuts = ip.get('stipend_cuts')
    if not isinstance(cuts, dict) or not cuts:
        cuts = None
    if cuts:
        # 是否由主控掌管内务府：克扣副作用（好感/威望）仅累及掌管者，不牵连非掌管的主控
        player_manages = (getattr(getattr(game_state, 'rank', None), 'name', '') == '皇后') \
            or (getattr(game_state, 'six_palace_assistant', None) == getattr(game_state, 'name', None))
        chief = ip.get('chief') or {}
        exposure = max(0.05, min(0.65,
                    (1 - int(chief.get('loyalty', 50) or 50) / 200.0)
                    + int(chief.get('corruption', 0) or 0) / 250.0))
        expired = []
        for tgt, v in list(cuts.items()):
            if not isinstance(v, dict):
                expired.append(tgt)
                continue
            left = int(v.get('periods', 0) or 0) - 1
            if left <= 0:
                expired.append(tgt)
                continue
            npc = (game_state.npcs or {}).get(tgt)
            if not isinstance(npc, dict) or not npc.get('alive', True):
                expired.append(tgt)
                continue
            v['periods'] = left
            pct = int(v.get('amount', 0) or 0)
            npc['health'] = max(0, int(npc.get('health', 50) or 50) - 1)
            if player_manages:
                rel = (game_state.relationships or {}).get(tgt)
                if isinstance(rel, dict):
                    rel['好感'] = max(-100, int(rel.get('好感', 0) or 0) - 3)
            if random.random() < exposure:
                ev = random.randint(5, 10)
                ip['corruption_evidence'] = int(ip.get('corruption_evidence', 0) or 0) + ev
                if player_manages:
                    game_state.attributes['威望'] = max(0, int(game_state.attributes.get('威望', 0) or 0) - 5)
                    _ip_log(ip, f'{chief.get("name", "总管")}揭发你克扣{tgt}份例，罪证+{ev}')
                    msgs.append(f'💥 克扣{tgt}份例被揭发！你威望-5，罪证+{ev}')
                else:
                    _ip_log(ip, f'{chief.get("name", "总管")}克扣{tgt}份例被揭发，罪证+{ev}')
                    msgs.append(f'💥 内务府克扣{tgt}份例被揭发！罪证+{ev}')
                expired.append(tgt)
        for t in expired:
            cuts.pop(t, None)
    # ---------- 8. 额外赏赐：到期递减 + 期满恩义递减 ----------
    gifts = ip.get('bonus_gifts')
    if not isinstance(gifts, dict) or not gifts:
        gifts = None
    if gifts:
        expired = []
        for tgt, v in list(gifts.items()):
            if not isinstance(v, dict):
                expired.append(tgt)
                continue
            left = int(v.get('periods', 0) or 0) - 1
            npc = (game_state.npcs or {}).get(tgt)
            if not isinstance(npc, dict) or not npc.get('alive', True):
                expired.append(tgt)
                continue
            if left <= 0:
                expired.append(tgt)
                rel = (game_state.relationships or {}).get(tgt)
                if isinstance(rel, dict):
                    rel['好感'] = max(-100, int(rel.get('好感', 0) or 0) - 2)
                _ip_log(ip, f'对{tgt}的额外赏赐期满，恩义渐散（好感-2）')
            else:
                v['periods'] = left
        for t in expired:
            gifts.pop(t, None)
    # ---------- 9. 产业收益与状态流转（Phase 5）----------
    projects = ip.get('projects')
    if not isinstance(projects, dict):
        ip['projects'] = {}
        projects = ip['projects']
    chief = ip.get('chief') or {}
    for pname, p in list(projects.items()):
        if not isinstance(p, dict) or int(p.get('level', 0) or 0) <= 0:
            continue
        base_inc = int(p.get('income_per_period', 0) or 0)
        status = p.get('status', '正常')
        if status in ('丰收', '灾荒', '贪墨'):
            left = int(p.get('status_periods', 0) or 0) - 1
            if left <= 0:
                p['status'] = '正常'
                p['status_periods'] = 0
                status = '正常'
            else:
                p['status_periods'] = left
        inc = base_inc
        if status == '丰收':
            inc = base_inc * 2
        elif status == '灾荒':
            inc = max(0, base_inc // 2)
        elif status == '贪墨':
            inc = 0
        if inc > 0:
            ip['budget'] = int(ip.get('budget', 0) or 0) + inc
            _ip_log(ip, f'{pname}{status if status != "正常" else ""}进账{inc}两')
        roll = random.random()
        if status == '正常':
            if roll < 0.05:
                p['status'] = '丰收'
                p['status_periods'] = random.randint(3, 6)
                msgs.append(f'🌾 {pname}风调雨顺，进入丰年（收益翻倍数旬）')
                _ip_log(ip, f'{pname}丰收')
            elif roll < 0.10:
                p['status'] = '灾荒'
                p['status_periods'] = random.randint(2, 4)
                msgs.append(f'🌪 {pname}遭遇灾荒，收益减半数旬')
                _ip_log(ip, f'{pname}灾荒')
            elif roll < 0.12 and int(chief.get('corruption', 0) or 0) > 50:
                p['status'] = '贪墨'
                p['status_periods'] = random.randint(2, 4)
                ip['corruption_evidence'] = int(ip.get('corruption_evidence', 0) or 0) + 5
                msgs.append(f'🐀 总管在{pname}账目上做手脚，收益被截，罪证+5')
                _ip_log(ip, f'{pname}被贪墨')
    # ---------- 10. 季度考绩（每30旬，Phase 4）----------
    day = int(getattr(game_state, 'day', 0) or 0)
    reviews = ip.get('performance_reviews')
    if not isinstance(reviews, dict):
        ip['performance_reviews'] = {'last_review': 0, 'score': 0, 'grade': '',
                                     'next_review': 30, 'history': []}
        reviews = ip['performance_reviews']
    if day >= int(reviews.get('next_review', 30) or 30) and day > 0:
        end_b = int(ip.get('budget', 0) or 0)
        budget_score = max(0, min(40, 40 - max(0, quarter_start_budget - end_b) // 10))
        low_store = sum(1 for k, v in (ip.get('storehouse') or {}).items() if int(v or 0) < 5)
        store_score = max(0, min(30, 30 - low_store * 10))
        favs = [int(v.get('favor', 50) or 50) for v in (game_state.npcs or {}).values()
                if isinstance(v, dict) and v.get('alive', True)]
        avg_fav = sum(favs) / len(favs) if favs else 50.0
        favor_score = max(0, min(30, int(avg_fav)))
        score = budget_score + store_score + favor_score
        if score >= 80:
            grade, pre, fav = '优', 5, 3
        elif score >= 60:
            grade, pre, fav = '平', 0, 0
        else:
            grade, pre, fav = '劣', -5, -3
        try:
            pmax = game_state.get_attr_max('威望')
        except Exception:
            pmax = 999
        if pre:
            game_state.attributes['威望'] = max(0, min(pmax,
                                                       int(game_state.attributes.get('威望', 0) or 0) + pre))
        em = (game_state.relationships or {}).get('皇帝')
        if isinstance(em, dict) and fav:
            em['好感'] = max(-100, min(100, int(em.get('好感', 0) or 0) + fav))
        chief = ip.get('chief') or {}
        chief['performance'] = max(-100, min(100, int(chief.get('performance', 0) or 0) + (10 if pre > 0 else -5)))
        record = {'period': day, 'score': score, 'grade': grade, 'budget_end': end_b}
        reviews['last_review'] = day
        reviews['score'] = score
        reviews['grade'] = grade
        reviews['next_review'] = day + 30
        hist = reviews.get('history')
        if not isinstance(hist, list):
            hist = []
        hist.append(record)
        reviews['history'] = hist[-12:]
        _ip_log(ip, f'季度考绩：{grade}（{score}分），威望{pre:+d}')
        msgs.append(f'📋 内务府季度考绩：{grade}（{score}分）' +
                    (f'，威望{pre:+d}' if pre else ''))
    # ---------- 11. 总管派系行为（Phase 2）----------
    chief = ip.get('chief') or {}
    faction = chief.get('faction', '中立')
    tenure = int(chief.get('tenure', 0) or 0) + 1
    chief['tenure'] = tenure
    if faction == '皇后派' and random.random() < 0.30:
        ev = int(ip.get('corruption_evidence', 0) or 0)
        if ev > 0:
            ip['corruption_evidence'] = ev + random.randint(3, 6)
            msgs.append('📢 皇后派总管向皇后密奏，内务府账目问题被传了出去！')
            _ip_log(ip, '皇后派总管告密，罪证扩散')
    elif faction == '太后派' and random.random() < 0.25:
        dw = (game_state.npcs or {}).get('太后')
        if isinstance(dw, dict):
            dw['favor'] = min(100, int(dw.get('favor', 50) or 50) + random.randint(1, 3))
            msgs.append('🙏 太后派总管替你美言，太后对你略有好感')
            _ip_log(ip, '太后派总管美言，太后好感+')
    elif faction == '皇帝派' and random.random() < 0.15:
        taken = random.randint(10, 30)
        cur = int(ip.get('budget', 0) or 0)
        if cur >= taken:
            ip['budget'] = cur - taken
            msgs.append(f'👑 皇帝调拨内务府库银{taken}两充作军费')
            _ip_log(ip, f'皇帝调库银{taken}两')
    if tenure >= 30:
        if faction in ('皇后派', '皇帝派'):
            chief['corruption'] = max(0, min(100, int(chief.get('corruption', 0) or 0) + 1))
        elif faction == '太后派':
            chief['loyalty'] = min(100, int(chief.get('loyalty', 0) or 0) + 1)
    # 重置本旬审计标记
    ip['audited_this_period'] = False

    # 日志裁剪
    logs = ip.get('logs', [])
    if isinstance(logs, list) and len(logs) > 50:
        ip['logs'] = logs[-50:]

    return msgs
