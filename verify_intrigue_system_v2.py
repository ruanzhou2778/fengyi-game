import json, random, sys
from pathlib import Path
import app as m
cid='intrigue-v2'; rep=[]
def ck(n,c,d=''): rep.append({'item':n,'ok':bool(c),'detail':str(d)[:180]})
def post(c,p,o): return c.post(p,data=json.dumps(o,ensure_ascii=False),headers={'Content-Type':'application/json','X-Client-ID':cid})
def get(c,p): return c.get(p,headers={'X-Client-ID':cid})
random.seed(7)
with m.app.test_client() as c:
 r=post(c,'/api/start',{'scenario':'才女入宫','name':'测试玩家','storyline':'权谋线','attributes':{'谋略':18,'心计':18,'威望':18},'character':{'appearance':'清丽','talent':'善谋','personality':'沉静','traits':[]}})
 d=r.get_json() or {}; ck('start',r.status_code==200,r.status_code); ck('start intrigue','intrigue' in d,d.get('intrigue')); pid=d.get('player_id'); gs=m.sessions.get(pid)
 t=next((n for n,x in gs.npcs.items() if n!='太后' and x.get('alive',True)),None) if gs else None; ck('target',bool(t),t)
 r=get(c,f'/api/state/{pid}'); s=r.get_json() or {}; ck('state',r.status_code==200,r.status_code); ck('state fields','intrigue' in s and 'intrigue_events' in s,list(s)[:8])
 r=get(c,f'/api/intrigue/targets?player_id={pid}'); td=r.get_json() or {}; ck('targets',r.status_code==200,r.status_code); ck('target listed',any(x.get('name')==t for x in td.get('targets',[])),td.get('targets',[])[:2])
 gs.attributes['谋略']=max(80,gs.attributes.get('谋略',0)); gs.attributes['心计']=max(80,gs.attributes.get('心计',0)); gs.attributes['威望']=max(80,gs.attributes.get('威望',0)); gs.silver=max(200,gs.silver)
 a=gs.remaining_actions; r=post(c,'/api/intrigue',{'player_id':pid,'action':'spy','target':t}); sd=r.get_json() or {}; ck('spy',r.status_code==200,sd); ck('spy action',gs.remaining_actions==a-1,f'{a}->{gs.remaining_actions}')
 gs.intrigue['dirt'][t]={'points':3,'age':0,'label':'旧账'}; r=post(c,'/api/intrigue',{'player_id':pid,'action':'blackmail','target':t}); bd=r.get_json() or {}; ck('blackmail',r.status_code==200,bd); ck('blackmail fields',bool(bd.get('narration')) and 'silver' in bd,bd)
 gs.intrigue['rumors']=[{'target':gs.name,'type':'player','severity':2,'turns_left':2,'text':'旧谣'}]; gs.intrigue['heat']=25; s0=gs.silver; r=post(c,'/api/intrigue',{'player_id':pid,'action':'cleanse','target':''}); cd=r.get_json() or {}; ck('cleanse',r.status_code==200,cd); ck('cleanse silver',cd.get('silver',s0)<=s0,f'{s0}->{cd.get("silver")}')
 gs.intrigue['dirt'][t]={'points':1,'age':0,'label':'不足'}; a1=gs.remaining_actions; s1=gs.silver; r=post(c,'/api/intrigue',{'player_id':pid,'action':'blackmail','target':t}); fd=r.get_json() or {}; ck('fail status',r.status_code==400,fd); ck('refund',gs.remaining_actions==a1,f'{a1}->{gs.remaining_actions}'); ck('no silver loss',gs.silver==s1,f'{s1}->{gs.silver}')
 r=post(c,'/api/intrigue',{'player_id':pid,'action':'spy','target':'不存在'}); ck('invalid target',r.status_code==400,r.get_json())
 gs.intrigue['rumors']=[{'target':gs.name,'type':'player','severity':2,'turns_left':2,'text':'旧谣'}]; gs.intrigue['heat']=25; gs.intrigue['dirt'][t]={'points':3,'age':6,'label':'旧账'}; day=gs.day
 r=post(c,'/api/next_period',{'player_id':pid}); nd=r.get_json() or {}; top=nd.get('intrigue',{}).get('top_dirt',[]); ck('next_period',r.status_code==200,r.status_code); ck('day+10',nd.get('day')==day+10,f'{day}->{nd.get("day")}'); ck('intrigue exists',isinstance(nd.get('intrigue'),dict),nd.get('intrigue')); ck('heat not runaway',nd.get('intrigue',{}).get('heat',999)<=27,nd.get('intrigue')); ck('dirt<=3',(top[0].get('points',99) if top else 99)<=3,top)
 save=Path(m.SAVE_DIR)/f'{pid}_default.json'; ck('autosave',save.exists(),save); m.sessions.pop(pid,None); r=get(c,f'/api/state/{pid}'); rd=r.get_json() or {}; ck('restore',r.status_code==200,r.status_code); ck('restored flag',rd.get('restored_from_save') is True,rd.get('restored_from_save')); r=post(c,'/api/load',{'player_id':pid,'slot_name':'default'}); ld=r.get_json() or {}; ck('load',r.status_code==200,r.status_code); ck('load intrigue',isinstance(ld.get('game_state',{}).get('intrigue'),dict),ld.get('game_state',{}).get('intrigue'))
out={'passed':sum(1 for x in rep if x['ok']),'total':len(rep),'report':rep}; print(json.dumps(out,ensure_ascii=False,indent=2)); sys.exit(0 if out['passed']==out['total'] else 1)
