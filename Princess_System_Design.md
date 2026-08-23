# 公主择婿与省亲系统 · 顶层设计文档

> 面向《凤仪天下》宫斗游戏（Flask 后端 + 单页 `index.html` 前端）。
> 本文档为"先设计后实现"的对齐稿，所有命名、数据结构、阈值均**贴合现有代码**（`models.py` / `app.py` / `family_backgrounds.py` / `index.html`），
> 便于确认后直接落地，不引入新框架与新依赖。

---

## 0. 现状盘点（本设计要接入的既有系统）

| 既有系统 | 位置 | 复用方式 |
| :--- | :--- | :--- |
| 位份体系 `RANK_ORDER` / `RANK_POWER` | `models.py:9`、`app.py:257` | 公主择婿门第与"体面度"复用同一套品级观 |
| 家世评分 `get_family_score`（官阶九品 1–9） | `family_backgrounds.py:294` | 候选驸马家世沿用 grade→score 映射，无需另造一套 |
| 官职生成 `_pick_official_title(grade)` | `family_backgrounds.py:46` | 直接用于生成"驸马之父官职" |
| 子嗣数据 `create_newborn_child` / `ensure_child_fields` | `app.py:2184 / 2059` | 公主本就是 `children` 里 `gender=="公主"` 的对象，扩展字段即可 |
| 成长节点 `process_child_milestones` | `app.py:2214` | 现止于 10 岁"及笄预备"，本设计从此续接婚嫁线 |
| 转旬驱动 `process_player_child_events` | `app.py:2291` | 择婿/省亲事件挂到既有转旬 tick 上，不新增循环 |
| 立储 `heir_status` / `is_child_heir` | `app.py:2455` | 公主婚事影响朝堂，与储位斗争联动 |
| 母家势力 `get_empress_family_power` | `app.py:400` | 驸马家族势力对"朝堂好感度"的加权公式参照此处写法 |
| 前端子嗣卡渲染 | `index.html:2388` 附近 | 公主卡追加"婚嫁状态/驸马/公主府"分区 |

> 设计原则：**公主对象仍是 `children` 中的一个 dict**，新增字段全部走 `ensure_child_fields` 的 `setdefault` 兼容旧存档；不改动存档顶层结构。

---

## 1. 世界观 / 品级框架（复用，不另起炉灶）

### 1.1 三大朝堂势力
沿用现有"母家/官阶"观念，抽象为三派，写入 `models.py` 常量：

```python
# models.py 拟新增
COURT_FACTIONS = {
    "文官党": {"desc": "科举清流、内阁六部，重礼法名分", "weight_attr": "才情"},
    "武官党": {"desc": "边镇将门、京营勋卫，重军功实力", "weight_attr": "威望"},
    "宗室党": {"desc": "亲王郡王、宗人府，重血脉正统", "weight_attr": "福运"},
}
```

### 1.2 家世 / 品级
不新增品级表，**候选驸马家世直接复用** `family_backgrounds.get_family_score` 与 `_pick_official_title(grade)`：

- grade 1–3 → 高门（score 70–95）：尚书、总督、大学士之子，或亲王世子。
- grade 4–6 → 中第（score 48–62）：知府、参将、郎中之子。
- grade 7–9 → 寒门（score 30–42）：知县、典史之子，或新科进士（寒门逆袭）。

### 1.3 公主"体面度"锚点
公主出嫁的"般配线"由**母亲位份**（`RANK_POWER`）+ **公主 `emperor_favor`** + **是否记名嫡出**共同决定，用于校验候选人门第是否"辱没天家"。

---

## 2. 公主数值系统（扩展现有 child 字段）

### 2.1 现有字段（保留）
`age / gender / emperor_favor / talent / wit / health / personality / title / affection / alive / uid`。

### 2.2 新增字段（经 `ensure_child_fields` 兼容旧档）

```python
# app.py ensure_child_fields 拟新增（仅对 gender=="公主" 生效）
child.setdefault("marriage_status", "未议")   # 未议→议婚中→已定→已嫁→省亲/和离/守寡
child.setdefault("suitors", [])               # 当前候选驸马列表（生成后缓存一旬）
child.setdefault("suitors_period", None)       # 候选人生成于哪一旬（防重复刷新）
child.setdefault("consort", None)              # 已定/已嫁后的驸马对象
child.setdefault("mansion", None)              # 公主府经营对象（出嫁后建立）
child.setdefault("marriage_events", [])        # 婚后事件流水
child.setdefault("preference", None)           # 公主本人隐藏好感倾向（情感锚点）
```

### 2.3 成长阶段（数值阈值，接 `process_child_milestones`）

