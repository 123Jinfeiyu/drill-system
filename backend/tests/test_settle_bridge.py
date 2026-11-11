"""互通桥接层单测：上游 → 本地的翻译规则。

这些规则都是「不能靠肉眼保证」的：
- 战区/HR 必须留空（上游有值也不能带过来）
- 手机号是登录账号，格式不对必须挡住
- 佣金比例是**反推**的，越界要标出来
- 幂等：重复导入不能产生第二条
"""
from __future__ import annotations

import os
import unittest
from decimal import Decimal

from app.services import settle_bridge as B
from app.services.trcipg_client import UpstreamDesigner, UpstreamOrder


def make_designer(**kw) -> UpstreamDesigner:
    base = dict(
        id=1001, name="陈富灿", nickname="小陈", phone="17737706163",
        alipay_account="17737706163@qq.com", war_zone="独角兽",
        production_level="标准档次", recruitment_source="其他",
        hr_name="若暖", quality_control_name="张三",
        design_supervisor_name="李四", allow_settlement=1, status=1,
        designer_type=1,
    )
    base.update(kw)
    return UpstreamDesigner(**base)


def make_order(**kw) -> UpstreamOrder:
    base = dict(
        id=2001, sn="SN-2026-001", order_sn="ORD-2026-001",
        order_desc="按客户模板改 10 页 PPT", customer_name="tb125212883",
        store_name="某某旗舰店", store_account="tb125212883",
        war_zone_name="独角兽", designer_id=1001, designer_name="陈富灿",
        user_name="若暖", customer_service="若暖",
        order_grade="PPT定制", order_type=0, status=5,
        order_commission=Decimal("100.00"),
        designer_commission=Decimal("60.00"),
        hr_commission=Decimal("20.00"),
        quality_control_commission=Decimal("10.00"),
        middle_control_commission=Decimal("10.00"),
        design_supervisor_bonus=Decimal("5.00"),
        request_delivery_time="2026-11-01", order_time="2026-10-20",
        created_at="2026-10-20 10:00:00",
    )
    base.update(kw)
    return UpstreamOrder(**base)


class TestDesignerMapping(unittest.TestCase):
    """上游设计师 → 本地档案。"""

    def test_basic_fields_mapped(self):
        row = B.designer_to_local(make_designer())
        self.assertEqual(row["upstream_id"], "1001")
        self.assertEqual(row["name"], "陈富灿")
        self.assertEqual(row["nickname"], "小陈")
        self.assertEqual(row["phone"], "17737706163")
        self.assertEqual(row["production_level"], "标准档次")

    def test_war_zone_not_imported(self):
        """课件要求战区留空 —— 上游有值也不能带过来。"""
        row = B.designer_to_local(make_designer(war_zone="独角兽"))
        self.assertEqual(row.get("war_zone", ""), "")

    def test_hr_not_imported(self):
        """课件要求 HR 留空。"""
        row = B.designer_to_local(make_designer(hr_name="若暖"))
        self.assertEqual(row.get("hr_id", ""), "")

    def test_disabled_designer_marked(self):
        """上游 status=0 = 停用。"""
        row = B.designer_to_local(make_designer(status=0))
        self.assertEqual(row["status"], "disabled")

    def test_enabled_designer(self):
        row = B.designer_to_local(make_designer(status=1))
        self.assertEqual(row["status"], "active")

    def test_settlement_forbidden_noted(self):
        """上游禁止结算的人，备注要留下痕迹。"""
        row = B.designer_to_local(make_designer(allow_settlement=0))
        self.assertIn("allow_settlement=0", row["note"])

    def test_settlement_allowed_no_note(self):
        row = B.designer_to_local(make_designer(allow_settlement=1))
        self.assertEqual(row["note"], "")


