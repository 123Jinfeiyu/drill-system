# -*- coding: utf-8 -*-
"""设计师结算系统 · 规则单测。

测的是课件里的每一条规则：模块二录入、模块三登记、模块四流程、
模块五异常、模块六结算条件。纯函数，不碰网络不碰数据库。

跑法：
    cd E:\\drill-system\\backend
    .\\.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_settle_ledger -v
"""
import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import settle_ledger as L  # noqa: E402


def good_designer(**kw):
    base = dict(
        name="陈富灿", nickname="小陈", phone="17737706163",
        alipay_account="17737706163", gender=1,
        recruitment_source="其他", production_level="标准档次",
        password="abc123456",
    )
    base.update(kw)
    return base


def good_order(**kw):
    base = dict(
        customer_id="tb125212883", war_zone="独角兽",
        customer_service="若暖", order_type="personal",
        service_type="PPT定制", order_amount="100.00",
        commission_rate="0.60", deliver_date="2026-11-01",
        order_date="2026-10-20",
    )
    base.update(kw)
    return base


def make_order(state="settleable", **kw):
    base = dict(
        id="o1", order_no="202602443", customer_id="tb125",
        war_zone="独角兽", customer_service="若暖",
        designer_id="d1", designer_name="陈富灿",
        order_type="personal", order_amount="100.00",
        commission_rate="0.60", designer_commission="60.00",
        deliver_date="2026-11-01", order_date="2026-10-20",
        state=state,
        chat_screenshot="chat.png", file_screenshot="file.png",
    )
    base.update(kw)
    return base


class TestDesignerValidation(unittest.TestCase):
    """模块二：录入设计师信息。"""

    def test_valid_form_passes(self):
        self.assertEqual(L.validate_designer(good_designer()), [])

    def test_required_fields(self):
        """课件必填项：姓名、花名、手机号、支付宝账户、性别、招聘来源、制作水平、登录密码。"""
        for field in ("name", "nickname", "phone", "alipay_account",
                      "recruitment_source", "production_level", "password"):
            payload = good_designer()
            payload[field] = ""
            issues = L.validate_designer(payload)
            self.assertTrue(
                any(i.field == field for i in issues),
                f"{field} 为空时应该报错")

    def test_war_zone_must_be_empty(self):
        """课件核心注意：「所属战区」保持为空，切勿填写任何内容。"""
        issues = L.validate_designer(good_designer(war_zone="独角兽"))
        self.assertTrue(any(i.field == "war_zone" for i in issues))
        self.assertIn("切勿填写", issues[0].message)

    def test_hr_must_be_empty(self):
        """课件核心注意：「所属HR」保持为空。"""
        issues = L.validate_designer(good_designer(hr_id="张主管"))
        self.assertTrue(any(i.field == "hr_id" for i in issues))

    def test_phone_format(self):
        issues = L.validate_designer(good_designer(phone="12345"))
        self.assertTrue(any(i.field == "phone" for i in issues))

    def test_password_min_length(self):
        issues = L.validate_designer(good_designer(password="12345"))
        self.assertTrue(any(i.field == "password" for i in issues))

    def test_invalid_production_level_reported(self):
        issues = L.validate_designer(good_designer(production_level="神级"))
        self.assertTrue(any(i.field == "production_level" for i in issues))

    def test_issue_carries_field_and_message(self):
        """前端要按字段定位，所以每条问题必须带字段名。"""
        issues = L.validate_designer(good_designer(name=""))
        self.assertTrue(issues)
        self.assertTrue(issues[0].field)
        self.assertTrue(issues[0].message)


