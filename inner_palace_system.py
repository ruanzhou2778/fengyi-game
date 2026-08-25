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

    # 重置本旬审计标记
    ip['audited_this_period'] = False

    # 日志裁剪
    logs = ip.get('logs', [])
    if isinstance(logs, list) and len(logs) > 50:
        ip['logs'] = logs[-50:]

    return msgs
