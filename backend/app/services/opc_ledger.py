"""OPC 一人公司系统 · 订单台账规则核心。

这里只放**规则**，不放流程：订单需求单怎么算合格、订单允许怎么流转、
交付证据链怎样才算完整、谁能验收谁不能、佣金怎么分、什么时候允许结算。
全部是纯函数，不依赖数据库、不依赖 FastAPI —— 这样规则只有一份实现，
可以被单测、被命令行、被 HTTP 路由同时复用（质量入口唯一）。

对应关系（沿用 CodexFDE 的方法论，业务域换成「设计师接单撮合」）：

============  ==========================  ==================================
CodexFDE      OPC                          说明
============  ==========================  ==================================
L03 六段式    订单需求单                    目标/范围/非目标/约束/验收标准/完成定义
L04 状态机    订单状态机                    待派单 → 已接单 → 初稿中 → 终稿中 → …
L01 证据链    交付证据链                    初稿不合格(红) → 返工(改) → 终稿合格(绿)
L04 责任分离  自审禁令                      设计师不能验收自己的稿
L04 门禁      结算门禁                      证据链完整 + 具名验收 才允许结算
L10 修复回路  返工轮次上限                  最多 N 轮，同因不恶化则停手转人工
L15 交付摘要  交付四要素                    结果 / 证据 / 边界 / 交接
============  ==========================  ==================================

新增（OPC 特有）：

- **分账计算**：按规则表把订单金额拆给设计师 / HR / 品控 / 主管 / 中控，
  金额一律 Decimal，比例从规则表读，代码里不写死。
- **AI 降级排序**：没配 LLM 时用关键词相关度排序，候选池不能为空。
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# ---------------------------------------------------------------------------
# 需求单六段式（订单需求合同）
# ---------------------------------------------------------------------------
SPEC_SECTIONS: tuple[str, ...] = ("目标", "范围", "非目标", "约束", "验收标准", "完成定义")

_HEADING = re.compile(r"^(#{1,6})\s*(.+?)\s*$")


def _normalize_heading(raw: str) -> str:
    return raw.strip().rstrip("：:").strip()


def parse_spec(text: str) -> dict[str, str]:
    """把 Markdown 正文按标题切成 {标题: 正文}。

    **文档标题（H1）不计入 section** —— 「# 订单需求单 · X-001」是这篇文档叫什么，
    不是需求的一个章节。留着它会让「需求单有 7 节」这种统计失真。

    未知标题照常保留（例如「附录」），是否合格由 :func:`validate_spec` 判定 ——
    解析与判定分开，才不会因为多写一节就把好合同判死。
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    seen_any_heading = False
    for line in (text or "").splitlines():
        match = _HEADING.match(line)
        if match:
            level = len(match.group(1))
            heading = _normalize_heading(match.group(2))
            # 第一个 H1 视为文档标题，跳过
            if level == 1 and not seen_any_heading:
                seen_any_heading = True
                current = None
                continue
            seen_any_heading = True
            current = heading
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def validate_spec(text: str) -> list[str]:
    """返回需求单的问题清单；空清单表示结构合格。

    注意：结构合格 ≠ 需求想清楚了。模板自带的占位说明也能通过结构校验，
    这正是 L03 反复强调的那条边界。
    """
    parsed = parse_spec(text)
    issues: list[str] = []
    for section in SPEC_SECTIONS:
        if section not in parsed:
            issues.append(f"需求单缺少必要章节：{section}")
        elif not parsed[section].strip():
            issues.append(f"需求单章节内容为空：{section}")
    return issues


SPEC_TEMPLATE: str = """# 订单需求单 · <订单编号>

## 目标
一句话说清这一单要让设计师交出什么。写不出这一句，说明需求还没想清楚。

## 范围
明确本次要做的稿件范围、尺寸、格式、份数。范围要能被列成清单。

## 非目标
明确本次**不做**什么。这一节最容易漏，也最容易被事后追加需求撑爆范围。

## 约束
交付时间、修改次数上限、素材版权、店铺视觉规范等硬性要求。

## 验收标准
逐条写成可执行的检查项（如「首图尺寸 800×800，主体占比 ≥ 60%」），不要写「好看」这类无法判定的描述。

## 完成定义
什么状态下可以判定「这单做完了」。注意区分：程序记录齐全 ≠ 已被客户接受。
"""


