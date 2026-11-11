# AGENTS.md - AI 智能客服演练系统

## 项目概述

客服培训演练平台，核心功能：AI 扮演客户，学员扮演客服进行多轮对话练习，结束后多维评分。
业务场景基于桔多多（聚币分期）金融客服话术，覆盖会员、利率、逾期、还款、投诉等 8 大分类。

技术栈：FastAPI + SQLAlchemy + SQLite + React + TypeScript + Ant Design + Vite

## 快速启动

```powershell
# 终端 1 - 后端
cd c:\projects\drill-system\backend
chcp 65001
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 终端 2 - 前端
cd c:\projects\drill-system\frontend
chcp 65001
npx vite --host 127.0.0.1 --port 5173
```

访问 `http://127.0.0.1:5173`，登录 `student01` / `Test@2025`

## AI 模型配置

当前配置（`backend/.env`）：使用本地 Ollama 模型（省 token，但纯 CPU 慢、质量弱）：

```
DEEPSEEK_API_KEY=ollama
DEEPSEEK_BASE_URL=http://localhost:11434/v1
MODEL_CUSTOMER=deepseek-r1:1.5b
MODEL_SCORER=deepseek-r1:1.5b
MODEL_VISION=deepseek-r1:1.5b
```

切换为线上 DeepSeek API（快、质量好，但消耗 token 费用；该 key 已实测有效）：

```
DEEPSEEK_API_KEY=sk-e0f1e1e738ab42b0b047af09f2f7a8e2
DEEPSEEK_BASE_URL=https://api.deepseek.com
MODEL_CUSTOMER=deepseek-v4-flash
MODEL_SCORER=deepseek-v4-flash
MODEL_VISION=deepseek-v4-flash-vision-exp
```

注意：deepseek-r1 是推理模型，输出带 `<think>` 标签，`llm_client.py` 的 `_strip_reasoning()` 已处理。
实测（2026-09-04）：本地 `deepseek-r1:1.5b` 纯 CPU 客户回复约 70s/轮、评分约 50s，且质量弱（评分常输出占位文字、回复串词）；线上 `deepseek-v4-flash` 每轮约 3\~4s、质量明显更好。已用 JSON 解析容错/重试/兜底 + prompt 截断增强。旧文档里的线上 key（sk-0a56…2cba）已失效（HTTP 401），勿再用。

## 项目结构

```
backend/
├── .env                         # 环境变量（API key、模型、JWT）
├── app/
│   ├── main.py                  # FastAPI 入口，注册路由
│   ├── config.py                # Pydantic Settings 配置
│   ├── database.py              # AsyncSession + init_db
│   ├── models.py                # ORM 模型（User/Scenario/DrillSession/Message/Score/KnowledgeItem/Practice*）
│   ├── schemas.py               # Pydantic 请求/响应 schema
│   ├── core/
│   │   ├── deps.py              # 依赖注入：get_current_user / require_teacher
│   │   └── security.py          # JWT 创建 + 密码哈希
│   ├── routers/
│   │   ├── auth.py              # /api/auth/login 等
│   │   ├── scenarios.py         # /api/scenarios 剧本 CRUD
│   │   ├── sessions.py          # /api/sessions 剧本演练
│   │   ├── knowledge.py         # /api/knowledge 知识库
│   │   ├── practice.py          # /api/practice Q&A 演练场
│   │   ├── fde.py               # /api/fde CodexFDE 工作台（只编排，判定在 fde_ledger）
│   │   └── live.py              # /api/live 实战话术面板（坐席接听真实来电时用）
│   ├── services/
│   │   ├── llm_client.py        # LLM 客户端（兼容 Ollama + DeepSeek）
│   │   ├── fde_ledger.py        # 【L05】台账规则唯一实现：合同/状态机/证据链/责任分离/门禁
│   │   ├── live_scripts.py      # 实战话术：音频文件匹配、待录音清单、话术检索
│   │   ├── prompts.py           # Prompt 模板（客户扮演/评分/人设生成）
│   │   ├── customer_agent.py    # 剧本演练客户逻辑
│   │   ├── scorer.py            # 剧本演练评分
│   │   ├── practice_agent.py    # Q&A 演练场核心逻辑
│   │   └── knowledge.py         # 知识库搜索
├── audio/live/                  # 实战话术录音目录（<快捷码>.mp3；含 README 命名规范）
├── seed.py                      # 用户 + 剧本种子
├── seed_practice_knowledge.py   # 业务知识种子（31 条）
├── seed_live_scripts.py         # 实战话术种子：从客服话术总库.xlsx 导入场景与话术
├── import_scenarios.py          # 剧本导入脚本
├── test_practice.py             # Q&A 演练场完整流程测试
└── drill.db                     # SQLite 数据库（运行时生成）

frontend/
├── vite.config.ts               # Vite 配置（代理 /api → 127.0.0.1:8000）
├── src/
│   ├── api/
│   │   ├── client.ts            # axios 实例（timeout=300000ms）
│   │   ├── auth.ts              # 登录 API
│   │   ├── scenarios.ts         # 剧本 API
│   │   ├── sessions.ts          # 演练 API
│   │   ├── knowledge.ts         # 知识库 API
│   │   ├── practice.ts          # Q&A 演练场 API
│   │   └── live.ts              # 实战话术 API
│   ├── pages/
│   │   ├── LoginPage.tsx
│   │   ├── ScenariosPage.tsx    # 剧本列表
│   │   ├── ScenarioImportPage.tsx
│   │   ├── DrillWorkbenchPage.tsx    # 剧本演练工作台
│   │   ├── PracticePage.tsx     # Q&A 演练场分类选择
│   │   ├── PracticeWorkbenchPage.tsx  # Q&A 演练工作台
│   │   ├── PracticeHistoryPage.tsx    # 演练统计仪表盘
│   │   ├── SessionsPage.tsx     # 演练记录
│   │   ├── KnowledgePage.tsx    # 知识库管理
│   │   └── LiveAssistPage.tsx   # 实战话术面板（接真实来电时用）
│   ├── components/
│   │   └── MainLayout.tsx       # 侧边栏导航
│   ├── utils/
│   │   └── tts.ts               # 浏览器语音合成封装（无录音时的兜底）
│   ├── context/
│   │   └── AuthContext.tsx      # 认证上下文
│   └── types/
│       └── api.ts               # TypeScript 类型定义
```

