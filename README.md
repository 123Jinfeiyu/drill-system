# drill-system · 设计师结算系统（源码包）

依据《数字结算系统操作指南》课件画面独立设计实现的一套**双角色**设计师结算系统，
与既有 OPC 一人公司系统同底座（FastAPI + SQLite + React）。

- 派单员在总后台录设计师、登订单、盯流程、给钱
- 设计师用手机号 + 密码登录结算端，看订单、一键结算、查收益

规则**只在**一份规则层里实现（`backend/app/services/settle_ledger.py`），页面上写的每条限制后端都会真的拦。

---

## 一、包内容

```
drill-system/
├── backend/                FastAPI 后端
│   ├── app/
│   │   ├── main.py             入口
│   │   ├── models.py           数据模型（含结算四表）
│   │   ├── database.py         连接与字段迁移
│   │   ├── core/
│   │   │   ├── designer_auth.py   设计师独立 JWT（scope=designer）
│   │   │   ├── timeutil.py        统一时间入口（支持 SETTLE_FAKE_TODAY）
│   │   │   └── ...
│   │   ├── routers/settle.py   派单员 + 设计师双角色接口
│   │   ├── services/
│   │   │   ├── settle_ledger.py  ★ 全部结算规则的唯一实现处
│   │   │   ├── settle_bridge.py  总系统只读导入桥接
│   │   │   └── trcipg_client.py  真实上游适配器
│   │   └── ...
│   ├── tests/                单元测试 + 冒烟测试
│   ├── requirements.txt
│   └── .env.example          复制为 .env 后按需填写
├── frontend/               React 19 + TS + AntD 6 + Vite
│   ├── src/pages/           派单员端 + 设计师端页面
│   ├── src/api/settle.ts    接口封装
│   ├── src/types/settle.ts  类型定义
│   └── package.json
├── docs/                   设计规格 + 交付说明（必读）
│   ├── 设计师结算系统设计规格.md
│   ├── 设计师结算系统交付说明.md
│   ├── OPC交付说明.md
│   └── opc_spec.md
├── deploy/serve_app.py     便捷启动脚本
└── AGENTS.md               项目开发约定
```

**未包含**：`node_modules/`、`.venv/`、`dist/`、日志、数据库、课件 PDF 原始资料。
体积 3.4 MB，可直接邮件传输。

---

## 二、怎么跑起来

### 2.1 后端

```bash
cd drill-system/backend

# 1) 建虚拟环境（Python 3.11+）
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2) 配置（按需改；不填也能跑本地演示）
copy .env.example .env

# 3) 启动
.venv\Scripts\python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2.2 前端

```bash
cd drill-system/frontend
npm install
npx vite --host 127.0.0.1 --port 5173
```

### 2.3 打开

| 入口 | 地址 | 用谁的号 |
| --- | --- | --- |
| 平台（派单员） | http://127.0.0.1:5173/ | 平台账号，如 `teacher01 / Test@2025` |
| 结算端（设计师） | http://127.0.0.1:5173/designer/login | 手机号 + 派单员设的初始密码 |

---

## 三、核心规则速查

| 课件要求 | 规则层函数 | 效果 |
| --- | --- | --- |
| 佣金比例 50%，最高 70% | `validate_commission_rate` | 越界直接拒绝，不产出金额 |
| 战区 / HR 必须留空 | `validate_designer` | 非空 → 422 并按字段列问题 |
| 订单编号初稿后补 | `check_transition` | 没编号进不了终稿阶段 |
| 两类截图缺一不可 | `check_transition` | 缺聊天记录 / 缺交付文件截图，分别提示 |
| 接单 60 天内有效 | `check_settle_eligibility` | 过期单进不了结算 |
| 每月 8-9 号窗口 | `settle_window` | 非窗口期发起 → 409 + 下次开放日期 |
| 结算必须设计师主动触发 | 派单员端无发起接口 | 派单员只能「标记已打款 + 填流水号」 |

订单状态机：

```
pending_design → drafting → finalizing → pending_audit
              → settleable → settling → settled
rejected → finalizing；canceled 为终止态
```

---

## 四、总系统互通（只读单向）

派单员端「结算系统 → 总系统互通」页，三步闭环：

1. **状态** —— 连通性检查 + 上游计数
2. **预览** —— 拉取待导入的设计师/订单，逐行校验并列出问题
3. **导入** —— 幂等落库（`upstream_id` 作跨系统幂等键，重复导入不会产生重复行）

设计原则：**总系统只读拉取，结算全部在本地完成，不回写生产系统。**

本地演示可开启假上游：`SETTLE_FAKE_UPSTREAM=1`。
真实上游凭据只从环境变量 `TRCIPG_USERNAME` / `TRCIPG_PASSWORD` 读取，不写进代码。

---

## 五、跑测试

```bash
cd drill-system/backend

# 单元测试（277 项）
.venv\Scripts\python.exe -m pytest tests/test_settle_ledger.py tests/test_settle_bridge.py \
    tests/test_opc_upstream.py tests/test_opc_ledger.py tests/test_fde_ledger.py -q

# 冒烟测试（74 + 43 项）
.venv\Scripts\python.exe -X utf8 tests/smoke_settle.py
.venv\Scripts\python.exe -X utf8 tests/smoke_settle_bridge.py
```

---

## 六、注意事项

- `.env` 未包含在包内（可能含真实凭据）。需要时用 `.env.example` 复制并填写。
- `drill.db` 未包含，数据库会在首次启动时自动建表。
- 若 `pip install` 卡住，换阿里云源：`https://mirrors.aliyun.com/pypi/simple/`
- 更多细节见 `docs/` 下两份中文文档。
