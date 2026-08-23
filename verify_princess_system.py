"""公主择婿与省亲系统验证：候选生成、门第校验、细察、决策权下放、
定亲/出降流转、和亲分支、公主府经营、省亲 tick、朝堂联动与旧存档兼容。

运行：python verify_princess_system.py
"""
import json
import random

import app as m
from models import Rank, GameState, default_court_faction_favor, normalize_court_faction_favor

cid = 'princess-verify'
rep = []


def ck(name, cond, detail=''):
    rep.append({'item': name, 'ok': bool(cond), 'detail': str(detail)[:200]})


def post(c, p, o):
    return c.post(p, data=json.dumps(o, ensure_ascii=False),
                  headers={'Content-Type': 'application/json', 'X-Client-ID': cid})


def get(c, p):
    return c.get(p, headers={'X-Client-ID': cid})


def make_princess(gs, name='昭阳', age=16, favor=50):
    child = m.create_newborn_child('公主', name, gs, mother_name=gs.name)
    child['age'] = age
    child['emperor_favor'] = favor
    m.ensure_child_fields(child)
    m.ensure_child_uid(gs, child)
    gs.children.append(child)
    gs.has_children = True
    return child


random.seed(20260223)
with m.app.test_client() as client:
    r = post(client, '/api/start', {
        'scenario': '才女入宫', 'name': '择婿验证', 'storyline': '权谋线',
        'attributes': {'心计': 18, '威望': 18},
        'character': {'appearance': '清丽', 'talent': '善谋', 'personality': '沉静', 'traits': []},
    })
    d = r.get_json() or {}
    pid = d.get('player_id')
    gs = m.sessions.get(pid)
    ck('会话建立', gs is not None, pid)

    # ---------- 1. 数据层：新字段 & 朝堂好感度 ----------
    ck('court_faction_favor 默认三派', normalize_court_faction_favor(gs.court_faction_favor) == default_court_faction_favor(),
       gs.court_faction_favor)
    princess = make_princess(gs, '昭阳', age=16, favor=55)
    m.ensure_child_fields(princess)
    ck('公主字段 marriage_status', princess.get('marriage_status') == '未议', princess.get('marriage_status'))
    ck('公主字段 suitors 为列表', isinstance(princess.get('suitors'), list), princess.get('suitors'))
    puid = princess['uid']

    # ---------- 2. 及笄前不可议婚 ----------
    young = make_princess(gs, '未笄', age=12)
    r = post(client, '/api/princess/suitors', {'player_id': pid, 'child_uid': young['uid']})
    ck('未及笄不得相看', r.status_code == 400, r.get_json())

    # ---------- 3. 候选人生成 ----------
    gs.silver = 2000
    r = post(client, '/api/princess/suitors', {'player_id': pid, 'child_uid': puid})
    body = r.get_json() or {}
    ck('相看返回成功', body.get('success'), body.get('error'))
    suitors = (body.get('princess') or {}).get('suitors', [])
    ck('生成候选驸马 3-5 名', 3 <= len(suitors) <= 5, len(suitors))
    ck('候选人默认未细察', all(not s.get('inspected') for s in suitors), suitors)
    ck('未细察隐藏野心', all(s.get('ambition') is None for s in suitors), suitors)
    ck('候选人含圣意契合度', all('court_favor' in s for s in suitors), suitors)
    first_uids = sorted(s['uid'] for s in suitors)
    r2 = post(client, '/api/princess/suitors', {'player_id': pid, 'child_uid': puid})
    suitors2 = (r2.get_json().get('princess') or {}).get('suitors', [])
    ck('候选人每旬缓存', sorted(s['uid'] for s in suitors2) == first_uids, suitors2)

    # ---------- 4. 细察揭示隐藏项（耗行动点） ----------
    gs.remaining_actions = 5
    sid = suitors[0]['uid']
    r = post(client, '/api/princess/inspect', {'player_id': pid, 'child_uid': puid, 'suitor_uid': sid})
    ins = r.get_json() or {}
    ck('细察返回成功', ins.get('success'), ins.get('error'))
    ck('细察消耗行动点', ins.get('remaining_actions') == 4, ins.get('remaining_actions'))
    inspected = next((s for s in (ins.get('princess') or {}).get('suitors', []) if s['uid'] == sid), None)
    ck('细察后揭示野心', inspected and inspected.get('ambition') is not None, inspected)
    gs.remaining_actions = 0
    r = post(client, '/api/princess/inspect', {'player_id': pid, 'child_uid': puid, 'suitor_uid': suitors[1]['uid']})
    ck('行动点不足不得细察', r.status_code == 400, r.get_json())

    # ---------- 5. 决策类型来源 ----------
    gs.emperor['personality'] = '昏君'
    princess['marriage_authority'] = None
    ck('昏君→功利型', m.emperor_decision_type(gs, princess) == '功利型', m.emperor_decision_type(gs, princess))
    gs.emperor['personality'] = '痴情'
    ck('痴情→慈父型', m.emperor_decision_type(gs, princess) == '慈父型', m.emperor_decision_type(gs, princess))
    princess['marriage_authority'] = gs.name
    gs.emperor['personality'] = '昏君'
    ck('下放决策权→慈父型', m.emperor_decision_type(gs, princess) == '慈父型', m.emperor_decision_type(gs, princess))
    princess['marriage_authority'] = None

    # ---------- 6. 请旨亲裁（依宠爱） ----------
    gs.attributes['宠爱'] = 30
    r = post(client, '/api/princess/authority', {'player_id': pid, 'child_uid': puid})
    ck('宠爱不足不得请旨', r.status_code == 400, r.get_json())
    gs.attributes['宠爱'] = 70
    r = post(client, '/api/princess/authority', {'player_id': pid, 'child_uid': puid})
    ck('宠爱足够可请旨', r.get_json().get('success'), r.get_json())
    ck('决策权归玩家', princess.get('marriage_authority') == gs.name, princess.get('marriage_authority'))

    # ---------- 7. 定亲 ----------
    gs.silver = 2000
    r = post(client, '/api/princess/betroth', {'player_id': pid, 'child_uid': puid, 'suitor_uid': sid})
    bet = r.get_json() or {}
    ck('定亲成功', bet.get('success'), bet.get('error'))
    ck('定亲后状态已定', princess.get('marriage_status') == '已定', princess.get('marriage_status'))
    ck('定亲写入 consort', isinstance(princess.get('consort'), dict), princess.get('consort'))
    ck('定亲清空候选', princess.get('suitors') == [], princess.get('suitors'))
    r = post(client, '/api/princess/suitors', {'player_id': pid, 'child_uid': puid})
    ck('已定不可再相看', r.status_code == 400, r.get_json())

    # ---------- 8. 出降（建立公主府 + 朝堂联动） ----------
    consort_faction = princess['consort']['faction']
    favor_before = dict(normalize_court_faction_favor(gs.court_faction_favor))
    gs.silver = 2000
    r = post(client, '/api/princess/marry', {'player_id': pid, 'child_uid': puid, 'mode': '出降'})
    mar = r.get_json() or {}
    ck('出降成功', mar.get('success'), mar.get('error'))
    ck('出降后状态已嫁', princess.get('marriage_status') == '已嫁', princess.get('marriage_status'))
    ck('出降建立公主府', isinstance(princess.get('mansion'), dict), princess.get('mansion'))
    favor_after = normalize_court_faction_favor(gs.court_faction_favor)
    ck('出降抬升驸马派系好感', favor_after[consort_faction] >= favor_before[consort_faction], (favor_before, favor_after))
    p3 = make_princess(gs, '清河', age=17)
    gs.silver = 2000
    r = post(client, '/api/princess/marry', {'player_id': pid, 'child_uid': p3['uid'], 'mode': '出降'})
    ck('未定亲不可出降', r.status_code == 400, r.get_json())

    # ---------- 9. 公主府扩建 ----------
    gs.silver = 5000
    lvl_before = princess['mansion']['level']
    r = post(client, '/api/princess/mansion', {'player_id': pid, 'child_uid': puid, 'op': 'upgrade'})
    ck('公主府扩建成功', r.get_json().get('success'), r.get_json())
    ck('公主府等级+1', princess['mansion']['level'] == lvl_before + 1, princess['mansion'])

    # ---------- 10. 和亲分支 ----------
    p4 = make_princess(gs, '安平', age=18)
    gs.silver = 2000
    wangwang_before = gs.attributes.get('威望', 0)
    r = post(client, '/api/princess/marry', {'player_id': pid, 'child_uid': p4['uid'], 'mode': '和亲'})
    hq = r.get_json() or {}
    ck('和亲成功', hq.get('success'), hq.get('error'))
    ck('和亲后状态', p4.get('marriage_status') == '和亲', p4.get('marriage_status'))
    ck('和亲提升威望', gs.attributes.get('威望', 0) >= wangwang_before, (wangwang_before, gs.attributes.get('威望')))

    # ---------- 11. 省亲/公主府 tick 不报错 ----------
    try:
        evs = m.process_princess_marriage_events(gs)
        ck('省亲 tick 正常执行', isinstance(evs, list), evs)
    except Exception as e:
        ck('省亲 tick 正常执行', False, repr(e))

    # ---------- 12. 及笄里程碑生成 preference ----------
    baby = m.create_newborn_child('公主', '及笄测试', gs, mother_name=gs.name)
    baby['age'] = 15
    m.ensure_child_uid(gs, baby)
    milestones = m.process_child_milestones(baby, '你的', gs)
    ck('十五岁及笄里程碑', any('及笄' in e for e in milestones), milestones)
    ck('及笄生成 preference', baby.get('preference') in m.PRINCESS_PREFERENCES, baby.get('preference'))

    # ---------- 13. 持久化：存读档 ----------
    saved = gs.to_dict()
    ck('to_dict 含 court_faction_favor', 'court_faction_favor' in saved, 'court_faction_favor' in saved)
    gs2 = GameState.from_save_data({'game_state': saved})
    ck('读档恢复朝堂好感', normalize_court_faction_favor(gs2.court_faction_favor) == favor_after,
       (gs2.court_faction_favor, favor_after))
    reloaded = next((c for c in gs2.children if c.get('uid') == puid), None)
    ck('读档恢复公主婚姻状态', reloaded and reloaded.get('marriage_status') == '已嫁',
       reloaded and reloaded.get('marriage_status'))

    # ---------- 14. 旧存档兼容 ----------
    legacy_save = {'game_state': gs.to_dict()}
    legacy_save['game_state'].pop('court_faction_favor', None)
    gs3 = GameState.from_save_data(legacy_save)
    ck('旧档补全朝堂好感', normalize_court_faction_favor(gs3.court_faction_favor) == default_court_faction_favor(),
       gs3.court_faction_favor)
    legacy_child = {'name': '旧档公主', 'gender': '公主', 'age': 16}
    m.ensure_child_fields(legacy_child)
    ck('旧档公主补全 marriage_status', legacy_child.get('marriage_status') == '未议', legacy_child.get('marriage_status'))


# ---------- 汇总 ----------
ok_count = sum(1 for x in rep if x['ok'])
print(f"\n{'='*60}")
print(f"公主择婿与省亲系统验证：{ok_count}/{len(rep)} 通过")
print('='*60)
for x in rep:
    flag = '✅' if x['ok'] else '❌'
    print(f"{flag} {x['item']}" + (f"  →  {x['detail']}" if not x['ok'] else ''))

if ok_count != len(rep):
    import sys
    sys.exit(1)