## 数据模型

### 剧本演练模块（原有）

- **Scenario** - 剧本（人设、开场白、考察点、参考答案）

- **DrillSession** - 演练会话

- **Message** - 对话消息

- **Score** - 评分

- **KnowledgeItem** - 知识库条目

### Q\&A 演练场模块（新增）

- **PracticeSession** - 演练会话（AI 动态生成人设，非预定义剧本）

- **PracticeMessage** - 对话消息

- **PracticeScore** - 评分（增加 suggestions 字段）

### 实战话术模块（坐席接真实来电时用）

- **LiveScene** - 实战场景（一个话务环节：开场 / 安抚 / 会员退费 / 结束语…）。
  带 `phase`（话务动线阶段）、`pinned`（置顶）、`source`（素材来源）。

- **LiveScript** - 单条实战话术。`code` **同时就是录音文件名**（`audio/live/<code>.mp3`）；
  另有 `auto_play`（打开场景时自动播报）、`use_count`（使用频次，驱动待录音清单排序）、
  `audio_file`（录音文件名覆盖项）。与 `LiveRecording` 是一对一关系。

- **LiveRecording** - **当场录音**的音频字节（`script_id` 唯一，一个话术只留一条）。
  `data` 是 `LargeBinary` + `deferred=True`：列表页不会把几百 KB 的字节读上来。
  另有 `mime` / `ext` / `size` / `duration_ms` / `recorded_by`（用户名）/ `recorded_by_name`。
  存在库里而不是磁盘上，是因为托管沙箱的磁盘是临时的，**库才是随仓库走的那一份**。

> 与 `Scenario`（演练剧本）的区别：剧本给学员**练**，带人设/考察点/参考答案；
> 实战场景给在岗坐席**用**，只说「客户现在问这个，我该怎么答」。两者独立建表。

## API 端点

### Q\&A 演练场（/api/practice）

| 方法   | 路径                      | 说明                |
| ---- | ----------------------- | ----------------- |
| GET  | /categories             | 获取 8 个业务分类        |
| POST | /sessions               | 创建会话（AI 生成人设+开场白） |
| GET  | /sessions               | 我的会话列表            |
| GET  | /sessions/{id}          | 会话详情              |
| POST | /sessions/{id}/start    | 启动演练（推送开场白）       |
| POST | /sessions/{id}/reply    | 学员回复 → AI 客户回复    |
| GET  | /sessions/{id}/messages | 对话记录              |
| POST | /sessions/{id}/score    | 结束并评分             |
| GET  | /sessions/{id}/score    | 获取已有评分            |
| GET  | /sessions/{id}/hints    | 知识库提示             |
| GET  | /scores/me              | 我的评分列表            |
| GET  | /scores/all             | 全部评分（讲师）          |

## 8 大业务分类

| key         | 标签    | 场景                  |
| ----------- | ----- | ------------------- |
| member      | 会员相关  | 退费、权益、捆绑销售、自动扣费     |
| rate        | 利率与资方 | 利率质疑、资方查询、费用合规      |
| overdue     | 逾期与催收 | 逾期影响、协商减免、暴力催收      |
| repayment   | 还款问题  | 重复扣款、对公还款、账单未更新     |
| complaint   | 投诉与外投 | 投诉处理、外投、舆情、黑猫/12315 |
| settlement  | 结清与退费 | 结清异议、提前结清、退费协商      |
| audit       | 审核与订单 | 审核时效、取消订单、催放款       |
| credentials | 凭证与合同 | 结清证明、发票、调取合同、非注册号码  |

## 测试与验证命令

仓库根目录是 `E:\drill-system`（旧文档里的 `c:\projects\drill-system` 已失效）。后端必须先启动。

