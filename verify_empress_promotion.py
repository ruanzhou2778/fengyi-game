import json
import random
import sys
from pathlib import Path
from unittest.mock import patch

import app as m
from models import GameState, Rank

PASS = 0
FAIL = 0
CID = 'empress-promotion-test'


def ck(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'[OK] {name}')
    else:
        FAIL += 1
        print(f'[FAIL] {name}: {detail}')


def new_state():
    gs = GameState('empress-verify', Rank.皇贵妃)
    gs.name = '沈昭宁'
    gs.family_background = '礼部尚书沈廷璋（嫡）女'
    gs.family_meta = {
        'surname': '沈',
        'official_title': '礼部尚书',
        'official_name': '沈廷璋',
        'official_grade': 2,
        'daughter_status': '嫡',
        'score': 80,
    }
    gs.attributes['宠爱'] = 560
    gs.attributes['威望'] = 360
    gs.attributes['才情'] = 92
    gs.attributes['心计'] = 86
    gs.rank_periods = 20
    gs.children = [
        {'name': '承祐', 'gender': '皇子', 'alive': True},
        {'name': '明华', 'gender': '公主', 'alive': True},
    ]
    gs.relationships = {'皇帝': {'好感': 62, '印象': '信重', '互动次数': 8}}
    gs.story_flags = []
    gs.npcs = {'太后': {'rank': '太后', 'alive': True}}
    return gs


def post(c, path, payload, pid='http-empress'):
    headers = {'Content-Type': 'application/json', 'X-Client-ID': CID}
    return c.post(path, data=json.dumps(payload, ensure_ascii=False), headers=headers)


print('\n=== 1. 立后门槛文案 ===')
gs = new_state()
status = m.get_empress_requirement_status(gs)
ck('识别为立后候选', status['is_candidate'] is True, status)
ck('母家势力达标', status['family_power'] >= status['family_power_required'], status)
reason = m.get_promotion_block_reason(gs)
ck('未起朝议时被拦截', reason == '册立皇后尚需朝臣请立中宫、六宫归心的时机', reason)

print('\n=== 2. 母家势力不足会拦截 ===')
gs = new_state()
gs.family_meta['score'] = 38
reason = m.get_promotion_block_reason(gs)
ck('低门第直接拦截', '母家势力' in (reason or ''), reason)
ck('常规晋升条件失败', m.check_promotion_condition(gs) is False, m.check_promotion_condition(gs))

print('\n=== 3. 关系晋升不能绕过立后门槛 ===')
gs = new_state()
with patch('app.random.random', return_value=0.0):
    promo = m._player_relationship_promotion(gs)
ck('未起朝议时关系晋升无效', promo is None, promo)
ck('位份仍是皇贵妃', gs.rank.name == '皇贵妃', gs.rank.name)

print('\n=== 4. 朝议事件触发后方可晋升 ===')
gs = new_state()
with patch('app.random.random', return_value=0.0):
    msg = m.maybe_trigger_empress_support_event(gs)
ck('朝议事件触发', bool(msg) and m.EMPRESS_SUPPORT_FLAG in gs.story_flags, msg)
ck('事件写入记忆', any(m.EMPRESS_SUPPORT_FLAG in x for x in gs.important_memories), gs.important_memories)
ck('触发后满足常规晋升', m.check_promotion_condition(gs) is True, m.check_promotion_condition(gs))
promo = m.try_player_promotion(gs)
ck('成功晋升皇后', bool(promo) and gs.rank.name == '皇后', promo)

print('\n=== 5. 三条朝议分支 ===')
gs = new_state()
with patch('app.random.random', return_value=0.0):
    msg = m.maybe_trigger_empress_support_event(gs)
status = m.get_empress_requirement_status(gs)
ck('皇子储位分支触发', status['support_source'] == 'heir', status)
ck('皇子分支含储位文案', '皇子储位' in (msg or ''), msg)
ck('皇子分支写入朝议缘由', m.EMPRESS_SUPPORT_SOURCE_FLAGS['heir'] in gs.story_flags, gs.story_flags)

gs = new_state()
gs.children = []
gs.attributes['威望'] = 420
gs.queen_assistance_count = 1
with patch('app.random.random', return_value=0.0):
    msg = m.maybe_trigger_empress_support_event(gs)
status = m.get_empress_requirement_status(gs)
ck('协理六宫分支触发', status['support_source'] == 'palace', status)
ck('协理分支授予临时协理', gs.six_palace_assistant == gs.name, gs.six_palace_assistant)
ck('协理分支含六宫文案', '协理六宫' in (msg or ''), msg)

