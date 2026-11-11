"""L05 验收测试：CodexFDE 工作台台账核心合同。

运行方式（在 backend/ 下）：
    ./.venv/Scripts/python.exe -X utf8 -m unittest tests.test_fde_ledger -v

这些用例把「工作台台账」的验收标准写成可执行断言。它们先于实现存在，
因此第一次运行必然是红的（ModuleNotFoundError）。红灯本身是证据，不是故障。
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from app.services import fde_ledger as L

T0 = datetime(2026, 9, 15, 10, 0, 0, tzinfo=timezone.utc)


class Rec(NamedTuple):
    """证据记录的最小契约：台账只看这些字段。"""

    phase: str
    command_text: str
    return_code: int
    observed_at: datetime


class Ev(NamedTuple):
    """事件记录的最小契约：修复回路投影只看这些字段。"""

    kind: str
    actor: str
    detail: str
    from_state: str | None
    to_state: str | None
    created_at: datetime


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def chain(phase: str, command: str, code: int, minutes: int) -> Rec:
    return Rec(phase=phase, command_text=command, return_code=code,
               observed_at=T0 + timedelta(minutes=minutes))


CMD = "python -X utf8 -m unittest tests.test_fde_ledger -v"


# --------------------------------------------------------------------------
# L03：需求合同六段式
# --------------------------------------------------------------------------
class SpecContractTests(unittest.TestCase):
    def test_six_sections_are_fixed(self) -> None:
        self.assertEqual(
            L.SPEC_SECTIONS,
            ("目标", "范围", "非目标", "约束", "验收标准", "完成定义"),
        )

    def test_complete_contract_passes(self) -> None:
        text = "\n\n".join(f"## {s}\n正文内容" for s in L.SPEC_SECTIONS)
        self.assertEqual(L.validate_spec(text), [])

    def test_missing_section_is_named_in_issues(self) -> None:
        text = "\n\n".join(
            f"## {s}\n正文内容" for s in L.SPEC_SECTIONS if s != "非目标"
        )
        issues = L.validate_spec(text)
        self.assertTrue(issues, "缺少「非目标」必须被拒绝")
        self.assertTrue(any("非目标" in i for i in issues), issues)

    def test_empty_section_body_counts_as_missing(self) -> None:
        text = "\n\n".join(
            f"## {s}\n" + ("" if s == "完成定义" else "正文内容")
            for s in L.SPEC_SECTIONS
        )
        issues = L.validate_spec(text)
        self.assertTrue(any("完成定义" in i for i in issues), issues)

    def test_unknown_section_does_not_break_parsing(self) -> None:
        text = "\n\n".join(f"## {s}\n正文内容" for s in L.SPEC_SECTIONS)
        text += "\n\n## 附录\n补充说明"
        self.assertEqual(L.validate_spec(text), [])

    def test_parse_returns_body_per_section(self) -> None:
        text = "## 目标\n让学员能练\n\n## 范围\n仅 Q&A 演练场"
        parsed = L.parse_spec(text)
        self.assertEqual(parsed.get("目标"), "让学员能练")
        self.assertEqual(parsed.get("范围"), "仅 Q&A 演练场")

    def test_shipped_template_is_itself_valid(self) -> None:
        """模板不能是一份自己不达标的合同。"""
        self.assertEqual(L.validate_spec(L.SPEC_TEMPLATE), [])


# --------------------------------------------------------------------------
# L04：任务状态机
# --------------------------------------------------------------------------
class StateMachineTests(unittest.TestCase):
    def test_happy_path_is_linear(self) -> None:
        trail = ("queued", "spec_ready", "executing", "evaluating", "review", "accepted")
        for src, dst in zip(trail, trail[1:]):
            self.assertTrue(L.can_transition(src, dst), f"{src} -> {dst}")

    def test_cannot_skip_stages(self) -> None:
        self.assertFalse(L.can_transition("queued", "executing"))
        self.assertFalse(L.can_transition("spec_ready", "review"))

    def test_rework_returns_to_execution(self) -> None:
        self.assertTrue(L.can_transition("review", "rework"))
        self.assertTrue(L.can_transition("rework", "executing"))

    def test_terminal_states_have_no_exit(self) -> None:
        self.assertEqual(L.next_states("accepted"), ())
        self.assertEqual(L.next_states("canceled"), ())

    def test_unknown_state_is_rejected(self) -> None:
        self.assertEqual(L.next_states("不存在的状态"), ())


# --------------------------------------------------------------------------
# 证据链：同一命令 + 红-改-绿有序
# --------------------------------------------------------------------------
class EvidenceChainTests(unittest.TestCase):
    def test_complete_chain_passes(self) -> None:
        records = [chain("red", CMD, 1, 0), chain("diff", CMD, 0, 5), chain("green", CMD, 0, 10)]
        self.assertEqual(L.check_evidence_chain(records), [])

    def test_missing_red_is_reported(self) -> None:
        records = [chain("diff", CMD, 0, 5), chain("green", CMD, 0, 10)]
        issues = L.check_evidence_chain(records)
        self.assertTrue(any("红灯" in i for i in issues), issues)

    def test_red_must_actually_fail(self) -> None:
        """返回码为 0 的「红灯」不是红灯。"""
        records = [chain("red", CMD, 0, 0), chain("diff", CMD, 0, 5), chain("green", CMD, 0, 10)]
        issues = L.check_evidence_chain(records)
        self.assertTrue(any("红灯" in i for i in issues), issues)

    def test_same_command_is_required(self) -> None:
        records = [
            chain("red", "python -m unittest tests.test_a", 1, 0),
            chain("diff", CMD, 0, 5),
            chain("green", CMD, 0, 10),
        ]
        issues = L.check_evidence_chain(records)
        self.assertTrue(any("同一命令" in i for i in issues), issues)

    def test_ordering_is_required(self) -> None:
        records = [chain("green", CMD, 0, 0), chain("diff", CMD, 0, 5), chain("red", CMD, 1, 10)]
        issues = L.check_evidence_chain(records)
        self.assertTrue(any("顺序" in i for i in issues), issues)

    def test_observation_only_is_incomplete(self) -> None:
        issues = L.check_evidence_chain([chain("observation", "ls", 0, 0)])
        self.assertTrue(len(issues) >= 3, issues)


# --------------------------------------------------------------------------
# 责任分离：构建者不得自审自评
# --------------------------------------------------------------------------
class SeparationTests(unittest.TestCase):
    def test_self_review_is_rejected(self) -> None:
        issues = L.separation_issues(builder="congde", reviewer="congde")
        self.assertTrue(issues, "构建者不能审阅自己的产物")

    def test_agent_signature_is_rejected(self) -> None:
        issues = L.separation_issues(builder="congde", reviewer="agent:codex")
        self.assertTrue(any("agent" in i.lower() for i in issues), issues)

    def test_named_human_reviewer_is_accepted(self) -> None:
        self.assertEqual(L.separation_issues(builder="congde", reviewer="zhang"), [])

    def test_is_human_actor(self) -> None:
        self.assertTrue(L.is_human_actor("zhang"))
        self.assertFalse(L.is_human_actor("agent:codex"))
        self.assertFalse(L.is_human_actor(""))
        self.assertFalse(L.is_human_actor(None))


# --------------------------------------------------------------------------
# 执行资格门禁 + 人工接受
# --------------------------------------------------------------------------
class GateTests(unittest.TestCase):
    def test_gate_blocks_when_evidence_incomplete(self) -> None:
        verdict = L.evaluate_gate(state="evaluating", evidence_complete=False,
                                  acceptance="pending_human_review",
                                  builder="congde", reviewer="zhang")
        self.assertFalse(verdict["allowed"])
        self.assertIn("证据", verdict["reason"])

    def test_gate_blocks_until_named_human_accepts(self) -> None:
        """证据齐全 ≠ 已被接受。这正是程序不能替人做的判断。"""
        verdict = L.evaluate_gate(state="review", evidence_complete=True,
                                  acceptance="pending_human_review",
                                  builder="congde", reviewer="zhang")
        self.assertFalse(verdict["allowed"])
        self.assertEqual(verdict["code"], 2)
        self.assertIn("接受", verdict["reason"])

    def test_gate_blocks_on_unaccepted_dependency(self) -> None:
        verdict = L.evaluate_gate(
            state="spec_ready", evidence_complete=False,
            acceptance="pending_human_review", builder="congde", reviewer="zhang",
            depends_on=[{"code": "L05-A", "acceptance": "pending_human_review"}],
        )
        self.assertFalse(verdict["allowed"])
        self.assertTrue(any("L05-A" in r for r in verdict["blockers"]), verdict)

    def test_gate_allows_when_everything_is_satisfied(self) -> None:
        verdict = L.evaluate_gate(
            state="review", evidence_complete=True, acceptance="accepted",
            builder="congde", reviewer="zhang",
            depends_on=[{"code": "L05-A", "acceptance": "accepted"}],
        )
        self.assertTrue(verdict["allowed"], verdict)
        self.assertEqual(verdict["code"], 0)

    def test_acceptance_is_independent_of_completeness(self) -> None:
        verdict = L.evaluate_gate(state="review", evidence_complete=True,
                                  acceptance="pending_human_review",
                                  builder="congde", reviewer="zhang")
        self.assertTrue(verdict["evidence_complete"])
        self.assertFalse(verdict["accepted"])


# --------------------------------------------------------------------------
# L10：有界修复回路（只判定不执行）
# --------------------------------------------------------------------------
def evaluate_rework_event(minutes: int, issues: list[str]) -> Ev:
    detail = "证据链不完整，退回返工：" + "；".join(issues)
    return Ev(kind="evaluate", actor="congde", detail=detail,
              from_state="evaluating", to_state="rework", created_at=at(minutes))


def transition_event(minutes: int, src: str, dst: str, detail: str = "") -> Ev:
    return Ev(kind="transition", actor="congde", detail=detail or f"{src} → {dst}",
              from_state=src, to_state=dst, created_at=at(minutes))


class RepairLoopTests(unittest.TestCase):
    def test_no_rework_is_ready(self) -> None:
        events = [transition_event(0, "spec_ready", "executing")]
        loop = L.repair_loop_projection(events)
        self.assertEqual(loop["status"], "ready")
        self.assertEqual(loop["rounds"], 0)
        self.assertIsNone(loop["handoff"])

    def test_one_rework_in_rework_is_continue(self) -> None:
        events = [
            transition_event(0, "spec_ready", "executing"),
            evaluate_rework_event(10, ["缺少有效红灯记录"]),
        ]
        loop = L.repair_loop_projection(events)
        self.assertEqual(loop["status"], "continue")
        self.assertTrue(loop["can_continue"])
        self.assertEqual(loop["rounds"], 1)
        self.assertEqual(loop["history"][0]["issues"], ["缺少有效红灯记录"])

    def test_round_closed_by_convergence(self) -> None:
        events = [
            transition_event(0, "spec_ready", "executing"),
            evaluate_rework_event(10, ["缺少绿灯"]),
            transition_event(20, "rework", "executing"),
            transition_event(30, "executing", "evaluating"),
            evaluate_rework_event(40, ["缺少绿灯"]),  # 第二轮，原因不同
            transition_event(50, "rework", "executing"),
            Ev(kind="evaluate", actor="congde", detail="证据链完整，转入待人审",
               from_state="evaluating", to_state="review", created_at=at(60)),
        ]
        loop = L.repair_loop_projection(events)
        self.assertEqual(loop["status"], "converged")
        self.assertEqual(loop["rounds"], 2)
        self.assertEqual(loop["history"][-1]["outcome"], "converged")

    def test_rejected_events_do_not_open_rounds(self) -> None:
        events = [
            Ev(kind="rejected", actor="congde", detail="流转被拒",
               from_state="review", to_state=None, created_at=at(0)),
        ]
        loop = L.repair_loop_projection(events)
        self.assertEqual(loop["status"], "ready")
        self.assertEqual(loop["rounds"], 0)

    def test_max_rounds_stops_the_loop(self) -> None:
        # 三轮返工、每轮原因都不同（不触发 no_progress），第三轮停在 rework
        issue_sets = [["缺少红灯"], ["缺少改动"], ["缺少绿灯"]]
        events: list[Ev] = [transition_event(0, "spec_ready", "executing")]
        clock = 10
        for issues in issue_sets:
            events.append(evaluate_rework_event(clock, issues))
            if issues is not issue_sets[-1]:
                events.append(transition_event(clock + 10, "rework", "executing"))
                events.append(transition_event(clock + 20, "executing", "evaluating"))
            clock += 30
        loop = L.repair_loop_projection(events)
        self.assertEqual(loop["status"], "stopped_max_rounds")
        self.assertEqual(loop["rounds"], 3)
        self.assertFalse(loop["can_continue"])
        self.assertIsNotNone(loop["handoff"])
        self.assertIn("具名负责人", loop["handoff"]["next_action"])

    def test_no_progress_fires_before_max_rounds(self) -> None:
        events = [
            transition_event(0, "spec_ready", "executing"),
            evaluate_rework_event(10, ["缺少绿灯"]),
            transition_event(20, "rework", "executing"),
            transition_event(30, "executing", "evaluating"),
            evaluate_rework_event(40, ["缺少绿灯"]),  # 两轮原因完全相同
        ]
        loop = L.repair_loop_projection(events)
        self.assertEqual(loop["status"], "stopped_no_progress")
        self.assertEqual(loop["rounds"], 2)
        self.assertIsNotNone(loop["handoff"])

    def test_human_rework_note_is_not_compared(self) -> None:
        """人工流转（review→rework）的备注是人的判断，不参与无进展比较。"""
        events = [
            transition_event(0, "spec_ready", "executing"),
            Ev(kind="evaluate", actor="congde", detail="证据链不完整，退回返工：缺少绿灯",
               from_state="evaluating", to_state="rework", created_at=at(10)),
            transition_event(20, "rework", "executing"),
            transition_event(30, "executing", "evaluating"),
            transition_event(40, "evaluating", "review"),
            transition_event(50, "review", "rework", detail="复核者认为质量不达标"),  # 人工第二轮
        ]
        loop = L.repair_loop_projection(events)
        # 第二轮 issues=None（不可比），不得触发 no_progress → 只按轮数判
        self.assertEqual(loop["status"], "continue")
        self.assertTrue(loop["can_continue"])

    def test_max_rounds_is_three(self) -> None:
        self.assertEqual(L.REPAIR_LOOP_MAX_ROUNDS, 3)


# --------------------------------------------------------------------------
# L15：交付摘要（交付四要素投影）
# --------------------------------------------------------------------------
class DeliverySummaryTests(unittest.TestCase):
    def make_spec(self) -> str:
        return (
            "## 目标\n让学员能练\n\n## 范围\n仅 Q&A 演练场\n\n"
            "## 非目标\n不做评分改造\n\n## 约束\n不引入新依赖\n\n"
            "## 验收标准\n单元测试全绿\n\n## 完成定义\n被具名接受\n"
        )

    def make_evidences(self) -> list[Rec]:
        return [
            chain("red", CMD, 1, 0), chain("diff", CMD, 0, 5), chain("green", CMD, 0, 10),
        ]

    def test_four_elements_present(self) -> None:
        s = L.delivery_summary(
            code="L05-A", title="台账核心", state="accepted", acceptance="accepted",
            accepted_by="teacher", accepted_at="2026-09-25T10:00:00", builder="congde",
            spec_snapshot=self.make_spec(), evidences=self.make_evidences(),
        )
        self.assertEqual(set(s["four"].keys()), {"结果", "证据", "边界", "交接"})
        self.assertTrue(s["converged"])

    def test_boundary_comes_from_frozen_spec(self) -> None:
        s = L.delivery_summary(
            code="L05-A", title="台账核心", state="accepted", acceptance="accepted",
            accepted_by="teacher", accepted_at="2026-09-25T10:00:00", builder="congde",
            spec_snapshot=self.make_spec(), evidences=self.make_evidences(),
        )
        self.assertEqual(s["four"]["边界"]["非目标"], "不做评分改造")
        self.assertEqual(s["four"]["边界"]["范围"], "仅 Q&A 演练场")

    def test_markdown_carries_four_sections_and_command(self) -> None:
        s = L.delivery_summary(
            code="L05-A", title="台账核心", state="accepted", acceptance="accepted",
            accepted_by="teacher", accepted_at="2026-09-25T10:00:00", builder="congde",
            spec_snapshot=self.make_spec(), evidences=self.make_evidences(),
        )
        md = s["markdown"]
        for heading in ("## 结果", "## 证据", "## 边界", "## 交接"):
            self.assertIn(heading, md)
        self.assertIn(CMD, md, "绿灯命令要进交接单")
        self.assertIn("不做评分改造", md)

    def test_unaccepted_task_states_the_fact(self) -> None:
        s = L.delivery_summary(
            code="L05-B", title="后续任务", state="review", acceptance="pending_human_review",
            accepted_by=None, accepted_at=None, builder="congde",
            spec_snapshot=self.make_spec(), evidences=[],
        )
        self.assertFalse(s["converged"])
        self.assertIn("尚未被具名接受", s["markdown"])
        self.assertEqual(s["four"]["证据"]["绿灯命令"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
