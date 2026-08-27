# -*- coding: utf-8 -*-
"""验证：NPC 妃嫔关系网 + 子嗣标签事件 + 协理事件（转旬生成/响应/存读档）。"""
import sys, os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')
import app as A
from app import app as flask_app

PASS = 0
FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")

client = flask_app.test_client()
r = client.post('/api/start', json={"player_name": "测试妃", "api_base": "", "api_key": "", "api_model": ""})
d = r.get_json()
pid = d["player_id"]

def get_state():
    return client.get(f'/api/state/{pid}').get_json()

st = get_state()
npc_names = [n for n, c in st["npcs"].items() if c.get("alive", True) and n != "太后" and n != "皇后"]
# 加个女儿方便子嗣事件
if not st["children"]:
    st2 = get_state()
    client.post(f'/api/state/{pid}', json={})  # noop
# 造一个子嗣
import json as _j
with flask_app.app_context():
    gs = A.sessions[pid]
    gs.children.append({"name": "测试公主", "gender": "公主", "age": 6.0, "alive": True,
                        "birth_mother": gs.name, "stats": {"文采": 50, "容貌": 50, "体魄": 50, "心性": 50, "仪态": 50},
                        "tags": [], "affection": 50})
    gs.has_children = True

# 1. 转旬 25 次，验证关系网/事件生成
rel_api_ok = child_ev_seen = gov_ev_seen = False
for i in range(25):
    rr = client.post(f'/api/next_period', json={"player_id": pid}).get_json()
    if rr.get("error"):
        print("next_period error:", rr["error"]); break
    st = get_state()
    if st.get("relationship_log") and not rel_api_ok:
        rel_api_ok = True
    if st.get("child_event_queue") and not child_ev_seen:
        child_ev_seen = True
    if st.get("governance_events") and not gov_ev_seen:
        gov_ev_seen = True
    # 有事件就处理掉（子嗣事件不耗行动点，协理耗1点）
    for ev in list(st.get("governance_events") or []):
        client.post('/api/governance/respond', json={"player_id": pid, "event_id": ev["id"], "choice_index": 0})
    for ev in list(st.get("child_event_queue") or []):
        client.post('/api/child_event/respond', json={"player_id": pid, "event_id": ev["id"], "choice_index": 0})

check("关系网日志已生成", rel_api_ok)
check("子嗣标签事件已生成", child_ev_seen)

# 2. 关系网 API
rr = client.get(f'/api/relationships?player_id={pid}').get_json()
check("关系网API返回net", isinstance(rr.get("net"), dict) and len(rr["net"]) >= 2)
if rr.get("net"):
    a0 = list(rr["net"].keys())[0]
    b0, e0 = list(rr["net"][a0].items())[0]
    check("关系网条目含类型/分数/图标", all(k in e0 for k in ("tier", "score", "icon", "color")))
    check("关系网分数在合法区间", -100 <= e0["score"] <= 100)

# 3. 直接调 modify_npc_rel 验证同步逻辑
with flask_app.app_context():
    gs = A.sessions[pid]
    a, b = npc_names[0], npc_names[1]
    A.modify_npc_rel(gs, a, b, -80, "测试结仇", "2000年1月")
    entry = A.get_npc_rel(gs, a, b)
    check("modify_npc_rel 更新好感", entry["好感"] <= -20, str(entry["好感"]))
    check("关系类型判定为仇敌/死敌", entry["关系类型"] in ("仇敌", "死敌"))
    A.sync_npc_rel_to_player(gs)
    check("同步到 rivalries", gs.rivalries.get(b, 0) >= 20, str(gs.rivalries.get(b)))
    check("relationship_events 推送", len(gs.relationship_events) >= 1)

# 4. 子嗣事件响应接口：直接塞一个事件再处理
import uuid
with flask_app.app_context():
    gs = A.sessions[pid]
    child = gs.children[0]
    uid = getattr(child, "uid", None) or child.get("uid") or "t1"
    child["uid"] = uid
    ev = {"id": "ev_t1", "child_uid": uid, "child_name": child["name"], "title": "测试事件",
          "stage": "童年", "narrative": "测试叙事",
          "choices": [{"text": "严加管教", "icon": "📏", "effects": {"心性": 5}, "tag": "勤奋"},
                       {"text": "放任", "icon": "🍬", "effects": {"心性": -2}}]}
    gs.child_event_queue = [ev]
rr = client.post('/api/child_event/respond', json={"player_id": pid, "event_id": "ev_t1", "choice_index": 0}).get_json()
check("子嗣事件响应成功", rr.get("success") is True)
check("子嗣事件从队列移除", len(rr.get("child_event_queue", [])) == 0)
with flask_app.app_context():
    gs = A.sessions[pid]
    c0 = [c for c in gs.children if c.get("name") == "测试公主"][0]
    check("子嗣事件标签已授予", "勤奋" in (c0.get("tags") or []), str(c0.get("tags")))
    check("子嗣事件属性已成长", c0["stats"].get("心性", 0) >= 52, str(c0["stats"].get("心性")))
# 重复处理同一事件 → 404
rr2 = client.post('/api/child_event/respond', json={"player_id": pid, "event_id": "ev_t1", "choice_index": 0})
check("重复事件返回404", rr2.status_code == 404)

# 5. 协理事件：低位份不应生成协理事件（非皇后/协理）；验证响应 404
st = get_state()
is_queen = st.get("rank") == "皇后"
check("低位份无协理事件队列", (st.get("governance_events") or []) == [] or is_queen,
      str(st.get("governance_events")))
rr3 = client.post('/api/governance/respond', json={"player_id": pid, "event_id": "no_such", "choice_index": 0})
check("不存在协理事件返回404", rr3.status_code == 404)

# 6. 存读档
with flask_app.app_context():
    gs = A.sessions[pid]
    data = gs.to_dict()
restored = A.GameState.from_save_data(data)
check("存读档 npc_relationships", restored.npc_relationships == gs.npc_relationships)
check("存读档 relationship_log", restored.relationship_log == gs.relationship_log)

# 7. 进程关系函数无异常（幂等）
with flask_app.app_context():
    gs = A.sessions[pid]
    msgs = A.process_npc_relationships(gs)
    check("process_npc_relationships 可重复执行", isinstance(msgs, list))

print(f"\n=== 关系网/事件系统验证: {PASS} passed, {FAIL} failed ===")
sys.exit(1 if FAIL else 0)