# 一人公司 OPC 系统 · 设计规格

> 项目代号：**OPC-Solo**（One Person Company · 设计师接单撮合）
> 技术底座：`E:\drill-system`（CodexFDE 工作台）
> 本文档采用 FDE 的**六段式需求合同**格式（L03 规范），本身就是新系统的规则来源。

---

## 目标

给**一人公司**（一个人同时是老板、HR、品控、主控）提供一套「设计师接单撮合」的运营系统：
把散落在微信/表格/记忆里的**订单、设计师、交付物、佣金、结算**收敛到一个台账里，
让「每笔钱从哪来、到哪去、谁该拿多少、证据是什么」随时可查、可交接、可审计。

对齐两个既有内部系统的真实业务模型：

- **总后台**（`uni.trcipg.com.cn`）：`/roleapi/` 族接口，核心表 `order / store / user / company / instrument / task`
- **结算端**（`uni-c.trcipg.com.cn`）：`/settlement/` 族接口，设计师视角的结算单与提现

## 范围

### 1. 台账核心（复用 `fde_ledger.py` 的规则层）

| 能力 | 来源 | 在 OPC 中的映射 |
| --- | --- | --- |
| 六段式需求合同 | `fde_ledger.parse_spec` | **订单需求单**：目标/范围/非目标/约束/验收标准/完成定义 |
| 状态机 | `fde_ledger.TRANSITIONS` | **订单状态机**：待派单 → 已接单 → 初稿中 → 终稿中 → 待验收 → 已交付 → 待结算 → 已结算 |
| 证据链（红→改→绿） | `fde_ledger.check_evidence_chain` | **交付证据链**：初稿不合格(红) → 返工改动(改) → 终稿合格(绿)，同一验收命令 |
| 责任分离 | `fde_ledger.separation_issues` | **自审禁令**：设计师不能验收自己的稿；机器不能替人签收 |
| 资格门禁 | `fde_ledger.evaluate_gate` | **结算门禁**：证据链完整 + 已具名验收 + 前置依赖已接受，才允许进入结算 |
| 有界修复回路 | `fde_ledger.repair_loop_projection` | **返工轮次上限**：最多 3 轮，连续两轮同因不恶化则停手转人工 |
| 交付摘要 | `fde_ledger.delivery_summary` | **交付四要素**：结果 / 证据 / 边界 / 交接 |

> **规则只写一份**：`services/opc_ledger.py` 里的订单规则是纯函数，不碰数据库。
> HTTP 路由、命令行、单测三方共用，杜绝「网页端改了、批量端没改」。

### 2. 数据模型（新增 7 张表，前缀 `opc_`）

| 表 | 含义 | 关键字段 |
| --- | --- | --- |
| `opc_orders` | 订单 | `order_sn` `store_name` `order_grade` `order_type` `order_commission` `designer_name` `state` `acceptance` `spec_snapshot` `spec_hash` `spec_issues` `depends_on` |
| `opc_designers` | 设计师 | `name` `phone` `alipay_account` `alipay_name` `production_level` `war_zone` `commission_rate` `hr_id` `quality_control_id` `status` |
| `opc_stores` | 店铺 | `name` `url` `customer_name` `manager` `commission` `settlement_days` |
| `opc_deliveries` | 交付物 | `order_id` `phase`(red/diff/green) `command_text` `output` `output_hash` `return_code` `observed_at` |
| `opc_events` | 事件流 | `order_id` `kind` `from_state` `to_state` `actor` `detail` |
| `opc_settlements` | 结算单 | `order_id` `designer_name` `commission` `settlement_type` `settlement_days` `status` `settlement_time` `alipay_account` |
| `opc_split_rules` | 分账规则 | `scope`(designer/hr/qc/supervisor/control) `rate` `basis` `enabled` |

> 分账模型照搬总后台的真实结构：**设计师佣金 / HR 佣金 / 品控佣金 / 中控金额 / 奖金基数**，
> 但把「奖金基数」这类易错的手工计算改为**规则表 + 自动分账**，金额由系统算，不靠人记。

### 3. 业务模块（API 契约）

| 模块 | 前缀 | 端点 |
| --- | --- | --- |
| 订单台账 | `/api/opc/orders` | `GET/POST /orders`、`GET /orders/{id}`、`POST /orders/{id}/deliveries`、`POST /orders/{id}/evaluate`、`POST /orders/{id}/transition`、`POST /orders/{id}/accept`、`GET /orders/{id}/gate`、`GET /orders/{id}/repair-loop`、`GET /orders/{id}/summary`、`POST /orders/{id}/spec/validate`、`GET /orders/export` |
| 设计师 | `/api/opc/designers` | `GET/POST /designers`、`POST /designers/{id}/edit`、`POST /designers/{id}/del` |
| 店铺 | `/api/opc/stores` | `GET/POST /stores`、`POST /stores/{id}/edit`、`POST /stores/{id}/del` |
| 撮合 | `/api/opc/match` | `GET /match/board`（订单池 + 推荐设计师）、`POST /match/assign`（派单）、`POST /match/claim`（设计师接单） |
| 结算 | `/api/opc/settlements` | `GET /settlements`（待结算/已结算）、`POST /settlements/generate`（一键生成结算单）、`POST /settlements/{id}/pay`、`GET /settlements/summary` |
| 看板 | `/api/opc/dashboard` | `GET /dashboard`（订单漏斗、佣金总额、初稿/终稿在制数、待结算额） |
| 规则 | `/api/opc/rules` | `GET/POST /rules`（分账规则）、`GET /rules/preview`（试算某单分账） |

