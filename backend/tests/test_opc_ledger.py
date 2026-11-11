"""OPC 一人公司系统 · 规则层单元测试。

测**纯函数**，不依赖服务、不碰数据库 —— 与 FDE 的 test_fde_ledger.py 同口径。

用法：
    python -X utf8 -m unittest tests.test_opc_ledger -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import opc_ledger as ledger  # noqa: E402


def _dt(offset_minutes: int = 0) -> datetime:
    base = datetime(2026, 10, 20, 10, 0, 0)
    return base + timedelta(minutes=offset_minutes)


class TestSpec(unittest.TestCase):
    """需求单六段式。"""

    GOOD = """# 订单需求单 · X-001

## 目标
做 5 张主图。

## 范围
5 张 800×800。

## 非目标
不做详情页。

## 约束
改稿不超过 2 轮。

## 验收标准
尺寸达标。

## 完成定义
客户确认。
"""

    def test_parse_sections(self):
        parsed = ledger.parse_spec(self.GOOD)
        # 六段必须齐全（标题行本身也是一个 section，不必清掉）
        for s in ledger.SPEC_SECTIONS:
            self.assertIn(s, parsed)
        self.assertIn("5 张 800×800", parsed["范围"])
        self.assertNotIn("订单需求单 · X-001", parsed)

    def test_parse_keeps_unknown_heading(self):
        parsed = ledger.parse_spec(self.GOOD + "\n## 附录\n补充说明\n")
        self.assertIn("附录", parsed)
        self.assertIn("补充说明", parsed["附录"])

    def test_validate_ok(self):
        self.assertEqual(ledger.validate_spec(self.GOOD), [])

    def test_validate_missing_sections(self):
        issues = ledger.validate_spec("# 标题\n\n随便写点\n")
        self.assertEqual(len(issues), len(ledger.SPEC_SECTIONS))
        for s in ledger.SPEC_SECTIONS:
            self.assertTrue(any(s in i for i in issues), f"缺 {s} 未报出")

    def test_validate_empty_section(self):
        text = self.GOOD.replace("## 非目标\n不做详情页。", "## 非目标\n\n")
        issues = ledger.validate_spec(text)
        self.assertTrue(any("非目标" in i and "为空" in i for i in issues), issues)

    def test_validate_empty_text(self):
        self.assertEqual(len(ledger.validate_spec("")), len(ledger.SPEC_SECTIONS))

    def test_template_is_valid(self):
        """模板自带的占位说明也应通过结构校验（结构合格 ≠ 想清楚了）。"""
        self.assertEqual(ledger.validate_spec(ledger.SPEC_TEMPLATE), [])

    def test_heading_variants(self):
        """允许写成「目标：」这种带冒号的变体。"""
        text = (
            "## 目标\nA\n## 范围\nB\n## 非目标\nC\n"
            "## 约束\nD\n## 验收标准\nE\n## 完成定义\nF\n"
        )
        self.assertEqual(ledger.validate_spec(text), [])


class TestStateMachine(unittest.TestCase):
    """订单状态机。"""

    def test_happy_path(self):
        path = ["assigned", "taken", "drafting", "finalizing",
                "pending_review", "delivered", "pending_settle", "settled"]
        state = "pending_assign"
        for nxt in path:
            self.assertTrue(ledger.can_transition(state, nxt),
                            f"{state} -> {nxt} 应允许")
            state = nxt
        self.assertTrue(ledger.is_terminal(state))

    def test_skip_stage_rejected(self):
        self.assertFalse(ledger.can_transition("pending_assign", "delivered"))
        self.assertFalse(ledger.can_transition("taken", "settled"))
        self.assertFalse(ledger.can_transition("drafting", "settled"))

    def test_unknown_state_has_no_exit(self):
        self.assertEqual(ledger.next_states("不存在的状态"), ())
        self.assertFalse(ledger.can_transition("不存在的状态", "taken"))

    def test_cancel_allowed_from_active(self):
        for s in ("pending_assign", "assigned", "taken", "drafting",
                  "finalizing", "pending_review", "delivered", "pending_settle"):
            self.assertTrue(ledger.can_transition(s, "canceled"), f"{s} 应可取消")

    def test_rework_self_loop(self):
        """drafting 自环 = 返工。"""
        self.assertTrue(ledger.can_transition("drafting", "drafting"))
        self.assertTrue(ledger.can_transition("finalizing", "drafting"))
        self.assertTrue(ledger.can_transition("pending_review", "drafting"))

    def test_terminal_no_exit(self):
        self.assertEqual(ledger.next_states("settled"), ())
        self.assertEqual(ledger.next_states("canceled"), ())

    def test_active_states(self):
        self.assertTrue(ledger.is_active("drafting"))
        self.assertTrue(ledger.is_active("pending_review"))
        self.assertFalse(ledger.is_active("settled"))
        self.assertFalse(ledger.is_active("pending_assign"))

    def test_state_label_fallback(self):
        self.assertEqual(ledger.state_label("drafting"), "初稿制作中")
        self.assertEqual(ledger.state_label("未知"), "未知")

    def test_mainline_covers_all_but_canceled(self):
        self.assertEqual(
            set(ledger.ORDER_MAINLINE),
            set(ledger.ORDER_STATES) - {"canceled"},
        )


class TestEvidenceChain(unittest.TestCase):
    """交付证据链：红 → 改 → 绿，同一命令。"""

    def _rec(self, phase, cmd, rc, minute):
        return {"phase": phase, "command_text": cmd, "return_code": rc,
                "observed_at": _dt(minute)}

    def test_complete_chain(self):
        recs = [
            self._rec("red", "check.py", 1, 0),
            self._rec("diff", "check.py", 0, 5),
            self._rec("green", "check.py", 0, 10),
        ]
        self.assertEqual(ledger.check_evidence_chain(recs), [])
        summary = ledger.chain_summary(recs)
        self.assertTrue(summary["evidence_complete"])
        self.assertEqual(summary["counts"]["red"], 1)
        self.assertEqual(summary["counts"]["diff"], 1)
        self.assertEqual(summary["counts"]["green"], 1)

    def test_missing_red(self):
        recs = [self._rec("diff", "c", 0, 0), self._rec("green", "c", 0, 5)]
        issues = ledger.check_evidence_chain(recs)
        self.assertTrue(any("红灯" in i for i in issues), issues)

    def test_missing_diff(self):
        recs = [self._rec("red", "c", 1, 0), self._rec("green", "c", 0, 5)]
        issues = ledger.check_evidence_chain(recs)
        self.assertTrue(any("返工" in i or "改动" in i for i in issues), issues)

    def test_missing_green(self):
        recs = [self._rec("red", "c", 1, 0), self._rec("diff", "c", 0, 5)]
        issues = ledger.check_evidence_chain(recs)
        self.assertTrue(any("绿灯" in i for i in issues), issues)

    def test_red_with_zero_return_code_is_not_valid(self):
        """红灯必须真的失败过。返回码 0 的红灯不算数。"""
        recs = [
            self._rec("red", "c", 0, 0),
            self._rec("diff", "c", 0, 5),
            self._rec("green", "c", 0, 10),
        ]
        issues = ledger.check_evidence_chain(recs)
        self.assertTrue(any("红灯" in i for i in issues), issues)

    def test_green_with_nonzero_return_code_is_not_valid(self):
        recs = [
            self._rec("red", "c", 1, 0),
            self._rec("diff", "c", 0, 5),
            self._rec("green", "c", 2, 10),
        ]
        issues = ledger.check_evidence_chain(recs)
        self.assertTrue(any("绿灯" in i for i in issues), issues)

    def test_different_command_not_accepted(self):
        recs = [
            self._rec("red", "check.py", 1, 0),
            self._rec("diff", "check.py", 0, 5),
            self._rec("green", "other.py", 0, 10),
        ]
        issues = ledger.check_evidence_chain(recs)
        self.assertTrue(any("同一" in i for i in issues), issues)

    def test_wrong_order_rejected(self):
        """绿灯早于红灯不算数。"""
        recs = [
            self._rec("green", "c", 0, 0),
            self._rec("red", "c", 1, 5),
            self._rec("diff", "c", 0, 10),
        ]
        issues = ledger.check_evidence_chain(recs)
        self.assertTrue(any("顺序" in i for i in issues), issues)

    def test_observation_does_not_count(self):
        recs = [
            self._rec("red", "c", 1, 0),
            self._rec("observation", "c", 0, 5),
            self._rec("green", "c", 0, 10),
        ]
        issues = ledger.check_evidence_chain(recs)
        self.assertTrue(any("返工" in i or "改动" in i for i in issues), issues)

    def test_empty_chain(self):
        issues = ledger.check_evidence_chain([])
        self.assertEqual(len(issues), 3)
        self.assertFalse(ledger.chain_summary([])["evidence_complete"])

    def test_supports_objects(self):
        """同时支持 dict 与带属性的对象。"""
        class Rec:
            def __init__(self, phase, cmd, rc, minute):
                self.phase = phase
                self.command_text = cmd
                self.return_code = rc
                self.observed_at = _dt(minute)

        recs = [Rec("red", "c", 1, 0), Rec("diff", "c", 0, 5), Rec("green", "c", 0, 10)]
        self.assertEqual(ledger.check_evidence_chain(recs), [])


class TestSeparation(unittest.TestCase):
    """责任分离。"""

    def test_human_actor(self):
        self.assertTrue(ledger.is_human_actor("张老板"))
        self.assertFalse(ledger.is_human_actor("agent:bot"))
        self.assertFalse(ledger.is_human_actor("Agent:Bot"))
        self.assertFalse(ledger.is_human_actor(""))
        self.assertFalse(ledger.is_human_actor(None))

    def test_missing_reviewer(self):
        issues = ledger.separation_issues("林小满", "")
        self.assertTrue(any("缺少具名" in i for i in issues), issues)

    def test_machine_reviewer(self):
        issues = ledger.separation_issues("林小满", "agent:x")
        self.assertTrue(any("机器署名" in i for i in issues), issues)

    def test_self_review(self):
        issues = ledger.separation_issues("林小满", "林小满")
        self.assertTrue(any("不能验收自己" in i for i in issues), issues)

    def test_ok(self):
        self.assertEqual(ledger.separation_issues("林小满", "张老板"), [])


class TestGate(unittest.TestCase):
    """结算门禁。"""

    def _gate(self, **kw):
        base = dict(
            state="delivered",
            evidence_complete=True,
            acceptance="accepted",
            designer="林小满",
            reviewer="张老板",
        )
        base.update(kw)
        return ledger.evaluate_gate(**base)

    def test_allowed(self):
        g = self._gate()
        self.assertTrue(g["allowed"])
        self.assertEqual(g["code"], ledger.GATE_ALLOWED)
        self.assertEqual(g["blockers"], [])
        self.assertTrue(g["evidence_complete"])
        self.assertTrue(g["accepted"])

    def test_blocked_on_evidence(self):
        g = self._gate(evidence_complete=False)
        self.assertFalse(g["allowed"])
        self.assertEqual(g["code"], ledger.GATE_BLOCKED)
        self.assertTrue(any("证据链" in b for b in g["blockers"]))

    def test_blocked_on_acceptance(self):
        g = self._gate(acceptance="pending_human_review")
        self.assertFalse(g["allowed"])
        self.assertTrue(any("具名验收" in b for b in g["blockers"]))

    def test_blocked_on_self_review(self):
        g = self._gate(reviewer="林小满")
        self.assertFalse(g["allowed"])

    def test_blocked_on_dependency(self):
        g = self._gate(depends_on=[{"code": "X-001", "acceptance": "pending_human_review"}])
        self.assertFalse(g["allowed"])
        self.assertTrue(any("X-001" in b for b in g["blockers"]))

    def test_dependency_accepted_ok(self):
        g = self._gate(depends_on=[{"code": "X-001", "acceptance": "accepted"}])
        self.assertTrue(g["allowed"])

    def test_evidence_and_acceptance_are_independent(self):
        """证据完整 ≠ 已验收。这两个字段必须独立呈现。"""
        g = self._gate(evidence_complete=True, acceptance="pending_human_review")
        self.assertTrue(g["evidence_complete"])
        self.assertFalse(g["accepted"])
        self.assertFalse(g["allowed"])

    def test_already_settled_passes(self):
        g = self._gate(state="settled", acceptance="pending_human_review",
                       evidence_complete=False)
        self.assertTrue(g["allowed"])


class TestAccept(unittest.TestCase):
    """具名验收。"""

    def _order(self, state="pending_review", designer="林小满"):
        return {"state": state, "designer_name": designer}

    def test_accept_ok(self):
        r = ledger.accept_order(order=self._order(), actor="张老板")
        self.assertTrue(r["ok"])

    def test_reject_machine(self):
        r = ledger.accept_order(order=self._order(), actor="agent:x")
        self.assertFalse(r["ok"])
        self.assertIn("具名的人", r["reason"])

    def test_reject_self(self):
        r = ledger.accept_order(order=self._order(), actor="林小满")
        self.assertFalse(r["ok"])
        self.assertIn("不能验收自己", r["reason"])

    def test_reject_wrong_state(self):
        r = ledger.accept_order(order=self._order(state="drafting"), actor="张老板")
        self.assertFalse(r["ok"])
        self.assertIn("待验收", r["reason"])

    def test_accept_from_delivered_ok(self):
        r = ledger.accept_order(order=self._order(state="delivered"), actor="张老板")
        self.assertTrue(r["ok"])


class TestRepairLoop(unittest.TestCase):
    """有界返工回路。"""

    def _ev(self, kind, to_state, detail="", minute=0):
        return {"kind": kind, "to_state": to_state, "detail": detail,
                "actor": "张老板", "created_at": _dt(minute).isoformat()}

    def test_ready_when_no_rework(self):
        p = ledger.repair_loop_projection([])
        self.assertEqual(p["status"], "ready")
        self.assertEqual(p["rounds"], 0)
        self.assertFalse(p["can_continue"])

    def test_normal_flow_is_not_rework(self):
        """正常接单→初稿不该被算成返工轮次。"""
        evs = [self._ev("transition", "taken", "接单", 0),
               self._ev("transition", "drafting", "开始初稿", 5)]
        p = ledger.repair_loop_projection(evs)
        self.assertEqual(p["rounds"], 0)
        self.assertEqual(p["status"], "ready")

    def test_converged(self):
        evs = [self._ev("evaluate", "drafting", "退回返工：尺寸不足", 0),
               self._ev("transition", "finalizing", "改完了", 10),
               self._ev("transition", "pending_review", "复验通过", 20)]
        p = ledger.repair_loop_projection(evs)
        self.assertEqual(p["rounds"], 1)
        self.assertEqual(p["status"], "converged")
        self.assertEqual(p["history"][0]["issues"], ["尺寸不足"])

    def test_continue_within_bound(self):
        evs = [self._ev("evaluate", "drafting", "退回返工：尺寸不足", 0),
               self._ev("transition", "finalizing", "改完了", 10)]
        p = ledger.repair_loop_projection(evs)
        self.assertEqual(p["status"], "verifying")
        self.assertTrue(p["can_continue"])

    def test_stopped_max_rounds(self):
        evs = []
        for i in range(4):
            evs.append(self._ev("evaluate", "drafting",
                                f"退回返工：问题{i}", i * 10))
            evs.append(self._ev("transition", "finalizing", "改", i * 10 + 5))
        p = ledger.repair_loop_projection(evs)
        self.assertEqual(p["status"], "stopped_max_rounds")
        self.assertFalse(p["can_continue"])
        self.assertIsNotNone(p["handoff"])
        self.assertIn("next_action", p["handoff"])

    def test_stopped_no_progress(self):
        """连续两轮原因完全相同 → 照原样再修没意义。"""
        evs = [
            self._ev("evaluate", "drafting", "退回返工：尺寸不足", 0),
            self._ev("transition", "finalizing", "改", 5),
            self._ev("evaluate", "drafting", "退回返工：尺寸不足", 10),
            self._ev("transition", "finalizing", "改", 15),
        ]
        p = ledger.repair_loop_projection(evs)
        self.assertEqual(p["status"], "stopped_no_progress")
        self.assertIn("照原样", p["reason"])

    def test_rejected_event_skipped(self):
        evs = [self._ev("rejected", "drafting", "退回返工：x", 0),
               self._ev("transition", "pending_review", "", 5)]
        p = ledger.repair_loop_projection(evs)
        self.assertEqual(p["rounds"], 0)

    def test_canceled_closes_loop(self):
        evs = [self._ev("evaluate", "drafting", "退回返工：x", 0),
               self._ev("transition", "canceled", "取消", 5)]
        p = ledger.repair_loop_projection(evs)
        self.assertEqual(p["status"], "closed")


class TestSplit(unittest.TestCase):
    """分账计算。"""

    def test_basic_split(self):
        rules = [
            {"scope": "designer", "rate": Decimal("0.70"), "enabled": True},
            {"scope": "hr", "rate": Decimal("0.10"), "enabled": True},
        ]
        r = ledger.split_commission("1000", rules)
        self.assertEqual(r["total"], Decimal("1000.00"))
        self.assertEqual(r["shares"]["designer"], Decimal("700.00"))
        self.assertEqual(r["shares"]["hr"], Decimal("100.00"))
        self.assertEqual(r["remainder"], Decimal("200.00"))

    def test_remainder_never_negative(self):
        rules = [
            {"scope": "designer", "rate": Decimal("0.80"), "enabled": True},
            {"scope": "hr", "rate": Decimal("0.50"), "enabled": True},
        ]
        r = ledger.split_commission("1000", rules)
        self.assertGreaterEqual(r["remainder"], Decimal("0"))
        self.assertTrue(r["issues"])

    def test_disabled_rule_ignored(self):
        rules = [{"scope": "designer", "rate": Decimal("0.70"), "enabled": False}]
        r = ledger.split_commission("1000", rules)
        self.assertNotIn("designer", r["shares"])
        self.assertEqual(r["remainder"], Decimal("1000.00"))

    def test_supervisor_uses_basis(self):
        """主管奖金按「奖金基数」算，不按总额。"""
        rules = [{"scope": "supervisor", "rate": Decimal("0.10"), "enabled": True}]
        r = ledger.split_commission("1000", rules, basis="2000")
        self.assertEqual(r["shares"]["supervisor"], Decimal("200.00"))
        self.assertEqual(r["basis"], Decimal("2000.00"))

    def test_decimal_no_float_error(self):
        """0.1 + 0.2 这类浮点误差必须被 Decimal 消掉。"""
        rules = [
            {"scope": "designer", "rate": Decimal("0.1"), "enabled": True},
            {"scope": "hr", "rate": Decimal("0.2"), "enabled": True},
        ]
        r = ledger.split_commission("0.3", rules)
        self.assertEqual(r["shares"]["designer"], Decimal("0.03"))
        self.assertEqual(r["shares"]["hr"], Decimal("0.06"))

    def test_rounding_half_up(self):
        rules = [{"scope": "designer", "rate": Decimal("0.335"), "enabled": True}]
        r = ledger.split_commission("100", rules)
        self.assertEqual(r["shares"]["designer"], Decimal("33.50"))

    def test_bad_rate_reported(self):
        rules = [{"scope": "designer", "rate": "不是数字", "enabled": True}]
        r = ledger.split_commission("100", rules)
        self.assertTrue(r["issues"])
        self.assertNotIn("designer", r["shares"])

    def test_unknown_scope_reported(self):
        rules = [{"scope": "外星岗位", "rate": Decimal("0.1"), "enabled": True}]
        r = ledger.split_commission("100", rules)
        self.assertTrue(any("外星岗位" in i for i in r["issues"]))

    def test_to_decimal_handles_garbage(self):
        self.assertEqual(ledger.to_decimal("¥1,234.50"), Decimal("1234.50"))
        self.assertEqual(ledger.to_decimal("￥88"), Decimal("88"))
        self.assertEqual(ledger.to_decimal(None), None)
        self.assertEqual(ledger.to_decimal("", Decimal("0")), Decimal("0"))
        self.assertEqual(ledger.to_decimal("abc", Decimal("7")), Decimal("7"))
        self.assertEqual(ledger.to_decimal(12.5), Decimal("12.5"))

    def test_float_input_no_binary_error(self):
        """float 先转 str 再转 Decimal，避免 0.1 的二进制误差。"""
        self.assertEqual(ledger.to_decimal(0.1), Decimal("0.1"))

    def test_split_summary_rows(self):
        rules = [{"scope": "designer", "rate": Decimal("0.70"), "enabled": True}]
        r = ledger.split_commission("1000", rules)
        rows = ledger.split_summary(r)
        self.assertEqual(rows[0]["label"], "设计师佣金")
        self.assertEqual(rows[0]["amount"], "700.00")
        self.assertEqual(rows[0]["percent"], "70.00")
        self.assertTrue(any(x["label"] == "公司留存" for x in rows))


class TestMatching(unittest.TestCase):
    """撮合推荐与降级。"""

    def test_extract_terms_splits_modifiers(self):
        """「元以内的女士连衣裙」不能保留「元以内」这个修饰片段。

        切出来可以是「女士连衣裙」这种长词（中文没有词边界），
        但**绝不能**是原封不动的「元以内的女士连衣裙」——
        那样这段修饰会稀释相关度，甚至让整词匹配失败。
        """
        terms = ledger.extract_terms("元以内的女士连衣裙")
        self.assertTrue(terms)
        joined = " ".join(terms)
        self.assertNotIn("元以内", joined)
        self.assertTrue(any("连衣裙" in t for t in terms), terms)

    def test_extract_terms_splits_number_phrase(self):
        terms = ledger.extract_terms("100 元以内的女士连衣裙")
        joined = " ".join(terms)
        self.assertNotIn("以内", joined)
        self.assertNotIn("100", joined)
        self.assertTrue(any("连衣裙" in t for t in terms), terms)

    def test_term_hit_fragment_overlap(self):
        """「女士连衣裙」应能命中只写了「连衣裙」的标签。"""
        self.assertTrue(ledger._term_hit("女士连衣裙", "女装 连衣裙 电商主图"))
        self.assertFalse(ledger._term_hit("运动鞋", "女装 连衣裙 电商主图"))

    def test_term_hit_single_char_exact_only(self):
        """单字词只走整词匹配，不做片段重叠。

        「鞋」命中「皮鞋」是对的（同类目）；
        但不能因为「皮」这一半重叠就算命中「跑步机」，那是噪音。
        """
        self.assertTrue(ledger._term_hit("鞋", "皮鞋 靴子"))
        self.assertFalse(ledger._term_hit("鞋", "跑步机 健身器材"))

    def test_extract_terms_drops_stopwords(self):
        terms = ledger.extract_terms("请帮我设计一个女士的连衣裙")
        self.assertNotIn("的", terms)
        self.assertTrue(any("连衣裙" in t for t in terms))

    def test_extract_terms_empty(self):
        self.assertEqual(ledger.extract_terms(""), [])
        self.assertEqual(ledger.extract_terms("   "), [])

    def test_score_higher_for_matching(self):
        cand_match = {"design_tags": "连衣裙 女装 主图", "name": "林小满", "note": ""}
        cand_other = {"design_tags": "数码 耳机", "name": "陈墨", "note": ""}
        s1 = ledger.score_candidate("做连衣裙主图", cand_match)
        s2 = ledger.score_candidate("做连衣裙主图", cand_other)
        self.assertGreater(s1, s2)
        self.assertLessEqual(s1, 1.0)

    def test_rank_stable(self):
        cands = [
            {"id": "1", "name": "乙", "design_tags": "连衣裙"},
            {"id": "2", "name": "甲", "design_tags": "连衣裙"},
        ]
        r1 = ledger.rank_candidates("连衣裙", cands)
        r2 = ledger.rank_candidates("连衣裙", cands)
        self.assertEqual([x["name"] for x in r1], [x["name"] for x in r2])
        self.assertEqual([x["name"] for x in r1], ["乙", "甲"])  # 同分按名称排序

    def test_rank_never_empty_when_pool_not_empty(self):
        cands = [{"id": "1", "name": "甲", "design_tags": "连衣裙"}]
        r = ledger.rank_candidates("完全无关的需求 数码", cands)
        self.assertEqual(len(r), 1)

    def test_fallback_reason_explains(self):
        cands = [{"id": "1", "name": "林小满", "design_tags": "连衣裙 女装"}]
        reason = ledger.fallback_recommendation("连衣裙主图", cands)
        self.assertIn("林小满", reason)
        self.assertIn("未接入大模型", reason)

    def test_fallback_reason_when_no_terms(self):
        reason = ledger.fallback_recommendation("", [{"id": "1", "name": "甲"}])
        self.assertIn("关键词", reason)

    def test_fallback_reason_when_empty_pool(self):
        reason = ledger.fallback_recommendation("连衣裙", [])
        self.assertIn("设计师库", reason)


class TestDeliverySummary(unittest.TestCase):
    """交付四要素。"""

    SPEC = """# 需求单

