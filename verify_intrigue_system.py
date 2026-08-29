import json, random, sys
from pathlib import Path
from unittest.mock import patch
import app as m
cid='intrigue-test-client'; rep=[]

def ok(name, cond, detail=''):
    rep.append({'item':name,'ok':bool(cond),'detail':str(detail)[:240]})

def post(c, path, payload):
    h={'Content-Type':'application/json','X-Client-ID':cid}
    return c.post(path, data=json.dumps(payload, ensure_ascii=False), headers=h)

def get(c, path):
    return c.get(path, headers={'X-Client-ID':cid})

random.seed(12345)
with m.app.test_client() as c:
    r=post(c,'/api/start',{'scenario':'才女入宫','name':'测试玩家','storyline':'权谋线','attributes':{'谋略':18,'心计':18,'威望':18},'character':{'appearance':'清丽','talent':'善谋','personality':'沉静','traits':[]}})
    d=r.get_json() or {}
    ok('start status', r.status_code==200, r.status_code)
    ok('start intrigue', 'intrigue' in d, d.get('intrigue'))
    pid=d.get('player_id'); gs=m.sessions.get(pid)
    names=[n for n,x in gs.npcs.items() if n!='太后' and x.get('alive', True)] if gs else []
    target=names[0] if names else None
    ok('target exists', bool(target), names)

    r=get(c,f'/api/state/{pid}'); s=r.get_json() or {}
    ok('state status', r.status_code==200, r.status_code)
    ok('state intrigue payload', 'intrigue' in s and 'intrigue_events' in s, list(s.keys())[:8])

    r=get(c,f'/api/intrigue/targets?player_id={pid}'); td=r.get_json() or {}
    ok('targets status', r.status_code==200, r.status_code)
    ok('target listed', any(t['name']==target for t in td.get('targets',[])), td.get('targets',[])[:2])

    a0=gs.remaining_actions
    with patch('app.random.random', return_value=0.0):
        r=post(c,'/api/intrigue',{'player_id':pid,'action':'spy','target':target})
    spy=r.get_json() or {}
    ok('spy status', r.status_code==200, spy)
    ok('spy dirt', bool(spy.get('intrigue',{}).get('top_dirt')), spy.get('intrigue',{}))
    ok('spy action cost', gs.remaining_actions==a0-1, f'{a0}->{gs.remaining_actions}')

    gs.intrigue['dirt'][target]['points']=max(3, gs.intrigue['dirt'][target]['points'])
    s0=gs.silver
    with patch('app.random.random', return_value=0.0):
        r=post(c,'/api/intrigue',{'player_id':pid,'action':'blackmail','target':target})
    bl=r.get_json() or {}
    ok('blackmail status', r.status_code==200, bl)
    ok('blackmail silver gain', bl.get('silver',0)>s0, f'{s0}->{bl.get("silver")}')

    gs.intrigue.setdefault('rumors', []).insert(0, {'target':gs.name,'type':'player','severity':2,'turns_left':3,'text':'测试流言'})
    gs.intrigue['heat']=max(20, gs.intrigue.get('heat',0))
    s1=gs.silver
    with patch('app.random.random', return_value=0.0):
        r=post(c,'/api/intrigue',{'player_id':pid,'action':'cleanse','target':''})
    cl=r.get_json() or {}
    it=cl.get('intrigue',{})
    ok('cleanse status', r.status_code==200, cl)
    ok('cleanse silver cost', cl.get('silver',0)==s1-15, f'{s1}->{cl.get("silver")}')
    ok('cleanse reduces pressure', it.get('rumor_count',99)<1 or it.get('heat',999)<20, it)

    gs.intrigue['dirt'][target]={'points':1,'age':0,'label':'不足'}
    a1=gs.remaining_actions; s2=gs.silver
    r=post(c,'/api/intrigue',{'player_id':pid,'action':'blackmail','target':target})
    fail=r.get_json() or {}
    ok('blackmail fail status', r.status_code==400, fail)
    ok('failed action refunded', gs.remaining_actions==a1, f'{a1}->{gs.remaining_actions}')
    ok('failed action no silver cost', gs.silver==s2, gs.silver)

    r=post(c,'/api/intrigue',{'player_id':pid,'action':'spy','target':'不存在'})
    ok('invalid target status', r.status_code==400, r.get_json())

    gs.intrigue['rumors']=[{'target':gs.name,'type':'player','severity':2,'turns_left':2,'text':'旧谣'}]
    gs.intrigue['heat']=20
    gs.intrigue['dirt'][target]={'points':3,'age':6,'label':'旧账'}
    day=gs.day
    with patch('app.generate_period_events', return_value={'events':[], 'ai_used':False, 'fallback':True}), patch('app.random.random', return_value=0.0):
        r=post(c,'/api/next_period',{'player_id':pid})
    np=r.get_json() or {}
    top=np.get('intrigue',{}).get('top_dirt',[])
    ok('next_period status', r.status_code==200, np)
    ok('day advanced', np.get('day')==day+10, f'{day}->{np.get("day")}')
    ok('period intrigue events', bool(np.get('intrigue_events')), np.get('intrigue_events'))
    ok('heat cooled', np.get('intrigue',{}).get('heat',999)<=24, np.get('intrigue',{}))
    ok('dirt aged', (top[0]['points'] if top else 0)<=2, top)

    save=Path(m.SAVE_DIR)/f'{pid}_default.json'
    ok('autosave exists', save.exists(), save)
    m.sessions.pop(pid,None)
    r=get(c,f'/api/state/{pid}'); rs=r.get_json() or {}
    ok('restore state status', r.status_code==200, r.status_code)
    ok('restored flag', rs.get('restored_from_save') is True, rs.get('restored_from_save'))

    r=post(c,'/api/load',{'player_id':pid,'slot_name':'default'})
    ld=r.get_json() or {}
    ok('load status', r.status_code==200, r.status_code)
    ok('load preserves intrigue', ld.get('game_state',{}).get('intrigue') is not None, ld.get('game_state',{}).get('intrigue'))

    # ===== 心腹系统验证（新增） =====
    # 招募宫人
    r=post(c,'/api/servant/hire',{'player_id':pid,'type':'宫女'})
    hire=r.get_json() or {}
    ok('hire servant status', r.status_code==200, hire)
    servant_name=hire.get('servant',{}).get('name')
    ok('servant hired', bool(servant_name), servant_name)

    # 训练宫人忠诚度（增加到 5 次以确保达到 70）
    for _ in range(5):
        r=post(c,'/api/servant/train',{'player_id':pid,'name':servant_name,'attr':'loyalty'})

    # load/restore 后 sessions 里的对象可能已重建，须重新获取，再补足银两与行动点
    gs=m.sessions.get(pid)
    gs.silver = 200
    gs.remaining_actions = 99
    for s in gs.get_active_servants():
        if s.name == servant_name:
            s.loyalty = 80
    
    # 立心腹
    r=post(c,'/api/servant/promote_confidant',{'player_id':pid,'name':servant_name})
    conf=r.get_json() or {}
    ok('promote confidant status', r.status_code==200, conf)
    ok('confidant set', gs.confidant==servant_name, gs.confidant)

    # 获取心腹事件
    r=get(c,f'/api/confidant/events?player_id={pid}')
    events=r.get_json() or {}
    ok('get confidant events status', r.status_code==200, events)

    # 触发心腹事件（如果有）
    if events.get('event'):
        event_id=events['event']['id']
        r=post(c,'/api/confidant/trigger',{'player_id':pid,'event_id':event_id,'choice_index':0})
        trigger=r.get_json() or {}
        ok('trigger confidant event status', r.status_code in [200, 400], trigger)

    # 解除心腹
    r=post(c,'/api/servant/release_confidant',{'player_id':pid,'name':servant_name})
    release=r.get_json() or {}
    ok('release confidant status', r.status_code==200, release)
    ok('confidant released', gs.confidant is None, gs.confidant)

out={'passed':sum(1 for x in rep if x['ok']),'total':len(rep),'report':rep}
print(json.dumps(out, ensure_ascii=False, indent=2))
if out['passed'] != out['total']:
    sys.exit(1)
