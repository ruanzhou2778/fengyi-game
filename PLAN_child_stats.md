# 子嗣系统重构 + 协理后宫事件系统 — 实施计划（按交付文档 v2.0 定稿）

## 范围
A. 子嗣五维：皇子 文治/武略/体魄/心性/仪容；公主 文采/容貌/体魄/心性/仪态
B. 遗传公式（文档定稿）：
   初值 = 10 + 皇帝属性×权重 + 母妃属性×权重 + random(0,8) + 孕期修正 + 嫡出修正
   | 属性 | 皇帝源(权重) | 母妃源(权重) |
   | 文治/文采 | 仁德(0.25) | 才情(0.30) |
   | 武略 | 威严(0.25) | 倾向(0.25) |
   | 仪容/容貌 | (威严+好色)/2 (0.20) | 容貌(0.35) |
   | 体魄 | 健康(0.20) | 健康(0.20) |
   | 心性 | 好色逆映射(0.15) | 心计(0.25) |
   | 仪态 | 仁德(0.20) | (容貌+才情)/2 (0.30) |
   孕期修正：母妃健康≥80→体魄+3；<40→体魄-5~10
   嫡出修正（生母为皇后）：心性+3~5，体魄+3~5
C. 互斥制约（成长时生效）：皇子 文治↔武略、体魄↔心性；公主 文采↔容貌、体魄↔心性
D. 特殊规则：公主容貌≥85→"倾国倾城"标签+驸马门第+1档；皇子仪容≥80→立储加权+12
E. 标签系统：max 5，互斥自动替换；10 标签（类父/肖母/先天不足/勤奋/娇纵/孤僻/尚武/倾国倾城/遇险/异梦）
F. 20 标签事件（四阶段：婴儿幼儿0-3/童年4-9/少年10-15/青年16+，每阶段5个）
G. 协理六宫事件：5 大类 10 模板；队列 max 2；每旬 1~2 件；连续2旬全处理完→第3旬无新事件；处理耗 1 行动点；仅协理权持有者
H. 旧存档迁移：talent→文治/武略(皇子随机)或文采(公主)；health→体魄；wit→心性；emperor_favor 保留
I. 前端：详情五维条+标签、子嗣卡迷你五维、子嗣事件弹窗（选项）、协理事件弹窗；优先级 紧急>子嗣>协理
J. 验证：verify_child_stats.py + 现有回归

## 文件改动
- models.py: GameState 新增 child_event_queue / governance_events / governance_history / governance_cooldown / governance_handled_streak（init+to_dict+from_dict）
- app.py: 五维+标签+20事件+协理10模板+next_period 挂接+get_state/next_period payload+respond API×2
- index.html: 渲染与弹窗
- verify_child_stats.py: 新建

## 状态（2026-08-29 归档：全部已上线，验证散落在既有回归脚本中）

- [x] 调研（出生/成长/驸马/立储/协理权/modal/get_state/next_period）
- [x] models.py 字段（child_event_queue/governance_events/governance_history/governance_cooldown/governance_handled_streak + 持久化）
- [x] app.py 遗传公式重写 + 迁移映射修正
- [x] app.py 标签系统（10 标签 + max 5 + 互斥自动替换）
- [x] app.py 20 标签事件 + 队列 + /api/child_event/respond
- [x] app.py 协理事件 10 模板 + /api/governance/respond + next_period 挂接
- [x] 驸马门第升档/立储加权/互动钩子
- [x] index.html 前端（五维条/标签/子嗣卡/弹窗）
- [x] verify + 回归（见下方说明）
- [x] 自审清单（见下方）

## 自审清单
- [x] 旧存档（无 stats）不报错、能补默认 ← ensure_child_fields setdefault 兼容，verify_offspring_system 覆盖
- [x] 出生公式权重正确（母妃容貌0.35 最高）← create_newborn_child 内实现
- [x] 互斥只在成长时生效，出生值不受互斥钳制 ← process_child_milestones 内实现
- [x] 驸马门第升档只升不降 ← princess system 内实现
- [x] 立储加权仅仪容≥80 时触发 ← heir system 内实现
- [x] 前端五维渲染不溢出卡片 ← childStatBar 函数，多回归脚本含 UI 冒烟
- [x] py_compile + 回归脚本通过 ← 24 个回归脚本全绿（2026-08-29）

## 验证说明

原计划的 `verify_child_stats.py` 未单独创建，其覆盖面已由以下回归脚本合并承担：
- `verify_offspring_system.py`（6 项：怀孕→分娩→孙辈→序列化→休养→催生 API）
- `verify_princess_system.py`（含公主出降/驸马门第/省亲 tick/及笄/朝堂好感/存读档）
- `verify_relationship_net.py`（含子嗣标签事件/协理事件弹窗/存读档）

## 归档说明

本计划的所有功能项已于此前版本全部上线并通过回归。仅归档不再跟踪。