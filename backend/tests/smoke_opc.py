"""OPC 一人公司系统 · 行为 smoke 测试。

测**行为**（真实 HTTP + 真实库），不是测规则（规则由 test_opc_ledger.py 覆盖）。
与 FDE 的 smoke_fde.py 同口径：跑之前会重置 opc_* 表作为测试夹具。

用法：
    python -X utf8 tests\\smoke_opc.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8000"
USER = "teacher01"
PWD = "Test@2025"

PASSED = 0
FAILED: list[str] = []
TOKEN = ""


def log(msg: str) -> None:
    print(msg, flush=True)


def check(name: str, cond: bool, detail: str = "") -> bool:
    global PASSED
    if cond:
        PASSED += 1
        log(f"  [OK]   {name}")
    else:
        FAILED.append(f"{name} — {detail}")
        log(f"  [FAIL] {name}  ({detail})")
    return bool(cond)


def api(method: str, path: str, body=None, expect: int | None = None):
    """带 token 的请求。返回 (status, parsed_json)。"""
    url = BASE + path
    data = None
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        status = e.code
    except Exception as e:
        return -1, {"error": str(e)}
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {"raw": raw[:400]}
    if expect is not None and status != expect:
        return status, parsed
    return status, parsed


SPEC_OK = """# 订单需求单 · OP-TEST-001

## 目标
为女装店铺做 5 张秋季新品主图，突出针织质感与显瘦版型。

## 范围
5 张 800×800 主图，含 1 张场景图与 4 张白底图；统一秋季暖色调。

## 非目标
不做详情页、不做视频、不改模特图。

## 约束
交付时间 2026-11-05 前；修改不超过 2 轮；素材版权客户提供。

## 验收标准
- 首图尺寸 800×800，主体占比不低于 60%
- 5 张风格统一，色温偏差不超过 200K
- 白底图背景纯白 RGB(255,255,255)

## 完成定义
5 张图全部交付并经客户确认，结算单生成。
"""

SPEC_BAD = """# 订单需求单 · OP-TEST-BAD

## 目标
做几张图。

