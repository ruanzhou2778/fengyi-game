"""重华宫系统验证：权限分级、容量、转旬结算、亲养规矩、授业限次、持久化。

运行：python verify_chonghua_system.py
"""
import json
import random
import sys
from pathlib import Path

import app as m
from models import Rank

cid = 'chonghua-verify'
rep = []


def ck(name, cond, detail=''):
    rep.append({'item': name, 'ok': bool(cond), 'detail': str(detail)[:200]})


def post(c, p, o):
    return c.post(p, data=json.dumps(o, ensure_ascii=False),
                  headers={'Content-Type': 'application/json', 'X-Client-ID': cid})


def get(c, p):
    return c.get(p, headers={'X-Client-ID': cid})


def new_child(gs, name, gender='皇子', age=1, mother=''):
    child = m.create_newborn_child(gender, name, gs, mother_name=mother or gs.name)
    child['age'] = age
    m.ensure_child_fields(child)
    m.ensure_child_uid(gs, child)
    return child


def fetch(c, pid):
    r = get(c, f'/api/chonghua?player_id={pid}')
    return r.status_code, (r.get_json() or {})


def act(c, pid, action, **kw):
    body = {'player_id': pid, 'action': action}
    body.update(kw)
    r = post(c, '/api/chonghua/action', body)
    return r.status_code, (r.get_json() or {})