# ---------------------------------------------------------------------------
# 订单状态机
# ---------------------------------------------------------------------------
ORDER_STATES: tuple[str, ...] = (
    "pending_assign",   # 待派单
    "assigned",         # 已派单（等设计师接单）
    "taken",            # 已接单
    "drafting",         # 初稿制作中
    "finalizing",       # 终稿制作中
    "pending_review",   # 待验收
    "delivered",        # 已交付
    "pending_settle",   # 待结算
    "settled",          # 已结算
    "canceled",         # 已取消
)

TERMINAL_STATES: tuple[str, ...] = ("settled", "canceled")

#: 允许的流转。跳阶段一律不允许。
ORDER_TRANSITIONS: Mapping[str, tuple[str, ...]] = {
    "pending_assign": ("assigned", "canceled"),
    "assigned": ("taken", "pending_assign", "canceled"),
    "taken": ("drafting", "canceled"),
    "drafting": ("finalizing", "drafting", "canceled"),  # drafting 自环 = 返工
    "finalizing": ("pending_review", "drafting", "canceled"),
    "pending_review": ("delivered", "drafting", "canceled"),
    "delivered": ("pending_settle", "canceled"),
    "pending_settle": ("settled", "delivered", "canceled"),
    "settled": (),
    "canceled": (),
}

STATE_LABELS: Mapping[str, str] = {
    "pending_assign": "待派单",
    "assigned": "已派单",
    "taken": "已接单",
    "drafting": "初稿制作中",
    "finalizing": "终稿制作中",
    "pending_review": "待验收",
    "delivered": "已交付",
    "pending_settle": "待结算",
    "settled": "已结算",
    "canceled": "已取消",
}

#: 履约主线（界面用 Steps 展示）。drafting 的自环与 canceled 是支线，单独用 Tag 标出。
ORDER_MAINLINE: tuple[str, ...] = (
    "pending_assign", "assigned", "taken", "drafting",
    "finalizing", "pending_review", "delivered", "pending_settle", "settled",
)

#: 处于这些状态说明钱还压着没结，统计「在制金额」时要算上。
ACTIVE_STATES: tuple[str, ...] = (
    "assigned", "taken", "drafting", "finalizing", "pending_review", "delivered",
)


def next_states(state: str) -> tuple[str, ...]:
    """当前状态允许到达的下一状态；未知状态没有出路。"""
    return ORDER_TRANSITIONS.get(state, ())


def can_transition(src: str, dst: str) -> bool:
    """是否允许 src -> dst。跳阶段一律不允许。"""
    return dst in next_states(src)


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def is_active(state: str) -> bool:
    """是否属于「在制」—— 已派单但还没结算。"""
    return state in ACTIVE_STATES


def state_label(state: str) -> str:
    return STATE_LABELS.get(state, state)


# ---------------------------------------------------------------------------
# 交付证据链：初稿不合格(红) → 返工改动(改) → 终稿合格(绿)，同一验收命令
# ---------------------------------------------------------------------------
EVIDENCE_PHASES: tuple[str, ...] = ("red", "diff", "green", "observation")

PHASE_LABELS: Mapping[str, str] = {
    "red": "初稿不合格",
    "diff": "返工改动",
    "green": "终稿合格",
    "observation": "观察记录",
}


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
        issues.append("缺少有效红灯记录（red 且返回码非 0）：没有先失败过，就没有交付证据")
    if not diffs:
        issues.append("缺少返工改动记录（diff 且返回码为 0）")
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
            issues.append("红灯与绿灯必须使用同一条验收命令，否则绿灯不能证明同一处修复")
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
            issues.append("证据顺序应为红灯 → 返工 → 绿灯")

    return issues