## 范围
若干。
"""


def reset_fixtures() -> None:
    """重置 opc_* 表（夹具动作，不是业务动作）。"""
    import asyncio

    from app.database import AsyncSessionLocal
    from app.models import (OpcDelivery, OpcDesigner, OpcEvent, OpcOrder,
                             OpcSettlement, OpcSplitRule, OpcStore)

    async def _reset():
        async with AsyncSessionLocal() as db:
            for model in (OpcDelivery, OpcEvent, OpcSettlement, OpcOrder,
                          OpcDesigner, OpcStore, OpcSplitRule):
                await db.execute(model.__table__.delete())
            await db.commit()

    asyncio.run(_reset())
    log("  夹具：opc_* 表已清空")


def seed_minimum() -> tuple[str, str]:
    """放一条最小可用的规则/设计师/店铺，返回它们的 id。"""
    status, rules = api("POST", "/api/opc/rules",
                        {"scope": "designer", "rate": "0.70", "basis": "total"}, 201)
    designer_id = ""
    store_id = ""
    status, ds = api("POST", "/api/opc/designers",
                      {"name": "测试设计师", "design_tags": "女装 连衣裙 主图"}, 201)
    if isinstance(ds, dict):
        designer_id = ds.get("id", "")
    status, ss = api("POST", "/api/opc/stores", {"name": "测试店铺"}, 201)
    if isinstance(ss, dict):
        store_id = ss.get("id", "")
    return designer_id, store_id


def main() -> int:
    global TOKEN
    log("=" * 70)
    log("OPC 一人公司系统 · 行为 smoke")
    log("=" * 70)

    # ---- 登录 ----
    status, data = api("POST", "/api/auth/login",
                       {"username": USER, "password": PWD})
    if status != 200:
        log(f"!! 登录失败：{status} {data}")
        return 1
    TOKEN = data.get("access_token", "")
    check("登录拿到 token", len(TOKEN) > 20, f"len={len(TOKEN)}")

    # ---- 夹具 ----
    reset_fixtures()
    designer_id, store_id = seed_minimum()

    # ================= 需求单 =================
    log("")
    log("── 需求单校验 ──")
    status, data = api("POST", "/api/opc/orders/specs/validate",
                       {"spec_snapshot": SPEC_OK})
    check("六段式齐全的需求单校验通过",
          status == 200 and data.get("ok") is True and not data.get("issues"),
          str(data)[:120])

    status, data = api("POST", "/api/opc/orders/specs/validate",
                       {"spec_snapshot": SPEC_BAD})
    issues = data.get("issues", []) if isinstance(data, dict) else []
    check("残缺需求单被拦下且逐条列出问题",
          status == 200 and data.get("ok") is False and len(issues) >= 3,
          f"issues={issues}")

    status, data = api("POST", "/api/opc/orders/specs/validate",
                       {"spec_snapshot": ""})
    check("空需求单被判不合格",
          status == 200 and data.get("ok") is False,
          str(data)[:100])

    # ================= 订单生命周期 =================
    log("")
    log("── 订单生命周期 ──")
    status, order = api("POST", "/api/opc/orders", {
        "order_sn": "OP-TEST-001",
        "title": "秋季新品主图 5 张",
        "store_id": store_id,
        "order_commission": "1000.00",
        "spec_snapshot": SPEC_OK,
    }, 201)
    ok = status == 201 and isinstance(order, dict) and order.get("id")
    check("创建订单成功", bool(ok), str(order)[:150])
    if not ok:
        log("\n订单都建不出来，后面没法测。")
        return 1
    oid = order["id"]
    check("初始状态为待派单", order.get("state") == "pending_assign", order.get("state", ""))
    check("需求单问题清单已随订单落库", order.get("spec_issues") == [], str(order.get("spec_issues")))

    status, data = api("POST", "/api/opc/orders", {
        "order_sn": "OP-TEST-001", "title": "重复", "spec_snapshot": SPEC_OK,
    })
    check("订单编号重复被拒绝", status == 400, f"status={status}")

    # 派单
    status, data = api("POST", f"/api/opc/orders/{oid}/assign",
                       {"designer_id": designer_id})
    check("派单成功 → 已派单",
          status == 200 and data.get("order", {}).get("state") == "assigned",
          str(data)[:150])

    status, data = api("POST", f"/api/opc/orders/{oid}/assign",
                       {"designer_id": designer_id})
    check("重复派单被拒（状态不对）", status == 400, f"status={status}")

    # 接单
    status, data = api("POST", f"/api/opc/orders/{oid}/claim",
                       {"designer_id": designer_id})
    check("接单成功 → 已接单",
          status == 200 and data.get("order", {}).get("state") == "taken",
          str(data)[:150])

    # 进入初稿
    status, data = api("POST", f"/api/opc/orders/{oid}/transition",
                       {"to_state": "drafting"})
    check("进入初稿制作中",
          status == 200 and data.get("order", {}).get("state") == "drafting",
          str(data)[:150])

    # 跳阶段必须被拒
    status, data = api("POST", f"/api/opc/orders/{oid}/transition",
                       {"to_state": "settled"})
    check("跳阶段流转被拒绝", status == 400, f"status={status}")

    # ================= 证据链 =================
    log("")
    log("── 交付证据链 ──")
    status, data = api("GET", f"/api/opc/orders/{oid}/gate")
    check("证据链为空时结算门禁 blocked",
          status == 200 and data.get("allowed") is False
          and any("证据链" in b for b in data.get("blockers", [])),
          str(data.get("blockers"))[:200])

    cmd = "check_images.py --dir ./out --spec spec.json"

    # 绿灯先来（顺序错）
    status, data = api("POST", f"/api/opc/orders/{oid}/deliveries", {
        "phase": "green", "command_text": cmd, "output": "全部通过", "return_code": 0,
    }, 201)
    check("绿灯记录可追加", status == 201, str(data)[:120])

    status, data = api("POST", f"/api/opc/orders/{oid}/deliveries", {
        "phase": "red", "command_text": cmd, "output": "尺寸不足", "return_code": 1,
    }, 201)
    check("红灯记录可追加", status == 201, str(data)[:120])

    status, data = api("GET", f"/api/opc/orders/{oid}/gate")
    chain = data.get("blockers", [])
    check("顺序错误时门禁仍 blocked",
          data.get("allowed") is False,
          str(chain)[:200])

    # 补返工
    status, data = api("POST", f"/api/opc/orders/{oid}/deliveries", {
        "phase": "diff", "command_text": cmd, "output": "重新出图", "return_code": 0,
    }, 201)
    check("返工记录可追加", status == 201, str(data)[:120])

    # 不同命令的绿灯 —— 必须被识别为「不是同一命令」
    status, data = api("POST", f"/api/opc/orders/{oid}/deliveries", {
        "phase": "green", "command_text": "other_check.py", "output": "通过", "return_code": 0,
    }, 201)
    check("不同命令的绿灯可追加（但不算数）", status == 201, str(data)[:120])

    status, data = api("GET", f"/api/opc/orders/{oid}/gate")
    blockers = data.get("blockers", [])
    # 换命令的绿灯不算数 → 证据链仍然不完整。
    # 判据是「evidence_complete 为 false 且仍卡在证据链这一条」，
    # 不要去匹配具体文案 —— 文案会改，判据不会。
    check("换命令的绿灯不被认作同一处修复",
          data.get("allowed") is False
          and data.get("evidence_complete") is False
          and any("证据链" in b for b in blockers),
          str(blockers)[:200])

    # 补一条同命令、晚于红灯的绿灯
    status, data = api("POST", f"/api/opc/orders/{oid}/deliveries", {
        "phase": "green", "command_text": cmd, "output": "全部通过", "return_code": 0,
    }, 201)
    check("同命令绿灯可追加", status == 201, str(data)[:120])

    # 复验
    status, data = api("POST", f"/api/opc/orders/{oid}/evaluate")
    check("复验通过 → 进入待验收",
          status == 200 and data.get("order", {}).get("state") == "pending_review",
          str(data.get("order", {}).get("state")))

    # ================= 具名验收 =================
    log("")
    log("── 具名验收与门禁 ──")
    status, data = api("POST", f"/api/opc/orders/{oid}/accept", {"actor": "测试设计师"})
    check("设计师自签被拒",
          status == 400 and "不能验收自己" in str(data.get("detail", "")),
          str(data)[:150])

    status, data = api("POST", f"/api/opc/orders/{oid}/accept", {"actor": "agent:bot"})
    # 机器署名被拒的判据是「被拒」，不是文案 —— 文案里写的是「具名的人」。
    check("机器署名被拒",
          status == 400 and ("agent:" in str(data.get("detail", ""))
                             or "具名的人" in str(data.get("detail", ""))),
          str(data)[:150])

    status, data = api("POST", f"/api/opc/orders/{oid}/accept", {"actor": "张老板"})
    check("具名验收成功 → 已交付",
          status == 200 and data.get("order", {}).get("state") == "delivered",
          str(data)[:150])

    status, data = api("GET", f"/api/opc/orders/{oid}/gate")
    check("验收后结算门禁 allowed",
          status == 200 and data.get("allowed") is True,
          str(data.get("blockers"))[:200])

    # ================= 结算 =================
    log("")
    log("── 结算 ──")
    status, data = api("POST", "/api/opc/settlements/generate", {}, 200)
    made = data.get("created", []) if isinstance(data, dict) else []
    skipped = data.get("skipped", []) if isinstance(data, dict) else []
    check("一键生成结算单成功", len(made) >= 1, f"生成 {len(made)} 张，跳过 {len(skipped)}")

    status, data = api("GET", "/api/opc/settlements")
    check("结算单列表可读", status == 200 and isinstance(data, list), str(data)[:100])

    status, data = api("GET", "/api/opc/settlements/summary")
    check("结算汇总可读", status == 200 and "pending_count" in data, str(data)[:120])

    if made:
        sid = made[0]["id"]
        status, data = api("POST", f"/api/opc/settlements/{sid}/pay",
                           {"actor": "张老板", "upstream_settlement_time": "2026-11-30"})
        check("标记已打款成功",
              status == 200 and data.get("status") == "paid",
              str(data)[:150])

        status, data = api("POST", f"/api/opc/settlements/{sid}/pay",
                           {"actor": "张老板"})
        check("重复打款被拒", status == 400, f"status={status}")

    status, data = api("GET", f"/api/opc/orders/{oid}")
    check("订单状态推进到已结算",
          status == 200 and data.get("order", {}).get("state") == "settled",
          str(data.get("order", {}).get("state")))

    # ================= 分账 =================
    log("")
    log("── 分账 ──")
    status, data = api("POST", "/api/opc/rules/preview", {"total": "1000"})
    rows = data.get("rows", []) if isinstance(data, dict) else []
    designer_row = next((r for r in rows if r.get("scope") == "designer"), None)
    check("分账试算有结果", len(rows) >= 1, str(rows)[:200])
    check("设计师分到 700（70%）",
          designer_row is not None and designer_row.get("amount") == "700.00",
          str(designer_row))
    total = sum(float(r.get("amount", 0) or 0) for r in rows)
    check("各角色份额合计不超过总额", total <= 1000.0, f"合计={total}")

    status, data = api("POST", "/api/opc/rules/preview", {"total": "1000.33"})
    rows = data.get("rows", []) if isinstance(data, dict) else []
    total = sum(float(r.get("amount", 0) or 0) for r in rows)
    check("零头金额也能正确拆分", abs(total - 1000.33) < 0.02, f"合计={total}")

    status, data = api("POST", "/api/opc/rules",
                       {"scope": "designer", "rate": "1.5"})
    check("比例超范围被拒", status == 400, f"status={status}")

    status, data = api("POST", "/api/opc/rules",
                       {"scope": "unknown_scope", "rate": "0.1"})
    check("未知分账口径被拒", status == 400, f"status={status}")

    # ================= 撮合 =================
    log("")
    log("── 撮合推荐 ──")
    status, order2 = api("POST", "/api/opc/orders", {
        "order_sn": "OP-TEST-002",
        "title": "连衣裙主图",
        "order_commission": "500",
        "spec_snapshot": SPEC_OK,
    }, 201)
    oid2 = order2.get("id") if isinstance(order2, dict) else ""
    if oid2:
        status, data = api("GET", f"/api/opc/match/recommend?order_id={oid2}")
        cands = data.get("candidates", []) if isinstance(data, dict) else []
        check("推荐返回非空候选（AI 不可用时降级到规则）",
              status == 200 and len(cands) >= 1,
              f"candidates={len(cands)} reason={str(data)[:100]}")
        check("降级时标明来源",
              data.get("source") in ("rule", "llm"),
              str(data.get("source")))

    status, data = api("GET", "/api/opc/match/board")
    check("撮合看板可读", status == 200 and "pending" in data, str(data)[:120])

    # ================= 看板 =================
    log("")
    log("── 看板 ──")
    status, data = api("GET", "/api/opc/dashboard")
    check("看板可读", status == 200 and "funnel" in data, str(data)[:120])
    check("漏斗包含各状态", len(data.get("funnel", [])) >= 9, str(len(data.get("funnel", []))))

    # ================= 事件流 =================
    log("")
    log("── 事件流与摘要 ──")
    status, data = api("GET", f"/api/opc/orders/{oid}")
    events = data.get("events", []) if isinstance(data, dict) else []
    check("订单事件全部留痕", len(events) >= 6, f"{len(events)} 条")
    kinds = {e.get("kind") for e in events}
    check("事件含流转与验收与证据",
          {"transition", "acceptance", "delivery"} <= kinds, str(kinds))

    status, data = api("GET", f"/api/opc/orders/{oid}/summary")
    check("交付摘要可生成",
          status == 200 and "four" in data and "markdown" in data,
          str(data)[:120])
    md = data.get("markdown", "") if isinstance(data, dict) else ""
    check("摘要含四要素标题",
          all(k in md for k in ("## 结果", "## 证据", "## 边界", "## 交接")), md[:120])

    status, data = api("GET", f"/api/opc/orders/{oid}/repair-loop")
    check("返工回路可读", status == 200 and "status" in data, str(data)[:120])

    # ================= 鉴权 =================
    log("")
    log("── 鉴权 ──")
    keep = TOKEN
    TOKEN = ""
    status, _ = api("GET", "/api/opc/dashboard")
    check("无 token 访问被拒 401", status == 401, f"status={status}")
    TOKEN = keep

    # ================= 汇总 =================
    log("")
    log("=" * 70)
    log(f"通过 {PASSED} 项，失败 {len(FAILED)} 项")
    if FAILED:
        log("")
        for f in FAILED:
            log(f"  [FAIL] {f}")
    log("=" * 70)
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