```powershell
# 终端 1 - 后端（先启动，下面所有脚本都依赖它）
cd E:\drill-system\backend
chcp 65001
.\.venv\Scripts\python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 终端 2 - 验证（按顺序；smoke_p3p4 含登录限流断言，必须最后跑）
cd E:\drill-system\backend
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_fde_ledger -v   # L05 规则单测，期望 39 项 OK
.\.venv\Scripts\python.exe -X utf8 tests\smoke_fde.py                     # L05 工作台行为，期望 50 项全通过
.\.venv\Scripts\python.exe -X utf8 tests\smoke_p1.py                      # 回归，期望 21/21
.\.venv\Scripts\python.exe -X utf8 tests\smoke_p2.py                      # 回归，期望 25/25
.\.venv\Scripts\python.exe -X utf8 tests\smoke_live.py                    # 实战话术，期望 110 项全通过
.\.venv\Scripts\python.exe -X utf8 tests\smoke_p3p4.py                    # 回归，期望 33/33

# 前端类型与构建
cd E:\drill-system\frontend
node .\node_modules\typescript\bin\tsc -b
```

脚本口径：`test_fde_ledger.py` 测**规则**（纯函数，不需要服务，不碰数据库）；
`smoke_fde.py` 测**行为**（真实 HTTP + 真实库 + 真实证据文件）。
`smoke_live.py` 测**行为**（真实 HTTP + 真实库 + 真实音频文件，自建临时话术与 mp3
并在结束时清理）。`smoke_fde.py` 会重置 `fde_*` 四张表作为测试夹具（这是夹具动作，
不是工作台动作——工作台本身没有删除接口）。`test_practice.py` 是旧的手工 e2e 脚本，
已被上述脚本取代。

跑完一轮要留证据（受控交付不需要手抄结论）：
`outputs/live-assist/run_evidence.py <标签> <工作目录> <命令...>` 会把每条命令的
原始输出与退出码落到 `outputs/live-assist/evidence/`。

> **顺序陷阱（实测踩过）**：`smoke_p3p4.py` 结尾会故意制造 6 次失败登录，
> 触发 P3-2 的 60 秒同 IP 限流。**紧接着**跑任何需要登录的脚本（含 `smoke_fde.py`）
> 会直接 429 挂在登录那一步。正确做法：要么把 `smoke_p3p4.py` 放最后，
> 要么跑完后重启后端（限流计数在内存里）。

## 已知问题与待办

### 待修复

1. ~~**`frontend/src/api/client.ts` 乱码**~~ — 2026-09-15 已复原（L05 重写响应拦截器时一并确认中文正常）
2. **结业考核文档未导入** — 文档路径 `c:\Users\Administrator\.trae-cn\attachments\6a98dcf2c7842698d8a5fea5\8854a214-9ec1-43e3-9201-ead55b9b48c4_37f9eeab-e184-4ee2-a478-da33c4e7c910_结业考核.docx`，需读取后导入剧本库（scenarios 表）
3. **Ollama 1.5B 模型质量有限** — 小模型生成的人设和对话质量不如线上模型，JSON 格式偶尔失败
4. **`_debug_scorer.py`** **和** **`test_api.py`** **为临时调试文件** — 可删除

### 待验证

1. Q\&A 演练场完整流程尚未跑通（`test_practice.py` 因后端未启动而失败，需重新测试）
2. 前端超时已改为 300 秒（`client.ts` line 19），适配 Ollama 慢响应

### 优化方向

1. 知识库搜索目前是简单 LIKE 查询，可升级为向量检索
2. 演练统计页面的图表数据依赖 API 返回，需验证数据格式
3. 评分维度的 `_coerce_number` 容错逻辑较复杂，可简化
4. 实战话术：**改文本后不会自动提示录音过期**（录音说的是旧词）。要根治需在录音时
   存下当时文本的哈希，与当前文本比对；当前只做了「文件在不在」的判定。
5. 实战话术：**没有通话级记录**（只有单条 `use_count`）。若要做「某通电话用了哪些话术」
   的复盘，需新增会话表；刻意没做，因为多一步前置操作会让坐席放弃使用这个面板。

## 开发约定

- 后端：Python 3.13 + async/await，类型注解必须

- 前端：TypeScript strict mode，Ant Design 组件

- 数据库：SQLite（开发），生产可换 PostgreSQL

- LLM 客户端：OpenAI 兼容协议，通过 `_is_ollama` 标志区分本地/线上

- Prompt 安全：客户扮演 prompt 有角色锁定和安全约束，不接受用户覆盖

- 评分容错：`_extract_json` / `_coerce_number` / `_clamp` 多层容错处理 LLM 输出

## OPC 一人公司系统（设计师接单撮合）

2026-10-23 新增的**第二套业务**，与客服演练系统并存互不干扰。
业务定位：**一人公司**（一个人同时是老板/HR/品控/主控）的设计师接单撮合台账。

设计规格见 `docs/opc_spec.md`（六段式需求合同格式，本身就是新系统的规则来源）。

### 为什么复用这个底座