gs = new_state()
gs.children = []
gs.attributes['威望'] = 320
gs.story_flags = [m.EMPRESS_SUPPORT_VACANCY_FLAG]
with patch('app.random.random', return_value=0.0):
    msg = m.maybe_trigger_empress_support_event(gs)
status = m.get_empress_requirement_status(gs)
ck('废后朝局分支触发', status['support_source'] == 'vacancy', status)
ck('废后分支含朝局文案', '废后之后朝局未稳' in (msg or ''), msg)

print('\n=== 6. 废后开启再立中宫线 ===')
gs = new_state()
gs.npcs['旧皇后'] = {'rank': '皇后', 'alive': True, 'attributes': {'宠爱': 80, '威望': 90}}
msg = m.try_depose_queen(gs, '前朝查明旧案')
ck('废后写入中宫悬空标记', m.EMPRESS_SUPPORT_VACANCY_FLAG in gs.story_flags, msg)
ck('废后后皇后空缺', m.get_queen_name(gs) is None, gs.npcs)

print('\n=== 7. 朝议标记可存档往返 ===')
gs = new_state()
gs.story_flags.extend([
    m.EMPRESS_SUPPORT_CLUE_FLAGS['heir'],
    m.EMPRESS_SUPPORT_SOURCE_FLAGS['heir'],
    m.EMPRESS_SUPPORT_FLAG,
])
data = gs.to_save_data()
restored = GameState.from_save_data(data)
ck('读档保留朝议标记', m.EMPRESS_SUPPORT_FLAG in restored.story_flags, restored.story_flags)
ck('读档保留朝议来源', m.get_empress_support_source(restored) == 'heir', restored.story_flags)
ck('读档后立后条件成立', m.check_promotion_condition(restored) is True, m.check_promotion_condition(restored))

print('\n=== 8. HTTP 存读档携带立后状态 ===')
random.seed(19)
with m.app.test_client() as c:
    r = post(c, '/api/start', {
        'scenario': '才女入宫',
        'name': '立后验证',
        'storyline': '权谋线',
        'attributes': {'谋略': 18, '心计': 18, '威望': 18},
        'character': {'appearance': '清丽', 'talent': '善谋', 'personality': '沉静', 'traits': []}
    })
    d = r.get_json() or {}
    pid = d.get('player_id')
    gs = m.sessions.get(pid)
    ck('start 返回 empress_status', 'empress_status' in d, d)
    ck('session 建立', gs is not None, pid)
    if gs is not None:
        gs.rank = Rank.皇贵妃
        gs.nobletitle = None
        gs.family_background = '礼部尚书沈廷璋（嫡）女'
        gs.family_meta = {'score': 80, 'official_grade': 2, 'daughter_status': '嫡', 'official_title': '礼部尚书'}
        gs.attributes['宠爱'] = 560
        gs.attributes['威望'] = 360
        gs.attributes['才情'] = 92
        gs.attributes['心计'] = 86
        gs.rank_periods = 20
        gs.children = [{'name': '承祐', 'gender': '皇子', 'alive': True}]
        gs.relationships['皇帝'] = {'好感': 62, '印象': '信重', '互动次数': 9}
        gs.story_flags.append(m.EMPRESS_SUPPORT_FLAG)
    r = c.get(f'/api/state/{pid}', headers={'X-Client-ID': CID})
    sd = r.get_json() or {}
    ck('state 返回 empress_status', sd.get('empress_status', {}).get('is_candidate') is True, sd.get('empress_status'))
    ck('state 显示朝议已起', sd.get('empress_status', {}).get('support_ready') is True, sd.get('empress_status'))
    r = post(c, '/api/save', {'player_id': pid, 'slot_name': 'empress_check'})
    ck('save status', r.status_code == 200, r.get_json())
    save_file = Path(m.SAVE_DIR) / f'{pid}_empress_check.json'
    ck('save file exists', save_file.exists(), save_file)
    m.sessions.pop(pid, None)
    r = post(c, '/api/load', {'player_id': pid, 'slot_name': 'empress_check'})
    ld = r.get_json() or {}
    empress = (ld.get('game_state') or {}).get('empress_status') or {}
    ck('load status', r.status_code == 200, ld)
    ck('load 携带 empress_status', empress.get('is_candidate') is True, empress)
    ck('load 保留朝议状态', empress.get('support_ready') is True, empress)
    if save_file.exists():
        save_file.unlink()
    default_file = Path(m.SAVE_DIR) / f'{pid}_default.json'
    if default_file.exists():
        default_file.unlink()

print(f'\n通过 {PASS}/{PASS + FAIL}')
sys.exit(0 if FAIL == 0 else 1)
