# -*- coding: utf-8 -*-
"""验证：前朝关联系统（玩家家族生成 / NPC 母族 / 家族事件生成与响应 / 前朝总览 / 存读档 / 升降位联动）。"""
import sys, os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')
from unittest.mock import patch
import app as m
from app import app as flask_app

PASS = 0
FAIL = 0
def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")

client = flask_app.test_client()
r = client.post('/api/start', json={"name": "沈语嫣", "api_base": "", "api_key": "", "api_model": ""})
d = r.get_json() or {}
ok('start status', r.status_code == 200, d)
pid = d.get("player_id")
gs = m.sessions.get(pid)
ok('player_clan generated', isinstance(gs.player_clan, dict) and gs.player_clan.get("father"), gs.player_clan if not isinstance(gs.player_clan, dict) else gs.player_clan.get("father"))
ok('clan matches surname', isinstance(gs.player_clan, dict) and gs.player_clan.get("surname") == "沈", gs.player_clan.get("surname") if isinstance(gs.player_clan, dict) else None)
npc_with_clan = [n for n, c in gs.npcs.items() if isinstance(c, dict) and isinstance(c.get("clan"), dict)]
ok('npc clans attached', len(npc_with_clan) >= 5, len(npc_with_clan))
rel_ok = all(isinstance(gs.npcs[n]["clan"].get("与玩家家族关系"), dict) for n in npc_with_clan)
ok('npc clan relations initialized', rel_ok, {n: gs.npcs[n]["clan"].get("与玩家家族关系") for n in npc_with_clan[:2]})

# ---- 家族事件生成（绕过 40% 概率门） ----
with patch('family_backgrounds.random.random', return_value=0.0):
    m.generate_family_events(gs)
queue = gs.family_event_queue
ok('family event queued', len(queue) == 1, len(queue))
ev = queue[0] if queue else {}
texts = [ev.get("title", ""), ev.get("desc", "")] + [c.get("text", "") for c in ev.get("choices", [])]
ok('no leftover placeholders', all('{' not in t and '}' not in t for t in texts), texts)
ok('event has 3 choices', len(ev.get("choices", [])) == 3, len(ev.get("choices", [])))

# ---- 响应家族事件 API ----
r = client.post('/api/family/respond', json={"player_id": pid, "event_id": ev.get("id"), "choice_index": 0})
resp = r.get_json() or {}
ok('respond status', r.status_code == 200, resp)
ok('respond narration', bool(resp.get("narration")), resp.get("narration"))
ok('event removed from queue', len(resp.get("family_event_queue", [])) == 0, resp.get("family_event_queue"))
ok('history recorded', len(gs.family_event_history) == 1, gs.family_event_history)

# ---- 不存在的事件 404 ----
r = client.post('/api/family/respond', json={"player_id": pid, "event_id": "fam_none", "choice_index": 0})
ok('missing event 404', r.status_code == 404, r.status_code)

# ---- 前朝总览 API ----
r = client.get(f'/api/court/overview?player_id={pid}')
ov = r.get_json() or {}
ok('overview status', r.status_code == 200, ov)
ok('overview has player clan', isinstance(ov.get("player_clan"), dict), bool(ov.get("player_clan")))
ok('overview factions', set((ov.get("factions") or {}).keys()) == {"文官党", "武官党", "宗室党"}, ov.get("factions"))
ok('overview npc clans', len(ov.get("npc_clans", [])) >= 5, len(ov.get("npc_clans", [])))
ov_row = (ov.get("npc_clans") or [{}])[0]
ok('npc clan row fields', all(k in ov_row for k in ("name", "rank", "faction", "prestige", "father", "relation", "favor")), ov_row)

# ---- 旧档迁移：清空家族后转旬自动补全 ----
gs.player_clan = None
for c in gs.npcs.values():
    if isinstance(c, dict) and "clan" in c:
        del c["clan"]
msgs = m.process_clan_period(gs)
ok('migration regenerates player clan', isinstance(gs.player_clan, dict), gs.player_clan)
mig = [n for n, c in gs.npcs.items() if isinstance(c, dict) and isinstance(c.get("clan"), dict)]
ok('migration regenerates npc clans', len(mig) >= 5, len(mig))

# ---- NPC 升降位联动家族威望 ----
npc_name = next(n for n in mig if n != "皇后" and gs.npcs[n].get("rank") != "皇后")
clan = gs.npcs[npc_name]["clan"]
clan["last_rank"] = "答应"
gs.npcs[npc_name]["rank"] = "答应"
before = clan["家族威望"]
gs.npcs[npc_name]["rank"] = "嫔"
m.process_clan_period(gs)
ok('promotion boosts clan prestige', clan["家族威望"] == before + 3, f'{before} -> {clan["家族威望"]}')
ok('last_rank updated', clan["last_rank"] == "嫔", clan["last_rank"])

# ---- 风险爆发 ----
gs.player_clan["风险值"] = 90
with patch('family_backgrounds.random.random', return_value=0.0):
    m.process_clan_period(gs)
ok('risk burst reduces prestige', gs.player_clan["风险值"] < 90, gs.player_clan["风险值"])

# ---- 存读档持久化 ----
with patch('family_backgrounds.random.random', return_value=0.0):
    m.generate_family_events(gs)
queued = len(gs.family_event_queue)
payload = gs.to_dict()
ok('to_dict includes queue', isinstance(payload.get("family_event_queue"), list) and len(payload["family_event_queue"]) == queued, payload.get("family_event_queue"))
restored = m.GameState.from_save_data(payload)
ok('from_dict restores queue', len(restored.family_event_queue) == queued, len(restored.family_event_queue))
ok('from_dict restores history', len(restored.family_event_history) == len(gs.family_event_history), len(restored.family_event_history))

print(f"\n前朝关联系统验证: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