class TestDesignerPrecheck(unittest.TestCase):
    """导入前的可导性检查。"""

    def test_valid_designer_pass(self):
        issues = B.check_designer_importable(B.designer_to_local(make_designer()))
        self.assertEqual(issues, [])

    def test_missing_name(self):
        issues = B.check_designer_importable(
            B.designer_to_local(make_designer(name="")))
        self.assertTrue(any("姓名" in i for i in issues))

    def test_missing_phone(self):
        issues = B.check_designer_importable(
            B.designer_to_local(make_designer(phone="")))
        self.assertTrue(any("手机号" in i for i in issues))

    def test_bad_phone_length(self):
        """9 位手机号必须挡住 —— 上游确实有短号。"""
        issues = B.check_designer_importable(
            B.designer_to_local(make_designer(phone="123456789")))
        self.assertTrue(any("11 位" in i for i in issues))

    def test_non_digit_phone(self):
        issues = B.check_designer_importable(
            B.designer_to_local(make_designer(phone="abcdefghijk")))
        self.assertTrue(any("11 位" in i for i in issues))

    def test_disabled_designer_flagged(self):
        issues = B.check_designer_importable(
            B.designer_to_local(make_designer(status=0)))
        self.assertTrue(any("停用" in i for i in issues))

    def test_settlement_forbidden_flagged(self):
        """上游禁结算 —— 是提醒不是拦截，但必须说出来。"""
        issues = B.check_designer_importable(
            B.designer_to_local(make_designer(allow_settlement=0)))
        self.assertTrue(any("禁止" in i for i in issues))


class TestOrderMapping(unittest.TestCase):
    """上游订单 → 本地订单。"""

    def test_amount_and_commission(self):
        row = B.order_to_local(make_order())
        self.assertEqual(row["order_amount"], Decimal("100.00"))
        self.assertEqual(row["designer_commission"], Decimal("60.00"))

    def test_rate_reversed(self):
        """60/100 = 0.6。"""
        row = B.order_to_local(make_order())
        self.assertEqual(row["commission_rate"], Decimal("0.6000"))

    def test_rate_zero_amount_returns_none(self):
        """金额为 0 不能反推 —— 不能拿 0.6 糊弄。"""
        self.assertIsNone(B._rate_of(Decimal("0"), Decimal("60.00")))
        self.assertIsNone(B._rate_of(Decimal("100"), Decimal("0")))

    def test_state_maps_from_upstream_status(self):
        """上游 5=验收成功 → 本地 settleable。"""
        row = B.order_to_local(make_order(status=5))
        self.assertEqual(row["state"], "settleable")

    def test_state_maps_status_1(self):
        """上游 1=初稿制作中 → 本地 drafting。"""
        row = B.order_to_local(make_order(status=1))
        self.assertEqual(row["state"], "drafting")

    def test_unknown_status_conservative(self):
        """未知状态不能瞎猜。"""
        row = B.order_to_local(make_order(status=99))
        self.assertEqual(row["state"], "pending_audit")

    def test_order_no_prefers_order_sn(self):
        row = B.order_to_local(make_order(order_sn="ORD-1", sn="SN-1"))
        self.assertEqual(row["order_no"], "ORD-1")

    def test_order_no_fallback_to_sn(self):
        row = B.order_to_local(make_order(order_sn="", sn="SN-1"))
        self.assertEqual(row["order_no"], "SN-1")

    def test_order_type_mapping(self):
        self.assertEqual(B.order_to_local(make_order(order_type=0))["order_type"],
                         "personal")
        self.assertEqual(B.order_to_local(make_order(order_type=1))["order_type"],
                         "internal")
        self.assertEqual(B.order_to_local(make_order(order_type=2))["order_type"],
                         "external")


class TestOrderPrecheck(unittest.TestCase):
    """订单可导性检查。"""

    def test_valid_order_pass(self):
        issues = B.check_order_importable(B.order_to_local(make_order()))
        self.assertEqual(issues, [])

    def test_missing_order_no(self):
        row = B.order_to_local(make_order(order_sn="", sn=""))
        issues = B.check_order_importable(row)
        self.assertTrue(any("订单编号" in i for i in issues))

    def test_rate_out_of_range_flagged(self):
        """比例 0.30 低于下限 —— 要标出来，但不硬拒（历史遗留单）。"""
        row = B.order_to_local(make_order(
            order_commission=Decimal("100.00"),
            designer_commission=Decimal("30.00"),
        ))
        issues = B.check_order_importable(row)
        self.assertTrue(any("佣金比例越界" in i for i in issues))

    def test_rate_above_max_flagged(self):
        row = B.order_to_local(make_order(
            order_commission=Decimal("100.00"),
            designer_commission=Decimal("80.00"),
        ))
        issues = B.check_order_importable(row)
        self.assertTrue(any("佣金比例越界" in i for i in issues))

    def test_commission_without_amount(self):
        row = B.order_to_local(make_order(
            order_commission=Decimal("0"),
            designer_commission=Decimal("60.00"),
        ))
        issues = B.check_order_importable(row)
        self.assertTrue(any("没有订单金额" in i for i in issues))