random.seed(20260101)
with m.app.test_client() as client:
    r = post(client, '/api/start', {
        'scenario': '才女入宫', 'name': '重华验证', 'storyline': '权谋线',
        'attributes': {'心计': 18, '威望': 18},
        'character': {'appearance': '清丽', 'talent': '善谋', 'personality': '沉静', 'traits': []},
    })
    d = r.get_json() or {}
    pid = d.get('player_id')
    gs = m.sessions.get(pid)
    ck('会话建立', gs is not None, pid)

    # ---------- 1. 权限分级 ----------
    gs.rank = Rank.嫔
    gs.six_palace_assistant = None
    ck('嫔仅见本宫（own）', m.chonghua_permission(gs) == 'own', m.chonghua_permission(gs))

    gs.rank = Rank.贵妃
    ck('贵妃可阅名册（view）', m.chonghua_permission(gs) == 'view', m.chonghua_permission(gs))
    ck('贵妃不可处置他人', not m.chonghua_can_manage_all(gs), True)
    ck('贵妃可查阅全宫', m.chonghua_can_see_all(gs), True)

    gs.rank = Rank.皇贵妃
    ck('皇贵妃仍为 view', m.chonghua_permission(gs) == 'view', m.chonghua_permission(gs))

    gs.rank = Rank.贵妃
    gs.six_palace_assistant = gs.name
    ck('协理六宫升为 full', m.chonghua_permission(gs) == 'full', m.chonghua_permission(gs))
    gs.six_palace_assistant = None
    gs.rank = Rank.皇后
    ck('皇后为 full', m.chonghua_permission(gs) == 'full', m.chonghua_permission(gs))

    # ---------- 2. 开设门槛 ----------
    gs.chonghua['founded'] = False  # 新档默认已开设，此处重置以测试开设流程
    gs.attributes['威望'] = 10
    gs.silver = 1000
    code, res = act(client, pid, 'found')
    ck('威望不足不得开设', code == 400 and not res.get('success'), res.get('error'))

    gs.attributes['威望'] = 200
    gs.silver = 50
    code, res = act(client, pid, 'found')
    ck('银两不足不得开设', code == 400, res.get('error'))

    gs.silver = 1000
    code, res = act(client, pid, 'found')
    ck('皇后开设成功', code == 200 and res.get('success'), res.get('message'))
    ck('开设扣银两', gs.silver == 1000 - m.CHONGHUA_FOUND_COST, gs.silver)
    code, res = act(client, pid, 'found')
    ck('重复开设被拒', code == 400, res.get('error'))

    # 低位份不得开设
    gs.chonghua['founded'] = False
    gs.rank = Rank.嫔
    code, res = act(client, pid, 'found')
    ck('嫔不得开设', code == 403, res.get('error'))
    gs.rank = Rank.皇后
    gs.chonghua['founded'] = True

    # ---------- 3. 名册与权限视图 ----------
    npc_name = next(n for n, v in gs.npcs.items() if n != '太后' and v.get('alive', True))
    gs.npcs[npc_name]['children'] = [new_child(gs, '萧宁远', '皇子', 5, npc_name)]
    gs.children = [new_child(gs, '萧承烨', '皇子', 6, gs.name)]
    gs.has_children = True

    code, data = fetch(client, pid)
    ck('皇后可见他人皇嗣', code == 200 and any(c['_owner_type'] == 'npc' for c in data['candidates']),
       [c['name'] for c in data['candidates']])
    ck('皇后对他人皇嗣 can_act',
       all(c['can_act'] for c in data['candidates']), data['candidates'])

    gs.rank = Rank.贵妃
    code, data = fetch(client, pid)
    npc_entries = [c for c in data['candidates'] if c['_owner_type'] == 'npc']
    ck('贵妃可见他人皇嗣', bool(npc_entries), npc_entries)
    ck('贵妃对他人皇嗣不可操作', all(not c['can_act'] for c in npc_entries), npc_entries)
    ck('贵妃对自己皇嗣可操作',
       all(c['can_act'] for c in data['candidates'] if c['_owner_type'] == 'player'), data['candidates'])

    gs.rank = Rank.嫔
    code, data = fetch(client, pid)
    ck('嫔看不到他人皇嗣',
       all(c['_owner_type'] == 'player' for c in data['candidates'] + data['children']),
       data['candidates'])

    # 贵妃越权处置他人皇嗣
    gs.rank = Rank.贵妃
    npc_child_uid = gs.npcs[npc_name]['children'][0]['uid']
    code, res = act(client, pid, 'admit', uid=npc_child_uid)
    ck('贵妃越权收容被拒 403', code == 403, res.get('error'))
    code, res = act(client, pid, 'adopt', uid=npc_child_uid)
    ck('贵妃越权亲养被拒 403', code == 403, res.get('error'))

    # 嫔连查询都看不到 → 404
    gs.rank = Rank.嫔
    code, res = act(client, pid, 'admit', uid=npc_child_uid)
    ck('嫔处置他人皇嗣 404', code == 404, res.get('error'))
    gs.rank = Rank.皇后

    # ---------- 4. GET 无副作用 ----------
    before = json.dumps(gs.chonghua, ensure_ascii=False, sort_keys=True)
    inside_before = m.chonghua_count_inside(gs)
    for _ in range(3):
        fetch(client, pid)
    ck('GET 不改动状态',
       json.dumps(gs.chonghua, ensure_ascii=False, sort_keys=True) == before
       and m.chonghua_count_inside(gs) == inside_before, before)

    # ---------- 5. 收容与容量 ----------
    code, res = act(client, pid, 'admit', uid=gs.children[0]['uid'])
    ck('收容自家皇嗣', code == 200 and res.get('success'), res.get('message'))
    ck('入馆写入名册', gs.children[0]['uid'] in gs.chonghua['children'], gs.chonghua['children'])
    ck('入馆置 palace', gs.children[0]['palace'] == m.CHONGHUA_PALACE_NAME, gs.children[0]['palace'])
    code, res = act(client, pid, 'admit', uid=gs.children[0]['uid'])
    ck('重复收容被拒', code == 400, res.get('error'))

    # 年长者不得入馆
    old_child = new_child(gs, '萧景年', '皇子', m.CHONGHUA_GRADUATE_AGE + 1, gs.name)
    gs.children.append(old_child)
    code, res = act(client, pid, 'admit', uid=old_child['uid'])
    ck('年长者不得入馆', code == 400, res.get('error'))
    gs.children.remove(old_child)

    # 容量上限（1 级 = 3 人），全局统计
    gs.chonghua['level'] = 1
    fillers = []
    for i in range(4):
        ch = new_child(gs, f'萧填{i}', '公主', 2, npc_name)
        gs.npcs[npc_name]['children'].append(ch)
        fillers.append(ch)
    admitted = 0
    for ch in fillers:
        code, res = act(client, pid, 'admit', uid=ch['uid'])
        if code == 200:
            admitted += 1
    ck('容量上限生效（3人）', m.chonghua_count_inside(gs) == m.chonghua_capacity(gs.chonghua),
       f'inside={m.chonghua_count_inside(gs)} cap={m.chonghua_capacity(gs.chonghua)}')
    ck('超额收容被拒', admitted < len(fillers), f'admitted={admitted}')

    # 名册不因低权限查询而被截断
    gs.rank = Rank.嫔
    fetch(client, pid)
    ck('低权限查询不截断名册',
       len(gs.chonghua['children']) == m.chonghua_count_inside(gs), gs.chonghua['children'])
    gs.rank = Rank.皇后

    # ---------- 6. 扩建 ----------
    gs.silver = 5000
    code, res = act(client, pid, 'upgrade')
    ck('扩建成功', code == 200 and gs.chonghua['level'] == 2, gs.chonghua['level'])
    ck('扩建后容量提升', m.chonghua_capacity(gs.chonghua) == 2 * m.CHONGHUA_PER_LEVEL_CAPACITY,
       m.chonghua_capacity(gs.chonghua))
    gs.chonghua['level'] = m.CHONGHUA_MAX_LEVEL
    code, res = act(client, pid, 'upgrade')
    ck('满级不得再扩建', code == 400, res.get('error'))

    # ---------- 7. 拨用度 ----------
    gs.silver = 1000
    gs.chonghua['budget'] = 0
    gs.chonghua['arrears'] = 2
    code, res = act(client, pid, 'patronize', amount=300)
    ck('拨用度成功', code == 200 and gs.chonghua['budget'] == 300, gs.chonghua['budget'])
    ck('拨用度清欠饷', gs.chonghua['arrears'] == 0, gs.chonghua['arrears'])
    code, res = act(client, pid, 'patronize', amount=-5)
    ck('负金额被拒', code == 400, res.get('error'))
    code, res = act(client, pid, 'patronize', amount=999999)
    ck('超额拨款被拒', code == 400, res.get('error'))

    # ---------- 8. 授业 ----------
    target = gs.children[0]
    target['age'] = 6
    gs.silver = 1000
    gs.chonghua['budget'] = 500
    lvl0, talent0 = target['tutor_level'], target['talent']
    code, res = act(client, pid, 'tutor', uid=target['uid'])
    ck('授业成功', code == 200 and target['tutor_level'] == lvl0 + 1, target['tutor_level'])
    ck('授业提升才情', target['talent'] >= talent0, f'{talent0}->{target["talent"]}')
    ck('授业优先动用用度', gs.chonghua['budget'] < 500, gs.chonghua['budget'])
    code, res = act(client, pid, 'tutor', uid=target['uid'])
    ck('同旬二次授业被拒', code == 400 and '本旬' in (res.get('error') or ''), res.get('error'))

    baby = new_child(gs, '萧稚儿', '公主', 1, gs.name)
    gs.children.append(baby)
    act(client, pid, 'release', uid=baby['uid'])
    m.chonghua_admit_child(gs, gs.chonghua, baby)
    code, res = act(client, pid, 'tutor', uid=baby['uid'])
    ck('年幼不得授业', code == 400 and '年纪' in (res.get('error') or ''), res.get('error'))

    # ---------- 9. 亲养规矩 ----------
    gs.rank = Rank.皇后
    gs.attributes['宠爱'] = 100
    gs.silver = 1000
    prince = gs.npcs[npc_name]['children'][0]
    prince['age'] = 4
    if not m.chonghua_is_inside(prince):
        m.chonghua_admit_child(gs, gs.chonghua, prince)
    gs.relationships.setdefault(npc_name, {'好感': 80, '印象': '亲厚', '互动次数': 0})
    gs.relationships[npc_name]['好感'] = 80
    gs.children = [c for c in gs.children if c.get('alive', True)][:1]
    silver_before = gs.silver
    prestige_before = gs.attributes['威望']
    code, res = act(client, pid, 'adopt', uid=prince['uid'])
    ck('皇后亲养他人皇子成功', code == 200 and res.get('success'), res.get('error') or res.get('message'))
    ck('亲养收取仪银', gs.silver < silver_before, f'{silver_before}->{gs.silver}')
    ck('亲养后威望增长', gs.attributes['威望'] > prestige_before,
       f'{prestige_before}->{gs.attributes["威望"]}')
    ck('亲养后移出生母名下',
       all(c.get('uid') != prince['uid'] for c in gs.npcs[npc_name]['children']),
       [c['name'] for c in gs.npcs[npc_name]['children']])
    ck('亲养后归入玩家膝下',
       any(c.get('uid') == prince['uid'] for c in gs.children), [c['name'] for c in gs.children])
    ck('亲养后离馆', not m.chonghua_is_inside(prince), prince.get('palace'))
    ck('亲养记录过继历史', bool(prince.get('adoption_history')), prince.get('adoption_history'))
    ck('亲养置养母', prince.get('adoptive_mother') == gs.name, prince.get('adoptive_mother'))

    # 亲养不能刷威望（已有 guardian 者再亲养被拒）
    code, res = act(client, pid, 'adopt', uid=prince['uid'])
    ck('已离馆者不可再亲养', code == 400, res.get('error'))

    # 膝下已满
    gs.children = []
    for i in range(m.ADOPT_MAX_CHILDREN):
        gs.children.append(new_child(gs, f'萧满{i}', '公主', 3, gs.name))
    spare = new_child(gs, '萧余生', '公主', 3, npc_name)
    gs.npcs[npc_name]['children'].append(spare)
    m.chonghua_admit_child(gs, gs.chonghua, spare)
    code, res = act(client, pid, 'adopt', uid=spare['uid'])
    ck('膝下已满不得再亲养', code == 400 and '已满' in (res.get('error') or ''), res.get('error'))

    # 年长者不得过继
    spare['age'] = m.ADOPT_MAX_AGE + 1
    gs.children = gs.children[:1]
    code, res = act(client, pid, 'adopt', uid=spare['uid'])
    ck('年长者不得亲养', code == 400 and '年长' in (res.get('error') or ''), res.get('error'))
    spare['age'] = 3

    # 圣宠不足不得亲养皇子
    boy = new_child(gs, '萧宠试', '皇子', 3, npc_name)
    gs.npcs[npc_name]['children'].append(boy)
    m.chonghua_admit_child(gs, gs.chonghua, boy)
    gs.attributes['宠爱'] = 0
    code, res = act(client, pid, 'adopt', uid=boy['uid'])
    ck('圣宠不足不得亲养皇子', code == 400 and '圣宠' in (res.get('error') or ''), res.get('error'))
    gs.attributes['宠爱'] = 100

    # ---------- 10. 迁出 ----------
    mine = gs.children[0]
    if not m.chonghua_is_inside(mine):
        act(client, pid, 'admit', uid=mine['uid'])
    code, res = act(client, pid, 'release', uid=mine['uid'])
    ck('迁出成功', code == 200 and not m.chonghua_is_inside(mine), res.get('error') or res.get('message'))
    ck('迁出摘除名册', mine['uid'] not in gs.chonghua['children'], gs.chonghua['children'])
    ck('迁出指定抚养人', bool(mine.get('guardian')), mine.get('guardian'))
    code, res = act(client, pid, 'release', uid=mine['uid'])
    ck('重复迁出被拒', code == 400, res.get('error'))

    # ---------- 11. 转旬结算 ----------
    # 学成出馆
    grad = new_child(gs, '萧成学', '皇子', m.CHONGHUA_GRADUATE_AGE, gs.name)
    gs.children.append(grad)
    m.chonghua_admit_child(gs, gs.chonghua, grad)
    msgs = m.chonghua_period_tick(gs)
    ck('学成出馆', not m.chonghua_is_inside(grad), [x for x in msgs if '学成' in x])

    # 自动收容
    gs.chonghua['level'] = m.CHONGHUA_MAX_LEVEL
    gs.chonghua['budget'] = 5000
    infant = new_child(gs, '萧襁褓', '公主', 1, npc_name)
    infant['guardian'] = ''
    gs.npcs[npc_name]['children'].append(infant)
    m.chonghua_period_tick(gs)
    ck('年幼者自动入馆', m.chonghua_is_inside(infant), infant.get('palace'))

    # 已有监护人者不自动入馆
    kept = new_child(gs, '萧亲带', '公主', 1, npc_name)
    kept['guardian'] = npc_name
    gs.npcs[npc_name]['children'].append(kept)
    m.chonghua_period_tick(gs)
    ck('有监护人者不自动入馆', not m.chonghua_is_inside(kept), kept.get('guardian'))

    # 用度扣减
    gs.chonghua['budget'] = 5000
    budget_before = gs.chonghua['budget']
    inside_now = m.chonghua_count_inside(gs)
    m.chonghua_period_tick(gs)
    ck('转旬扣用度',
       gs.chonghua['budget'] == budget_before - inside_now * m.CHONGHUA_UPKEEP_PER_CHILD,
       f'{budget_before}->{gs.chonghua["budget"]} inside={inside_now}')

    # 教养收益
    watch = next(c for _o, _t, _i, c in m.chonghua_collect_all_children(gs) if m.chonghua_is_inside(c))
    watch['talent'] = 40
    gs.chonghua['budget'] = 5000
    for _ in range(8):
        m.chonghua_period_tick(gs)
    ck('在馆教养提升才情', watch['talent'] > 40, watch['talent'])

    # 欠饷
    gs.chonghua['budget'] = 0
    gs.chonghua['arrears'] = 0
    msgs = m.chonghua_period_tick(gs)
    ck('用度不足计欠饷', gs.chonghua['arrears'] == 1, gs.chonghua['arrears'])
    ck('欠饷有播报', any('用度短缺' in x for x in msgs), msgs)
    inside_pre = m.chonghua_count_inside(gs)
    m.chonghua_period_tick(gs)
    msgs = m.chonghua_period_tick(gs)
    ck('连欠三旬有皇嗣被领回',
       m.chonghua_count_inside(gs) < inside_pre or any('领回' in x for x in msgs),
       f'{inside_pre}->{m.chonghua_count_inside(gs)}')

    # 授业限次随转旬重置
    gs.chonghua['budget'] = 2000
    gs.silver = 2000
    stu = next((c for _o, _t, _i, c in m.chonghua_collect_all_children(gs)
                if m.chonghua_is_inside(c) and float(c.get('age', 0) or 0) >= m.CHONGHUA_TUTOR_MIN_AGE), None)
    if stu is None:
        stu = new_child(gs, '萧新学', '皇子', 7, gs.name)
        gs.children.append(stu)
        m.chonghua_admit_child(gs, gs.chonghua, stu)
    code, res = act(client, pid, 'tutor', uid=stu['uid'])
    ck('转旬后可再授业', code == 200, res.get('error') or res.get('message'))
    code, res = act(client, pid, 'tutor', uid=stu['uid'])
    ck('同旬仍限一次', code == 400, res.get('error'))
    m.chonghua_period_tick(gs)
    code, res = act(client, pid, 'tutor', uid=stu['uid'])
    ck('转旬重置授业次数', code == 200, res.get('error') or res.get('message'))

    # ---------- 12. next_period 集成 ----------
    gs.chonghua['budget'] = 3000
    gs.remaining_actions = gs.max_actions
    r = post(client, '/api/next_period', {'player_id': pid})
    ck('next_period 200', r.status_code == 200, r.status_code)
    npd = r.get_json() or {}
    ck('next_period 返回 chonghua_events', 'chonghua_events' in npd, list(npd.keys())[:12])
    ck('next_period 返回 chonghua 快照',
       isinstance(npd.get('chonghua'), dict) and npd['chonghua'].get('founded') is True,
       npd.get('chonghua'))

    # ---------- 13. 持久化 ----------
    gs.chonghua['budget'] = 777
    gs.chonghua['arrears'] = 0
    roster_before = list(gs.chonghua['children'])
    level_before = gs.chonghua['level']
    r = post(client, '/api/save', {'player_id': pid, 'slot_name': 'chonghua_check'})
    ck('存档成功', r.status_code == 200, r.get_json())
    m.sessions.pop(pid, None)
    r = post(client, '/api/load', {'player_id': pid, 'slot_name': 'chonghua_check'})
    ck('读档成功', r.status_code == 200, r.status_code)
    gs2 = m.sessions.get(pid)
    ck('读档保留用度', gs2 and gs2.chonghua.get('budget') == 777, gs2.chonghua.get('budget') if gs2 else None)
    ck('读档保留等级', gs2 and gs2.chonghua.get('level') == level_before, gs2.chonghua.get('level') if gs2 else None)
    ck('读档保留名册', gs2 and list(gs2.chonghua.get('children') or []) == roster_before,
       gs2.chonghua.get('children') if gs2 else None)
    code, data = fetch(client, pid)
    ck('读档后接口可用', code == 200 and data.get('chonghua', {}).get('founded'), data.get('chonghua'))

    # ---------- 14. 旧存档兼容 ----------
    gs2.chonghua = {'founded': True, 'level': 2,
                    'children': [{'uid': 'legacy1'}, 'legacy2', {'uid': 'legacy1'}],
                    'log': ['旧字符串日志']}
    ch = m.chonghua_state(gs2)
    ck('旧存档 children 归一化为 uid', ch['children'] == ['legacy1', 'legacy2'], ch['children'])
    ck('旧存档 log 归一化为字典', isinstance(ch['log'][0], dict), ch['log'][0])
    ck('旧存档补齐 arrears/tutored',
       'arrears' in ch and isinstance(ch.get('tutored'), dict), list(ch.keys()))

    # ---------- 15. 未开设时拒绝子嗣操作 ----------
    gs2.chonghua['founded'] = False
    for a in ('admit', 'tutor', 'adopt', 'release', 'upgrade', 'patronize'):
        code, res = act(client, pid, a, uid='legacy1', amount=10)
        if code != 400:
            ck(f'未开设拒绝 {a}', False, f'{code} {res}')
            break
    else:
        ck('未开设拒绝全部子嗣/宫务操作', True, '')

    code, res = act(client, pid, 'unknown_action')
    ck('未知操作被拒', code == 400, res.get('error'))

    for slot in ('chonghua_check', 'default'):
        f = Path(m.SAVE_DIR) / f'{pid}_{slot}.json'
        if f.exists():
            f.unlink()

out = {'passed': sum(1 for x in rep if x['ok']), 'total': len(rep),
       'failed': [x for x in rep if not x['ok']], 'report': rep}
print(json.dumps(out, ensure_ascii=False, indent=2))
sys.exit(0 if out['passed'] == out['total'] else 1)
