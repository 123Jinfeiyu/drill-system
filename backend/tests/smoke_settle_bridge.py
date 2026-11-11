"""互通桥接 smoke：真起 HTTP、真落库，用**假上游数据**。

不依赖上游网络 —— 桥接的翻译逻辑与幂等性在这里就能验完，
上游真连不上的问题由 ``smoke_opc_upstream.py`` 负责。
"""
from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.security import create_access_token  # noqa: E402,F401
from app.main import app  # noqa: E402
from app.models import SlDesigner, SlOrder  # noqa: E402
from app.services import settle_bridge as bridge  # noqa: E402,F401
from app.services.trcipg_client import UpstreamDesigner, UpstreamOrder  # noqa: E402

# ---------------------------------------------------------------------------
# 迷你断言框架
# ---------------------------------------------------------------------------

PASSED = 0
FAILED: list[str] = []


def check(title: str, ok: bool, extra: str = "") -> None:
    global PASSED
    if ok:
        PASSED += 1
        print("  [OK]   %s" % title)
    else:
        FAILED.append(title)
        print("  [FAIL] %s  %s" % (title, extra))


def section(title: str) -> None:
    print("\n" + "═" * 68)
    print("  " + title)
    print("═" * 68)


# ---------------------------------------------------------------------------
# 假上游数据
# ---------------------------------------------------------------------------

FAKE_DESIGNERS = [
    UpstreamDesigner(id=90001, name="陈富灿", nickname="小陈",
                     phone="17737706163", alipay_account="17737706163@qq.com",
                     war_zone="独角兽", production_level="标准档次",
                     recruitment_source="其他", hr_name="若暖",
                     allow_settlement=1, status=1, designer_type=1),
    # 手机号只有 9 位 → 应被挡
    UpstreamDesigner(id=90002, name="李四", nickname="小李", phone="123456789",
                     alipay_account="x@y.com", war_zone="独角兽",
                     production_level="标准档次", recruitment_source="内推",
                     allow_settlement=1, status=1, designer_type=2),
    # 上游停用
    UpstreamDesigner(id=90003, name="王五", nickname="小王",
                     phone="13800138000", alipay_account="w@y.com",
                     war_zone="", production_level="精英档次",
                     recruitment_source="猎头", allow_settlement=1,
                     status=0, designer_type=1),
    # 上游禁止结算
    UpstreamDesigner(id=90004, name="赵六", nickname="小赵",
                     phone="13800138001", alipay_account="z@y.com",
                     war_zone="", production_level="标准档次",
                     recruitment_source="其他", allow_settlement=0,
                     status=1, designer_type=1),
]

FAKE_ORDERS = [
    UpstreamOrder(id=80001, sn="SN-001", order_sn="ORD-001",
                  order_desc="按客户模板改 10 页 PPT",
                  customer_name="tb125212883", store_account="tb125212883",
                  war_zone_name="独角兽", designer_id=90001,
                  designer_name="陈富灿", user_name="若暖",
                  customer_service="若暖", order_grade="PPT定制",
                  order_type=0, status=5,
                  order_commission=Decimal("100.00"),
                  designer_commission=Decimal("60.00"),
                  request_delivery_time="2026-11-01",
                  order_time="2026-10-20", created_at="2026-10-20 10:00:00"),
    # 比例 0.30 越界 → 标出来但不拦（only_valid=False 时导入）
    UpstreamOrder(id=80002, sn="SN-002", order_sn="ORD-002",
                  order_desc="旧规则下的单", customer_name="tb999",
                  designer_id=90001, designer_name="陈富灿",
                  order_grade="PPT定制", order_type=0, status=5,
                  order_commission=Decimal("100.00"),
                  designer_commission=Decimal("30.00"),
                  order_time="2026-10-20", created_at="2026-10-20 10:00:00"),
    # 设计师本地不存在 → 未派单
    UpstreamOrder(id=80003, sn="SN-003", order_sn="ORD-003",
                  order_desc="查无此人的单", customer_name="tb888",
                  designer_name="不存在的人", order_grade="PPT定制",
                  order_type=0, status=9,
                  order_commission=Decimal("200.00"),
                  designer_commission=Decimal("120.00"),
                  order_time="2026-10-20", created_at="2026-10-20 10:00:00"),
]