def chain_summary(records: Iterable[Any]) -> dict[str, Any]:
    """给界面用的证据链摘要：各阶段条数 + 完整性。"""
    records = list(records or [])
    counts = {phase: 0 for phase in EVIDENCE_PHASES}
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
# 责任分离：设计师不能验收自己的稿；机器不得替人签收
# ---------------------------------------------------------------------------
AGENT_PREFIX = "agent:"


def is_human_actor(actor: Any) -> bool:
    """机器署名（``agent:`` 前缀）与空署名都不算人。"""
    if not actor or not isinstance(actor, str):
        return False
    return not actor.strip().lower().startswith(AGENT_PREFIX)


def separation_issues(builder: Any, reviewer: Any) -> list[str]:
    """验收人资格检查。空清单表示责任分离成立。

    一人公司里「设计师」和「老板」常常是同一个人，但**验收**这件事上不能自己签自己 ——
    这条在一人公司场景下依然成立：系统要留下「谁验的」这一笔，
    将来对账/交接时才有据可查。机器署名（agent:）一律不接受。
    """
    issues: list[str] = []
    if not reviewer:
        issues.append("缺少具名验收人：验收必须由人署名")
    elif not is_human_actor(reviewer):
        issues.append(f"验收人不能是机器署名（agent: 前缀不被接受，收到：{reviewer}）")
    elif builder and str(builder).strip().lower() == str(reviewer).strip().lower():
        issues.append("设计师不能验收自己的稿：验收人必须是另一个人")
    return issues


# ---------------------------------------------------------------------------
# 结算门禁
# ---------------------------------------------------------------------------
GATE_ALLOWED = 0
GATE_BLOCKED = 2


