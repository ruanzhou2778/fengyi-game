# -*- coding: utf-8 -*-
"""内务府 Phase 1-6 扩展验证脚本。运行：python verify_inner_palace_expansion.py"""
import json, random, sys, copy
from pathlib import Path
import app as m
cid='ip-expansion-test'; rep=[]
def ck(n,c,d=''): rep.append({'item':n,'ok':bool(c),'detail':str(d)[:200]})
def post(c,p,o): return c.post(p,data=json.dumps(o,ensure_ascii=False),headers={'Content-Type':'application/json','X-Client-ID':cid})
def get(c,p): return c.get(p,headers={'X-Client-ID':cid})
random.seed(7)
with m.app.test_client() as c:
    r=post(c,'/api/start',{'scenario':'才女入宫','name':'测试玩家','storyline':'权谋线','attributes':{'谋略':18,'心计':18,'威望':18},'character':{'appearance':'清丽','talent':'善谋','personality':'沉静','traits':[]}})
    d=r.get_json() or {}; ck('start',r.status_code==200,r.status_code); pid=d.get('player_id'); gs=m.sessions.get(pid)
    from models import Rank; gs.rank=Rank.皇后  # 需求：内务府须皇后或协理六宫方可掌管
    t=next((n for n,x in gs.npcs.items() if n!='太后' and x.get('alive',True)),None) if gs else None; ck('target',bool(t),t)
    r=get(c,f'/api/inner_palace/status?player_id={pid}'); s=r.get_json() or {}
    ck('status 200',r.status_code==200,r.status_code)
    for k in ('stipend_cuts','bonus_gifts','banquet','banquet_history','private_purse','performance_reviews','projects','chief','budget'):
        ck(f'status.{k}',k in s,k)
    ck('chief.faction',s.get('chief',{}).get('faction') in ('皇后派','太后派','皇帝派','中立'),s.get('chief',{}).get('faction'))
    a=gs.remaining_actions
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/cut_stipend',{'player_id':pid,'target':t,'pct':30,'periods':10}); sd=r.get_json() or {}
    ck('cut 200',r.status_code==200,sd); ck('cut action',gs.remaining_actions==6,f'7->{gs.remaining_actions}')
    ck('cut stored',gs.inner_palace['stipend_cuts'].get(t,{}).get('amount')==30,gs.inner_palace['stipend_cuts'])
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/cut_stipend',{'player_id':pid,'target':t,'pct':30}); ck('cut dup 400',r.status_code==400,r.get_json())
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/cut_stipend',{'player_id':pid,'target':'不存在'}); ck('cut invalid 400',r.status_code==400,r.get_json())
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/cut_stipend',{'player_id':pid,'target':'太后'}); ck('cut dowager 400',r.status_code==400,r.get_json())
    b0=gs.inner_palace['budget']
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/give_bonus',{'player_id':pid,'target':t,'amount':20,'periods':5}); sd=r.get_json() or {}
    ck('bonus 200',r.status_code==200,sd)
    ck('bonus cost',gs.inner_palace['budget']==b0-100,f'{b0}->{gs.inner_palace["budget"]}')
    ck('bonus favor+5',gs.relationships[t]['好感']>=5,gs.relationships[t])
    gs.inner_palace['budget']=0
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/give_bonus',{'player_id':pid,'target':t,'amount':100,'periods':30}); ck('bonus poor 400',r.status_code==400,r.get_json())
    pre0=gs.attributes['威望']
    gs.inner_palace['budget']=500
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/banquet',{'player_id':pid,'tier':'中等'}); sd=r.get_json() or {}
    ck('banquet 200',r.status_code==200,sd)
    ck('banquet pre',gs.attributes['威望']>=pre0+2,f'{pre0}->{gs.attributes["威望"]}')
    ck('banquet hist',len(gs.inner_palace['banquet_history'])==1,gs.inner_palace['banquet_history'])
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/banquet',{'player_id':pid,'tier':'豪华'}); ck('banquet bad tier 400',r.status_code==400,r.get_json())
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/private_purse/enable',{'player_id':pid}); ck('purse low pre 400',r.status_code==400,r.get_json())
    gs.attributes['威望']=120
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/private_purse/enable',{'player_id':pid}); ck('purse enable',r.status_code==200,r.get_json())
    ck('purse flag',gs.inner_palace['private_purse']['enabled'] is True)
    gs.inner_palace['chief']['loyalty']=10; gs.inner_palace['corruption_evidence']=60
    random.seed(1)
    s1=gs.silver; b1=gs.inner_palace['budget']
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/private_purse/transfer',{'player_id':pid,'amount':30}); td=r.get_json() or {}
    ok_state=(gs.silver==s1+30 and gs.inner_palace['budget']==b1-30) or (gs.silver==s1 and gs.inner_palace['budget']==b1)
    ck('transfer',r.status_code==200 and ok_state,td)
    gs.inner_palace['chief']['loyalty']=90; gs.inner_palace['corruption_evidence']=0
    gs.inner_palace['private_purse']['last_transfer_period']=int(gs.day or 0)
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/private_purse/transfer',{'player_id':pid,'amount':30}); ck('transfer same period 400',r.status_code==400,r.get_json())
    gs.inner_palace['budget']=300
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/chief/appoint',{'player_id':pid}); ad=r.get_json() or {}
    ck('appoint',r.status_code==200,ad); ck('appoint faction',gs.inner_palace['chief']['faction'] in ('皇后派','太后派','皇帝派','中立'),gs.inner_palace['chief'])
    ck('appoint budget',gs.inner_palace['budget']<=201,gs.inner_palace['budget'])
    ck('chief_faction sync',gs.chief_faction==gs.inner_palace['chief']['faction'],(gs.chief_faction,gs.inner_palace['chief']['faction']))
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/chief/dismiss',{'player_id':pid}); dd=r.get_json() or {}
    ck('dismiss',r.status_code==200,dd); ck('dismiss ev clear',gs.inner_palace['corruption_evidence']==0,gs.inner_palace['corruption_evidence'])
    gs.attributes['威望']=20; gs.inner_palace['corruption_evidence']=0
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/chief/dismiss',{'player_id':pid}); ck('dismiss weak 400',r.status_code==400,r.get_json())
    gs.inner_palace['budget']=500
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/project/upgrade',{'player_id':pid,'name':'皇庄'}); pd=r.get_json() or {}
    ck('project 200',r.status_code==200,pd)
    ck('project lv',gs.inner_palace['projects']['皇庄']['level']==1,gs.inner_palace['projects']['皇庄'])
    ck('project cost',gs.inner_palace['budget']==400,gs.inner_palace['budget'])
    gs.remaining_actions=7
    r=post(c,'/api/inner_palace/project/upgrade',{'player_id':pid,'name':'钱庄'}); ck('project unknown 400',r.status_code==400,r.get_json())
    r=get(c,f'/api/inner_palace/performance?player_id={pid}'); pf=r.get_json() or {}
    ck('performance 200',r.status_code==200 and 'next_review' in pf,pf)
    # advance_calendar 每月30天循环：day=20 推进后为30，触发考绩
    gs.day=20; gs.inner_palace['performance_reviews']['next_review']=30; gs.inner_palace['performance_reviews']['last_review']=0
    gs.inner_palace['chief']['loyalty']=100; gs.inner_palace['chief']['corruption']=0
    gs.inner_palace['budget']=500
    r=post(c,'/api/next_period',{'player_id':pid}); nd=r.get_json() or {}
    ck('next_period 200',r.status_code==200,r.status_code)
    ck('day advanced',nd.get('day')==30,f"{nd.get('day')}")
    ck('review triggered',gs.inner_palace['performance_reviews']['last_review']==30,gs.inner_palace['performance_reviews'])
    ck('review grade',gs.inner_palace['performance_reviews']['grade'] in ('优','平','劣'),gs.inner_palace['performance_reviews'])
    cut_v=gs.inner_palace['stipend_cuts'].get(t)
    ck('cut decay or exposed',(cut_v is None and gs.inner_palace['corruption_evidence']>0) or (isinstance(cut_v,dict) and cut_v.get('periods')==9),gs.inner_palace['stipend_cuts'])
    ck('gift decay',gs.inner_palace['bonus_gifts'].get(t,{}).get('periods',0)==4,gs.inner_palace['bonus_gifts'])
    saved=gs.to_dict(); d2=copy.deepcopy(saved)
    gs2=m.GameState.from_save_data(d2)
    ck('roundtrip cuts',gs2.inner_palace['stipend_cuts']==gs.inner_palace['stipend_cuts'])
    ck('roundtrip projects',gs2.inner_palace['projects']==gs.inner_palace['projects'])
    ck('roundtrip purse',gs2.inner_palace['private_purse']==gs.inner_palace['private_purse'])
    ck('roundtrip chief faction',gs2.inner_palace['chief']['faction']==gs.inner_palace['chief']['faction'])
    ck('roundtrip chief_faction',gs2.chief_faction==gs.chief_faction)
    ck('roundtrip reviews',gs2.inner_palace['performance_reviews']==gs.inner_palace['performance_reviews'])
    old_saves=sorted(Path(m.SAVE_DIR).glob('*.json'))
    if old_saves:
        raw=json.loads(old_saves[0].read_text(encoding='utf-8'))
        raw=raw.get('game_state', raw) if isinstance(raw, dict) else {}
        if not isinstance(raw.get('inner_palace'), dict):
            raw['inner_palace']={}
        raw['inner_palace'].pop('stipend_cuts',None); raw['inner_palace']['chief']={'name':'苏培盛','loyalty':60,'corruption':25,'skill':70}
        gs3=m.GameState.from_save_data(raw)
        ck('old save migrate',gs3.inner_palace['stipend_cuts']=={} and gs3.inner_palace['projects']['皇庄']['level']==0 and gs3.inner_palace['chief']['faction']=='中立',gs3.inner_palace['chief'])
        ck('old save chief_faction',gs3.chief_faction=='中立',gs3.chief_faction)
    gs.ending={'key':'测试','headline':'测试结局'}
    for p,b in (('/api/inner_palace/cut_stipend',{'player_id':pid,'target':t}),('/api/inner_palace/banquet',{'player_id':pid,'tier':'中等'}),('/api/inner_palace/private_purse/enable',{'player_id':pid})):
        r=post(c,p,b); ck(f'gameover {p} 409',r.status_code==409,r.status_code)
    out={'passed':sum(1 for x in rep if x['ok']),'total':len(rep),'report':rep}
    print(json.dumps(out,ensure_ascii=False,indent=2)); sys.exit(0 if out['passed']==out['total'] else 1)