async def main() -> int:
    from sqlalchemy import delete, select

    from app.database import AsyncSessionLocal, init_db

    await init_db()

    # 清掉上一轮跑出来的数据，保证可重复
    async with AsyncSessionLocal() as db:
        await db.execute(delete(SlOrder))
        await db.execute(delete(SlDesigner))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as client:
        # ------------------------------------------------------------------
        section("⓪ 准备派单员账号")
        # ------------------------------------------------------------------
        await client.post("/api/auth/register", json={
            "username": "bridge_admin", "password": "Bridge@2026",
            "display_name": "桥接派单员",
        })
        login = await client.post("/api/auth/login", json={
            "username": "bridge_admin", "password": "Bridge@2026",
        })
        if login.status_code != 200:
            print("  [FAIL] 派单员登录失败 HTTP %s %s"
                  % (login.status_code, login.text[:200]))
            return 1
        token = login.json().get("access_token") or login.json().get("token")
        check("派单员登录成功", bool(token), str(token)[:24])
        headers = {"Authorization": "Bearer %s" % token}

        # ------------------------------------------------------------------
        section("① 互通状态：未配上游凭据时要说清楚")
        # ------------------------------------------------------------------
        old_u = os.environ.pop("TRCIPG_USERNAME", None)
        old_p = os.environ.pop("TRCIPG_PASSWORD", None)
        resp = await client.get("/api/settle/admin/bridge/status", headers=headers)
        body = resp.json()
        check("状态接口 200", resp.status_code == 200, str(resp.status_code))
        check("识别出未配置凭据", body.get("configured") is False, str(body))
        check("说明只读单向模式", "只读" in str(body.get("mode", "")), str(body))
        check("给出配置指引", "TRCIPG_USERNAME" in str(body.get("hint", "")), str(body))

        # ------------------------------------------------------------------
        section("② 预览上游数据（假上游，替换客户端）")
        # ------------------------------------------------------------------
        from app.routers import settle as settle_router

        class FakeClient:
            async def list_designer_detail(self, page=1, num=50):
                return FAKE_DESIGNERS[:num], len(FAKE_DESIGNERS)

            async def list_orders(self, page=1, num=50, **kw):
                return FAKE_ORDERS[:num], len(FAKE_ORDERS)

        orig_client = settle_router._upstream_client
        settle_router._upstream_client = lambda: FakeClient()
        try:
            resp = await client.get("/api/settle/admin/bridge/preview?kind=designers&limit=10",
                                    headers=headers)
            body = resp.json()
            check("预览设计师 200", resp.status_code == 200, str(resp.status_code))
            items = body.get("items", [])
            by_uid = {i["upstream_id"]: i for i in items}
            check("返回 4 条设计师", len(items) == 4, str(len(items)))
            check("9 位手机号标为不可导",
                  by_uid.get("90002", {}).get("importable") is False,
                  str(by_uid.get("90002")))
            check("停用设计师被标出",
                  any("停用" in x for x in by_uid.get("90003", {}).get("issues", [])),
                  str(by_uid.get("90003")))
            check("禁结算设计师被标出",
                  any("禁止" in x for x in by_uid.get("90004", {}).get("issues", [])),
                  str(by_uid.get("90004")))
            check("正常设计师可导",
                  by_uid.get("90001", {}).get("importable") is True,
                  str(by_uid.get("90001")))
            check("预览不泄露战区",
                  "war_zone" not in (items[0] if items else {}),
                  str(list(items[0].keys()) if items else []))

            resp = await client.get("/api/settle/admin/bridge/preview?kind=orders&limit=10",
                                    headers=headers)
            body = resp.json()
            check("预览订单 200", resp.status_code == 200, str(resp.status_code))
            oitems = {i["upstream_id"]: i for i in body.get("items", [])}
            check("上游状态标签正确",
                  oitems["80001"]["upstream_status_label"] == "验收成功",
                  str(oitems.get("80001")))
            check("本地状态映射正确",
                  oitems["80001"]["local_state"] == "settleable",
                  str(oitems.get("80001")))
            check("比例越界被标出",
                  any("越界" in x for x in oitems["80002"]["issues"]),
                  str(oitems.get("80002")))
            check("反推比例正确",
                  oitems["80001"]["commission_rate"] == "0.6000",
                  str(oitems.get("80001")))

            # ------------------------------------------------------------------
            section("③ 导入设计师")
            # ------------------------------------------------------------------
            resp = await client.post("/api/settle/admin/bridge/import",
                                     json={"kind": "designers", "limit": 10,
                                           "only_valid": True},
                                     headers=headers)
            body = resp.json()
            check("导入接口 200", resp.status_code == 200, str(resp.status_code))
            check("只导了 1 个有效设计师",
                  body.get("created_count") == 1,
                  "created=%s skipped=%s" % (body.get("created_count"),
                                             body.get("skipped_count")))
            check("跳过原因说清楚",
                  len(body.get("skipped", [])) == 3,
                  str(body.get("skipped"))[:200])

            # ------------------------------------------------------------------
            section("④ 幂等：再导一次不会产生第二条")
            # ------------------------------------------------------------------
            resp = await client.post("/api/settle/admin/bridge/import",
                                     json={"kind": "designers", "limit": 10},
                                     headers=headers)
            body = resp.json()
            check("第二次导入新增 0 条",
                  body.get("created_count") == 0, str(body.get("created_count")))
            skipped = {s["upstream_id"]: s["reason"] for s in body.get("skipped", [])}
            check("已导入的那条按重复跳过",
                  "已导入过" in skipped.get("90001", ""), str(skipped.get("90001")))
            check("本来就不可导的仍然不可导",
                  "11 位" in skipped.get("90002", ""), str(skipped.get("90002")))

            # ------------------------------------------------------------------
            section("⑤ 导入订单")
            # ------------------------------------------------------------------
            resp = await client.post("/api/settle/admin/bridge/import",
                                     json={"kind": "orders", "limit": 10,
                                           "only_valid": False},
                                     headers=headers)
            body = resp.json()
            check("导入接口 200", resp.status_code == 200, str(resp.status_code))
            check("导了 3 条订单",
                  body.get("created_count") == 3,
                  "created=%s" % body.get("created_count"))
            created = {c["upstream_id"]: c for c in body.get("created", [])}
            check("比例越界的单也导进来了（带问题标记）",
                  "80002" in created, str(list(created.keys())))
            check("越界单带 issues",
                  any("越界" in x for x in created.get("80002", {}).get("issues", [])),
                  str(created.get("80002")))
            check("匹配到的设计师标 True",
                  created.get("80001", {}).get("designer_matched") is True,
                  str(created.get("80001")))
            check("查无此人的单标 False",
                  created.get("80003", {}).get("designer_matched") is False,
                  str(created.get("80003")))

            # ------------------------------------------------------------------
            section("⑥ 落库校验")
            # ------------------------------------------------------------------
            from app.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                designers = (await db.execute(select(SlDesigner))).scalars().all()
                orders = (await db.execute(select(SlOrder))).scalars().all()
                check("本地 1 个设计师", len(designers) == 1, str(len(designers)))
                check("本地 3 笔订单", len(orders) == 3, str(len(orders)))
                d = designers[0]
                check("upstream_id 已落库", d.upstream_id == "90001", d.upstream_id)
                check("战区留空", not d.war_zone, repr(d.war_zone))
                check("HR 留空", not d.hr_id, repr(d.hr_id))
                check("临时密码已设", bool(d.password_hash), "空")
                check("首登必须改密", d.must_change_password is True, str(d.must_change_password))
                o = [x for x in orders if x.upstream_id == "80001"][0]
                check("订单金额正确", Decimal(str(o.order_amount)) == Decimal("100.00"),
                      str(o.order_amount))
                check("佣金正确", Decimal(str(o.designer_commission)) == Decimal("60.00"),
                      str(o.designer_commission))
                check("比例正确", Decimal(str(o.commission_rate)) == Decimal("0.6000"),
                      str(o.commission_rate))
                check("状态映射到 settleable", o.state == "settleable", o.state)
                check("订单关联到设计师", o.designer_id == d.id, str(o.designer_id))
                o3 = [x for x in orders if x.upstream_id == "80003"][0]
                check("查无此人的单 designer_id 为空", not o3.designer_id, str(o3.designer_id))

            # ------------------------------------------------------------------
            section("⑦ 非法 kind 被拒")
            # ------------------------------------------------------------------
            resp = await client.post("/api/settle/admin/bridge/import",
                                     json={"kind": "wrong", "limit": 5}, headers=headers)
            check("非法 kind 返回 422", resp.status_code == 422, str(resp.status_code))

        finally:
            settle_router._upstream_client = orig_client
            if old_u is not None:
                os.environ["TRCIPG_USERNAME"] = old_u
            if old_p is not None:
                os.environ["TRCIPG_PASSWORD"] = old_p

    print("\n" + "═" * 68)
    if FAILED:
        print("  结果：%d 通过 / %d 失败" % (PASSED, len(FAILED)))
        for f in FAILED:
            print("    ✗ " + f)
        print("═" * 68)
        return 1
    print("  结果：%d 通过 / 0 失败" % PASSED)
    print("═" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