### 4. 前端页面（React + Ant Design，遵循 FDE 约定）

| 页面 | 路由 | 内容 |
| --- | --- | --- |
| 撮合看板 | `/opc` | 订单漏斗 + 在制订单 + 待结算 + AI 推荐设计师（用需求合同文本算相关度） |
| 订单池 | `/opc/orders` | 订单列表 + 状态流转 + 需求单编辑 + 详情抽屉（履约时间轴） |
| 订单详情 | `/opc/orders/:id` | 六段式合同编辑 + 证据链（红/改/绿）+ 门禁 + 返工回路 + 交付摘要 |
| 设计师 | `/opc/designers` | 设计师档案、佣金比例、战区/HR/品控归属、派单记录 |
| 店铺 | `/opc/stores` | 店铺档案、结算周期、中控额度 |
| 结算 | `/opc/settlements` | 待结算清单、一键生成结算单、结算状态机、提现信息 |
| 规则 | `/opc/rules` | 分账规则编辑 + 试算器 |

## 非目标

1. **不做移动端 App** —— OPC 的使用场景是「一个人在电脑前处理今天的事」，桌面 Web 足够。
2. **不做在线支付/提现** —— 结算端只做**记录与对账**，实际打款走支付宝手工操作，
   系统负责记录「已打款 + 流水号 + 截图证据」，不碰资金通道。
3. **不做 IM/消息推送** —— 微信/钉钉自己看，系统只在页面内提示。
4. **不替代总后台/结算端** —— 本系统是**一人公司自用的轻量台账**，
   不追求覆盖大平台的全部功能（权限体系、菜单管理、角色管理一律不做）。
5. **不做多租户** —— 只有一个人用，不做组织隔离。
6. **不实现抓取** —— 订单来源是人工录入或从既有系统导出 CSV 导入，
   不做爬虫（避免与平台规则冲突）。

## 约束

1. **技术底座必须是 FDE 工作台** —— 复用 `app/core/`（鉴权/限流）、`app/main.py`（注册路由）、
   `app/database.py`（AsyncSession）、`frontend/src/api/client.ts`（token 通道）。
   **不新建独立工程**，避免两套鉴权、两套构建、两套部署。
2. **后端**：Python 3.13 + async/await + 类型注解必须齐全；
   SQLAlchemy 2.0 async + SQLite（生产可换 PostgreSQL）。
3. **前端**：TypeScript strict mode + Ant Design 6 + Vite 8；
   状态与请求走 `api/client.ts` 统一封装，**不许在页面里裸写 axios**。
4. **规则层纯函数化** —— `services/opc_ledger.py` 不 import 数据库、不 import FastAPI。
5. **金额一律 Decimal** —— 佣金计算禁止浮点。展示层再转字符串。
6. **数据只增不改** —— 交付物与事件只追加，不覆盖；这是证据链的前提。
7. **金额口径唯一** —— 分账规则表是唯一真相来源，代码里不写死任何比例。
8. **LLM 可选** —— AI 推荐设计师走 FDE 已有的 `llm_client.py`（OpenAI 兼容）；
   没配 key 时降级为**关键词相关度排序**，功能不缺失。

## 验收标准

逐条可执行检查（命令 + 期望返回码）：

```powershell
# 1. 规则单测（纯函数，不依赖服务与数据库）
cd E:\drill-system\backend
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_opc_ledger -v
# 期望：全部 OK，不允许 skipped

# 2. 行为 smoke（真实 HTTP + 真实库 + 真实证据文件）
.\.venv\Scripts\python.exe -X utf8 tests\smoke_opc.py
# 期望：全部通过

# 3. FDE 回归（确保没动坏原有模块）
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_fde_ledger -v
.\.venv\Scripts\python.exe -X utf8 tests\smoke_fde.py

# 4. 前端类型与构建
cd E:\drill-system\frontend
node .\node_modules\typescript\bin\tsc -b
# 期望：退出码 0，无 TS 错误

# 5. 端到端手测
# 浏览器打开 http://127.0.0.1:5173/opc
# a. 创建订单 → 需求单六段式校验通过 → 派单 → 设计师接单
# b. 上传红灯证据（return_code != 0）→ 改动 → 绿灯（同一命令、返回码 0）
# c. 门禁：证据链不全时结算门禁必须 blocked，理由逐条列出
# d. 具名验收后结算门禁 allowed → 一键生成结算单 → 标记已打款
# e. 订单详情页能看到交付四要素摘要
```

## 完成定义

1. 上述 5 条验收全部通过，且 `smoke_opc.py` 与 `smoke_fde.py` 均无回归。
2. 前端 `tsc -b` 退出码 0，`vite build` 产物可加载。
3. **规则只有一份**：`grep -rn "TRANSITIONS\|evaluate_gate" backend/app/services/opc_ledger.py`
   能找到全部状态机与门禁逻辑，其它模块只 import 不重写。
4. **金额无浮点**：`grep -rn "float(" backend/app/services/opc_ledger.py` 结果为空。
5. **AI 降级可用**：删掉 API key 后，AI 推荐仍能返回按相关度排序的候选（不报错、不空数组）。
6. 交接文档写明：8 个页面清单、全部 API 端点、状态机图、分账口径、数据导入格式。
7. 关键决策写进 `backend/AGENTS.md` 与项目记忆（含踩坑）。