def evaluate_gate(
    *,
    state: str,
    evidence_complete: bool,
    acceptance: str,
    designer: Any,
    reviewer: Any,
    depends_on: Sequence[Any] = (),
    settlement_status: str = "",
) -> dict[str, Any]:
    """判定一个订单是否有资格进入结算。

    四道门，按「越靠前越不该被绕过」的顺序累积：
    1. 前置订单必须已被**具名验收**（别人的东西没验收，不要拿来当地基）
    2. 证据链必须完整（红→改→绿，同一命令）
    3. 责任分离必须成立（设计师 ≠ 验收人，验收人是人）
    4. 本订单必须已被**具名验收** —— 这道门程序永远不会自动通过

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
                f"前置订单 {code} 尚未被具名验收（acceptance={dep_acceptance}）"
            )

    if not evidence_complete:
        blockers.append("证据链不完整：缺少有效的红灯→返工→绿灯")

    blockers.extend(separation_issues(designer, reviewer))

    accepted = acceptance == "accepted"
    if not accepted:
        blockers.append(f"订单尚未被具名验收（acceptance={acceptance}）")

    # 已结清的订单再判一次门禁没有意义，直接放行。
    already = state == "settled" or settlement_status in ("paid", "settled")

    allowed = not blockers or already
    reason = "全部条件满足，可以进入结算" if allowed else "；".join(blockers)
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
# 验收动作：只有人能签，且不能自签
# ---------------------------------------------------------------------------
ACCEPTANCE_PENDING = "pending_human_review"
ACCEPTANCE_ACCEPTED = "accepted"
ACCEPTANCE_REJECTED = "rejected"


def accept_order(*, order: Any, actor: Any, designer: Any = None) -> dict[str, Any]:
    """尝试对订单做人工验收。返回 ``ok`` 与原因；不修改任何外部状态。

    ``designer`` 建议显式传入**设计师的具名身份**（而非数据库主键），否则
    责任分离会退化成「两个不同类型的字符串永不相等」，等于没有校验。
    """
    designer = designer if designer is not None else _field(order, "designer_name")
    if not is_human_actor(actor):
        return {"ok": False, "reason": f"验收人必须是具名的人（收到：{actor}）"}
    if designer and str(designer).strip().lower() == str(actor).strip().lower():
        return {"ok": False, "reason": "设计师不能验收自己的稿，请由他人复核"}
    state = _field(order, "state")
    if state not in ("pending_review", "delivered"):
        return {"ok": False, "reason": f"只有待验收/已交付状态的订单可以验收（当前：{state_label(state)}）"}
    return {"ok": True, "reason": f"已由 {actor} 具名验收"}


# ---------------------------------------------------------------------------
# 有界返工回路（只判定不执行：投影不改任何订单状态）
# ---------------------------------------------------------------------------
REPAIR_LOOP_MAX_ROUNDS = 3

_REWORK_ISSUE_PREFIX = "退回返工："

# 离开 drafting 的归宿：收敛类真的结束本轮；drafting 自环只是「本轮已开修」
_ROUND_CLOSED_BY: Mapping[str, str] = {
    "pending_review": "converged",   # 复验通过进人审
    "delivered": "converged",
    "settled": "accepted",
    "canceled": "canceled",
}


def repair_rounds(events: Iterable[Any]) -> list[dict[str, Any]]:
    """从事件流重放返工轮次。进入 ``drafting``（且带返工原因）= 开一轮。

    - ``kind=rejected`` 的事件不算流转（它被门禁拦下了），跳过；
    - 轮次终止于收敛（→pending_review / delivered / settled / canceled）或下一轮返工；
    - 返工原因的可比性：只有 evaluate 事件写的「退回返工：…」能解析出结构化原因清单；
      人工流转的备注是人的判断，不参与「无进展」比较。
    """
    rounds: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for ev in events or ():
        if _field(ev, "kind") == "rejected":
            continue
        to_state = _field(ev, "to_state")
        created_at = str(_field(ev, "created_at") or "")
        if to_state == "drafting":
            detail = str(_field(ev, "detail") or "")
            # 只有带返工原因的 drafting 才算「开一轮」，
            # 否则正常的「接单 → 初稿中」也会被误算成返工。
            is_rework = _field(ev, "kind") in ("evaluate", "rework") or _REWORK_ISSUE_PREFIX in detail
            if not is_rework:
                if current is not None and current["outcome"] is None:
                    current["ended_at"] = created_at
                    current["outcome"] = "failed_again"
                continue
            if current is not None and current["outcome"] is None:
                current["ended_at"] = created_at
                current["outcome"] = "failed_again"
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
        elif current is not None and to_state == "finalizing":
            current["repaired_at"] = created_at
    return rounds


def repair_loop_projection(
    events: Iterable[Any], *, max_rounds: int = REPAIR_LOOP_MAX_ROUNDS
) -> dict[str, Any]:
    """有界返工回路的只读投影：状态、轮次历史、停止原因与交接建议。

    状态语义：
    - ``ready``              还没返工过
    - ``continue``           在界内（未达轮数上限、原因未见恶化），可以继续修
    - ``verifying``          上一轮已开修，等下一轮复验
    - ``converged``          最近一轮已收敛（进待验收 / 已交付）
    - ``closed``             订单取消，回路随之关闭
    - ``stopped_max_rounds`` 返工轮次达上限
    - ``stopped_no_progress`` 连续两轮返工原因完全相同（照原样再修没有意义）
    """
    rounds = repair_rounds(events)
    last = rounds[-1] if rounds else None
    comparable = [r for r in rounds if r["issues"]]

    if not rounds:
        status, reason = "ready", "尚未进入返工"
    elif last["outcome"] in ("converged", "accepted"):
        status, reason = "converged", "最近一轮返工已收敛，进入验收或已结清"
    elif last["outcome"] == "canceled":
        status, reason = "closed", "订单已取消，返工回路随之关闭"
    elif (
        len(comparable) >= 2
        and comparable[-1]["issues"] == comparable[-2]["issues"]
    ):
        # 停止条件必须**先于**「等待复验」判断。
        # 否则最后一轮已开修、还没复验时，状态永远是 verifying，
        # 「已达轮数上限」「连续两轮同因」这两个停止信号会被彻底吞掉。
        status, reason = (
            "stopped_no_progress",
            "连续两轮返工原因完全相同：照原样再修不会变好",
        )
    elif len(rounds) >= max_rounds:
        status, reason = "stopped_max_rounds", f"返工轮次已达上限（{max_rounds} 轮）"
    elif last["outcome"] is None and last["repaired_at"]:
        status, reason = "verifying", "上一轮已开修，等待复验"
    else:
        status, reason = "continue", "返工轮次在界内，可以继续修复"

    handoff = None
    if status.startswith("stopped_"):
        handoff = {
            "stop_reason": reason,
            "rounds": len(rounds),
            "last_issues": list(last["issues"]) if last and last["issues"] else None,
            "next_action": (
                "由具名负责人决策：换设计方案、缩小范围或取消订单；"
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
# 分账计算：金额一律 Decimal，比例只从规则表读
# ---------------------------------------------------------------------------
#: 分账口径的名字（与总后台的结构对齐）。
SPLIT_SCOPES: tuple[str, ...] = (
    "designer",       # 设计师佣金
    "hr",             # HR 佣金
    "quality_control",  # 品控佣金
    "supervisor",     # 主管奖金
    "control",        # 中控金额
)

SPLIT_SCOPE_LABELS: Mapping[str, str] = {
    "designer": "设计师佣金",
    "hr": "HR 佣金",
    "quality_control": "品控佣金",
    "supervisor": "主管奖金",
    "control": "中控金额",
}

#: 金额保留两位。
MONEY_EXP = Decimal("0.01")


def to_decimal(value: Any, default: Decimal | None = None) -> Decimal | None:
    """把任意输入安全地转成 Decimal。

    - None / 空串 → default（默认 None）
    - 带 ¥ 与千分位逗号的字符串 → 剥掉再转
    - 非法值 → default（**不抛异常**，脏数据不该让整个页面挂掉）
    """
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return default
    if isinstance(value, (int,)):
        return Decimal(value)
    if isinstance(value, float):
        # float 先转 str 再转 Decimal，避免二进制误差被放大
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return default
    text = text.replace("¥", "").replace("￥", "").replace(",", "").replace(" ", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return default


def quantize_money(value: Decimal) -> Decimal:
    """金额量化到两位，四舍五入（ROUND_HALF_UP，财务惯例，不是银行家舍入）。"""
    return value.quantize(MONEY_EXP, rounding=ROUND_HALF_UP)


def split_commission(
    total: Any,
    rules: Iterable[Any],
    *,
    basis: Any = None,
) -> dict[str, Any]:
    """按规则表把订单金额拆成各角色应得份额。

    参数：
    - ``total``  订单总金额（字符串/数字都收，内部转 Decimal）
    - ``rules``  规则集合，每条含 ``scope`` / ``rate`` / ``enabled``
    - ``basis``  奖金基数；为 None 时用 ``total``（总后台的「奖金基数」是独立概念）

    返回：
    ``{"total": Decimal, "shares": {scope: Decimal}, "rates": {scope: Decimal},
      "remainder": Decimal, "basis": Decimal, "issues": [str]}``

    **关键口径**：比例之和不为 1 时，多出来的部分归入 ``remainder``（中控/公司留存），
    绝不让各角色份额悄悄超过总额 —— 这是分账系统最容易出的错。
    """
    total_dec = to_decimal(total, Decimal("0")) or Decimal("0")
    basis_dec = to_decimal(basis, None)
    if basis_dec is None:
        basis_dec = total_dec

    shares: dict[str, Decimal] = {}
    rates: dict[str, Decimal] = {}
    issues: list[str] = []
    used = Decimal("0")

    enabled_rules = []
    for rule in rules or ():
        scope = str(_field(rule, "scope", "") or "")
        enabled = _field(rule, "enabled", True)
        if not scope or not enabled:
            continue
        if scope not in SPLIT_SCOPES:
            issues.append(f"未知的分账口径：{scope}")
            continue
        rate = to_decimal(_field(rule, "rate"), None)
        if rate is None:
            issues.append(f"分账口径 {scope} 的比例不是合法数字")
            continue
        enabled_rules.append((scope, rate))

    for scope, rate in enabled_rules:
        # 奖金按基数算，其余按总额算
        base = basis_dec if scope == "supervisor" else total_dec
        amount = quantize_money(base * rate)
        shares[scope] = shares.get(scope, Decimal("0")) + amount
        rates[scope] = rate
        used += amount

    remainder = quantize_money(total_dec - used)

    # 兜底：份额合计不得超过总额（负数说明规则配错，强制归零并报告）
    if remainder < 0:
        issues.append(
            f"分账比例之和超过 100%（合计 {quantize_money(used)} > 总额 {total_dec}），"
            f"已把超出部分归入中控"
        )
        remainder = Decimal("0")

    return {
        "total": quantize_money(total_dec),
        "basis": quantize_money(basis_dec),
        "shares": shares,
        "rates": rates,
        "remainder": remainder,
        "issues": issues,
    }


def split_summary(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """把分账结果渲染成界面可用的行。"""
    rows: list[dict[str, Any]] = []
    total = result.get("total", Decimal("0"))
    shares = result.get("shares", {}) or {}
    for scope in SPLIT_SCOPES:
        if scope not in shares:
            continue
        amount = shares[scope]
        rate = (result.get("rates", {}) or {}).get(scope, Decimal("0"))
        percent = Decimal("0")
        if total:
            percent = quantize_money(amount / total * 100)
        rows.append({
            "scope": scope,
            "label": SPLIT_SCOPE_LABELS.get(scope, scope),
            "amount": str(amount),
            "rate": str(rate),
            "percent": str(percent),
        })
    remainder = result.get("remainder", Decimal("0"))
    if remainder:
        rows.append({
            "scope": "remainder",
            "label": "公司留存",
            "amount": str(remainder),
            "rate": "",
            "percent": str(quantize_money(remainder / total * 100)) if total else "0",
        })
    return rows


# ---------------------------------------------------------------------------
# 撮合推荐：AI 降级排序（没配 key 时也要能用）
# ---------------------------------------------------------------------------
#: 中文停用词 —— 分词时剔除，避免「的」「一个」这类词主导相关度。
_STOPWORDS: frozenset[str] = frozenset({
    "的", "了", "和", "与", "或", "在", "是", "有", "个", "张", "个", "要", "做", "个",
    "要求", "需要", "请", "把", "给", "用", "以", "及", "等", "并", "对", "从",
    "设计", "稿件", "订单", "客户", "店铺",
})


def extract_terms(text: str) -> list[str]:
    """从文本里抽关键词。

    中文没有空格，不能只按标点切 —— 那样「元以内的女士连衣裙」会整块当一个词，
    直接零命中。所以按「修饰词 + 品类词」的粒度切。

    实测踩过的坑（三次）：
    1. 只按标点切 → 「元以内的女士连衣裙」整块当一个词，相关度永远 0。
    2. 只处理「数字+量词」→ 「元以内」「以内」这种「量词+方位」组合没被切开。
       现在量词后面再跟方位词（以/内/以上/以下/左右/上下）也一并切。
    3. 停用词没剔干净 → 「的」「一个」「要求」这类词主导相关度。

    统一规则：先切出「量词 + 方位」这类修饰片段，再把剩下的按标点/空白切词。
    """
    if not text:
        return []
    # 先把「量词 + 方位词」的组合切掉（10 元以内 / 3 件以上 / 5 张左右）
    normalized = re.sub(
        r"[0-9]+(?:\.[0-9]+)?\s*(?:元|块|个|张|款|套|次|天|小时|分钟|px)"
        r"\s*(?:以内|以上|以下|左右|上下|之内|之外)?",
        " ", text)
    # 再把「量词 + 方位」切掉（无数字的情况：「元以内」「件以上」）
    normalized = re.sub(
        r"(?:元|块|个|张|款|套|次)\s*(?:以内|以上|以下|左右|上下|之内|之外)",
        " ", normalized)
    # 标点与符号
    normalized = re.sub(
        r"[，,。；;：:！!？?、（）()\[\]【】<>《》\"'`~@#￥$%^&*\-_=+|\\/]",
        " ", normalized)
    terms: list[str] = []
    seen: set[str] = set()
    for raw in normalized.split():
        term = raw.strip()
        if not term:
            continue
        if term in _STOPWORDS:
            continue
        # 单字只保留不是停用词的（如「鞋」「包」有意义）
        if len(term) == 1 and term in _STOPWORDS:
            continue
        if term not in seen:
            seen.add(term)
            terms.append(term)
    return terms


def _term_hit(term: str, value: str) -> bool:
    """一个关键词是否命中一段文本。

    中文没有词边界，整词包含会漏：
    需求写「女士连衣裙」，标签写「连衣裙」—— 整词判断 ``"女士连衣裙" in "连衣裙"``
    是 False，相关度直接归零。

    所以按片段重叠判断：**任意 2 字以上的片段命中**即算命中。
    单字词（如「鞋」「包」）仍走整词匹配，避免「包」命中「背包」这种噪音。
    """
    if not term or not value:
        return False
    if term in value:
        return True
    if len(term) < 2:
        return False
    for i in range(len(term) - 1):
        if term[i:i + 2] in value:
            return True
    return False


def score_candidate(
    requirement: str,
    candidate: Mapping[str, Any],
    *,
    fields: Sequence[str] = ("design_tags", "name", "note"),
) -> float:
    """给单个候选人算相关度（0-1）。

    需求文本里的关键词，命中候选人字段里越多分越高。
    权重按字段顺序递减：标签命中 > 姓名 > 备注。
    """
    terms = extract_terms(requirement)
    if not terms:
        return 0.0
    weights = (1.0, 0.6, 0.35)
    score = 0.0
    max_score = 0.0
    for field, weight in zip(fields, weights):
        value = str(_field(candidate, field, "") or "")
        if not value:
            max_score += weight
            continue
        max_score += weight
        hit = sum(1 for t in terms if _term_hit(t, value))
        if hit:
            score += weight * (hit / len(terms))
    if max_score <= 0:
        return 0.0
    return round(min(score / max_score, 1.0), 4)


def rank_candidates(
    requirement: str,
    candidates: Iterable[Any],
    *,
    fields: Sequence[str] = ("design_tags", "name", "note"),
    limit: int = 10,
) -> list[dict[str, Any]]:
    """按相关度给候选人排序。候选池不能为空 —— 空数组对界面毫无意义。

    没有 LLM 时的降级路径：纯关键词相关度。分数相同按名称排序，保证结果稳定可复现。
    """
    scored: list[dict[str, Any]] = []
    for cand in candidates or ():
        score = score_candidate(requirement, cand, fields=fields)
        scored.append({
            "designer": cand,
            "score": score,
            "name": str(_field(cand, "name", "") or ""),
        })
    scored.sort(key=lambda x: (-x["score"], x["name"]))
    return scored[:limit] if limit > 0 else scored


def fallback_recommendation(requirement: str, candidates: Iterable[Any]) -> str:
    """没有 LLM 时给出的推荐说明（纯规则，可解释）。"""
    terms = extract_terms(requirement)
    if not terms:
        return "需求单里没抽到关键词，无法按相关度推荐，请先补充「目标」章节。"
    top = rank_candidates(requirement, candidates, limit=3)
    if not top:
        return "设计师库是空的，先去「设计师」页添加几个候选人。"
    names = "、".join(f"{t['name']}({t['score']:.0%})" for t in top)
    return (
        f"按需求关键词（{'、'.join(terms[:6])}）的相关度排序，推荐：{names}。"
        f"当前为本地规则排序（未接入大模型），可在「规则」页配置后由模型给出推荐理由。"
    )


# ---------------------------------------------------------------------------
# 交付摘要：交付四要素（结果 / 证据 / 边界 / 交接）
# ---------------------------------------------------------------------------
def delivery_summary(
    *,
    code: Any,
    title: Any,
    state: Any,
    acceptance: Any,
    accepted_by: Any,
    accepted_at: Any,
    designer: Any,
    spec_snapshot: str,
    deliveries: Iterable[Any],
    depends_on: Sequence[Mapping[str, Any]] = (),
    commission: Any = None,
    split: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """把台账数据投影成一页可交接的交付摘要。

    只汇总「已经发生的事实」，不产生新判断；边界一节直接取自冻结的需求单
    （范围 / 非目标 / 约束），防止交接时口头扩大或缩小范围。
    """
    parsed = parse_spec(spec_snapshot)
    greens = [e for e in deliveries or () if _field(e, "phase") == "green" and _field(e, "return_code") == 0]
    reds = [e for e in deliveries or () if _field(e, "phase") == "red" and _field(e, "return_code") != 0]
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

    chain = chain_summary(deliveries)
    accepted = acceptance == ACCEPTANCE_ACCEPTED
    accepted_text = (
        f"{accepted_by}（{accepted_at}）" if accepted and accepted_by else "尚未具名验收"
    )

    money_rows: list[dict[str, Any]] = []
    if split:
        money_rows = split_summary(split)
    elif commission is not None:
        total = to_decimal(commission, Decimal("0")) or Decimal("0")
        money_rows = [{
            "scope": "total", "label": "订单金额", "amount": str(quantize_money(total)),
            "rate": "", "percent": "100",
        }]

    four: dict[str, dict[str, Any]] = {
        "结果": {
            "订单": f"{code} · {title}",
            "状态": f"{state}（{state_label(state)}）",
            "验收": accepted_text,
            "设计师": designer or "",
        },
        "证据": {
            "链完整性": "完整（红→改→绿，同一命令）" if chain["evidence_complete"] else "不完整",
            "计数": f"红灯 {chain['counts']['red']} · 返工 {chain['counts']['diff']} · 绿灯 {chain['counts']['green']} · 观察 {chain['counts']['observation']}",
            "绿灯命令": _field(green, "command_text") if green is not None else "",
            "红灯命令": _field(red, "command_text") if red is not None else "",
        },
        "边界": {
            "范围": parsed.get("范围", ""),
            "非目标": parsed.get("非目标", ""),
            "约束": parsed.get("约束", ""),
        },
        "交接": {
            "设计师": designer or "",
            "验收人": accepted_by if accepted else "",
            "金额": "、".join(f"{r['label']} {r['amount']}" for r in money_rows) or "—",
            "前置依赖": [
                {"code": d.get("code"), "acceptance": d.get("acceptance")} for d in depends_on or ()
            ],
        },
    }
    markdown = render_delivery_markdown(code, title, four, chain["evidence_complete"], accepted)
    return {"converged": accepted, "four": four, "markdown": markdown, "money": money_rows}


def render_delivery_markdown(
    code: Any, title: Any, four: Mapping[str, Mapping[str, Any]],
    evidence_complete: bool, accepted: bool,
) -> str:
    """把四要素渲染成可直接贴进交接单的 Markdown。"""
    lines: list[str] = [f"# 交付摘要 · {code} {title}", ""]
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
        f"{'已由具名的人验收' if accepted else '尚未被具名验收——验收是人的判断，程序不代签'}。"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 看板漏斗统计
# ---------------------------------------------------------------------------
def order_funnel(orders: Iterable[Any]) -> list[dict[str, Any]]:
    """按状态统计订单数与金额，用于看板漏斗图。"""
    counts: dict[str, int] = {s: 0 for s in ORDER_STATES}
    amounts: dict[str, Decimal] = {s: Decimal("0") for s in ORDER_STATES}
    for order in orders or ():
        state = str(_field(order, "state", "") or "")
        if state not in counts:
            continue
        counts[state] += 1
        amount = to_decimal(_field(order, "order_commission"), Decimal("0")) or Decimal("0")
        amounts[state] += amount
    return [
        {
            "state": state,
            "label": state_label(state),
            "count": counts[state],
            "amount": str(quantize_money(amounts[state])),
        }
        for state in ORDER_STATES
    ]