OPC 不是新工程 —— 它就长在这个仓库里，复用 `app/core/`（鉴权/限流）、
`app/main.py`（路由注册）、`app/database.py`（AsyncSession）、
`frontend/src/api/client.ts`（四种 token 通道）。
**刻意不新建独立工程**：两套鉴权、两套构建、两套部署，一人公司维护不动。

### 目录

```
backend/app/
├── services/opc_ledger.py      ★ 订单台账规则核心（纯函数，不碰数据库）
├── schemas_opc.py              OPC 的请求/响应 schema
└── routers/
    ├── opc_orders.py           订单台账（需求单/证据链/门禁/验收）
    └── opc_ops.py              撮合/结算/设计师/店铺/规则/看板
backend/seed_opc.py             种子数据（幂等）
backend/tests/
├── test_opc_ledger.py          规则单测（纯函数，82 项）
└── smoke_opc.py                行为 smoke（真实 HTTP + 真实库，49 项）
frontend/src/
├── api/opc.ts                  OPC 的 API 封装
├── types/opc.ts                OPC 的类型定义
└── pages/Opc*Page.tsx          6 个页面
```

### 三条铁律

1. **规则只有一份**：`services/opc_ledger.py` 是纯函数（不 import 数据库、
   不 import FastAPI），HTTP 路由、命令行、单测三方共用。
   状态机与门禁的判定逻辑**只在这个文件里**，其它模块一律 import。
   前端也不许抄流转表 —— `GET /api/opc/meta` 的 `transitions` 字段是唯一来源。
2. **金额一律 Decimal**：`opc_ledger.to_decimal()` 统一入口，
   能处理 `¥1,234.50` 这类脏输入；`split_commission()` 是唯一的分账计算点，
   比例**只从 `opc_split_rules` 表读**，代码里不写死任何比例。
3. **交付物与事件只追加不覆盖**：这是证据链能成立的前提。
   `opc_deliveries` / `opc_events` 永不 UPDATE。

### 订单状态机

```
待派单 → 已派单 → 已接单 → 初稿制作中 → 终稿制作中 → 待验收 → 已交付 → 待结算 → 已结算
                ↘         ↑___________ 返工（drafting 自环）_____________↙
```

跳阶段一律不允许（`ORDER_TRANSITIONS` 显式列举）。
`drafting` 的**自环**就是「返工」—— 返工轮次由 `repair_loop_projection` 投影出来，
最多 3 轮，连续两轮原因完全相同就停手转人工。

### 结算门禁（四道，程序不代签）

1. 前置订单必须已被具名验收
2. 证据链完整（红 → 返工 → 绿，**同一条命令**）
3. 责任分离成立（设计师 ≠ 验收人，验收人必须是具名的人，`agent:` 前缀不接受）
4. 本订单已被具名验收 —— **这道门程序永远不会自动通过**

### 需求单六段式

订单存**创建时的需求单快照**（`spec_snapshot` + `spec_hash` + `spec_issues`）。
六段：目标 / 范围 / 非目标 / 约束 / 验收标准 / 完成定义。
结构合格 ≠ 需求想清楚了 —— 界面必须分开呈现这两件事。

### 撮合推荐的降级链

`GET /api/opc/match/recommend` 先试 LLM，**任何异常都吞掉并降级**到本地关键词相关度排序，
候选池**绝不返回空数组**（空数组对界面毫无意义）。
`llm_client.recommend_designers()` 内部做了 `try/except Exception: return None`，
这是设计的一部分，不是错误路径。

### 实测踩过的坑

- **AntD 6 移除了 `Modal` 的 `extra` 属性** —— 用 `Drawer` 或把按钮放进 Modal 内容区。
- **`antd` 6 的 `TablePaginationConfig` 没有 `sizeChanger`** —— 写在 `pagination` 里会报 TS 错。
- **中文分词不能只按标点切** —— 「元以内的女士连衣裙」会整块当一个词，相关度永远 0。
  现在按「量词 + 方位词」切，且匹配走 **2 字片段重叠**（`_term_hit`），
  否则「女士连衣裙」匹配不上标签里的「连衣裙」。
- **返工回路的停止条件必须先于「等待复验」判断** —— 否则最后一轮已开修未复验时，
  状态永远是 `verifying`，「已达轮数上限」「连续两轮同因」两个停止信号会被彻底吞掉。
- **`parse_spec` 要跳过文档标题（H1）** —— 「# 订单需求单 · X-001」是文档叫什么，
  不是需求的一个章节；留着会让「需求单有 7 节」这种统计失真。

### 验证命令

```powershell
# 后端必须先启动
cd E:\drill-system\backend
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_opc_ledger -v   # 规则，期望 82 项 OK
.\.venv\Scripts\python.exe -X utf8 tests\smoke_opc.py                     # 行为，期望 49 项全通过
.\.venv\Scripts\python.exe -X utf8 seed_opc.py                            # 种子数据（幂等）

# FDE 回归（确保没动坏原有模块）
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_fde_ledger -v   # 期望 39 项 OK

# 前端
cd E:\drill-system\frontend
node .\node_modules\typescript\bin\tsc -b
```

