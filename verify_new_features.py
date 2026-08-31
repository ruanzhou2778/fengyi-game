# -*- coding: utf-8 -*-
"""验证：节令宴饮 / 太医网络 / 宫廷市集（new_features.py + 路由 + 旧档兼容）。"""
import sys, os
sys.path.insert(0, '.')
import app as A
from app import app as flask_app
import random

client = flask_app.test_client()
passed = failed = 0

def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} :: {detail}")

# ===== 0. 开局 =====
r = client.post('/api/start', json={"name": "新玩法验证", "api_base": "", "api_key": "", "api_model": ""})
pid = r.get_json()["player_id"]
gs = A.sessions[pid]

# ===== 1. 旧档兼容：删字段后 to_dict/from_dict 兜底 =====
saved = (gs.banquet, gs.medical, gs.market)
del gs.banquet, gs.medical, gs.market
d = gs.to_dict()
ok("to_dict 缺字段不崩", "banquet" in d and "medical" in d and "market" in d)
gs2 = A.GameState.from_save_data({"game_state": d})
ok("from_dict 兜底 dict", isinstance(gs2.banquet, dict) and isinstance(gs2.medical, dict) and isinstance(gs2.market, dict))
ok("medical 兜底 physician", isinstance(gs2.medical.get("physician"), dict) and gs2.medical["physician"].get("name"))
ok("market 兜底 stock", isinstance(gs2.market.get("stock"), list))

# ===== 2. 节令宴饮 =====
gs2.month, gs2.day, gs2.year = 1, 1, 1
msg = A.generate_banquet(gs2)
ok("正月生成上元灯会", msg and "上元" in msg, str(msg))
ok("pending 已挂起", gs2.banquet.get("pending") and gs2.banquet["pending"]["key"] == "shangyuan")
msg2 = A.generate_banquet(gs2)
ok("已有 pending 不重复生成", msg2 is None)
gs2.silver = 500
random.seed(7)
res_ok, res_msg, eff = A.resolve_banquet(gs2, 1)
ok("择对成功", res_ok, res_msg)
ok("pending 已清空", gs2.banquet.get("pending") is None)
ok("attended 记年份", gs2.banquet["attended"].get("shangyuan") == 1)
msg3 = A.generate_banquet(gs2)
ok("同年不重复办宴", msg3 is None)
gs2.year = 2
msg4 = A.generate_banquet(gs2)
ok("来年可再办", msg4 and "上元" in msg4)
# 银两不足
gs2.silver = 10
ok("献花灯缺银被拒", not A.resolve_banquet(gs2, 0)[0])
# 无效选择
ok("无效选择被拒", not A.resolve_banquet(gs2, 99)[0])
# 下旬不发请柬
gs2.month, gs2.day = 5, 15
gs2.banquet["pending"] = None
ok("中旬不发柬", A.generate_banquet(gs2) is None)

# ===== 3. 太医网络 =====
m = gs2.medical
gs2.silver = 500
ok("打点太医", A.medical_action(gs2, "gift")[0])
ok("太医好感上升", m["physician"]["favor"] > 20)
ok("请脉", A.medical_action(gs2, "consult")[0])
ok("无效动作被拒", not A.medical_action(gs2, "fly")[0])
# 病症结算
m["conditions"] = [{"name": "风寒", "months": 0}]
hp0 = gs2.attributes["健康"]
msgs = A.medical_period_tick(gs2)
ok("病症扣健康", gs2.attributes["健康"] < hp0 and any("风寒" in x for x in msgs))
ok("医治风寒", A.medical_action(gs2, "treat", "风寒")[0])
ok("病症已清", not m["conditions"])
# 孕期胎象：安胎药优先消耗
gs2.is_pregnant = True
m["herbs"]["安胎药"] = 1
random.seed(3)
hit = False
for _ in range(40):
    gs2.is_pregnant = True
    m["herbs"]["安胎药"] = 1
    msgs = A.medical_period_tick(gs2)
    if any("安胎药" in x for x in msgs):
        hit = True
        break
