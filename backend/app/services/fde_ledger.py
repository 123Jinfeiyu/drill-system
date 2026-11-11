"""CodexFDE 工作台台账核心。

这里只放**规则**，不放流程：需求合同怎么算合格、任务允许怎么流转、证据链怎样才算完整、
谁能签收谁不能。全部是纯函数，不依赖数据库、不依赖 FastAPI —— 这样规则只有一份实现，
可以被测试、被命令行、被 HTTP 路由同时复用（质量入口唯一）。

对应 CodexFDE 课程：
- L01 证据链：红（先失败）→ 改动 → 绿（同一命令通过）
- L02 规则层：把隐性经验写成稳定上下文（见仓库 AGENTS.md）
- L03 需求入口：模糊需求 → 可验收 Spec（六段式合同）
- L04 受控执行：状态机 + 责任分离 + 前置任务资格门禁 + 人工接受
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# ---------------------------------------------------------------------------
# L03 · 需求合同六段式
# ---------------------------------------------------------------------------
SPEC_SECTIONS: tuple[str, ...] = ("目标", "范围", "非目标", "约束", "验收标准", "完成定义")

_HEADING = re.compile(r"^(#{1,6})\s*(.+?)\s*$")
_KNOWN = {s: s for s in SPEC_SECTIONS}
# 允许写成「目标：」「范围:」等带冒号的变体
def _normalize_heading(raw: str) -> str:
    return raw.strip().rstrip("：:").strip()


def parse_spec(text: str) -> dict[str, str]:
    """把 Markdown 正文按标题切成 {标题: 正文}。

    未知标题照常保留（例如「附录」），是否合格由 :func:`validate_spec` 判定 ——
    解析与判定分开，才不会因为多写一节就把好合同判死。
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in (text or "").splitlines():
        match = _HEADING.match(line)
        if match:
            current = _normalize_heading(match.group(2))
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def validate_spec(text: str) -> list[str]:
    """返回合同的问题清单；空清单表示结构合格。

    注意：结构合格 ≠ 需求想清楚。模板自带的占位说明也能通过结构校验，
    这正是 L03 反复强调的那条边界。
    """
    parsed = parse_spec(text)
    issues: list[str] = []
    for section in SPEC_SECTIONS:
        if section not in parsed:
            issues.append(f"Spec 缺少必要章节：{section}")
        elif not parsed[section].strip():
            issues.append(f"Spec 章节内容为空：{section}")
    return issues


SPEC_TEMPLATE: str = """# 交付合同 · <任务编号>

## 目标
一句话说清这次交付要让谁得到什么。写不出这一句，说明需求还没想清楚。

## 范围
明确本次要动的模块、接口或文件。范围要能被列成清单。

## 非目标
明确本次**不做**什么。这一节最容易漏，也最容易被事后追加需求撑爆范围。

## 约束
技术栈、兼容性、性能预算、不可改动的既有行为、外部依赖的可用性等。

## 验收标准
逐条写成可执行的检查项（命令 + 期望返回码），不要写「体验良好」这类无法判定的描述。

## 完成定义
什么状态下可以判定「做完了」。注意区分：程序记录齐全 ≠ 已被人接受。
"""


# ---------------------------------------------------------------------------
# L04 · 任务状态机
# ---------------------------------------------------------------------------
TASK_STATES: tuple[str, ...] = (
    "queued", "spec_ready", "executing", "evaluating", "review", "accepted", "rework", "canceled",
)
TERMINAL_STATES: tuple[str, ...] = ("accepted", "canceled")

TRANSITIONS: Mapping[str, tuple[str, ...]] = {
    "queued": ("spec_ready", "canceled"),
    "spec_ready": ("executing", "canceled"),
    "executing": ("evaluating", "canceled"),
    "evaluating": ("review", "rework", "canceled"),
    "review": ("accepted", "rework"),
    "rework": ("executing", "canceled"),
    "accepted": (),
    "canceled": (),
}

STAGE_LABELS: Mapping[str, str] = {
    "queued": "已登记",
    "spec_ready": "需求已冻结",
    "executing": "受控执行中",
    "evaluating": "自动复验中",
    "review": "待人审",
    "accepted": "已具名接受",
    "rework": "待返工",
    "canceled": "已取消",
}