class TestCommission(unittest.TestCase):
    """模块三：佣金结构与核算（50%-70%）。"""

    def test_rate_within_range_ok(self):
        for rate in ("0.50", "0.60", "0.70"):
            self.assertEqual(L.validate_commission_rate(rate), [], f"{rate} 应该合法")

    def test_rate_below_min_rejected(self):
        issues = L.validate_commission_rate("0.40")
        self.assertTrue(issues)
        self.assertIn("下限", issues[0])

    def test_rate_above_max_rejected(self):
        """课件：最高上限 70%，超出须有变动协议。"""
        issues = L.validate_commission_rate("0.80")
        self.assertTrue(issues)
        self.assertIn("上限", issues[0])
        self.assertIn("变动协议", issues[0])

    def test_missing_rate_rejected(self):
        self.assertTrue(L.validate_commission_rate(None))

    def test_calc_commission(self):
        result = L.calc_commission("100.00", "0.60")
        self.assertTrue(result.ok)
        self.assertEqual(result.commission, Decimal("60.00"))

    def test_calc_rounds_to_two_decimals(self):
        result = L.calc_commission("99.99", "0.555")
        self.assertEqual(result.commission, Decimal("55.49"))

    def test_calc_refuses_invalid_rate(self):
        """越界的比例算出来的钱也是错的，宁可不算。"""
        result = L.calc_commission("100.00", "0.90")
        self.assertFalse(result.ok)
        self.assertEqual(result.commission, Decimal("0"))
        self.assertTrue(result.issues)

    def test_decimal_no_float_error(self):
        """浮点路径会丢精度，Decimal 不会。

        0.615 这个比例在 float 下算出 61.49999999999999，
        Decimal 下是 61.50 —— 差一分钱，在结算场景就是事故。
        """
        result = L.calc_commission("100.00", "0.615")
        self.assertTrue(result.ok)
        self.assertEqual(str(result.commission), "61.50")
        # 同样输入走 float 会拿到不一样的结果
        self.assertNotEqual(str(result.commission), str(100.00 * 0.615))


class TestOrderValidation(unittest.TestCase):
    """模块三：登记新订单。"""

    def test_valid_form_passes(self):
        self.assertEqual(L.validate_order(good_order()), [])

    def test_customer_id_required(self):
        """客户 ID 是订单追溯的唯一凭证。"""
        issues = L.validate_order(good_order(customer_id=""))
        self.assertTrue(any(i.field == "customer_id" for i in issues))

    def test_war_zone_required(self):
        issues = L.validate_order(good_order(war_zone=""))
        self.assertTrue(any(i.field == "war_zone" for i in issues))

    def test_customer_service_required(self):
        issues = L.validate_order(good_order(customer_service=""))
        self.assertTrue(any(i.field == "customer_service" for i in issues))

    def test_order_type_required_and_validated(self):
        issues = L.validate_order(good_order(order_type=""))
        self.assertTrue(any(i.field == "order_type" for i in issues))
        issues = L.validate_order(good_order(order_type="unknown"))
        self.assertTrue(any(i.field == "order_type" for i in issues))

    def test_amount_must_be_positive(self):
        issues = L.validate_order(good_order(order_amount="0"))
        self.assertTrue(any(i.field == "order_amount" for i in issues))

    def test_deliver_date_required(self):
        issues = L.validate_order(good_order(deliver_date=""))
        self.assertTrue(any(i.field == "deliver_date" for i in issues))

    def test_order_no_optional(self):
        """课件：订单编号在初稿完成后补充录入，登记时可以为空。"""
        issues = L.validate_order(good_order(order_no=""))
        self.assertFalse(any(i.field == "order_no" for i in issues))

    def test_order_no_format_checked_when_present(self):
        issues = L.validate_order(good_order(order_no="abc"))
        self.assertTrue(any(i.field == "order_no" for i in issues))

    def test_commission_rate_issue_attached(self):
        issues = L.validate_order(good_order(commission_rate="0.9"))
        self.assertTrue(any(i.field == "commission_rate" for i in issues))


