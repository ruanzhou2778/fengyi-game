# -*- coding: utf-8 -*-
"""验证 5 项需求的后端核心改动：
  需求2: 宫中账目 = 后宫账目（inner_palace/status 返回 can_manage）
  需求3: 内务府仅皇后/协理六宫可掌管（before_request 拦截写操作）
  需求4: 重华宫默认开设（新游戏 founded=True）
  需求5: generate_period_events 参数统一为 api_base/api_model
运行：python verify_fixes.py
"""
import json, sys, inspect
import app as m
from models import Rank
import ai_service

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

    # 需求4: 重华宫默认开设
    ck('重华宫默认开设(founded=True)', gs.chonghua.get('founded') is True, gs.chonghua.get('founded'))

    # 需求2/3: inner_palace/status 返回 can_manage 字段
    r = c.get(f'/api/inner_palace/status?player_id={pid}')
    s = r.get_json() or {}
    ck('status 返回 can_manage 字段', 'can_manage' in s, s.get('can_manage'))

    # 需求3: 低位份主控 can_manage=False
    ck('低位份 can_manage=False', s.get('can_manage') is False, s.get('can_manage'))

    # 需求3: 低位份写操作被 403 拦截
    r = c.post('/api/inner_palace/purchase', data=json.dumps({'player_id': pid, 'item': '米', 'qty': 1}),
               headers={'Content-Type': 'application/json'})
    ck('低位份采买被 403 拦截', r.status_code == 403, r.status_code)

    # 升为皇后
    gs.rank = Rank.皇后
    gs.remaining_actions = 7
    r = c.get(f'/api/inner_palace/status?player_id={pid}')
    s = r.get_json() or {}
    ck('皇后 can_manage=True', s.get('can_manage') is True, s.get('can_manage'))

    # 皇后写操作不被 403（可能因库银/名目返回 400，但不应是 403）
    r = c.post('/api/inner_palace/purchase', data=json.dumps({'player_id': pid, 'item': '米', 'qty': 1}),
               headers={'Content-Type': 'application/json'})
    ck('皇后采买不被 403 拦截', r.status_code != 403, r.status_code)

    # 协理六宫也可管理
    gs.rank = Rank.妃
    gs.six_palace_assistant = gs.name
    r = c.get(f'/api/inner_palace/status?player_id={pid}')
    s = r.get_json() or {}
    ck('协理六宫 can_manage=True', s.get('can_manage') is True, s.get('can_manage'))
    r = c.post('/api/inner_palace/purchase', data=json.dumps({'player_id': pid, 'item': '米', 'qty': 1}),
               headers={'Content-Type': 'application/json'})
    ck('协理六宫采买不被 403', r.status_code != 403, r.status_code)

    # 撤销协理后低位份又被拦
    gs.six_palace_assistant = None
    r = c.post('/api/inner_palace/purchase', data=json.dumps({'player_id': pid, 'item': '米', 'qty': 1}),
               headers={'Content-Type': 'application/json'})
    ck('撤销协理后妃位被 403', r.status_code == 403, r.status_code)

# 需求5: generate_period_events 参数统一为 api_base/api_model
params = list(inspect.signature(ai_service.generate_period_events).parameters.keys())
ck('generate_period_events 用 api_base', 'api_base' in params, params)
ck('generate_period_events 用 api_model', 'api_model' in params, params)
ck('generate_period_events 无 base_url/model', 'base_url' not in params and 'model' not in params, params)

passed = sum(1 for x in rep if x['ok'])
print(f'\n=== {passed}/{len(rep)} passed ===')
sys.exit(0 if passed == len(rep) else 1)