def next_states(state: str) -> tuple[str, ...]:
    """当前状态允许到达的下一状态；未知状态没有出路。"""
    return TRANSITIONS.get(state, ())


def can_transition(src: str, dst: str) -> bool:
    """是否允许 src -> dst。跳阶段一律不允许。"""
    return dst in next_states(src)


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


# ---------------------------------------------------------------------------
# L01 · 证据链：同一命令 + 红→改→绿有序
# ---------------------------------------------------------------------------
def _field(record: Any, name: str, default: Any = None) -> Any:
    """同时支持 dict 与 ORM/具名元组对象。"""
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def check_evidence_chain(records: Iterable[Any]) -> list[str]:
    """检查红-改-绿证据链；返回问题清单，空清单表示记录完整。

    三个判定互相独立，缺什么就说什么：
    1. 红灯必须真的失败过（red 且返回码非 0）
    2. 改动必须被记录（diff 且返回码为 0）
    3. 绿灯必须用**同一条命令**、且在红灯之后通过
    """
    records = list(records or [])
    issues: list[str] = []

    reds = [r for r in records if _field(r, "phase") == "red" and _field(r, "return_code") != 0]
    diffs = [r for r in records if _field(r, "phase") == "diff" and _field(r, "return_code") == 0]
    greens = [r for r in records if _field(r, "phase") == "green" and _field(r, "return_code") == 0]

    if not reds:
        issues.append("缺少有效红灯记录（red 且返回码非 0）：没有先失败过，就没有功能证据")
    if not diffs:
        issues.append("缺少改动记录（diff 且返回码为 0）")
    if not greens:
        issues.append("缺少有效绿灯记录（green 且返回码为 0）")

    if reds and greens:
        same = [
            (r, g)
            for r in reds
            for g in greens
            if _field(r, "command_text") == _field(g, "command_text")
        ]
        if not same:
            issues.append("红灯与绿灯必须使用同一命令，否则绿灯不能证明同一处修复")
        elif not any(_field(r, "observed_at") < _field(g, "observed_at") for r, g in same):
            issues.append("证据顺序错误：红灯必须早于绿灯")

    if reds and diffs and greens:
        ordered = any(
            _field(r, "observed_at") < _field(d, "observed_at") < _field(g, "observed_at")
            for r in reds
            for d in diffs
            for g in greens
        )
        if not ordered:
            issues.append("证据顺序应为红灯 → 改动 → 绿灯")

    return issues