ok("胎象不稳自动服安胎药", hit)
ok("安胎药已消耗", int(m["herbs"].get("安胎药", 0)) == 0)
gs2.is_pregnant = False
# 毒检：解毒散优先
mit, herb, txt = A.poison_screen(gs2)
ok("无药无好感不拦截", not mit or herb is False)
m["herbs"]["解毒散"] = 1
mit, herb, txt = A.poison_screen(gs2)
ok("解毒散自动化解", mit and herb and int(m["herbs"].get("解毒散", 0)) == 0)
m["herbs"].pop("解毒散", None)
m["physician"]["favor"] = 80
hit2 = any(A.poison_screen(gs2)[0] for _ in range(30))
ok("高好感太医可拦截", hit2)

# ===== 4. 宫廷市集 =====
A.market_refresh(gs2, force=True)
stock = A.market_payload(gs2)["stock"]
ok("货架 5-6 件", 5 <= len(stock) <= 6, str(len(stock)))
gs2.silver = 1000
npc = [n for n in gs2.npcs if n != "太后"][0]
gift = next((s for s in stock if s["kind"] == "gift"), None)
if gift:
    rel0 = gs2.relationships.get(npc, {}).get("好感", 0)
    ok("买礼物送妃", A.market_buy(gs2, gift["id"], npc)[0])
    ok("好感上升", gs2.relationships[npc]["好感"] > rel0)
    ok("无受赠人被拒", not A.market_buy(gs2, gift["id"], "")[0])
attr_item = next((s for s in stock if s["kind"] == "attr"), None)
if attr_item:
    ok("买属性货", A.market_buy(gs2, attr_item["id"])[0])
herb_item = next((s for s in stock if s["kind"] == "herb"), None)
if herb_item:
    ok("买药材入药匣", A.market_buy(gs2, herb_item["id"])[0])
ok("未上架被拒", not A.market_buy(gs2, "不存在的货")[0])
gs2.silver = 5
exp = next((s for s in A.market_payload(gs2)["stock"] if s["stock"] > 0), None)
if exp:
    ok("银两不足被拒", not A.market_buy(gs2, exp["id"])[0])
# 月度刷新幂等
mk = gs2.market
A.market_refresh(gs2)
ok("同月不重复刷新", mk.get("refreshed") == f"{gs2.year}-{gs2.month}")

# ===== 5. API 路由 =====
A.sessions[pid] = gs2
gs2.silver = 1000
for path in [f"/api/banquet/overview?player_id={pid}", f"/api/medical/overview?player_id={pid}", f"/api/market/overview?player_id={pid}"]:
    rr = client.get(path)
    ok(f"GET {path.split('?')[0]}", rr.status_code == 200)
gs2.banquet["pending"] = None
rr = client.post('/api/banquet/respond', json={"player_id": pid, "choice_index": 0})
ok("无 pending 择宴 400", rr.status_code == 400)
gs2.month, gs2.day = 7, 5
gs2.banquet["attended"] = {}
A.generate_banquet(gs2)
rr = client.post('/api/banquet/respond', json={"player_id": pid, "choice_index": 2})
ok("择宴 200", rr.status_code == 200, rr.get_json())
rr = client.post('/api/medical/action', json={"player_id": pid, "action": "consult"})
ok("请脉 200", rr.status_code == 200)
rr = client.post('/api/market/buy', json={"player_id": pid, "item_id": "pill_yangshen"})
ok("市集购买路由", rr.status_code in (200, 400))
rr = client.get(f"/api/state/{pid}")
sd = rr.get_json()
ok("state 含三新键", all(k in sd for k in ("banquet", "medical", "market")))
rr = client.post('/api/next_period', json={"player_id": pid})
nd = rr.get_json()
ok("next_period 含三新键", all(k in nd for k in ("banquet", "medical", "market")))

# ===== 6. 存档往返 =====
save = gs2.to_save_data()
gs3 = A.GameState.from_save_data(save)
ok("存档往返保宴饮记录", gs3.banquet.get("attended") == gs2.banquet.get("attended"))
ok("存档往返保太医好感", gs3.medical["physician"]["favor"] == gs2.medical["physician"]["favor"])
ok("存档往返保货架", len(gs3.market.get("stock", [])) == len(gs2.market.get("stock", [])))

print(f"\n新玩法验证: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