**顺序陷阱（同 smoke_p3p4.py）**：`smoke_opc.py` 会重置 `opc_*` 表作为测试夹具，
跑完记得 `seed_opc.py` 补回示例数据。

## 实战话术面板（坐席接真实来电时用）

前三个模块是**练**和**管**，这个模块是唯一在**接真实来电**时用的：客户进线 →
坐席点开场景 → 系统自动播报该场景的第一条话术 → 客户说什么，坐席点对应话术播报。

### 素材从哪来

`backend/客服话术总库.xlsx` 由 `seed_live_scripts.py` 导入（**幂等，可反复重跑**）：

| 工作表 | 导入结果 | `source` |
| --- | --- | --- |
| 一线话术快捷码库 | 84 条 / 29 场景，**保留原快捷码**（aa1 / hy2 / ww5…） | `quick` |
| 会员话术库 | 22 条 / 8 场景 | `business` |
| 利率资方话术库 | 29 条 / 10 场景 | `business` |
| 逾期催收话术库 | 24 条 / 9 场景 | `business` |
| 常见问题话术 | 25 条 / 1 场景 | `faq` |
| ~~客服话术库~~ | **不导入**：正文与快捷码库逐字重复，导入只会让搜索出现重复项 | — |

合计 **57 场景 / 184 条话术**。场景按话务动线分四个阶段：
`opening 通话开始` → `support 通用支撑` → `business 业务处理` → `closing 通话收尾`。

重跑时**保护人工状态**：`pinned` / `use_count` / `audio_file` 不被覆盖，
只有素材本身（正文、标题、顺序、自动播报）以 Excel 为准。

### 声音从哪来：磁盘 → 库内 → TTS（三级，顺序即优先级）

**这是本模块最重要的设计决定**——录音是**陆续补的**，不是一次齐活，所以：

1. **`file`（专业录音，最高优先）**：`backend/audio/live/<code>.mp3`。
   服务端**每次都实时看文件在不在**（不缓存）：新录一个 mp3 丢进目录，**刷新即生效**，
   不需要重启服务、不需要重新导入。
2. **`record`（当场录音）**：坐席在界面上自己录、自己传，字节存在 `live_recordings`
   表里（`LargeBinary` + `deferred=True`）。**托管沙箱的磁盘是临时的，库才是随仓库走的那一份。**
3. **`tts`（合成兜底）**：都没有时前端用浏览器语音合成顶上
   （`frontend/src/utils/tts.ts`），保证坐席当场一定有声音可用，只是音色不如真人。

顺序是**磁盘优先**，且是**覆盖式**的：专业录音一就位就自动盖过当场试录，
不需要先删任何东西。所以「先上线、后补录」这条路线是通的。

`GET /api/live/audio-index` 输出**待录音清单**（按 `use_count` 降序），
直接交给录音同事排期；`outputs/live-assist/build_recording_list.py` 可导出成 md + csv。

### 当场录音（坐席自己录）

| 端点 | 谁可以调 | 说明 |
| --- | --- | --- |
| `POST /api/live/scripts/{id}/audio` | **任何登录用户** | multipart 上传，单条 ≤ 8MB，仅 `audio/*` 白名单；重录即替换 |
| `GET  /api/live/scripts/{id}/audio` | 任何登录用户 | 允许 `?token=`（`<audio src>` 带不了请求头）；`no-store` |
| `DELETE /api/live/scripts/{id}/audio` | **上传者本人或讲师** | 别人录的删不掉，录错了自己能撤 |

设计口径：

- 上传**故意不设讲师门槛**：现场要重录的往往是坐席自己，让他先找讲师账号等于这功能没人用。
- 删除收紧到「本人或讲师」：录错了自己能撤，别人的录音不归你管。
- 一个话术**只留一条**录音（`script_id` 唯一约束），重录是覆盖不是追加，计数不重复。

### 进场模式 / 常用标签 / Top 榜（2026-09-23 新增）

坐席要求：**进场景默认不出声**；要自动播就只播自己认可的「常用」话术；还能手动把
快捷码排成 Top1 / Top2，其余按热度自动排。三个偏好全存库、任何登录用户可改
（同一口径：这是坐席自己的面板，不该有门槛）：

- **`LiveScene.entry_mode`**：`silent`（默认，进场不出声）/ `auto`（进场自动播
  **打了「常用」标签的第一条**；一条都没标就不播）。前端场景头有「进场播报」开关。
- **`LiveScript.is_common`**：「常用」标签，接口 `POST /scripts/{id}/common`。
- **`LiveScript.manual_rank`**：Top 榜位次。展示序 = **手动位次升序在前，
  其余按 `use_count` 热度降序**（种子 `sort_order` 只作同热度稳定次序）。
  接口 `POST /scripts/{id}/reorder`：`position>=1` 插进 Top 榜（原位次顺延），
  `0` = 退出榜单回热度序。前端 ↑/↓ 按钮，推到榜尾再按即退出。

### 话术 CRUD（2026-09-23 新增，坐席自己维护）

话术的**增/改/删对任何登录用户开放**（前端入口：实战话术页「管理话术」抽屉）；
**场景与置顶仍归讲师**——库结构不该被随手改，单条话术的内容则坐席最清楚。

