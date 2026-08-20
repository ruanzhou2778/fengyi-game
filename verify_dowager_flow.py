import json, random, sys
from pathlib import Path
import app as m

cid = 'dowager-flow'
rep = []


def ck(name, cond, detail=''):
    rep.append({'item': name, 'ok': bool(cond), 'detail': str(detail)[:180]})


def post(c, p, o):
    return c.post(p, data=json.dumps(o, ensure_ascii=False),
                  headers={'Content-Type': 'application/json', 'X-Client-ID': cid})


def get(c, p):
    return c.get(p, headers={'X-Client-ID': cid})


def valid_dowager(v):
    return isinstance(v, dict) and bool(v.get('personality')) and bool(v.get('age'))


random.seed(11)
with m.app.test_client() as c:
    r = post(c, '/api/start', {'scenario': '才女入宫', 'name': '太后验证', 'storyline': '权谋线',
                               'attributes': {'谋略': 18, '心计': 18, '威望': 18},
                               'character': {'appearance': '清丽', 'talent': '善谋',
                                             'personality': '沉静', 'traits': []}})
    d = r.get_json() or {}
    ck('start status', r.status_code == 200, r.status_code)
    ck('start dowager', valid_dowager(d.get('dowager')), d.get('dowager'))
    pid = d.get('player_id')
    gs = m.sessions.get(pid)
    ck('session exists', gs is not None, pid)

    r = get(c, f'/api/state/{pid}')
    s = r.get_json() or {}
    ck('state status', r.status_code == 200, r.status_code)
    ck('state dowager', valid_dowager(s.get('dowager')), s.get('dowager'))

    r = post(c, '/api/act', {'player_id': pid, 'action': '四处看看'})
    a = r.get_json() or {}
    ck('act status', r.status_code == 200, r.status_code)
    ck('act dowager', valid_dowager(a.get('dowager')), a.get('dowager'))

    r = post(c, '/api/next_period', {'player_id': pid})
    n = r.get_json() or {}
    ck('next_period status', r.status_code == 200, r.status_code)
    ck('next_period dowager', valid_dowager(n.get('dowager')), n.get('dowager'))

    r = post(c, '/api/save', {'player_id': pid, 'slot_name': 'dowager_check'})
    ck('save status', r.status_code == 200, r.get_json())
    save = Path(m.SAVE_DIR) / f'{pid}_dowager_check.json'
    ck('save file', save.exists(), save)

    m.sessions.pop(pid, None)
    r = post(c, '/api/load', {'player_id': pid, 'slot_name': 'dowager_check'})
    ld = r.get_json() or {}
    ck('load status', r.status_code == 200, r.status_code)
    lgs = ld.get('game_state', {})
    ck('load dowager', valid_dowager(lgs.get('dowager')), lgs.get('dowager'))
    ck('load npcs dowager', valid_dowager((lgs.get('npcs') or {}).get('太后')),
       (lgs.get('npcs') or {}).get('太后'))

    m.sessions.pop(pid, None)
    r = get(c, f'/api/state/{pid}')
    rs = r.get_json() or {}
    ck('restore status', r.status_code == 200, r.status_code)
    ck('restore dowager', valid_dowager(rs.get('dowager')), rs.get('dowager'))

    for slot in ('dowager_check', 'default'):
        f = Path(m.SAVE_DIR) / f'{pid}_{slot}.json'
        if f.exists():
            f.unlink()

out = {'passed': sum(1 for x in rep if x['ok']), 'total': len(rep), 'report': rep}
print(json.dumps(out, ensure_ascii=False, indent=2))
sys.exit(0 if out['passed'] == out['total'] else 1)