def chain_summary(records: Iterable[Any]) -> dict[str, Any]:
    """给界面用的证据链摘要：各阶段条数 + 完整性。"""
    records = list(records or [])
    counts = {phase: 0 for phase in ("red", "diff", "green", "observation")}
    for record in records:
        phase = _field(record, "phase")
        if phase in counts:
            counts[phase] += 1
    issues = check_evidence_chain(records)
    return {
        "counts": counts,
        "total": len(records),
        "evidence_complete": not issues,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# L04 · 责任分离：构建者不得自审自评、机器不得替人签收
# ---------------------------------------------------------------------------
AGENT_PREFIX = "agent:"


def is_human_actor(actor: Any) -> bool:
    """机器署名（``agent:`` 前缀）与空署名都不算人。"""
    if not actor or not isinstance(actor, str):
        return False
    return not actor.strip().lower().startswith(AGENT_PREFIX)


def separation_issues(builder: Any, reviewer: Any) -> list[str]:
    """审阅者的资格检查。空清单表示责任分离成立。"""
    issues: list[str] = []
    if not reviewer:
        issues.append("缺少具名审阅者：人工接受必须由人署名")
    elif not is_human_actor(reviewer):
        issues.append(f"审阅者不能是机器署名（agent: 前缀不被接受，收到：{reviewer}）")
    elif builder and str(builder).strip().lower() == str(reviewer).strip().lower():
        issues.append("构建者不能审阅自己的产物：审阅者必须是另一个人")
    return issues


# ---------------------------------------------------------------------------
# L04 · 执行资格门禁
# ---------------------------------------------------------------------------
GATE_ALLOWED = 0
GATE_BLOCKED = 2


def evaluate_gate(
    *,
    state: str,
    evidence_complete: bool,
    acceptance: str,
    builder: Any,
    reviewer: Any,
    depends_on: Sequence[Any] = (),
) -> dict[str, Any]:
    """判定一个任务是否有资格进入交付。

    四道门，按「越靠前越不该被绕过」的顺序累积：
    1. 前置任务必须已被**具名接受**（别人的东西没验收，不要拿来当地基）
    2. 证据链必须完整（红→改→绿，同一命令）
    3. 责任分离必须成立（构建者 ≠ 审阅者，审阅者是人）
    4. 本任务必须已被**具名接受** —— 这道门程序永远不会自动通过

    返回字典含 ``allowed`` / ``code`` / ``reason`` / ``blockers`` /
    ``evidence_complete`` / ``accepted``。``evidence_complete`` 与 ``accepted``
    是两个独立字段，界面必须分开呈现。
    """
    blockers: list[str] = []

    for dep in depends_on or ():
        code = _field(dep, "code", "?")
        dep_acceptance = _field(dep, "acceptance")
        if dep_acceptance != "accepted":
            blockers.append(
                f"前置任务 {code} 尚未被具名接受（acceptance={dep_acceptance}）"
            )

    if not evidence_complete:
        blockers.append("证据链不完整：缺少有效的红灯→改动→绿灯")

    blockers.extend(separation_issues(builder, reviewer))

    accepted = acceptance == "accepted"
    if not accepted:
        blockers.append(f"工作台尚未被具名接受（acceptance={acceptance}）")

    allowed = not blockers
    reason = "全部条件满足，可以进入交付" if allowed else "；".join(blockers)
    return {
        "allowed": allowed,
        "code": GATE_ALLOWED if allowed else GATE_BLOCKED,
        "reason": reason,
        "blockers": blockers,
        "evidence_complete": bool(evidence_complete),
        "accepted": accepted,
        "state": state,
    }


# ---------------------------------------------------------------------------
# 接受动作：只有人能签，且不能自签
# ---------------------------------------------------------------------------
ACCEPTANCE_PENDING = "pending_human_review"
ACCEPTANCE_ACCEPTED = "accepted"
ACCEPTANCE_REJECTED = "rejected"


def accept_task(*, task: Any, actor: Any, builder: Any = None) -> dict[str, Any]:
    """尝试对任务做人工接受。返回 ``ok`` 与原因；不修改任何外部状态。

    ``builder`` 建议显式传入**构建者的具名身份**（而非数据库主键），否则
    责任分离会退化成「两个不同类型的字符串永不相等」，等于没有校验。
    """
    builder = builder if builder is not None else _field(task, "created_by")
    if not is_human_actor(actor):
        return {"ok": False, "reason": f"签收人必须是具名的人（收到：{actor}）"}
    if builder and str(builder).strip().lower() == str(actor).strip().lower():
        return {"ok": False, "reason": "构建者不能签收自己的交付物，请由他人复核"}
    state = _field(task, "state")
    if state != "review":
        return {"ok": False, "reason": f"只有 review 状态的任务可以接受（当前：{state}）"}
    return {"ok": True, "reason": f"已由 {actor} 具名接受"}


# ---------------------------------------------------------------------------
# L10 · 有界修复回路（只判定不执行：投影不改任何任务状态）
# ---------------------------------------------------------------------------
# 来源：CodexFDE L10「建立有停止条件的修复 Loop」。本仓库的 rework 状态机允许
# 无限次返工；这道投影在事件流上重放修复轮次，给出「还能不能继续修」的判定与
# 停止时的交接建议。它与上游一样**不改变任何状态**——停不停，由具名的人决定。
REPAIR_LOOP_MAX_ROUNDS = 3

_REWORK_ISSUE_PREFIX = "退回返工："

# 离开 rework 的归宿：收敛类真的结束本轮；executing 只是「本轮已开修」
_ROUND_CLOSED_BY: Mapping[str, str] = {
    "review": "converged",   # 复验通过，进人审
    "accepted": "accepted",
    "canceled": "canceled",
}


def repair_rounds(events: Iterable[Any]) -> list[dict[str, Any]]:
    """从事件流重放修复轮次。进入 ``rework`` = 开一轮。

    - ``kind=rejected`` 的事件不算流转（它被门禁拦下了），跳过；
    - 轮次终止于收敛（→review / accepted / canceled）或下一轮返工（前者记
      ``failed_again``）；``rework→executing`` 只是标记「本轮已开修」，不关轮；
    - 返工原因的可比性：只有 evaluate 事件写的「证据链不完整，退回返工：…」
      能解析出结构化原因清单；人工流转（review→rework）的备注是人的判断，
      不参与「无进展」比较。
    """
    rounds: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for ev in events or ():
        if _field(ev, "kind") == "rejected":
            continue
        to_state = _field(ev, "to_state")
        created_at = str(_field(ev, "created_at") or "")
        if to_state == "rework":
            if current is not None and current["outcome"] is None:
                current["ended_at"] = created_at
                current["outcome"] = "failed_again"
            detail = str(_field(ev, "detail") or "")
            issues: list[str] | None = None
            if _field(ev, "kind") == "evaluate" and _REWORK_ISSUE_PREFIX in detail:
                issues = [s for s in detail.split(_REWORK_ISSUE_PREFIX, 1)[1].split("；") if s]
            current = {
                "round": len(rounds) + 1,
                "entered_at": created_at,
                "actor": str(_field(ev, "actor") or ""),
                "reason": detail,
                "issues": issues,
                "repaired_at": None,
                "outcome": None,
                "ended_at": None,
            }
            rounds.append(current)
        elif current is not None and to_state in _ROUND_CLOSED_BY:
            current["ended_at"] = created_at
            current["outcome"] = _ROUND_CLOSED_BY[to_state]
            current = None
        elif current is not None and to_state == "executing":
            current["repaired_at"] = created_at
    return rounds


def repair_loop_projection(
    events: Iterable[Any], *, max_rounds: int = REPAIR_LOOP_MAX_ROUNDS
) -> dict[str, Any]:
    """有界修复回路的只读投影：状态、轮次历史、停止原因与交接建议。

    状态语义（对齐上游 repair_loop 的口径，去掉本仓库测不到的 token/时间预算——
    我们不执行命令，那两个预算在这里没有可核验的依据）：
    - ``ready``              还没返工过
    - ``continue``           在界内（未达轮数上限、原因未见恶化），可以继续修
    - ``verifying``          上一轮已开修，等下一轮复验
    - ``converged``          最近一轮已收敛（进 review / 被接受）
    - ``closed``             任务取消，回路随之关闭
    - ``stopped_max_rounds`` 返工轮次达上限
    - ``stopped_no_progress`` 连续两轮返工原因完全相同（照原样再修没有意义）
    """
    rounds = repair_rounds(events)
    last = rounds[-1] if rounds else None
    comparable = [r for r in rounds if r["issues"]]

    if not rounds:
        status, reason = "ready", "尚未进入返工"
    elif last["outcome"] in ("converged", "accepted"):
        status, reason = "converged", "最近一轮返工已收敛，进入人审或已接受"
    elif last["outcome"] == "canceled":
        status, reason = "closed", "任务已取消，修复回路随之关闭"
    elif last["outcome"] is None and last["repaired_at"]:
        status, reason = "verifying", "上一轮已开修，等待复验"
    elif (
        len(comparable) >= 2
        and comparable[-1]["issues"] == comparable[-2]["issues"]
    ):
        status, reason = (
            "stopped_no_progress",
            "连续两轮返工原因完全相同：照原样再修不会变好",
        )
    elif len(rounds) >= max_rounds:
        status, reason = "stopped_max_rounds", f"返工轮次已达上限（{max_rounds} 轮）"
    else:
        status, reason = "continue", "返工轮次在界内，可以继续修复"

    handoff = None
    if status.startswith("stopped_"):
        handoff = {
            "stop_reason": reason,
            "rounds": len(rounds),
            "last_issues": list(last["issues"]) if last and last["issues"] else None,
            "next_action": (
                "由具名负责人决策：换修复方案、缩小范围或取消任务；"
                "照原样重跑不算修复，也不该被记成新的一轮。"
            ),
        }
    return {
        "max_rounds": max_rounds,
        "rounds": len(rounds),
        "status": status,
        "reason": reason,
        "can_continue": status in ("continue", "verifying"),
        "history": [
            {
                "round": r["round"],
                "entered_at": r["entered_at"],
                "ended_at": r["ended_at"],
                "actor": r["actor"],
                "reason": r["reason"],
                "outcome": r["outcome"] or ("verifying" if r["repaired_at"] else "in_rework"),
                "issues": r["issues"],
            }
            for r in rounds
        ],
        "handoff": handoff,
    }


# ---------------------------------------------------------------------------
# L15 · 交付摘要（交付四要素的结案投影：结果 / 证据 / 边界 / 交接）
# ---------------------------------------------------------------------------
def delivery_summary(
    *,
    code: Any,
    title: Any,
    state: Any,
    acceptance: Any,
    accepted_by: Any,
    accepted_at: Any,
    builder: Any,
    spec_snapshot: str,
    evidences: Iterable[Any],
    depends_on: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """把台账数据投影成一页可交接的交付摘要。

    只汇总「已经发生的事实」，不产生新判断；边界一节直接取自冻结的需求合同
    （范围 / 非目标 / 约束），防止交接时口头扩大或缩小范围。
    """
    parsed = parse_spec(spec_snapshot)
    greens = [e for e in evidences or () if _field(e, "phase") == "green" and _field(e, "return_code") == 0]
    reds = [e for e in evidences or () if _field(e, "phase") == "red" and _field(e, "return_code") != 0]
    green = greens[-1] if greens else None
    red = None
    if green is not None:
        same = [
            r
            for r in reds
            if _field(r, "command_text") == _field(green, "command_text")
            and _field(r, "observed_at") < _field(green, "observed_at")
        ]
        red = same[-1] if same else (reds[-1] if reds else None)

    chain = chain_summary(evidences)
    accepted = acceptance == ACCEPTANCE_ACCEPTED
    accepted_text = (
        f"{accepted_by}（{accepted_at}）" if accepted and accepted_by else "尚未具名接受"
    )
    four: dict[str, dict[str, Any]] = {
        "结果": {
            "任务": f"{code} · {title}",
            "状态": f"{state}（{STAGE_LABELS.get(state, state)}）",
            "签收": accepted_text,
        },
        "证据": {
            "链完整性": "完整（红→改→绿，同一命令）" if chain["evidence_complete"] else "不完整",
            "计数": f"红灯 {chain['counts']['red']} · 改动 {chain['counts']['diff']} · 绿灯 {chain['counts']['green']} · 观察 {chain['counts']['observation']}",
            "绿灯命令": _field(green, "command_text") if green is not None else "",
            "红灯命令": _field(red, "command_text") if red is not None else "",
        },
        "边界": {
            "范围": parsed.get("范围", ""),
            "非目标": parsed.get("非目标", ""),
            "约束": parsed.get("约束", ""),
        },
        "交接": {
            "构建者": builder or "",
            "签收人": accepted_by if accepted else "",
            "前置依赖": [
                {"code": d.get("code"), "acceptance": d.get("acceptance")} for d in depends_on or ()
            ],
        },
    }
    markdown = render_delivery_markdown(code, title, four, chain["evidence_complete"], accepted)
    return {"converged": accepted, "four": four, "markdown": markdown}


def render_delivery_markdown(
    code: Any, title: Any, four: Mapping[str, Mapping[str, Any]],
    evidence_complete: bool, accepted: bool,
) -> str:
    """把四要素渲染成可直接贴进交接单的 Markdown。"""
    lines = [f"# 交付摘要 · {code} {title}", ""]
    labels = {"结果": "结果", "证据": "证据", "边界": "边界", "交接": "交接"}
    for key in ("结果", "证据", "边界", "交接"):
        lines.append(f"## {labels[key]}")
        for name, value in four[key].items():
            if isinstance(value, list):
                items = "、".join(
                    f"{d.get('code')}（{d.get('acceptance') or '缺失'}）" for d in value
                )
                lines.append(f"- {name}：{items or '无'}")
            elif value:
                lines.append(f"- {name}：{value}")
            else:
                lines.append(f"- {name}：—")
        lines.append("")
    lines.append("---")
    lines.append(
        f"> 证据链{'完整' if evidence_complete else '不完整'}；"
        f"{'已由具名的人接受' if accepted else '尚未被具名接受——接受是人的判断，程序不代签'}。"
    )
    return "\n".join(lines)