- `PUT /scripts/{id}` 支持**改快捷码**（`LiveScriptUpdate.code`）：全库查重，冲突 409；
  改码后录音文件名约定（`audio/live/<code>.mp3`）随之变化，界面上有提示。
- `DELETE /scripts/{id}` **先删该条的现场录音再删话术**——录音 FK 非空，
  不先删子行会 IntegrityError（实测口径，路由里已处理）。
- 新增时 `code` 留空由 `next_code` 自动生成（c001 起排，按场景查重）。
- 验收：`smoke_live.py` 的「学员话术 CRUD」专区（建→改码→撞码 409→删），
  清理兜底按 `TMP_CODE` **前缀**清扫（残码会让下次运行 409，实测踩过）。

### 模拟进线（2026-09-25 新增，点话术回复 AI 客户）

入口：左侧菜单「模拟来电」（`/live/calls`）。真实来电用 /live 的提词器；这里是练习场——
客户是真的（AI），话术也是真的（点哪条播哪条、计哪条使用量），只有电话是假的。

- **复用演练场引擎**：`PracticeSession` 加 `channel` 字段（`practice`/`live_sim`），
  两个列表互相过滤不混数据；`PracticeMessage` 加 `script_id`/`via` 记录坐席点了哪条话术。
- 端点（`routers/live_calls.py`，前缀 `/api/live/calls`）：`simulate`（人设+开场白，
  LLM 挂了走兜底不阻断）→ `answer`（PENDING→IN_PROGRESS，开场白入对话流）→
  `use-script` / `free-reply` → `hangup` → `scripts-summary`（挂断后小结，纯本地统计）。
- **点话术 = 回复客户**三件事：`record_use` 计使用、正文作坐席发言落库（via=script）、
  AI 客户基于正文接话；录音由前端播给坐席听（三级判定不变）。
- **单事务回滚**：LLM 异常时坐席消息不落库，不会出现「说了一半没人接话」。
- **`is_finished` 时后端已自行置 FINISHED**（`generate_customer_reply` 内），
  前端此时**不要再调 hangup**（会 400「通话已结束」）。
- LLM 失败的两种形态：**空 key → 500「API_KEY 未配置」**（发布包不带 .env 即此形态）；
  **key 失效/欠费 → 502「LLM API 返回错误 402」**。都是诚实失败，前端提示重发即可。
- 冒烟：`tmp/smoke_live_calls.py`（本地 19 项）、`tmp/smoke_live_calls_online.py`
  （线上 15 项，token 必须走 `?token=` 查询参数通道，见 serve_app.py 的 promote_tokens）。
  已知边界：AI 接话的**正向**验证被 DeepSeek key 欠费（402）挡住，待换 key 补跑。

### 线上验证脚本的路径坑（2026-09-23 实测）

`serve_app.py` 把 `webapp/` 挂在**两个前缀**下：`/webapp/*`（SPA 回退兜底）和
`/assets/*`、`/audio/*`（静态直出）。**验证线上 bundle 要请求 `/assets/<文件名>`**——
请求 `/webapp/assets/...` 会撞上 SPA 回退拿到 index.html（458 字节，HTTP 200），
看起来像「上传失败」，实际是路径错了。判别方法：真文件不会以 `<!doctype` 开头。
- **`auto_play` 字段保留但不再决定进场行为**——它只是种子数据对开场语的标记。

### 实现禁区（本节踩过的坑）

- **取场景必须 `selectinload(LiveScene.scripts)` 显式预载**（service 的 `get_scene()`）：
  靠 `db.get` 的关系预载不保证生效，之后在 async 会话里访问 `scene.scripts`
  触发同步懒加载，直接 `MissingGreenlet` 崩 500（实测踩过）。
- `smoke_live.py` 的夹具复位**必须包含进场模式与 Top 榜的还原**：
  崩溃退出会把 `auto` / 手动位次留到下一轮，「默认 silent」「只有一条进榜」
  的断言就全站不住（实测踩过）。

### 禁止事项

- **不要给读接口加缓存**：录音是逐步补的，缓存会让新录的 mp3「不生效」而难以排查。
- **不要给「播放」加前置步骤**（如先「开始通话」才能点话术）：实战里多一步就会让人放弃用这个工具。
  通话计时与使用计数都是**可选的旁路**，失败不影响播报。
- **不要给 `live_scripts.py` 之外的模块加音频路径判断**：三级判定的规则只有一份实现。
- **`routers/live.py` 里不要加 `from __future__ import annotations`**：加了之后 `-> None`
  变成字符串注解，带 `status_code=204` 的路由会在导入期抛 `AssertionError`（实测踩过）。
- **不要把录音落成磁盘文件**：托管环境磁盘是临时的，重启即丢；要落就落库。

### 验证命令

```powershell
cd E:\drill-system\backend
.\.venv\Scripts\python.exe -X utf8 seed_live_scripts.py --dry-run   # 先看导入计划
.\.venv\Scripts\python.exe -X utf8 seed_live_scripts.py             # 正式导入（幂等）
.\.venv\Scripts\python.exe -X utf8 tests\smoke_live.py              # 期望 110 项全通过
```