class TestTransitions(unittest.TestCase):
    """模块四：订单流程管理。"""

    def test_dispatch_does_not_require_order_no(self):
        """派单（设计待定 → 初稿制作中）不需要编号。

        编号是**初稿完成后**才补的（模块四节点一），
        派单时还没有编号，所以这里不能卡人。
        """
        order = make_order("pending_design", order_no="")
        self.assertEqual(L.check_transition(order, "drafting"), [])

    def test_finalizing_requires_order_no(self):
        """节点一：初稿完成后必须更新订单编号。"""
        order = make_order("drafting", order_no="")
        issues = L.check_transition(order, "finalizing")
        self.assertTrue(any("订单编号" in i for i in issues))

    def test_finalizing_ok_with_number(self):
        order = make_order("drafting", order_no="DR-2026-001")
        self.assertEqual(L.check_transition(order, "finalizing"), [])

    def test_finalizing_rejects_bad_number(self):
        order = make_order("drafting", order_no="ab")
        issues = L.check_transition(order, "finalizing")
        self.assertTrue(any("格式不正确" in i for i in issues))

    def test_audit_requires_two_screenshots(self):
        """节点二：终稿完成后的交付验收，两类截图缺一不可。"""
        order = make_order("finalizing", chat_screenshot="", file_screenshot="")
        issues = L.check_transition(order, "pending_audit")
        self.assertTrue(any("聊天记录" in i for i in issues))
        self.assertTrue(any("交付文件" in i for i in issues))

    def test_audit_requires_chat_screenshot(self):
        order = make_order("finalizing", chat_screenshot="")
        issues = L.check_transition(order, "pending_audit")
        self.assertTrue(any("聊天记录" in i for i in issues))
        self.assertFalse(any("交付文件" in i for i in issues))

    def test_audit_requires_file_screenshot(self):
        order = make_order("finalizing", file_screenshot="")
        issues = L.check_transition(order, "pending_audit")
        self.assertTrue(any("交付文件" in i for i in issues))

    def test_audit_ok_with_both(self):
        order = make_order("finalizing")
        self.assertEqual(L.check_transition(order, "pending_audit"), [])

    def test_cannot_skip_stage(self):
        """跳阶段一律不允许。"""
        order = make_order("pending_design")
        issues = L.check_transition(order, "settleable")
        self.assertTrue(issues)
        self.assertIn("不能从", issues[0])

    def test_settleable_checks_validity(self):
        old = make_order("pending_audit", order_date="2026-01-01")
        issues = L.check_transition(old, "settleable")
        self.assertTrue(any("超过两个月" in i for i in issues))

    def test_transition_graph_complete(self):
        for state in L.ORDER_STATES:
            for target in L.next_states(state):
                self.assertIn(target, L.ORDER_STATES, f"{state}→{target} 目标状态不存在")
                self.assertTrue(L.can_transition(state, target))

    def test_rejected_goes_back_to_finalizing(self):
        """审核驳回 → 回到终稿制作中改稿，不是回到初稿。"""
        self.assertIn("finalizing", L.next_states("rejected"))

    def test_upstream_status_mapping_round_trip(self):
        """本地状态与上游 status 必须能对上，否则「两系统互通」是空话。"""
        for upstream, local in L.UPSTREAM_STATUS_TO_LOCAL.items():
            self.assertIn(local, L.ORDER_STATES)
            # 反向翻译后至少要落回同一族状态
            back = L.upstream_status_from_local(local)
            self.assertIn(back, L.UPSTREAM_STATUS_TO_LOCAL)

    def test_unknown_upstream_status_is_conservative(self):
        """未知上游状态一律落「待审核」，不能猜成已完结。"""
        self.assertEqual(L.local_state_from_upstream(999), "pending_audit")
        self.assertEqual(L.local_state_from_upstream(0), "pending_audit")


