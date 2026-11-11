# -*- coding: utf-8 -*-
"""设计师结算系统 · HTTP + 数据库 smoke。

真起服务、真走接口、真落库，验证一条完整业务链：

  派单员录设计师 → 录订单 → 派单 → 补订单编号 → 传两类截图 → 审核通过
  → 设计师登录 → 一键结算 → 派单员标记打款 → 设计师查收益

跑法：
    cd E:\\drill-system\\backend
    .\\.venv\\Scripts\\python.exe -X utf8 tests\\smoke_settle.py

**结算窗口的处理**：真实规则是「每月只有 8、9 号能发起结算」。
本 smoke 要跑完整条链路，所以结算那一段把「今天」**注入**成窗口内的日期
（``app.core.timeutil.today`` 被替换）。被注入的是日期，不是规则 ——
规则仍然由规则层判定，窗口外该拒还是拒（下面单独验一次）。
"""
import asyncio
import sys
import unittest.mock
from datetime import date, timedelta
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


class FixedDate(date):
    """把「今天」钉死到窗口内（结算窗口 = 每月 8、9 号）。"""

    FIXED = date(2026, 11, 8)

    @classmethod
    def today(cls) -> date:
        return cls.FIXED


async def main() -> int:
    import httpx
    from app.core import timeutil
    from app.database import AsyncSessionLocal, init_db
    from app.main import app
    from app.models import SlDesigner, SlOrder, SlSettlement
    from sqlalchemy import delete

    await init_db()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver") as client:
        print("=" * 74)
        print("① 准备派单员账号")
        print("=" * 74)
        await client.post("/api/auth/register", json={
            "username": "settle_admin", "password": "Settle@2026",
            "display_name": "派单员",
        })
        login = await client.post("/api/auth/login", json={
            "username": "settle_admin", "password": "Settle@2026",
        })
        if login.status_code != 200:
            print("  [FAIL] 派单员登录失败 HTTP %s %s" % (login.status_code, login.text[:200]))
            return 1
        token = login.json().get("access_token") or login.json().get("token")
        check("派单员登录成功", bool(token), str(token)[:20])
        headers = {"Authorization": "Bearer %s" % token}

        # 清掉历史数据，保证 smoke 可重复跑
        async with AsyncSessionLocal() as db:
            await db.execute(delete(SlSettlement))
            await db.execute(delete(SlOrder))
            await db.execute(delete(SlDesigner))
            await db.commit()

        print("\n" + "=" * 74)
        print("② 派单员录设计师（模块二）")
        print("=" * 74)
        payload = {
            "name": "陈富灿", "nickname": "小陈", "phone": "17737706163",
            "alipay_account": "17737706163", "gender": 1,
            "recruitment_source": "其他", "production_level": "标准档次",
            "password": "temp123456",
        }
        resp = await client.post("/api/settle/admin/designers", json=payload, headers=headers)
        check("录入设计师 200", resp.status_code == 200,
              "HTTP %s %s" % (resp.status_code, resp.text[:200]))
        designer = resp.json() if resp.status_code == 200 else {}
        did = designer.get("id")
        check("返回设计师 ID", bool(did), str(did))
        check("标记为需改密（临时密码）", designer.get("must_change_password") is True)
        check("战区保持为空", designer.get("war_zone") == "")
        check("所属 HR 保持为空", designer.get("hr_id") == "")

        # 战区非空要被拒
        bad = dict(payload, war_zone="独角兽", phone="17737706164")
        resp = await client.post("/api/settle/admin/designers", json=bad, headers=headers)
        check("战区非空被拒 422", resp.status_code == 422, "HTTP %s" % resp.status_code)
        detail = resp.json().get("detail") if resp.status_code == 422 else {}
        issues = detail.get("issues") if isinstance(detail, dict) else []
        check("拒绝时按字段给问题", bool(issues), str(issues)[:150])

        # 手机号重复要被拒
        resp = await client.post("/api/settle/admin/designers", json=payload, headers=headers)
        check("手机号重复被拒 409", resp.status_code == 409, "HTTP %s" % resp.status_code)

        # 【回归】设计师**列表**接口必须能返回并带上订单数。
        # 之前这个接口 500 —— 里面 `for o in await db.execute(select(SlOrder))`
        # 迭代出的是 Row 元组不是 ORM 对象，访问 o.designer_id 直接抛异常。
        # smoke 当时只测了 POST 没测 GET，这条就漏过去了，
        # 前端 Promise.all 一失败，三个页面全空。
        resp = await client.get("/api/settle/admin/designers", headers=headers)
        check("设计师列表 200", resp.status_code == 200,
              "HTTP %s %s" % (resp.status_code, resp.text[:200]))
        dlist = resp.json() if resp.status_code == 200 else []
        check("设计师列表有数据", isinstance(dlist, list) and len(dlist) >= 1,
              str(dlist)[:150])
        if isinstance(dlist, list) and dlist:
            check("列表带订单数字段", "order_count" in dlist[0], str(list(dlist[0].keys())))

        # 订单列表同理 —— 一起守住
        resp = await client.get("/api/settle/admin/orders", headers=headers)
        check("订单列表 200", resp.status_code == 200,
              "HTTP %s %s" % (resp.status_code, resp.text[:200]))

        print("\n" + "=" * 74)
        print("③ 派单员录订单（模块三）")
        print("=" * 74)
        order_payload = {
            "customer_id": "tb125212883", "war_zone": "独角兽",
            "customer_service": "若暖", "order_type": "personal",
            "service_type": "PPT定制", "order_amount": "100.00",
            "commission_rate": "0.60", "deliver_date": "2026-11-01",
            "order_date": FixedDate.FIXED.isoformat(),
            "requirement": "按客户模板改 10 页 PPT",
        }
        resp = await client.post("/api/settle/admin/orders", json=order_payload, headers=headers)
        check("录订单 200", resp.status_code == 200,
              "HTTP %s %s" % (resp.status_code, resp.text[:250]))
        order = resp.json() if resp.status_code == 200 else {}
        oid = order.get("id")
        check("订单佣金算对", order.get("designer_commission") == "60.00",
              str(order.get("designer_commission")))
        check("订单初始状态是设计待定", order.get("state") == "pending_design",
              str(order.get("state")))
        check("订单还没派给人", not order.get("designer_id"),
              str(order.get("designer_id")))

        # 佣金比例越界要拒
        bad_order = dict(order_payload, commission_rate="0.85", customer_id="x2")
        resp = await client.post("/api/settle/admin/orders", json=bad_order, headers=headers)
        check("佣金比例 85% 被拒 422", resp.status_code == 422, "HTTP %s" % resp.status_code)

        # 客户 ID 缺失要拒
        bad_order = dict(order_payload, customer_id="")
        resp = await client.post("/api/settle/admin/orders", json=bad_order, headers=headers)
        check("客户 ID 缺失被拒 422", resp.status_code == 422, "HTTP %s" % resp.status_code)

        print("\n" + "=" * 74)
        print("④ 订单流程（模块四两个节点）")
        print("=" * 74)
        # 派单前必须指定设计师
        resp = await client.post(f"/api/settle/admin/orders/{oid}/transition",
                                 json={"to_state": "drafting"}, headers=headers)
        check("未指定设计师不能派单 422", resp.status_code == 422, "HTTP %s" % resp.status_code)

        resp = await client.post(f"/api/settle/admin/orders/{oid}/transition",
                                 json={"to_state": "drafting", "designer_id": did},
                                 headers=headers)
        check("派单进初稿 200", resp.status_code == 200,
              "HTTP %s %s" % (resp.status_code, resp.text[:150]))
        check("派单后状态是初稿制作中",
              resp.json().get("state") == "drafting" if resp.status_code == 200 else False,
              str(resp.json().get("state")))

        # 节点一：初稿完成 → 终稿制作中，必须有订单编号
        resp = await client.post(f"/api/settle/admin/orders/{oid}/transition",
                                 json={"to_state": "finalizing"}, headers=headers)
        check("无订单编号进不了终稿 422", resp.status_code == 422, "HTTP %s" % resp.status_code)
        detail = resp.json().get("detail") if resp.status_code == 422 else {}
        issues = detail.get("issues") if isinstance(detail, dict) else []
        check("提示要填订单编号", any("订单编号" in str(i) for i in issues), str(issues)[:150])

        resp = await client.post(f"/api/settle/admin/orders/{oid}/transition",
                                 json={"to_state": "finalizing", "order_no": "DR-2026-0001"},
                                 headers=headers)
        check("补编号后进终稿 200", resp.status_code == 200,
              "HTTP %s %s" % (resp.status_code, resp.text[:150]))
        check("订单编号已落库",
              resp.json().get("order_no") == "DR-2026-0001" if resp.status_code == 200 else False,
              str(resp.json().get("order_no")))

        # 节点二：终稿完成 → 待审核，必须两类截图
        resp = await client.post(f"/api/settle/admin/orders/{oid}/transition",
                                 json={"to_state": "pending_audit"}, headers=headers)
        check("无截图进不了待审核 422", resp.status_code == 422, "HTTP %s" % resp.status_code)
        detail = resp.json().get("detail") if resp.status_code == 422 else {}
        issues = detail.get("issues") if isinstance(detail, dict) else []
        check("提示要两类截图",
              any("聊天记录" in str(i) for i in issues) and any("交付文件" in str(i) for i in issues),
              str(issues)[:200])

        resp = await client.post(f"/api/settle/admin/orders/{oid}/transition",
                                 json={"to_state": "pending_audit",
                                       "chat_screenshot": "chat.png",
                                       "file_screenshot": "file.png"},
                                 headers=headers)
        check("两类截图齐全后进待审核 200", resp.status_code == 200,
              "HTTP %s %s" % (resp.status_code, resp.text[:150]))

        print("\n" + "=" * 74)
        print("⑤ 审核与异常诊断")
        print("=" * 74)
        resp = await client.get(f"/api/settle/admin/orders/{oid}/diagnose", headers=headers)
        check("异常诊断 200", resp.status_code == 200, "HTTP %s" % resp.status_code)
        if resp.status_code == 200:
            body = resp.json()
            check("干净订单无异常", body.get("case_count") == 0, str(body.get("issues"))[:200])

        resp = await client.post(f"/api/settle/admin/orders/{oid}/audit",
                                 json={"action": "approve", "remark": "材料齐全"},
                                 headers=headers)
        check("审核通过 200", resp.status_code == 200,
              "HTTP %s %s" % (resp.status_code, resp.text[:150]))
        check("状态变可结算", resp.json().get("state") == "settleable",
              str(resp.json().get("state")))

        print("\n" + "=" * 74)
        print("⑥ 设计师登录结算端")
        print("=" * 74)
        resp = await client.post("/api/settle/auth/login", json={
            "phone": "17737706163", "password": "temp123456",
        })
        check("设计师登录 200", resp.status_code == 200,
              "HTTP %s %s" % (resp.status_code, resp.text[:200]))
        dlogin = resp.json() if resp.status_code == 200 else {}
        check("返回设计师 ID", bool(dlogin.get("designer_id")), str(dlogin.get("designer_id")))
        check("提示需改密", dlogin.get("must_change_password") is True)
        dtok = dlogin.get("token") or ""
        check("返回签名令牌", bool(dtok) and dtok != "sl::%s" % dlogin.get("designer_id"),
              dtok[:24])
        dheaders = {"Authorization": "Bearer %s" % dtok}

        # 密码错
        resp = await client.post("/api/settle/auth/login", json={
            "phone": "17737706163", "password": "wrong",
        })
        check("密码错被拒 401", resp.status_code == 401, "HTTP %s" % resp.status_code)

        # 未录入的号
        resp = await client.post("/api/settle/auth/login", json={
            "phone": "19900000000", "password": "whatever",
        })
        check("未录入账号被拒 403", resp.status_code == 403, "HTTP %s" % resp.status_code)
        detail = resp.json().get("detail") if resp.status_code == 403 else ""
        check("提示要先在总后台录入", "录入" in str(detail), str(detail)[:150])

        print("\n" + "=" * 74)
        print("⑦ 一键结算（模块六）")
        print("=" * 74)
        # 把「今天」注入到结算窗口内，让完整链路能跑通
        with unittest.mock.patch.object(timeutil, "today", FixedDate.today):
            resp = await client.get("/api/settle/me/settleable", headers=dheaders)
            check("查可结算 200", resp.status_code == 200,
                  "HTTP %s %s" % (resp.status_code, resp.text[:150]))
            if resp.status_code == 200:
                body = resp.json()
                check("窗口信息有", "window" in body)
                check("窗口状态明确", isinstance(body["window"].get("open"), bool),
                      str(body["window"].get("message"))[:100])
                check("窗口内可结算", body["window"].get("open") is True)
                check("列出可结算订单", len(body.get("eligible") or []) == 1,
                      "可结算 %d 笔" % len(body.get("eligible") or []))

            resp = await client.post("/api/settle/me/settle",
                                     json={"order_ids": [oid]}, headers=dheaders)
            check("窗口内发起结算 200", resp.status_code == 200,
                  "HTTP %s %s" % (resp.status_code, resp.text[:150]))
            if resp.status_code == 200:
                created = resp.json().get("created") or []
                check("生成一笔结算单", len(created) == 1, "%d 笔" % len(created))
                if created:
                    check("结算单金额正确", created[0]["commission"] == "60.00",
                          created[0]["commission"])

        # 重复发起要被拒
        with unittest.mock.patch.object(timeutil, "today", FixedDate.today):
            resp = await client.post("/api/settle/me/settle",
                                     json={"order_ids": [oid]}, headers=dheaders)
            skipped = resp.json().get("skipped") or [] if resp.status_code == 200 else []
            check("重复发起被跳过", bool(skipped) or resp.status_code != 200,
                  "HTTP %s skipped=%d" % (resp.status_code, len(skipped)))

        # 窗口外必须拒 —— 这是硬规则，不能因为注入了日期就放水
        with unittest.mock.patch.object(timeutil, "today",
                                        lambda: date(2026, 11, 20)):
            resp = await client.post("/api/settle/me/settle",
                                     json={"order_ids": [oid]}, headers=dheaders)
            check("非结算窗口被拒 409", resp.status_code == 409,
                  "HTTP %s %s" % (resp.status_code, str(resp.json().get("detail"))[:120]))

        print("\n" + "=" * 74)
        print("⑧ 派单员标记打款 + 收益明细")
        print("=" * 74)
        resp = await client.get("/api/settle/admin/settlements", headers=headers)
        check("查结算单 200", resp.status_code == 200, "HTTP %s" % resp.status_code)
        settlements = resp.json() if resp.status_code == 200 else []
        check("有结算单记录", len(settlements) >= 1, "%d 条" % len(settlements))

        if settlements:
            sid = settlements[0]["id"]
            resp = await client.post(f"/api/settle/admin/settlements/{sid}/pay",
                                     json={"flow_no": "ALIPAY20261115001"}, headers=headers)
            check("标记打款 200", resp.status_code == 200,
                  "HTTP %s %s" % (resp.status_code, resp.text[:150]))
            check("状态变已打款", resp.json().get("status") == "paid",
                  str(resp.json().get("status")))
            check("流水号已记录", resp.json().get("flow_no") == "ALIPAY20261115001")

        resp = await client.get("/api/settle/me/settlements", headers=dheaders)
        check("设计师查收益 200", resp.status_code == 200,
              "HTTP %s %s" % (resp.status_code, resp.text[:150]))
        mine = resp.json() if resp.status_code == 200 else []
        check("收益明细有记录", len(mine) >= 1, "%d 条" % len(mine))
        if mine:
            check("金额正确", mine[0]["commission"] == "60.00", mine[0]["commission"])

        print("\n" + "=" * 74)
        print("⑨ 设计师改密码")
        print("=" * 74)
        resp = await client.post("/api/settle/me/password", json={
            "old_password": "temp123456", "new_password": "newpass123",
        }, headers=dheaders)
        check("改密码 200", resp.status_code == 200,
              "HTTP %s %s" % (resp.status_code, resp.text[:150]))
        resp = await client.post("/api/settle/auth/login", json={
            "phone": "17737706163", "password": "newpass123",
        })
        check("新密码能登录 200", resp.status_code == 200, "HTTP %s" % resp.status_code)
        resp = await client.post("/api/settle/auth/login", json={
            "phone": "17737706163", "password": "temp123456",
        })
        check("旧密码失效 401", resp.status_code == 401, "HTTP %s" % resp.status_code)

        print("\n" + "=" * 74)
        print("⑩ 看板与字典")
        print("=" * 74)
        resp = await client.get("/api/settle/admin/dashboard", headers=headers)
        check("看板 200", resp.status_code == 200, "HTTP %s" % resp.status_code)
        if resp.status_code == 200:
            body = resp.json()
            check("漏斗有数据", len(body.get("funnel") or []) > 0)
            check("设计师数正确", body.get("designer_count") == 1,
                  str(body.get("designer_count")))
            check("结算窗口信息在", "window" in body)

        resp = await client.get("/api/settle/meta", headers=headers)
        check("字典 200", resp.status_code == 200, "HTTP %s" % resp.status_code)
        if resp.status_code == 200:
            body = resp.json()
            check("佣金比例说明含 50%/70%",
                  "50%" in body["commission_rate"]["text"] and "70%" in body["commission_rate"]["text"])
            check("结算窗口日是 8/9", body["settle_window_days"] == [8, 9],
                  str(body["settle_window_days"]))
            check("打款日是 15 号", body["payout_day"] == 15)
            check("字典含上游状态映射", "upstream_statuses" in body)

        print("\n" + "=" * 74)
        print("⑪ 鉴权保护")
        print("=" * 74)
        resp = await client.get("/api/settle/admin/dashboard")
        check("无 token 被拒 401", resp.status_code == 401, "HTTP %s" % resp.status_code)
        resp = await client.get("/api/settle/me/orders", headers={"Authorization": "Bearer fake"})
        check("假令牌被拒 401", resp.status_code == 401, "HTTP %s" % resp.status_code)
        # 派单员令牌不能进设计师端
        resp = await client.get("/api/settle/me/orders", headers=headers)
        check("派单员令牌进不了结算端 401", resp.status_code == 401,
              "HTTP %s" % resp.status_code)
        # 设计师令牌不能进派单员端
        resp = await client.get("/api/settle/admin/dashboard", headers=dheaders)
        check("设计师令牌进不了派单员端 401", resp.status_code == 401,
              "HTTP %s" % resp.status_code)

    print("\n" + "=" * 74)
    print("结果：%d 通过 / %d 失败" % (PASS, FAIL))
    for f in FAILURES:
        print("  -", f)
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
