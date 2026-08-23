# 凤仪·后宫模拟

**凤仪** 是一款基于 Flask + 前端单页应用的中文后宫策略模拟游戏。玩家扮演入宫新人，从答应起步，通过宫斗、宫务、子嗣培育与权势经营，争取最终登顶 / 被贬 / 多种结局。

> 核心玩法：位份晋升 · 子嗣经营 · 情报宫斗 · 重华宫收养 · 陷害与洗白
> 运行环境：Windows / macOS / Linux，Python 3.10+，Flask，现代浏览器。

---

## 功能亮点

- **身份与权势**
  - 皇后身份判定优化：`player_is_queen`、`get_queen_name(include_player)`，凤仪玺在身时玩家被正确识别为皇后。
  - 皇后权威周期、六宫协理、太后摄政、进阶朝议等权力线完整。
- **重华宫收养（Chonghua）**
  - 开设 / 扩建 / 拨用度，收容宫中皇子公主、延师授业、亲养归名、迁出。
  - 权限分级：皇后本人或协理六宫者可统管全宫皇嗣；贵妃及以上仅可查阅全宫名册；其余位份只见己出。
  - 转旬统一结算：学成出馆（≥15 岁）→ 幼嗣自动入馆（≤3 岁且无监护人）→ 用度支给 → 在馆教养收益 → 馆中轶事。
  - 用度经济：每名在馆皇嗣每旬 8 两，欠饷则膳食减半（健康/亲密下滑），连欠三旬有皇嗣被生母领回且威望-3。
  - 亲养他人皇嗣沿用宗人府规矩（位份、年龄、转继次数、皇子圣宠与皇帝恩准、生母意愿），仪银减半、遗孤再减半。
  - 授业每旬每人限一次，需满 4 岁，束脩随学级递增，优先动用宫中用度、不足再自付。
  - API：`POST /api/chonghua/action`（found、upgrade、patronize、admit、tutor、adopt、release）；
    `GET /api/chonghua` 为纯只读查询，返回宫务、在馆名册、候选与权限信息。
  - UI：「后宫」页内联可展开面板，显示等级/容量/用度收支/欠饷与权限态，按钮按权限与冷却分流禁用。
- **陷害 / 洗白（Frameup）**
  - 罪状类型 `{陷害, 告发, 造谣, 谣言, 打胎, 下毒, 巫蛊}` 自动立案，嫌疑累积、证据收集、翻案。
  - 申辩（才情/威望压嫌疑）、查证（心计/谋略花费 20 两）、翻案（证据达标花费 35 两）。
  - 落罪自动降位；被洗白后案件清除入日志。
  - API：`POST /api/frameup/action`（plead、investigate、appeal）；`GET /api/frameup` 返回案件摘要。
  - UI：在「宫斗」页罪状与洗白面板，案件选择、申辩/查证/翻案按钮与日志。
- **持久化**
  - `models.GameState.to_dict / from_dict` 支持 `chonghua`、`frameups` 字段，新旧存档兼容。
  - 存档/读档 `/api/save`、`/api/load` 支持客户端校验。
- **宫斗情报网**
  - 转旬时若无流言到期/把柄触发，保证至少一条情报状态回执，避免静默回合。
- **结局系统**
  - 多条结局分支：登后、太后摄政、白绫、宫变、流放等，支持存档后恢复结局状态。
- **前端体验**
  - 弹窗取消键 `modalCancelBtn`，`openModal` 支持 `dismissOnly` 模式。
  - `updateUI` 统一挂载 `chonghua`、`frameups`、`chonghua_events`，页面切换自动刷新对应数据。
  - 迁出按钮与 `release` 动作完整闭环。

---

## 快速开始

### 1. 克隆仓库
```bash
git clone https://github.com/ruanzhou2778/fengyi-game.git
cd fengyi-game
```

### 2. 安装依赖
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. 配置环境
复制 `.env.example` 为 `.env`，按需填写：
```
FLASK_ENV=development
FLASK_APP=app.py
# 如需 AI 生成故事，可填 OpenAI 兼容接口
OPENAI_API_BASE=
OPENAI_API_KEY=
OPENAI_MODEL=
```

### 4. 启动后端
```bash
python app.py
```
默认监听 `http://127.0.0.1:5000`。

### 5. 打开前端
用现代浏览器打开 `index.html`（本地或通过简单静态服务器）。游戏首次进入自动创建会话，支持存档/读档。

---

## 主要 API

### 会话与状态
- `POST /api/start` — 新建会话
- `POST /api/state` — 获取当前状态（包含 `chonghua`、`frameups`、`chonghua_events`）
- `POST /api/next_period` — 转旬结算，触发宫斗/宫务/子嗣成长

### 重华宫
- `GET /api/chonghua` — 只读查询重华宫状态、在馆名册、候选与权限（不产生副作用）
- `POST /api/chonghua/action` — `{player_id, action}`  
  支持：`found`、`upgrade`、`patronize`（amount）、`admit`（uid）、`tutor`（uid）、`adopt`（uid）、`release`（uid）  
  权限：`found`/`upgrade` 与处置他人皇嗣须 `permission == 'full'`（皇后或协理六宫）；
  `permission == 'view'`（贵妃及以上）可查阅全宫名册、拨用度、处置己出皇嗣