class TestSettleConditions(unittest.TestCase):
    """模块六：设计师结算条件。"""

    def test_window_open_on_8th(self):
        window = L.settle_window(date(2026, 10, 8))
        self.assertTrue(window.open)

    def test_window_open_on_9th(self):
        window = L.settle_window(date(2026, 10, 9))
        self.assertTrue(window.open)

    def test_window_closed_on_10th(self):
        window = L.settle_window(date(2026, 10, 10))
        self.assertFalse(window.open)
        self.assertIn("未开放", window.message)

    def test_window_closed_on_7th(self):
        window = L.settle_window(date(2026, 10, 7))
        self.assertFalse(window.open)
        self.assertEqual(window.days_until_open, 1)

    def test_window_open_today_message(self):
        window = L.settle_window(date(2026, 10, 8))
        self.assertIn("开放中", window.message)

    def test_payout_day_is_15(self):
        window = L.settle_window(date(2026, 10, 1))
        self.assertEqual(window.payout_day, 15)
        self.assertEqual(window.days_until_payout, 14)

    def test_payout_day_rolls_to_next_month(self):
        window = L.settle_window(date(2026, 10, 20))
        self.assertGreater(window.days_until_payout, 0)
        self.assertLessEqual(window.days_until_payout, 31)

    def test_valid_within_60_days(self):
        order = make_order(order_date=(date.today() - timedelta(days=30)).isoformat())
        self.assertEqual(L.check_settle_eligibility(order), [])

    def test_invalid_beyond_60_days(self):
        """课件：接单时间必须两个月内，超出无法进入结算。"""
        order = make_order(order_date=(date.today() - timedelta(days=61)).isoformat())
        issues = L.check_settle_eligibility(order)
        self.assertTrue(issues)
        self.assertIn("超过两个月", issues[0])

    def test_exactly_60_days_still_valid(self):
        order = make_order(order_date=(date.today() - timedelta(days=60)).isoformat())
        self.assertEqual(L.check_settle_eligibility(order), [])

    def test_missing_order_date_reported(self):
        issues = L.check_settle_eligibility(make_order(order_date=""))
        self.assertTrue(issues)

    def test_settle_eligible_orders_explains(self):
        orders = [
            make_order("settleable", id="a", order_date=date.today().isoformat()),
            make_order("settleable", id="b",
                       order_date=(date.today() - timedelta(days=90)).isoformat()),
            make_order("drafting", id="c", order_date=date.today().isoformat()),
        ]
        rows = L.settle_eligible_orders(orders)
        by_id = {r["order_id"]: r for r in rows}
        self.assertTrue(by_id["a"]["eligible"])
        self.assertFalse(by_id["b"]["eligible"])
        self.assertFalse(by_id["c"]["eligible"])
        self.assertTrue(by_id["b"]["reasons"])
        self.assertTrue(by_id["c"]["reasons"])


class TestExceptions(unittest.TestCase):
    """模块五：六大常见异常。"""

    def test_amount_mismatch(self):
        order = make_order(order_amount="100.00")
        issues = L.diagnose_order(order, "120.00")
        kinds = {i["kind"] for i in issues}
        self.assertIn("amount_mismatch", kinds)

    def test_order_no_invalid_format(self):
        order = make_order(order_no="ab")
        kinds = {i["kind"] for i in L.diagnose_order(order)}
        self.assertIn("order_no_missing", kinds)

    def test_missing_order_no(self):
        order = make_order(order_no="")
        kinds = {i["kind"] for i in L.diagnose_order(order)}
        self.assertIn("draft_no_missing", kinds)

    def test_internal_order_without_war_zone(self):
        order = make_order(order_type="internal", war_zone="")
        kinds = {i["kind"] for i in L.diagnose_order(order)}
        self.assertIn("business_scope", kinds)

    def test_commission_rate_out_of_range(self):
        order = make_order(commission_rate="0.90")
        kinds = {i["kind"] for i in L.diagnose_order(order)}
        self.assertIn("commission_mismatch", kinds)

    def test_commission_amount_mismatch(self):
        order = make_order(order_amount="100.00", commission_rate="0.60",
                           designer_commission="50.00")
        kinds = {i["kind"] for i in L.diagnose_order(order)}
        self.assertIn("commission_mismatch", kinds)

    def test_unconfirmed_draft(self):
        order = make_order(chat_screenshot="", file_screenshot="")
        kinds = {i["kind"] for i in L.diagnose_order(order)}
        self.assertIn("draft_unconfirmed", kinds)

    def test_clean_order_no_exception(self):
        order = make_order()
        self.assertEqual(L.diagnose_order(order), [])

    def test_every_issue_has_action(self):
        """课件通用处理原则：每条问题都要有处理方案。"""
        order = make_order(order_no="", chat_screenshot="", file_screenshot="",
                           order_amount="100.00", commission_rate="0.9")
        for issue in L.diagnose_order(order, "200.00"):
            self.assertTrue(issue.get("action"), f"{issue['kind']} 缺处理方案")
            self.assertTrue(issue.get("label"))

    def test_six_cases_defined(self):
        self.assertEqual(len(L.EXCEPTION_CASES), 6)


