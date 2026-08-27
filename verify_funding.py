# -*- coding: utf-8 -*-
"""验证内务府初始库银 + 皇帝交互「请拨内帑」拨款功能。
   覆盖：初始5000 / 低位403 / 皇后200(5000-8000) / 库银增加 / 同旬400
   运行：python verify_funding.py
"""
import json, sys
import app as m
from models import Rank

rep = []
def ck(name, cond, detail=''):
    rep.append({'item': name, 'ok': bool(cond), 'detail': str(detail)[:200]})
    print(('[OK] ' if cond else '[FAIL] ') + name + (' :: ' + str(detail)[:200] if detail else ''))

with m.app.test_client() as c:
    r = c.post('/api/start', data=json.dumps({
        'scenario': '才女入宫', 'name': '验证者', 'storyline': '权谋线',
        'attributes': {'心计': 18, '威望': 18},
        'character': {'appearance': '清丽', 'talent': '善谋', 'personality': '沉静', 'traits': []}
    }, ensure_ascii=False), headers={'Content-Type': 'application/json'})
    d = r.get_json() or {}
    pid = d.get('player_id')
    gs = m.sessions.get(pid)
    ck('会话建立', gs is not None, pid)

    # 初始库银 = 5000（改动后默认）
    b0 = gs.inner_palace['budget']
    ck('内务府初始库银5000', b0 == 5000, b0)

    # 低位份(默认)请拨内帑 → 403（非皇后/协理）
    gs.remaining_actions = 7
    r = c.post('/api/emperor/interact', data=json.dumps({'player_id': pid, 'action': 'request_funding'}),
               headers={'Content-Type': 'application/json'})
    ck('低位请拨内帑被403拦截', r.status_code == 403, r.status_code)

    # 升为皇后 → 200，拨款 5000-8000
    gs.rank = Rank.皇后
    gs.remaining_actions = 7
    r = c.post('/api/emperor/interact', data=json.dumps({'player_id': pid, 'action': 'request_funding'}),
               headers={'Content-Type': 'application/json'})
    d2 = r.get_json() or {}
    grant = (d2.get('effects') or {}).get('内务府库银')
    ck('皇后请拨内帑成功200', r.status_code == 200, (r.status_code, d2.get('narration')))
    ck('拨款随机5000-8000', grant is not None and 5000 <= grant <= 8000, grant)

    # 库银实际增加
    b1 = gs.inner_palace['budget']
    ck('库银增加=初始+拨款', b1 == b0 + grant, f'{b0}+{grant}={b0+grant} vs {b1}')

    # 记忆含拨款记录
    mems = [x for x in (gs.important_memories or []) if '内帑' in str(x)]
    ck('记忆记录拨款', len(mems) >= 1, mems[-1] if mems else '')

    # 同旬再请 → 400
    gs.remaining_actions = 7
    r = c.post('/api/emperor/interact', data=json.dumps({'player_id': pid, 'action': 'request_funding'}),
               headers={'Content-Type': 'application/json'})
    ck('同旬再请被400拦截', r.status_code == 400, (r.get_json() or {}).get('error'))

ok = all(x['ok'] for x in rep)
print(f'\n=== {sum(1 for x in rep if x["ok"])}/{len(rep)} passed ===')
sys.exit(0 if ok else 1)