| 阶段 | 年龄 | 触发 | 现状 | 本设计动作 |
| :--- | :--- | :--- | :--- | :--- |
| 及笄预备 | 10 | 已有 | 仅一句提示 | 追加：生成 `preference`（对某"性情/才学"类型的偏好） |
| 及笄 | 15 | **新增里程碑** | 无 | `marriage_status="未议"→可议婚`，解锁"择婿"入口 |
| 议婚 | 15+ | 玩家主动 | 无 | 生成 3–5 名候选驸马，进入相亲事件 |
| 出降 | 定亲后 1–3 旬 | 赐婚圣旨 | 无 | `marriage_status="已嫁"`，建立公主府 |
| 省亲 | 出嫁后每 6+ 旬 | 概率事件 | 无 | 触发回宫省亲叙事 |

> **公主本人意愿（情感锚点）**：`preference` 是隐藏字段。玩家为政治联姻挑了高门武将，但公主偏好"文雅清流"，则赐婚后公主 `affection`（对母亲的亲密）下降、`mood="委屈"`，省亲时反映为疏离——这是父母视角最动人的张力点。

---

## 3. 择婿候选人生成引擎

### 3.1 生成规则（`app.py` 新增 `generate_suitors(game_state, child)`）

复用 `_pick_player_grade` 思路，但门第权重随**公主体面度**上移：

```python
# 伪代码 · app.py 拟新增
def suitor_grade_weights(prestige_tier):
    # prestige_tier 由母亲位份 + 公主 emperor_favor 得出：低/中/高
    return {
        "low":  [1,2,4,8,14,18,20,16,10],   # 偏中下门第
        "mid":  [3,5,10,16,18,14,10,6,4],
        "high": [10,14,18,16,12,8,5,3,2],   # 偏高门
    }[prestige_tier]

def generate_suitors(game_state, child):
    tier = princess_prestige_tier(game_state, child)
    n = random.randint(3, 5)
    suitors = []
    for _ in range(n):
        grade = random.choices(GRADE_WEIGHTS, weights=suitor_grade_weights(tier))[0]
        faction = weighted_faction(grade)          # 高品偏文/宗室，将门偏武
        s = {
            "uid": next_suitor_uid(game_state),
            "name": male_name_for_faction(faction), # 复用 names.py
            "father_title": _pick_official_title(grade),
            "faction": faction,
            "family_score": GRADE_BASE_SCORE[grade], # 复用既有映射
            # 四维明属性
            "family": GRADE_BASE_SCORE[grade],       # 家世
            "talent": random.randint(30, 95),        # 才学
            "looks":  random.randint(30, 95),        # 样貌
            "ambition": random.randint(10, 95),      # 野心（部分隐藏）
            # 隐藏标签
            "hidden_tags": roll_hidden_tags(),       # 见 3.2
        }
        suitors.append(s)
    child["suitors"] = suitors
    child["suitors_period"] = game_state.rank_periods  # 或用日历旬标识
    return suitors
```

### 3.2 隐藏标签（`roll_hidden_tags`）
按概率赋予，考察不足时不显示，联姻后逐旬暴露：

| 标签 | 效果 | 暴露时机 |
| :--- | :--- | :--- |
| 外戚之相 | 驸马家族坐大，日后威胁储位 | 省亲/朝堂事件 |
| 栋梁之材 | 驸马升迁快，母家朝堂好感+ | 婚后 3 旬 |
| 金玉其外 | 样貌高但才学虚标，公主渐失望 | 婚后 6 旬 |
| 薄情寡义 | 婚后纳妾/冷落，公主 mood 恶化 | 公主府事件 |
| 深情专一 | 驸马不纳妾，公主 affection 持续+ | 省亲 |
| 潜龙在渊 | 野心隐藏值远高于明面 | 夺嫡关键期 |

### 3.3 决策权重（皇帝/皇后性格 → 看重维度）
复用 `emperor["favor_factors"]` 的写法，为"择婿决策"定义权重：

```python
SUITOR_DECISION_WEIGHTS = {
    "慈父型": {"talent": 0.35, "looks": 0.15, "family": 0.20, "preference_match": 0.30},
    "功利型": {"family": 0.45, "ambition": 0.25, "talent": 0.20, "preference_match": 0.10},
    "平衡型": {"family": 0.30, "talent": 0.30, "looks": 0.20, "preference_match": 0.20},
}
```
> 决策类型可由玩家在相亲事件中的历史选择动态推断，或由当前皇帝 `personality` 映射。

---

## 4. 父母视角决策（相亲事件 · 接入现有事件系统）

### 4.1 新增后端路由（对齐现有 `/api` 风格）

| 路由 | 方法 | 作用 |
| :--- | :--- | :--- |
| `/api/princess/suitors` | POST | 入参 `player_id, child_uid`；生成/返回候选人（每旬缓存） |
| `/api/princess/inspect` | POST | 考察某候选人，花行动点，揭示部分隐藏标签 |
| `/api/princess/betroth` | POST | 定亲，写 `consort`，`marriage_status="已定"` |
| `/api/princess/marry` | POST | 下赐婚圣旨，出降，建立公主府 |
| `/api/princess/mansion` | POST | 公主府经营操作（招门客/产业/为驸马谋官） |