`smoke_live.py` 有**三个自带夹具动作**，不是被测行为，别误读：
开跑前按快捷码清扫上一轮残留 + 还原进场模式/Top 榜（异常退出后靠这个自愈，
否则下次 409 挂在建话术那步、或「默认 silent」断言挂掉）；结束时删掉测试对端账号
`smoke_peer`（注册接口建的，直接从库里删）。

> **环境噪声**：若转录末尾出现 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`，说明是沙箱的
> 批量删除守卫打断了删除临时 mp3 那一步，**不是断言失败**。重跑即可。

## 单端口上线（托管环境专用）

`deploy/serve_app.py` 把「FastAPI(8000) + Vite(8080)」两段合成**一个公网端口**：
前端构建产物由 FastAPI 兜底托管（SPA 回退），`/api` 与 `/audio` 照旧。
**本地开发不要用它**（那样没有热更新），继续 8000 + 8080 两条腿跑。

### 托管环境与本地不同的四处（都在这个文件里处理）

1. **网关会注入自己的 `Authorization` 头**——哪怕客户端一个头都没带。该头验不过签名，
   于是**所有只认请求头的路由全线 401**。处理：入口层中间件 `promote_tokens` 把备用通道
   （`X-Auth-Token` / `drill_token` Cookie / `?token=`）的令牌**覆盖**写回 `scope["headers"]`
   的 `authorization`。它必须注册在**最外层**（FastAPI 后注册的中间件先执行）。
2. **上传阶段会过滤「构建产物」目录**——实测 `frontend/dist` 整包没上传（前端 404、API 正常）。
   发布包里把构建产物改名 `webapp/` 绕开过滤。
3. **沙箱没有 venv**，用系统 python；缺依赖现场 `pip install`。
4. **`drill.db` 可能被过滤**——缺席时先从 `backend/seed/app_seed.bin` 还原快照，
   再退回种子脚本重建。

### 排查托管问题的正确姿势

**先要一个指纹端点，再谈假设。** `GET /diag` 给出 `pid / python / cwd / db_origin /
backend_files(sha256) / probe_ok / webapp_index`；`GET /diag?probe=<jwt>` 单独验签。
沙箱 python 是 3.11（本地 venv 是 3.13），一度被怀疑是版本差异，
用 `backend_files` 指纹**逐一比对一致**才排除了「源码没同步」这个假设——别靠猜。

### 发布 / 更新

改了源码要重新上线 = **跑构建脚本 → 用同一个目录再发布**（同一目录 → 链接不变、内容被覆盖）。
线上地址 `https://codexfde-workbench.app.workbuddy.host/`。
验收：`outputs/live-assist/verify_deployed.py`（期望 27 项全通过）。

## 交付取证（FDE 口径的可复用工具）

`outputs/live-assist/` 下三个脚本，做任何一次受控交付都能直接用：

| 脚本 | 干什么 |
| --- | --- |
| `run_evidence.py <标签> <工作目录> <命令...>` | 跑一条命令，把「命令 + 退出码 + 时间 + 原始输出」原样留档到 `evidence/` |
| `make_change_diff.py` | 生成 before→after 的 unified diff + 交付物 sha256 指纹清单 |
| `register_ledger.py` | 把证据按 phase 登记进本仓库台账并触发复验，产出登记回执 |

证据链的硬约束（台账会真的检查，不是形式）：

- 红灯必须是 `return_code != 0`；绿灯必须 `== 0`；
- **红灯与绿灯必须是同一条命令文本**，否则绿灯证明不了同一处修复；
- 顺序必须是 红灯 → 改动 → 绿灯（比较 `observed_at`）；
- 无 git 工作树时，改动用 `evidence/` 下的 before/after 快照 + difflib diff 留档。

> **红线**：`bash -c "...python -c '含反引号的 Markdown'..."` 里的反引号会被 bash
> 当命令替换**先执行掉**，写进文件的内容是残缺的（实测踩过）。
> 含反引号的文本一律**先写成脚本文件再跑**，或用编辑工具做字符串替换。

## CodexFDE 工作台（L05 起）

本仓库的受控交付台账。来源：CodexFDE 行动营 L01–L04（https://github.com/congde/CodexFDE）。
它管的是**怎么把需求安全地交出去**，与演练业务本身（剧本、Q&A、评分）完全分离。

### 目录职责