class TestDeletable(unittest.TestCase):
    """模块五：退款/删除规则。"""

    def test_pending_design_deletable(self):
        ok, _ = L.check_deletable(make_order("pending_design"))
        self.assertTrue(ok)

    def test_drafting_deletable(self):
        ok, _ = L.check_deletable(make_order("drafting"))
        self.assertTrue(ok)

    def test_finalizing_deletable(self):
        """终稿制作中仍算「制作中」，可以直接删。"""
        ok, _ = L.check_deletable(make_order("finalizing"))
        self.assertTrue(ok)

    def test_pending_audit_not_deletable(self):
        ok, reason = L.check_deletable(make_order("pending_audit"))
        self.assertFalse(ok)
        self.assertTrue(reason)

    def test_settled_not_deletable(self):
        ok, reason = L.check_deletable(make_order("settled"))
        self.assertFalse(ok)
        self.assertIn("结算", reason)

    def test_settleable_not_deletable(self):
        ok, _ = L.check_deletable(make_order("settleable"))
        self.assertFalse(ok)


class TestStats(unittest.TestCase):
    """看板统计。"""

    def test_funnel_counts_and_amounts(self):
        orders = [
            make_order("pending_design", order_amount="100.00"),
            make_order("drafting", order_amount="200.00"),
            make_order("settled", order_amount="300.00"),
        ]
        rows = L.order_funnel(orders)
        by_state = {r["state"]: r for r in rows}
        self.assertEqual(by_state["pending_design"]["count"], 1)
        self.assertEqual(by_state["drafting"]["amount"], "200.00")
        self.assertEqual(by_state["settled"]["count"], 1)

    def test_funnel_covers_mainline(self):
        rows = L.order_funnel([])
        self.assertEqual(len(rows), len(L.ORDER_MAINLINE))

    def test_remind_designers(self):
        """可结算但未结算的都要提醒。"""
        orders = [make_order("settleable", designer_id="d1", designer_name="陈富灿",
                             order_date=date.today().isoformat())]
        designers = [{"id": "d1", "name": "陈富灿", "phone": "17737706163"}]
        rows = L.remind_designers(orders, designers)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["designer_name"], "陈富灿")
        self.assertEqual(rows[0]["order_count"], 1)
        self.assertEqual(rows[0]["commission"], "60.00")

    def test_remind_excludes_non_settleable(self):
        orders = [make_order("drafting", designer_id="d1")]
        designers = [{"id": "d1", "name": "陈富灿"}]
        self.assertEqual(L.remind_designers(orders, designers), [])

    def test_remind_marks_expired(self):
        orders = [make_order("settleable", designer_id="d1",
                             order_date=(date.today() - timedelta(days=100)).isoformat())]
        designers = [{"id": "d1", "name": "陈富灿"}]
        rows = L.remind_designers(orders, designers)
        self.assertTrue(rows[0]["expired"])

    def test_settlement_summary(self):
        rows = [
            {"status": "pending", "commission": "100.00", "designer_name": "A"},
            {"status": "paid", "commission": "200.00", "designer_name": "A"},
            {"status": "invalid", "commission": "50.00", "designer_name": "B"},
        ]
        summary = L.settlement_summary(rows)
        self.assertEqual(summary["pending_count"], 1)
        self.assertEqual(summary["pending_amount"], "100.00")
        self.assertEqual(summary["paid_amount"], "200.00")
        self.assertEqual(summary["invalid_count"], 1)
        self.assertEqual(len(summary["by_designer"]), 2)

    def test_summary_sorted_by_amount(self):
        rows = [
            {"status": "pending", "commission": "10.00", "designer_name": "A"},
            {"status": "pending", "commission": "90.00", "designer_name": "B"},
        ]
        summary = L.settlement_summary(rows)
        self.assertEqual(summary["by_designer"][0]["designer_name"], "B")


class TestDictionaries(unittest.TestCase):
    def test_meta_has_everything(self):
        data = L.dictionaries()
        for key in ("states", "mainline", "transitions", "order_types",
                    "production_levels", "genders", "recruitment_sources",
                    "commission_rate", "settle_window_days", "payout_day",
                    "exception_cases"):
            self.assertIn(key, data)

    def test_commission_text_mentions_bounds(self):
        text = L.dictionaries()["commission_rate"]["text"]
        self.assertIn("50%", text)
        self.assertIn("70%", text)

    def test_state_labels_complete(self):
        for state in L.ORDER_STATES:
            self.assertIn(state, L.STATE_LABELS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