> **校验**：均需 `child.gender=="公主"`、`age>=15`、`marriage_status` 合法流转；行动点/银两消耗参照 `ADOPT_IN_COST` 等既有常量风格新增 `BETROTH_COST` 等。

### 4.2 前端交互（`index.html` 公主卡扩展）
- 公主卡（现 `index.html:2388` 区）在 `age>=15` 时出现「议婚」按钮。
- 「相亲大会」弹层：横向列出候选人卡（家世/才学/样貌 明示，野心与隐藏标签打码），提供"细察（花行动点）/ 定亲 / 再议"。
- 「赐婚圣旨」用文言诏书样式文本呈现仪式感。
- 复用现有 `parseApiResponse` 统一错误呈现、按钮防抖与冷却禁用。

---

## 5. 婚后线：省亲 / 公主府

### 5.1 公主府数据结构

```python
child["mansion"] = {
    "level": 1,               # 府邸规模 1–5（复用重华宫扩建 1–5 的上限观）
    "income": 0,              # 每旬产业进项（银两）
    "retainers": [],          # 门客列表（可介入朝堂舆论）
    "reputation": 50,         # 公主府声望 0–100
    "consort_office": None,   # 为驸马谋得的官职（影响朝堂）
    "log": [],
}
```

### 5.2 省亲事件（转旬概率触发，挂 `process_player_child_events`）
- 触发条件：`marriage_status=="已嫁"` 且距上次省亲 ≥6 旬，`reputation` 越高概率越高。
- 事件内容由 `preference` 与驸马 `hidden_tags` 生成："幸福省亲/委屈省亲/带子省亲/求助省亲"四类基调。
- 结果反哺母亲属性：幸福→母亲 `宠爱/威望` 小增；委屈→母亲 `mood`、母女 `affection` 受损。

### 5.3 公主府随机事件
"驸马纳妾""产业增收""世子教育""驸马升迁/贬谪""为夫谋官牵动朝堂"等，接入既有事件流水 `marriage_events`。

---

## 6. 朝堂联动反馈

参照 `get_empress_family_power` 的加权写法，新增 `apply_marriage_court_effect`：

```python
# 伪代码
def apply_marriage_court_effect(game_state, child):
    consort = child["consort"]
    faction = consort["faction"]
    power = consort["family_score"]
    # 驸马家族越强，其所属派系"好感/权重"越高
    game_state.court_faction_favor[faction] += round(power / 20)
    # 若命中"外戚之相"且公主子嗣接近储位，触发储位危机事件
    if "外戚之相" in consort.get("hidden_tags", []) and has_heir_pressure(game_state):
        queue_court_event(game_state, "外戚坐大", ...)
```
> `court_faction_favor` 作为 `models.py` 新字段（dict，默认三派各 50），经 `to_dict/from_dict` 持久化并做旧档兼容。

---

## 7. 数据流与持久化（不破坏现有存档）

1. 所有新字段走 `ensure_child_fields` / `GameState.__init__` 的默认值，旧存档加载即补全。
2. `models.py` 的 `to_dict` / `from_dict` 增补 `court_faction_favor`（缺失时默认三派 50）。
3. 候选人 `suitors` 每旬缓存、转旬清理，避免存档膨胀。
4. `verify_*.py` 风格新增 `verify_princess_system.py`：覆盖候选人生成、门第校验、定亲/出降流转、省亲触发、朝堂联动、旧档兼容。

---

## 8. 实施顺序（确认后按此落地）

1. **数据层**：`models.py` 加 `COURT_FACTIONS/court_faction_favor` + `ensure_child_fields` 公主字段。
2. **生成引擎**：`generate_suitors` / `roll_hidden_tags` / `princess_prestige_tier`。
3. **决策与流转**：五条 `/api/princess/*` 路由 + 校验 + 消耗常量。
4. **婚后线**：省亲/公主府 tick，接 `process_player_child_events`。
5. **朝堂联动**：`apply_marriage_court_effect`。
6. **前端**：公主卡扩展 + 相亲大会弹层 + 赐婚诏书样式。
7. **验证**：`verify_princess_system.py`，跑通全部断言。

---

## 9. 待确认的设计取舍（实现前需你拍板）

1. **决策类型来源**：用当前皇帝 `personality` 直接映射，还是由玩家历史选择动态推断"慈父/功利型"？
2. **公主府深度**：只做"数值经营（产业/门客/声望）"，还是要做到"介入朝堂舆论、为驸马谋官"的完整势力玩法？
3. **和亲分支**：是否要为公主保留"番邦和亲"选项（现有 `和亲公主` 场景是玩家侧，公主侧和亲是新内容）？
4. **前端体量**：`index.html` 已较大，相亲大会是内嵌弹层，还是独立标签页？

> 确认以上四点后，我即按第 8 节顺序进入实现（B 阶段）。

