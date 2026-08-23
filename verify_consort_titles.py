# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import app
from models import GameState, Rank, is_four_consort_title, FOUR_CONSORT_TITLES

passed = failed = 0
def ck(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} -> {extra}")

print("=== 1. 位份阶梯（方案 B）===")
ck("RANK_ORDER 无独立四妃", all(x not in app.RANK_ORDER for x in ["淑妃","德妃","贤妃","宸妃"]), app.RANK_ORDER)
ck("妃后直接是贵妃", app.RANK_ORDER[app.RANK_ORDER.index("妃")+1] == "贵妃")
ck("RANK_LIMITS 贵妃=1或2", app.RANK_LIMITS.get("贵妃") in (1,2))
ck("四妃封号各限1", app.FOUR_CONSORT_TITLE_LIMIT == 1)

print("\n=== 2. 妃位内封号阶梯 get_promotion_step ===")
gs = GameState("t", Rank.妃)
gs.name = "测试"
gs.npcs = {}
gs.nobletitle = None
step = app.get_promotion_step(gs)
ck("无号妃→赐封号", step and step["type"] == "赐封号", step)

gs.nobletitle = "容"  # 普通封号
step = app.get_promotion_step(gs)
ck("普通封号妃→四妃封号", step and step["type"] == "四妃封号" and step["target"] in FOUR_CONSORT_TITLES, step)

gs.nobletitle = "淑"  # 四妃封号
step = app.get_promotion_step(gs)
ck("四妃封号妃→贵妃(位份)", step and step["type"] == "位份" and step["target"] == "贵妃", step)

print("\n=== 3. consort_stage 判定 ===")
gs.nobletitle = None
ck("stage none", app.consort_stage(gs) == "none")
gs.nobletitle = "容"
ck("stage ordinary", app.consort_stage(gs) == "ordinary")
gs.nobletitle = "德"
ck("stage four", app.consort_stage(gs) == "four")

print("\n=== 4. 四妃封号名额（各限1）===")
gs2 = GameState("t2", Rank.妃)
gs2.name = "玩家"
gs2.nobletitle = "淑"
gs2.npcs = {
    "甲": {"rank": "妃", "nobletitle": "德", "alive": True},
}
ck("淑已被玩家占→不可再用", not app.can_use_four_consort_title(gs2, "淑"))
ck("德已被NPC占→不可再用", not app.can_use_four_consort_title(gs2, "德"))
ck("贤仍空缺", app.can_use_four_consort_title(gs2, "贤"))
picked = app.pick_available_four_consort_title(gs2)
ck("pick 返回空缺(贤或宸)", picked in ("贤","宸"), picked)

print("\n=== 5. 门槛单调递增（阶梯自洽）===")
none_favor = app.CONSORT_TITLE_THRESHOLDS["none"]["宠爱"]
ord_favor = app.CONSORT_TITLE_THRESHOLDS["ordinary"]["宠爱"]
gui_favor = app.PROMOTION_THRESHOLDS["贵妃"]["宠爱"]
huang_favor = app.PROMOTION_THRESHOLDS["皇贵妃"]["宠爱"]
ck("无号<普通<妃(→四妃后→贵妃)<皇贵妃 单调",
   none_favor < ord_favor and ord_favor <= app.PROMOTION_THRESHOLDS["妃"]["宠爱"] <= gui_favor < huang_favor,
   (none_favor, ord_favor, app.PROMOTION_THRESHOLDS["妃"]["宠爱"], gui_favor, huang_favor))

print("\n=== 6. 完整晋升链模拟（属性拉满 + 免资历）===")
gs3 = GameState("t3", Rank.妃)
gs3.name = "晋升测试"
gs3.npcs = {}
gs3.nobletitle = None
gs3.children = [{"name":"皇子","gender":"皇子","alive":True}]  # 满足四妃/贵妃母凭子贵
chain = []
for _ in range(6):
    # 拉满属性 + 宠爱，免资历
    for k in ("宠爱","威望","才情","心计"):
        gs3.attributes[k] = 999
    gs3.rank_periods = 999
    gs3._promotion_done = False
    step = app.get_promotion_step(gs3)
    if not step:
        break
    msg = app.apply_promotion_step(gs3, step)
    chain.append(gs3.get_display_rank())
    if gs3.rank.name == "贵妃":
        break
print("  链条:", " → ".join(chain))
ck("链条含 容妃类普通封号", any(c.endswith("妃") and c not in ("妃","贵妃") and c[0] not in FOUR_CONSORT_TITLES for c in chain), chain)
ck("链条含四妃封号", any(c[0] in FOUR_CONSORT_TITLES for c in chain if c.endswith("妃")), chain)
ck("最终到贵妃", gs3.rank.name == "贵妃", gs3.rank.name)

print("\n=== 7. 降位对称 ===")
gs4 = GameState("t4", Rank.贵妃)
gs4.name = "降位测试"
gs4.npcs = {}
gs4.nobletitle = None
app.demote_player(gs4, "测试")
ck("贵妃降为四妃封号妃", gs4.rank.name == "妃" and is_four_consort_title(gs4.nobletitle), gs4.get_display_rank())
app.demote_player(gs4, "测试")
ck("四妃封号妃降为普通封号妃", gs4.rank.name == "妃" and gs4.nobletitle and not is_four_consort_title(gs4.nobletitle), gs4.get_display_rank())
app.demote_player(gs4, "测试")
ck("普通封号妃降为无号妃", gs4.rank.name == "妃" and not gs4.nobletitle, gs4.get_display_rank())
app.demote_player(gs4, "测试")
ck("无号妃降为嫔", gs4.rank.name == "嫔", gs4.get_display_rank())

print("\n=== 8. 旧存档迁移（四妃位份→妃+封号）===")
save = {"game_state": {"player_id":"old","rank":"德妃","name":"旧档","npcs":{
    "甲":{"rank":"淑妃","nobletitle":None,"alive":True,"attributes":{}},
    "乙":{"rank":"贤妃","alive":True,"attributes":{}},
}}}
gs5 = GameState.from_save_data(save)
ck("玩家 德妃→妃+德", gs5.rank.name == "妃" and gs5.nobletitle == "德", gs5.get_display_rank())
ck("NPC甲 淑妃→妃+淑", gs5.npcs["甲"]["rank"] == "妃" and gs5.npcs["甲"]["nobletitle"] == "淑")
ck("NPC乙 贤妃→妃+贤", gs5.npcs["乙"]["rank"] == "妃" and gs5.npcs["乙"]["nobletitle"] == "贤")

print("\n=== 9. NPC 初始生成无重复四妃/贵妃 ===")
from collections import Counter
dup = 0
for _ in range(500):
    npcs = app.generate_all_npcs(count=12)
    ranks = [v.get("rank") for v in npcs.values()]
    titles = [(v.get("rank"), v.get("nobletitle")) for v in npcs.values() if v.get("rank")=="妃"]
    c = Counter(ranks)
    if c.get("贵妃",0) > app.RANK_LIMITS.get("贵妃",2):
        dup += 1
    # 四妃封号重复检查
    ftitles = Counter(t for r,t in titles if is_four_consort_title(t))
    if any(v>1 for v in ftitles.values()):
        dup += 1
ck("500次生成无超额", dup == 0, dup)

print(f"\n通过 {passed}/{passed+failed}")
sys.exit(0 if failed == 0 else 1)
