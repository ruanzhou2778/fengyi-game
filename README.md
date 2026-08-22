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
  - 开设 / 扩建 / 拨银，收容宫中皇子公主、抚养、教育、收养归名。
  - 转旬自动结算用度、成长、事件日志；容量随等级提升。
  - API：`POST /api/chonghua/action`（found、upgrade、patronize、admit、tutor、adopt、release）；
    `GET /api/chonghua` 返回当前宫务与候选人列表。
  - UI：在「后宫」页展示宫务面板、候选收容、宫内子女选择、迁出按钮与日志。
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
- `GET /api/chonghua` — 查询重华宫状态、候选、子女
- `POST /api/chonghua/action` — `{player_id, action}`  
  支持：`found`、`upgrade`、`patronize`（amount）、`admit`（uid）、`tutor`（uid）、`adopt`（uid）、`release`（uid）

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
```

运行前可先编译检查：
```bash
python -m py_compile app.py models.py
```

---

## 游戏流程示例

1. **入宫**：从答应开始，日常行动 5-9 点/旬，经营属性、关系与银两。
2. **宫斗**：通过情报网发现流言与把柄，压制对手或发起宫斗，必要时触发罪状立案。
3. **重华宫**：积累银两开设重华宫，扩建提升容量，收容无依靠子嗣，抚养/教育提升才情，出养归名提升立嗣概率。
4. **陷害与洗白**：被栽赃后及时申辩压嫌疑、查证攒证据，证据足时翻案洗白；若嫌疑爆表则落罪降位。
5. **结局**：位份、子嗣、权势、名声共同决定结局走向。

---

## 变更日志

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