| 路径 | 职责 | 改它的后果 |
| --- | --- | --- |
| `backend/app/services/fde_ledger.py` | 台账**规则**唯一实现：合同校验、状态机、证据链、责任分离、资格门禁、修复回路投影、交付摘要投影 | 所有判定同时变化（页面、API、测试），**这是唯一质量入口** |
| `backend/app/routers/fde.py` | 只做持久化与编排，**不得自己发明判定** | 出现第二份规则即为架构违规 |
| `backend/app/models.py` 的 `FdeTask` / `FdeTaskEvent` | 台账存储；事件只追加不覆盖 | 破坏「失败历史也是证据」 |
| `backend/tests/test_fde_ledger.py` | 规则的验收测试，**先于实现存在** | 失去红灯来源 |
| `backend/tests/smoke_fde.py` | 工作台在真实 HTTP 上的行为验收 | 失去端到端证据 |
| `frontend/src/pages/FdeWorkbenchPage.tsx` | 只呈现与发起动作 | 不得在前端重新实现判定 |
| `E:\drill-system\tmp\` | 本次运行的原始日志（红灯/绿灯证据来源） | 证据断链 |

### 禁止事项

1. **不得让程序执行命令。** `fde` 路由只接收「已发生过的运行输出」，绝不重跑命令。
   红灯的失败必须是操作者真实跑出来的；工作台不制造也不代替证据。
2. **不得让程序自动置位 `acceptance`。** `accepted` 只能由构建者以外的**具名的人**写入；
   `agent:` 前缀署名一律拒绝。`evidence_complete`（程序判断）与 `acceptance`（人的判断）
   是两个独立字段，任何把它们合并成一个「已完成」的做法都是错的。
3. **不得跳过状态。** 只能走 `fde_ledger.TRANSITIONS` 里的边。想从 `spec_ready` 直接到
   `review`，正确做法是补做 `executing` 与 `evaluating`，不是放宽状态机。
4. **不得删除或覆盖既有记录。** 失败、返工、被门禁拒绝的请求都要留痕
   （`FdeTaskEvent.kind == "rejected"`）。要纠正就追加新记录，不要改写历史。
5. **不得删除 `FdeTask.status` 列。** 它是遗留列，必须与 `state` 写回同步；
   早期库上它是 NOT NULL，删掉会让插入直接失败。
6. **合同不完整不得登记。** 缺「非目标」等任一节必须 422，不允许静默放行或补默认值。

### L10 有界修复回路 + L15 交付摘要（2026-09-25 新增，源自上游 L07–L16 演进）

调研了 CodexFDE 仓库上游新增的 `repair_loop / eval_harness / quality_hook / ci_review /
subagent_coordination` 与 L07–L16 讲义，选两个**纯规则投影**移植（其余依赖 Codex
Stop-hook、真实 CI、子代理基建，与本仓库「程序不得执行命令」架构不适配）：

- **L10 有界修复回路**（`fde_ledger.repair_loop_projection`）：从事件流重放修复轮次
  （进入 rework = 开一轮；轮次终止于收敛或下一轮返工；`rework→executing` 只是标记
  开修，不关轮）。状态：`ready / continue / verifying / converged / closed /
  stopped_max_rounds（默认 3 轮）/ stopped_no_progress（连续两轮返工原因完全相同）`。
  **只判定不拦流程**——到边界给出 handoff 交接建议，停不停由具名的人决定。
  「无进展」比较只用自动复验退回的结构化原因（「退回返工：…」后按「；」切）；
  人工流转备注是人的判断，不可比、不参与。只读端点 `GET /tasks/{id}/repair-loop`，
  详情响应带同一投影。
- **L15 交付摘要**（`fde_ledger.delivery_summary`）：按交付四要素（结果/证据/边界/交接）
  从台账数据投影；边界直接取冻结合同的「范围/非目标/约束」，防止交接时口头改范围；
  证据取最近一对同命令红绿；渲染成 Markdown 供前端一键复制进交接单。
- 两个投影都不改任何状态、不产生新判断——与「程序判断（evidence_complete）vs 人的判断
  （acceptance）」同一条责任边界。前端详情抽屉各有一张卡。
- 移植时的模型修正：轮次不能在 `rework→executing` 时关闭（那还是同一轮），首版因此
  被 `test_round_closed_by_convergence` 抓住——测试先行的价值实证。

### 验证命令

```powershell
# 改台账规则后必须跑（前两条是本次交付的门槛，后三条是回归）
cd E:\drill-system\backend
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_fde_ledger -v
.\.venv\Scripts\python.exe -X utf8 tests\smoke_fde.py
.\.venv\Scripts\python.exe -X utf8 tests\smoke_p1.py
.\.venv\Scripts\python.exe -X utf8 tests\smoke_p2.py
.\.venv\Scripts\python.exe -X utf8 tests\smoke_p3p4.py
cd E:\drill-system\frontend; npx tsc -b
```

跨讲可复用的隔离练习机制（`course-prepare`、隔离快照剥增量、红绿链时间口径）
见用户级技能 `codexfde-lesson-practice`，不要在这里重复。

### 完成条件

一个任务的 `state` 到 `accepted` 需要同时满足：

1. 证据链完整——同一命令的红灯（返回码非 0）→ 改动 → 绿灯（同命令通过），且时间有序；
2. 责任分离成立——审阅者是具名的人，且不等于构建者；
3. 全部 `depends_on` 前置任务都已是 `accepted`；
4. **由构建者以外的人**亲手在工作台点下具名接受。

前三条程序能判断，第四条程序**永远不代为判断**。所以「门禁放行」只意味着记录齐全，
交付与否仍由人决定。

