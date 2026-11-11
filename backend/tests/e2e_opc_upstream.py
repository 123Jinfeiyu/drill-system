# -*- coding: utf-8 -*-
"""
OPC 上游连接 · 端到端 HTTP 实测

真起 FastAPI 服务、真登录、真调上游、真落库、真查库。
这是「两个系统连起来了」的最终证明。

跑法：
    cd E:\\drill-system\\backend
    .\\.venv\\Scripts\\python.exe -X utf8 tests\\e2e_opc_upstream.py
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (label, (" — " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILURES.append(label)
        print("  [FAIL] %s%s" % (label, (" — " + detail) if detail else ""))
    return cond


async def main() -> int:
    import httpx
    from app.database import AsyncSessionLocal, init_db
    from app.main import app
    from app.models import OpcDesigner, OpcOrder
    from sqlalchemy import func, select

    username = os.getenv("TRCIPG_USERNAME", "").strip()
    password = os.getenv("TRCIPG_PASSWORD", "").strip()
    if not username or not password:
        print("!! 未配置上游凭据，跳过")
        return 0

    await init_db()

    print("=" * 74)
    print("① 准备：注册一个测试用户 + 拿 token")
    print("=" * 74)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver") as client:
        reg = await client.post("/api/auth/register", json={
            "username": "opc_e2e_user", "password": "E2eTest@2026",
            "display_name": "OPC 联调",
        })
        if reg.status_code not in (200, 201):
            # 已存在就直接登录
            pass
        login = await client.post("/api/auth/login", json={
            "username": "opc_e2e_user", "password": "E2eTest@2026",
        })
        if login.status_code != 200:
            print("  [FAIL] 登录失败 HTTP %s %s" % (login.status_code, login.text[:200]))
            return 1
        token = login.json().get("access_token") or login.json().get("token")
        check("拿到登录 token", bool(token), str(token)[:24])
        headers = {"Authorization": "Bearer %s" % token}

        print("\n" + "=" * 74)
        print("② 未配置上游凭据时的行为（不该崩，该给清晰提示）")
        print("=" * 74)
        # 临时把环境变量挪走
        saved_u, saved_p = os.environ.pop("TRCIPG_USERNAME", None), os.environ.pop("TRCIPG_PASSWORD", None)
        resp = await client.get("/api/opc/upstream/status", headers=headers)
        check("status 缺凭据仍返回 200", resp.status_code == 200,
              "HTTP %s" % resp.status_code)
        if resp.status_code == 200:
            check("标记为未配置", resp.json().get("configured") is False)
            check("给出配置提示", bool(resp.json().get("hint")), resp.json().get("hint"))

        # 其它接口缺凭据应返回 400 而不是 500
        resp = await client.get("/api/opc/upstream/designers", headers=headers)
        check("业务接口缺凭据返回 400 而不是 500", resp.status_code == 400,
              "HTTP %s %s" % (resp.status_code, resp.text[:100]))

        if saved_u:
            os.environ["TRCIPG_USERNAME"] = saved_u
        if saved_p:
            os.environ["TRCIPG_PASSWORD"] = saved_p

        print("\n" + "=" * 74)
        print("③ 上游连通性")
        print("=" * 74)
        resp = await client.get("/api/opc/upstream/status", headers=headers)
        check("status 接口 200", resp.status_code == 200, "HTTP %s" % resp.status_code)
        if resp.status_code == 200:
            body = resp.json()
            check("凭据已配置", body.get("configured") is True)
            check("上游可达", body.get("reachable") is True, str(body.get("base")))
            check("返回结算线说明", len(body.get("settlement_types") or []) == 3)

        print("\n" + "=" * 74)
        print("④ 拉上游设计师（真数据）")
        print("=" * 74)
        resp = await client.get("/api/opc/upstream/designers?limit=30", headers=headers)
        check("designers 200", resp.status_code == 200, "HTTP %s %s" % (resp.status_code, resp.text[:120]))
        items = resp.json().get("items") if resp.status_code == 200 else []
        check("拉到设计师", bool(items), "%d 人" % len(items or []))
        if items:
            d0 = items[0]
            check("设计师带战区", bool(d0.get("war_zone")), d0.get("war_zone"))
            check("设计师带档次", bool(d0.get("production_level")), d0.get("production_level"))
            check("结算资格是布尔", isinstance(d0.get("can_settle"), bool))

        print("\n" + "=" * 74)
        print("⑤ 拉上游结算单 + 字典")
        print("=" * 74)
        resp = await client.get("/api/opc/upstream/settlements?num=20", headers=headers)
        check("settlements 200", resp.status_code == 200, "HTTP %s" % resp.status_code)
        if resp.status_code == 200:
            sbody = resp.json()
            check("结算单有数据", bool(sbody.get("items")),
                  "总数 %s / 佣金合计 %s" % (sbody.get("total"), sbody.get("commission_sum")))
            check("标注了结算线类型", bool(sbody.get("settlement_type_label")),
                  sbody.get("settlement_type_label"))

        resp = await client.get("/api/opc/upstream/dictionaries", headers=headers)
        check("dictionaries 200", resp.status_code == 200, "HTTP %s" % resp.status_code)
        if resp.status_code == 200:
            dbody = resp.json()
            check("档次字典有 6 项", len(dbody.get("order_grades") or []) == 6,
                  str([g["name"] for g in dbody.get("order_grades", [])]))
            check("问题类型有 4 项", len(dbody.get("order_issue_types") or []) == 4)

        print("\n" + "=" * 74)
        print("⑥ 同步落库（幂等，验证两次结果一致）")
        print("=" * 74)
        async with AsyncSessionLocal() as db:
            before_d = (await db.execute(select(func.count(OpcDesigner.id)))).scalar_one()
            before_o = (await db.execute(select(func.count(OpcOrder.id)))).scalar_one()
        print("  同步前：设计师 %d / 订单 %d" % (before_d, before_o))

        resp = await client.post("/api/opc/upstream/sync?limit=30&write=true", headers=headers)
        check("sync 200", resp.status_code == 200, "HTTP %s %s" % (resp.status_code, resp.text[:200]))
        sync1 = resp.json() if resp.status_code == 200 else {}
        if sync1:
            print("  第一次：新建 %s / 更新 %s"
                  % (sync1.get("created"), sync1.get("updated")))
            check("同步确实写库了", (sync1.get("created") or {}).get("designers", 0) > 0,
                  "新建设计师 %d" % (sync1.get("created") or {}).get("designers", 0))

        async with AsyncSessionLocal() as db:
            mid_d = (await db.execute(select(func.count(OpcDesigner.id)))).scalar_one()
            mid_o = (await db.execute(select(func.count(OpcOrder.id)))).scalar_one()
        print("  同步后：设计师 %d / 订单 %d" % (mid_d, mid_o))
        check("设计师已落库", mid_d > before_d, "%d → %d" % (before_d, mid_d))

        resp2 = await client.post("/api/opc/upstream/sync?limit=30&write=true", headers=headers)
        sync2 = resp2.json() if resp2.status_code == 200 else {}
        async with AsyncSessionLocal() as db:
            after_d = (await db.execute(select(func.count(OpcDesigner.id)))).scalar_one()
        check("二次同步不产生重复（幂等）", after_d == mid_d,
              "%d → %d" % (mid_d, after_d))
        if sync2:
            check("二次同步全是更新",
                  (sync2.get("created") or {}).get("designers", 0) == 0,
                  "新建 %d" % (sync2.get("created") or {}).get("designers", 0))

        print("\n" + "=" * 74)
        print("⑦ 对账（台账已有数据 → 应该能算出总额）")
        print("=" * 74)
        resp = await client.get("/api/opc/upstream/reconcile?limit=30", headers=headers)
        check("reconcile 200", resp.status_code == 200, "HTTP %s" % resp.status_code)
        if resp.status_code == 200:
            rbody = resp.json()
            print("  差异 %d 条 / 上游订单佣金 %s / 上游结算单佣金 %s / 台账佣金 %s"
                  % (rbody.get("issue_count"), rbody.get("upstream_total_commission"),
                     rbody.get("upstream_settlement_commission"),
                     rbody.get("opc_total_commission")))
            check("对账报告结构完整", "issues" in rbody and "commission_gap" in rbody)

        print("\n" + "=" * 74)
        print("⑧ 撮合候选（真实订单）")
        print("=" * 74)
        resp = await client.get("/api/opc/upstream/settlements?num=1", headers=headers)
        if resp.status_code == 200 and resp.json().get("items"):
            oid = resp.json()["items"][0]["order_id"]
            resp = await client.get(f"/api/opc/upstream/orders/{oid}", headers=headers)
            check("订单详情 200", resp.status_code == 200, "HTTP %s" % resp.status_code)
            if resp.status_code == 200:
                obody = resp.json()
                check("详情带佣金拆分", "split" in obody, str(obody.get("split", {}).get("total")))
                check("拆分是平衡的", obody.get("split", {}).get("balanced") is True,
                      "差额 %s" % obody.get("split", {}).get("residual"))
                check("带六段式合同草稿", "## 目标" in (obody.get("spec_draft") or ""))

            resp = await client.get(f"/api/opc/upstream/orders/{oid}/candidates?limit=5",
                                    headers=headers)
            check("候选 200", resp.status_code == 200, "HTTP %s" % resp.status_code)
            if resp.status_code == 200:
                cands = resp.json().get("candidates") or []
                check("候选非空", len(cands) > 0, "%d 个" % len(cands))
                check("候选有分数", all("score" in c for c in cands))
                check("候选有理由", all(c.get("reasons") is not None for c in cands))

        print("\n" + "=" * 74)
        print("⑨ 鉴权保护")
        print("=" * 74)
        resp = await client.get("/api/opc/upstream/designers")
        check("无 token 被拒", resp.status_code == 401, "HTTP %s" % resp.status_code)
        resp = await client.get("/api/opc/upstream/designers",
                                headers={"Authorization": "Bearer garbage"})
        check("假 token 被拒", resp.status_code == 401, "HTTP %s" % resp.status_code)

    print("\n" + "=" * 74)
    print("结果：%d 通过 / %d 失败" % (PASS, FAIL))
    for f in FAILURES:
        print("  -", f)
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
