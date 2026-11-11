# -*- coding: utf-8 -*-
"""OPC · 上游连接层规则单测。

测的是**纯函数**部分：状态映射、分账拆分、需求合同生成、撮合打分、对账。
不碰网络、不碰数据库 —— 这些规则必须能在没有上游的情况下被守住。

跑法：
    cd E:\\drill-system\\backend
    .\\.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_opc_upstream -v
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import opc_sync as sync  # noqa: E402
from app.services.trcipg_client import (UpstreamDesigner,  # noqa: E402
                                         UpstreamOrder, UpstreamSettlement,
                                         to_decimal)


def make_order(**kw) -> UpstreamOrder:
    base = dict(
        id=2443, sn="202602443", order_sn="5127739632007081020",
        order_desc="这个PPT按格式调整下，融合客户的视频",
        customer_name="18957420969+许凤",
        store_id=10, store_name="再飞", store_account="金丝猴团队",
        war_zone_name="独角兽",
        designer_id=951, designer_name="苟彭伟",
        order_grade="标准档次", order_type=1, status=5,
        order_commission=Decimal("35.00"),
        designer_commission=Decimal("15.00"),
        middle_control_commission=Decimal("20.00"),
        design_supervisor_bonus=Decimal("1.45"),
        request_delivery_time="2026-09-25",
        sample_manuscript_time="2026-09-24",
        final_draft_time="2026-09-25",
    )
    base.update(kw)
    return UpstreamOrder(**base)


def make_designer(**kw) -> UpstreamDesigner:
    base = dict(
        id=1501, name="陈富灿", nickname="小陈", phone="17737706163",
        alipay_account="17737706163", war_zone="独角兽",
        production_level="标准档次", allow_settlement=1, status=1,
    )
    base.update(kw)
    return UpstreamDesigner(**base)


class TestDecimalSafety(unittest.TestCase):
    """金额必须是 Decimal —— 浮点在结算场景会差一分钱。"""

    def test_to_decimal_from_string(self):
        self.assertEqual(to_decimal("35.00"), Decimal("35.00"))
        self.assertEqual(to_decimal("0"), Decimal("0"))
        self.assertEqual(to_decimal(""), Decimal("0"))
        self.assertEqual(to_decimal(None), Decimal("0"))

    def test_to_decimal_garbage_does_not_raise(self):
        """脏数据不能把整个页面搞挂。"""
        self.assertEqual(to_decimal("abc"), Decimal("0"))
        self.assertEqual(to_decimal("--"), Decimal("0"))

    def test_float_precision_preserved(self):
        """35.10 必须精确等于 35.10，而不是 float 的 35.09999...。

        断言用 ``str()`` 比字符串而不是比数值 ——
        ``Decimal('35.10') == Decimal('35.1')`` 在数值上是 True（都是 35.1），
        但**量化指数不同**，落库与对账时表现不一样，所以要比字符串。
        """
        v = to_decimal("35.10")
        self.assertEqual(str(v), "35.10")
        # float 路径会丢精度
        self.assertNotEqual(str(Decimal(str(35.10))), "35.10")


class TestStateMapping(unittest.TestCase):
    """上游 9 态 → OPC 状态机。方向错了会提前放款。"""

    def test_all_upstream_states_mapped(self):
        for s in range(1, 10):
            self.assertIn(s, sync.UPSTREAM_TO_OPC_STATE, f"状态 {s} 没映射")

    def test_production_states(self):
        self.assertEqual(sync.map_upstream_state(1), "drafting")
        self.assertEqual(sync.map_upstream_state(2), "finalizing")

    def test_review_states_never_auto_accepted(self):
        """验收中/问题待审核 都必须落在 pending_review，不能放行。"""
        for s in (3, 4, 8):
            self.assertEqual(sync.map_upstream_state(s), "pending_review")

    def test_problem_states_go_back_to_drafting(self):
        for s in (6, 7):
            self.assertEqual(sync.map_upstream_state(s), "drafting")

    def test_accepted_but_not_settled(self):
        """验收成功 ≠ 已结算。"""
        self.assertEqual(sync.map_upstream_state(5), "delivered")

    def test_unknown_state_is_conservative(self):
        """未知状态必须保守 —— 停在 pending_review，不能落到 delivered。"""
        for s in (0, 99, -1, 100):
            self.assertEqual(sync.map_upstream_state(s), "pending_review")

    def test_mapped_states_are_valid_opc_states(self):
        from app.services.opc_ledger import ORDER_STATES
        for s in sync.UPSTREAM_TO_OPC_STATE.values():
            self.assertIn(s, ORDER_STATES, f"{s} 不在 OPC 状态机里")

    def test_settlement_status_labels(self):
        self.assertEqual(sync.map_settlement_status(0), "待结算")
        self.assertEqual(sync.map_settlement_status(2), "已结算")


class TestSplitExtraction(unittest.TestCase):
    """上游五项佣金 → 分账结构。"""

    def test_extract_all_five(self):
        order = make_order(
            hr_commission=Decimal("5.00"),
            quality_control_commission=Decimal("2.00"),
        )
        split = sync.extract_upstream_split(order)
        self.assertEqual(split.total, Decimal("35.00"))
        self.assertEqual(split.designer, Decimal("15.00"))
        self.assertEqual(split.hr, Decimal("5.00"))
        self.assertEqual(split.quality_control, Decimal("2.00"))
        self.assertEqual(split.supervisor, Decimal("1.45"))
        self.assertEqual(split.control, Decimal("20.00"))

    def test_residual_detects_mismatch(self):
        """上游五项加不出总额 → residual 非 0，要在对账里报出来。"""
        order = make_order(designer_commission=Decimal("10.00"))
        split = sync.extract_upstream_split(order)
        self.assertNotEqual(split.residual, Decimal("0.00"))

    def test_balanced_split_has_zero_residual(self):
        """真实上游口径：designer + control + hr + qc == order。

        主管奖金是**额外支出**，不算进 residual ——
        算进去会凭空造出一笔差额，把正常单子全标成异常。
        """
        order = make_order(
            designer_commission=Decimal("15.00"),
            hr_commission=Decimal("0.00"),
            quality_control_commission=Decimal("0.00"),
            design_supervisor_bonus=Decimal("1.45"),
            middle_control_commission=Decimal("20.00"),
            order_commission=Decimal("35.00"),
        )
        split = sync.extract_upstream_split(order)
        self.assertEqual(split.residual, Decimal("0.00"))
        self.assertTrue(split.is_balanced)
        # 主管奖金是独立的，不参与分配
        self.assertEqual(split.supervisor, Decimal("1.45"))
        self.assertEqual(split.allocated, Decimal("35.00"))

    def test_hr_and_qc_participate_in_balance(self):
        """上游实测：有 HR/品控佣金时，四项才凑得齐总额。"""
        order = make_order(
            designer_commission=Decimal("35.70"),
            hr_commission=Decimal("1.78"),
            quality_control_commission=Decimal("0.00"),
            design_supervisor_bonus=Decimal("35.70"),
            middle_control_commission=Decimal("13.52"),
            order_commission=Decimal("51.00"),
        )
        split = sync.extract_upstream_split(order)
        self.assertEqual(split.residual, Decimal("0.00"))
        self.assertTrue(split.is_balanced)

    def test_supervisor_does_not_break_balance(self):
        """主管奖金再大也不该让单子变成不平衡。"""
        order = make_order(
            designer_commission=Decimal("15.00"),
            middle_control_commission=Decimal("20.00"),
            design_supervisor_bonus=Decimal("99.99"),
            order_commission=Decimal("35.00"),
        )
        split = sync.extract_upstream_split(order)
        self.assertEqual(split.residual, Decimal("0.00"))

    def test_as_dict_all_strings(self):
        """给前端的必须是字符串，Decimal 直接序列化会变 float。"""
        d = sync.extract_upstream_split(make_order()).as_dict()
        for k, v in d.items():
            if k == "balanced":
                self.assertIsInstance(v, bool)
            else:
                self.assertIsInstance(v, str, f"{k} 不是字符串")


class TestSpecDraft(unittest.TestCase):
    """六段式需求合同草稿 —— 只用真实字段，不编造。"""

    def test_has_all_six_sections(self):
        spec = sync.build_spec_from_upstream(make_order())
        for section in ("目标", "范围", "非目标", "约束", "验收标准", "完成定义"):
            self.assertIn(f"## {section}", spec, f"缺 {section}")

    def test_uses_real_fields(self):
        spec = sync.build_spec_from_upstream(make_order())
        self.assertIn("标准档次", spec)
        self.assertIn("再飞", spec)
        self.assertIn("2026-09-25", spec)

    def test_missing_info_marked_not_fabricated(self):
        """上游没有的信息必须写「需补」，不能编。"""
        order = make_order(order_desc="", store_name="", order_grade="",
                           request_delivery_time="")
        spec = sync.build_spec_from_upstream(order)
        self.assertIn("需补", spec)
        self.assertNotIn("目标\n\n\n", spec)

    def test_spec_is_valid_markdown(self):
        from app.services.opc_ledger import parse_spec
        spec = sync.build_spec_from_upstream(make_order())
        sections = parse_spec(spec)
        for s in ("目标", "范围", "非目标", "约束", "验收标准", "完成定义"):
            self.assertIn(s, sections)


class TestReconcile(unittest.TestCase):
    """对账 —— 只报告差异，不自动改上游。"""

    def test_matching_commission_no_issue(self):
        order = make_order()
        issues = sync.reconcile_order(order, Decimal("35.00"))
        self.assertEqual(issues, [])

    def test_mismatch_reported(self):
        order = make_order()
        issues = sync.reconcile_order(order, Decimal("30.00"))
        kinds = [i.kind for i in issues]
        self.assertIn("commission_mismatch", kinds)
        issue = next(i for i in issues if i.kind == "commission_mismatch")
        self.assertEqual(issue.upstream, "35.00")
        self.assertEqual(issue.opc, "30.00")

    def test_not_synced_is_not_issue(self):
        """OPC 里还没这条 → 只是没同步，不算差异。"""
        issues = sync.reconcile_order(make_order(), None)
        self.assertEqual(issues, [])

    def test_residual_reported(self):
        order = make_order(designer_commission=Decimal("10.00"))
        issues = sync.reconcile_order(order, Decimal("35.00"))
        kinds = {i.kind for i in issues}
        self.assertIn("split_residual", kinds)

    def test_settlement_mismatch(self):
        st = UpstreamSettlement(id=1, order_id=2443, sn="202602443",
                                commission=Decimal("15.00"))
        issues = sync.reconcile_settlement(st, Decimal("12.00"))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "settlement_commission_mismatch")

    def test_report_aggregates(self):
        orders = [make_order(), make_order(id=2, sn="20260002")]
        settlements = [UpstreamSettlement(id=1, order_id=2443, sn="202602443",
                                          commission=Decimal("15.00"))]
        report = sync.build_report(orders, settlements, {}, {})
        self.assertEqual(report.checked_orders, 2)
        self.assertEqual(report.checked_settlements, 1)
        self.assertEqual(report.upstream_total_commission, Decimal("70.00"))
        # 结算单佣金单独记，不与订单佣金混加
        self.assertEqual(report.upstream_settlement_commission, Decimal("15.00"))
        # 台账里没有对应记录 → 不算差异，但上游总额仍然统计
        self.assertTrue(report.ok)

    def test_two_commission_scales_not_mixed(self):
        """订单佣金与结算单佣金是两个口径，不能加在一起。"""
        orders = [make_order()]           # order_commission = 35.00
        settlements = [UpstreamSettlement(id=1, order_id=2443, sn="202602443",
                                          commission=Decimal("15.00"))]
        report = sync.build_report(orders, settlements, {}, {})
        self.assertEqual(report.upstream_total_commission, Decimal("35.00"))
        self.assertEqual(report.upstream_settlement_commission, Decimal("15.00"))
        # 绝不能变成 50
        self.assertNotEqual(report.upstream_total_commission, Decimal("50.00"))

    def test_report_detects_issues(self):
        orders = [make_order()]
        report = sync.build_report(orders, [], {"202602443": Decimal("1.00")}, {})
        self.assertFalse(report.ok)
        self.assertGreaterEqual(len(report.issues), 1)


class TestMatching(unittest.TestCase):
    """撮合打分 —— 只用上游真实字段。"""

    def test_perfect_match_scores_high(self):
        order = make_order()
        d = make_designer()
        c = sync.score_designer_for_order(order, d)
        self.assertGreater(c.score, 3.0)
        self.assertEqual(c.blocked, "")

    def test_settlement_disabled_blocked(self):
        """上游禁了结算资格 → 不能派单。"""
        order = make_order()
        d = make_designer(allow_settlement=0)
        c = sync.score_designer_for_order(order, d)
        self.assertNotEqual(c.blocked, "")
        self.assertIn("结算", c.blocked)

    def test_no_alipay_blocked(self):
        order = make_order()
        d = make_designer(alipay_account="")
        c = sync.score_designer_for_order(order, d)
        self.assertNotEqual(c.blocked, "")

    def test_inactive_blocked(self):
        order = make_order()
        d = make_designer(status=0)
        c = sync.score_designer_for_order(order, d)
        self.assertNotEqual(c.blocked, "")

    def test_grade_mismatch_penalized(self):
        """档位不匹配要扣分，但**不是禁止** —— 差档位也能接单。"""
        order = make_order(order_grade="首席档次")
        good = make_designer(production_level="首席档次")
        bad = make_designer(production_level="简单档次")
        score_good = sync.score_designer_for_order(order, good).score
        score_bad = sync.score_designer_for_order(order, bad).score
        self.assertLess(score_bad, score_good)
        self.assertEqual(sync.score_designer_for_order(order, bad).blocked, "")

    def test_war_zone_mismatch_penalized(self):
        """跨战区扣分，但同样不禁止。"""
        order = make_order(war_zone_name="金丝猴")
        good = make_designer(war_zone="金丝猴")
        bad = make_designer(war_zone="独角兽")
        score_good = sync.score_designer_for_order(order, good).score
        score_bad = sync.score_designer_for_order(order, bad).score
        self.assertLess(score_bad, score_good)

    def test_busy_designer_penalized(self):
        order = make_order()
        d = make_designer()
        c = sync.score_designer_for_order(order, d, busy_designer_ids={d.id})
        self.assertLess(c.score, 3.0)

    def test_ranking_puts_blocked_last(self):
        order = make_order()
        good = make_designer(id=1, name="好的")
        bad = make_designer(id=2, name="禁用", allow_settlement=0)
        ranked = sync.rank_designers_for_order(order, [bad, good], limit=10)
        self.assertEqual(ranked[0].designer.id, 1)
        self.assertNotEqual(ranked[-1].blocked, "")

    def test_ranking_respects_limit(self):
        order = make_order()
        ds = [make_designer(id=i, name=f"人{i}") for i in range(1, 21)]
        ranked = sync.rank_designers_for_order(order, ds, limit=5)
        self.assertEqual(len(ranked), 5)

    def test_empty_pool_returns_empty_not_crash(self):
        """候选池不能因为空而崩 —— 这是 AI 推荐模块的老教训。"""
        ranked = sync.rank_designers_for_order(make_order(), [], limit=10)
        self.assertEqual(ranked, [])


class TestMatchTerms(unittest.TestCase):
    def test_terms_include_desc_and_grade(self):
        terms = sync.extract_terms_for_match(make_order())
        self.assertIn("标准档次", terms)
        self.assertIn("再飞", terms)

    def test_terms_skip_empty(self):
        order = make_order(order_desc="", store_name="", customer_name="",
                           store_account="", order_grade="")
        self.assertEqual(sync.extract_terms_for_match(order), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