class TestRateReversal(unittest.TestCase):
    """比例反推的精度。"""

    def test_decimal_precision_kept(self):
        """33.33/50 = 0.6666，不能变成 0.66666666。"""
        rate = B._rate_of(Decimal("50.00"), Decimal("33.33"))
        self.assertEqual(str(rate), "0.6666")

    def test_exact_ratio(self):
        rate = B._rate_of(Decimal("1000.00"), Decimal("615.00"))
        self.assertEqual(str(rate), "0.6150")

    def test_zero_commission_returns_none(self):
        """佣金为 0 → 比例**未知**，不是 0。

        规则层硬下限是 50%，真实比例不可能是 0；
        佣金为 0 说明上游还没算这笔佣金（数据不全）。
        拿 0 去填会被规则层当成「比例 0，越界」，把数据不全的单说成违规单。
        """
        self.assertIsNone(B._rate_of(Decimal("100.00"), Decimal("0")))

    def test_zero_amount_returns_none(self):
        self.assertIsNone(B._rate_of(Decimal("0"), Decimal("60.00")))


class TestFakeUpstream(unittest.TestCase):
    """本地演示数据源。"""

    def test_disabled_by_default(self):
        """不设环境变量时，走真实上游。"""
        old = os.environ.pop(B.ENV_FAKE_UPSTREAM, None)
        try:
            self.assertFalse(B.fake_upstream_enabled())
        finally:
            if old is not None:
                os.environ[B.ENV_FAKE_UPSTREAM] = old

    def test_enabled_by_env(self):
        old = os.environ.get(B.ENV_FAKE_UPSTREAM)
        os.environ[B.ENV_FAKE_UPSTREAM] = "1"
        try:
            self.assertTrue(B.fake_upstream_enabled())
        finally:
            if old is None:
                os.environ.pop(B.ENV_FAKE_UPSTREAM, None)
            else:
                os.environ[B.ENV_FAKE_UPSTREAM] = old

    def test_fake_data_has_problem_cases(self):
        """演示数据必须**带问题**，否则预览页的两列没东西可看。"""
        designers = B.fake_designers()
        self.assertTrue(len(designers) >= 5)
        # 有一份手机号不对
        self.assertTrue(any(len(d.phone) != 11 for d in designers))
        # 有一个已停用
        self.assertTrue(any(d.status == 0 for d in designers))
        # 有一个禁止结算
        self.assertTrue(any(not d.can_settle for d in designers))

        orders = B.fake_orders()
        self.assertTrue(len(orders) >= 4)
        # 有一笔比例越界
        self.assertTrue(any(
            B.order_to_local(o)["commission_rate"] < B.ledger.COMMISSION_RATE_MIN
            for o in orders))
        # 有一笔找不到设计师
        self.assertTrue(any(
            o.designer_name and o.designer_name not in
            {d.name for d in designers} for o in orders))


class TestFakeClientSignature(unittest.TestCase):
    """假客户端的接口签名必须跟真客户端一致 —— 否则换过去就炸。"""

    def test_same_methods(self):
        from app.services.trcipg_client import TrcipgClient
        for name in ("list_designer_detail", "list_orders"):
            self.assertTrue(hasattr(B.FakeUpstreamClient, name),
                            "FakeUpstreamClient 缺 %s" % name)
            self.assertTrue(hasattr(TrcipgClient, name),
                            "TrcipgClient 缺 %s" % name)

    def test_fake_client_returns_tuples(self):
        import asyncio
        client = B.FakeUpstreamClient()

        async def pull():
            designers, total = await client.list_designer_detail(page=1, num=50)
            orders, ototal = await client.list_orders(page=1, num=50)
            return designers, total, orders, ototal

        designers, total, orders, ototal = asyncio.run(pull())
        self.assertIsInstance(total, int)
        self.assertTrue(all(isinstance(d, UpstreamDesigner) for d in designers))
        self.assertIsInstance(ototal, int)
        self.assertTrue(all(isinstance(o, UpstreamOrder) for o in orders))


if __name__ == "__main__":
    unittest.main()