### 陷害与洗白
- `GET /api/frameup` — 查询案件列表与玩家风险
- `POST /api/frameup/action` — `{player_id, action, case_id}`  
  支持：`plead`、`investigate`、`appeal`

### 存档
- `POST /api/save` — `{player_id, slot_name, client_id}`
- `POST /api/load` — `{player_id, slot_name, client_id}`

---

## 目录结构
```
fengyi-game/
├─ app.py                 # Flask 后端、路由、宫务结算
├─ models.py              # GameState 模型、持久化
├─ index.html             # 前端单页、UI 渲染
├─ chonghua.py            # 重华宫逻辑（已合并至 app/models，保留文档）
├─ frameup.py             # 陷害系统（已合并至 app/models，保留文档）
├─ scenarios.py           # 起始场景
├─ events.py              # 随机事件
├─ endings.py             # 结局判定
├─ palace_extra.py        # 宫斗、压力、决斗等额外机制
├─ saves/                 # 本地存档目录
├─ requirements.txt
├─ .env.example
└─ README.md
```

---

## 开发与测试

项目包含多条验证脚本，保持绿色：
```bash
python verify_empress_promotion.py
python verify_dowager_flow.py
python verify_endings.py
python verify_intrigue_system.py
python verify_intrigue_system_v2.py
python verify_chonghua_system.py
```

运行前可先编译检查：
```bash
python -m py_compile app.py models.py
```

---

## 游戏流程示例

1. **入宫**：从答应开始，日常行动 5-9 点/旬，经营属性、关系与银两。
2. **宫斗**：通过情报网发现流言与把柄，压制对手或发起宫斗，必要时触发罪状立案。
3. **重华宫**：皇后或协理六宫者开设重华宫，扩建提升容量、按旬拨足用度；幼嗣自动入馆，延师授业提升才情机敏，亲养归名提升立嗣概率，年满十五学成出馆。
4. **陷害与洗白**：被栽赃后及时申辩压嫌疑、查证攒证据，证据足时翻案洗白；若嫌疑爆表则落罪降位。
5. **结局**：位份、子嗣、权势、名声共同决定结局走向。

---

## 变更日志

- **v1.6 — 重华宫系统闭环**
  - 权限分级：`chonghua_permission()` 返回 `full`（皇后/协理六宫）/ `view`（贵妃及以上）/ `own`；
    贵妃、皇贵妃不再凭位份直接处置他人皇嗣，越权返回 403。
  - `GET /api/chonghua` 改为纯只读，自动收容等副作用移入转旬结算，反复查询不再改动存档。
  - 容量与名册按全宫统计（`chonghua_count_inside` / `chonghua_sync_roster`），
    修复低权限视角下容量可被绕过、名册被截断的问题。
  - 新增 `chonghua_period_tick()` 并挂入 `/api/next_period`：学成出馆、幼嗣自动入馆、
    用度支给与欠饷惩罚、在馆教养收益、馆中轶事，返回 `chonghua_events` 与 `chonghua` 快照。
  - 亲养他人皇嗣改为沿用过继规矩（位份/年龄/转继上限/皇子圣宠与恩准/生母意愿）并收取仪银，
    修复「亲养自己已在馆子嗣即可无成本反复 +10 威望」的刷分漏洞（己出改为 +3）。
  - 授业加入 4 岁门槛、每旬每人限一次、学级上限 10 与递增束脩，优先动用宫中用度。
  - 扩建加入 5 级上限；开设/扩建/亲养写入回忆与日志；终局后拒绝一切重华宫操作。
  - 前端：分离渲染与操作两个防抖标志（修复渲染在途时按钮无法点击），统一走
    `parseApiResponse` 呈现后端错误文案，卡片展示储君/学级/入馆时间与才情等提示，
    按钮按权限与冷却禁用并给出原因，面板显示用度收支与欠饷预警。
  - 新增 `verify_chonghua_system.py`（85 项断言，覆盖权限、容量、经济、转旬、持久化与旧存档兼容）。

- **v1.5**
  - 皇后身份判定新增 `include_player`，玩家持有凤仪玺时被正确识别。
  - 新增 `重华宫收养`：开设、扩建、拨银、收容、抚养、收养、迁出，完整持久化。
  - 新增 `陷害/洗白`：案件生命周期、申辩/查证/翻案、落罪降位、洗白。
  - 宫斗情报网转旬空回执兜底，避免静默。
  - UI 补全迁出按钮、案件选择、日志渲染，弹窗取消键修复。

---

## 许可

本项目仅供学习与娱乐使用。历史背景与人物均属虚构，如有雷同纯属巧合。

---

**作者**：ruanzhou2778  
**仓库**：https://github.com/ruanzhou2778/fengyi-game.git