## 目标
做主图。

## 范围
5 张。

## 非目标
不做详情页。

## 约束
改稿不超 2 轮。

## 验收标准
尺寸达标。

## 完成定义
客户确认。
"""

    def _deliveries(self):
        return [
            {"phase": "red", "command_text": "c", "return_code": 1,
             "observed_at": _dt(0)},
            {"phase": "diff", "command_text": "c", "return_code": 0,
             "observed_at": _dt(5)},
            {"phase": "green", "command_text": "c", "return_code": 0,
             "observed_at": _dt(10)},
        ]

    def test_summary_structure(self):
        s = ledger.delivery_summary(
            code="X-001", title="主图", state="delivered",
            acceptance="accepted", accepted_by="张老板",
            accepted_at=_dt(20), designer="林小满",
            spec_snapshot=self.SPEC, deliveries=self._deliveries(),
        )
        self.assertTrue(s["converged"])
        self.assertEqual(set(s["four"].keys()), {"结果", "证据", "边界", "交接"})
        self.assertIn("不做详情页", s["four"]["边界"]["非目标"])
        self.assertIn("林小满", s["four"]["交接"]["设计师"])

    def test_markdown_contains_all_sections(self):
        s = ledger.delivery_summary(
            code="X-001", title="主图", state="delivered",
            acceptance="pending_human_review", accepted_by=None,
            accepted_at=None, designer="林小满",
            spec_snapshot=self.SPEC, deliveries=[],
        )
        md = s["markdown"]
        for sec in ("## 结果", "## 证据", "## 边界", "## 交接"):
            self.assertIn(sec, md)
        self.assertIn("尚未被具名验收", md)

    def test_not_accepted_is_not_converged(self):
        s = ledger.delivery_summary(
            code="X-001", title="主图", state="drafting",
            acceptance="pending_human_review", accepted_by=None,
            accepted_at=None, designer="林小满",
            spec_snapshot=self.SPEC, deliveries=self._deliveries(),
        )
        self.assertFalse(s["converged"])


class TestFunnel(unittest.TestCase):
    """看板漏斗。"""

    def test_funnel_counts(self):
        orders = [
            {"state": "drafting", "order_commission": Decimal("100")},
            {"state": "drafting", "order_commission": Decimal("50")},
            {"state": "settled", "order_commission": Decimal("200")},
        ]
        f = ledger.order_funnel(orders)
        by_state = {r["state"]: r for r in f}
        self.assertEqual(by_state["drafting"]["count"], 2)
        self.assertEqual(by_state["drafting"]["amount"], "150.00")
        self.assertEqual(by_state["settled"]["count"], 1)
        self.assertEqual(len(f), len(ledger.ORDER_STATES))

    def test_funnel_empty(self):
        f = ledger.order_funnel([])
        self.assertEqual(len(f), len(ledger.ORDER_STATES))
        self.assertTrue(all(r["count"] == 0 for r in f))


if __name__ == "__main__":
    unittest.main(verbosity=2)
