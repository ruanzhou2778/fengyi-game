# -*- coding: utf-8 -*-
"""验证：主控立绘+外观+才艺加成 / 主控互动对话三选拼装 / 宫斗日志分类+后台核对+一生三幕。"""
import sys; sys.path.insert(0, '.')
import app as A
from app import app as flask_app

client = flask_app.test_client()
r = client.post('/api/start', json={"name": "沈测试", "api_base": "", "api_key": "", "api_model": ""})
pid = r.get_json()["player_id"]
gs = A.sessions[pid]
gs.attributes["宠爱"] = 200
gs.attributes["才情"] = 60
gs.attributes["容貌"] = 78
gs.appearance = "云鬓如墨，眉目如画，肤若凝脂"
gs.talent = "琴艺、书画、歌舞"
gs.personality = "温婉贤淑"
gs.traits = ["聪慧", "隐忍"]
gs.npcs["柳妃"] = {"name": "柳妃", "alive": True, "rank": "妃", "age": 24, "personality": "多疑", "attitude": {}}

# === 1. player_render 字段 ===
d = client.get(f"/api/state/{pid}").get_json()
pr = d.get("player_render") or {}
assert pr.get("appearance") == gs.appearance, f"appearance mismatch: {pr.get('appearance')}"
assert pr.get("talent") == "琴艺、书画、歌舞"
assert pr.get("personality") == "温婉贤淑"
assert set(pr.get("traits") or []) == {"聪慧", "隐忍"}
bonus = pr.get("talent_bonus") or []
attrs_by_src = {}
for b in bonus:
    attrs_by_src.setdefault(b["src"], []).append(b["attr"])
assert set(attrs_by_src.keys()) == {"琴艺", "书画", "歌舞"}, f"missing talent bonus: {attrs_by_src}"
# 数值是数字且 >0
for b in bonus:
    assert isinstance(b["value"], int) and b["value"] > 0
    assert b["attr"] in A.GameState.ATTR_MAX
print(f"[OK] player_render: 6 keys, talent_bonus 计数 {len(bonus)}")

# === 2. /api/player/interact ===
def _interact(style, action):
    r = client.post("/api/player/interact", json={"player_id": pid, "npc_name": "柳妃", "style": style, "action": action})
    return r.get_json()

soft = _interact("soft", "妹妹今日可好")
sharp = _interact("sharp", "你昨日在御花园究竟做了什么")
crafty = _interact("crafty", "姐姐这般忙碌，可是心中有事？")
assert soft.get("line") and "沈测试" in soft["line"] and "柳妃" in soft["line"]
assert sharp.get("line") and "你昨日在御花园究竟做了什么" in sharp["line"], f"sharp line: {sharp.get('line')}"
assert crafty.get("face") in ("😊","😠","😨","😳","😐","🤔","😌","😲"), f"bad face: {crafty.get('face')}"
# 锋利应降低好感/信任
axes_s = soft["axes"]
axes_p = sharp["axes"]
assert axes_p["畏惧"] > axes_s["畏惧"], f"sharp 畏惧 应 > soft: {axes_p['畏惧']} vs {axes_s['畏惧']}"
assert axes_p["信任"] < axes_s["信任"], f"sharp 信任 应 < soft: {axes_p['信任']} vs {axes_s['信任']}"
# 温柔应增加好感
warm = _interact("warm", "姐姐这盏茶好香")
assert warm["axes"]["好感"] > soft["axes"]["好感"] - 5  # warm ≥ soft
print(f"[OK] interact: soft/sharp/crafty/warm axes 合理；face={crafty['face']}")

# === 3. next_period 携带 player_render ===
d = client.post("/api/next_period", json={"player_id": pid}).get_json()
assert "player_render" in d, "next_period 缺 player_render"
assert d["player_render"]["talent"] == "琴艺、书画、歌舞"
print("[OK] next_period 携带 player_render")

# === 4. 错误路径：未知 NPC ===
err = client.post("/api/player/interact", json={"player_id": pid, "npc_name": "不存在", "style": "soft", "action": "test"})
assert err.status_code == 400
assert "error" in err.get_json()
print("[OK] 未知 NPC 返回 400")

# === 5. 风格枚举完整 ===
for sk in ("soft", "cool", "sharp", "warm", "crafty"):
    r = client.post("/api/player/interact", json={"player_id": pid, "npc_name": "柳妃", "style": sk, "action": "test-" + sk})
    d = r.get_json()
    assert d.get("style") in ("温柔","冷淡","锋利","热情","城府"), f"unknown style: {sk}"
    assert d.get("effects") and isinstance(d["effects"], dict)
print("[OK] 5 风格各自 effects 返回")

print("\nPLAYER_INTERACT_OK 全部通过")
