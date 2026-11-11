"""OPC · 上游业务映射与对账层。

上游（数字教育平台）与 OPC 的**语义差异**在这里统一处理，
让上游的脏活（状态编号、隐藏筛选、字符串金额、多结算线）不渗进业务层。

====================  ==========================  ==========================
概念                  上游                        OPC
====================  ==========================  ==========================
订单状态              1..9 整数                  pending_assign..settled
结算状态              designer_settlement_status  结算单 status
佣金拆分              5 个独立字段                分账规则表 + 自动计算
需求描述              order_desc 一句话            六段式需求合同
====================  ==========================  ==========================

三条铁律（写在这里，别在别处重复实现）：

1. **状态映射是纯函数**，不碰数据库 —— 便于单测，也便于「上游又加了一个状态」
   时只改一张表。
2. **分账金额一律 Decimal**，上游给的是字符串 ``"35.00"``，
   走 float 会差一分钱，而一分钱在结算场景就是事故。
3. **对账只报告差异，不自动改上游**。OPC 是台账，不是上游的管理员。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from app.services.opc_ledger import MONEY_EXP, to_decimal
from app.services.trcipg_client import (SETTLEMENT_TYPES, UPSTREAM_ORDER_STATUS,
                                         UpstreamDesigner, UpstreamOrder,
                                         UpstreamSettlement)

# ---------------------------------------------------------------------------
# 上游订单状态 → OPC 状态机
# ---------------------------------------------------------------------------

#: 上游 ``status`` → OPC 状态。
#:
#: 上游 9 个状态里，OPC 只认 8 个主状态 + canceled。
#: 「验收中/问题处理中/问题待审核」这三个上游状态在 OPC 里都落在
#: ``pending_review``（还在等人验收），因为 OPC 的门禁要求**具名验收**才放行，
#: 上游的「问题待审核」不等于「已验收」，不能因为上游状态变了就放钱。
#:
#: 「已完结」(9) → ``settled``：上游把已结算订单标成完结。
UPSTREAM_TO_OPC_STATE: Mapping[int, str] = {
    1: "drafting",        # 初稿制作中
    2: "finalizing",      # 终稿制作中
    3: "pending_review",  # 已交付 → 等具名验收
    4: "pending_review",  # 验收中
    5: "delivered",       # 验收成功 → 已验收，未结算
    6: "drafting",        # 问题待处理 → 返工
    7: "drafting",        # 问题处理中 → 返工
    8: "pending_review",  # 问题待审核 → 等人判断
    9: "settled",         # 已完结
}

#: 上游状态 → 是否说明「上游认为这单已经结算完」
#:
#: 注意 ``designer_settlement_status`` 才是结算口径，
#: ``status==9`` 只是订单生命周期结束（可能走了「不结算」分支）。
UPSTREAM_SETTLED_STATUSES: frozenset[int] = frozenset({9})

#: 上游「结算状态」字典（实测：0=未结算 1=已发起 2=已结算 3=已取消 4=已完结）
UPSTREAM_SETTLEMENT_STATUS: Mapping[int, str] = {
    0: "待结算",
    1: "结算中",
    2: "已结算",
    3: "已取消",
    4: "已完结",
}


def map_upstream_state(upstream_status: int) -> str:
    """上游订单状态 → OPC 状态。

    未知状态**保守**映射到 ``pending_review``（等人看），
    绝不映射到 ``delivered`` / ``settled`` —— 放错方向会直接导致提前结算。
    """
    return UPSTREAM_TO_OPC_STATE.get(int(upstream_status or 0), "pending_review")


def map_settlement_status(upstream_status: int) -> str:
    """上游结算状态 → OPC 结算单状态。"""
    return UPSTREAM_SETTLEMENT_STATUS.get(int(upstream_status or 0), "待结算")


def upstream_state_label(upstream_status: int) -> str:
    return UPSTREAM_ORDER_STATUS.get(int(upstream_status or 0), f"未知({upstream_status})")


# ---------------------------------------------------------------------------
# 佣金拆分
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SplitBreakdown:
    """一张订单的佣金拆分结果。

    **上游口径（实测 300 条结算单确认）**：

    ==================  ==========================================
    关系                 说明
    ==================  ==========================================
    designer+control     恒等式，193/300 条严格成立
    +hr+qc == order      加入 HR 与品控佣金后 100% 成立
    supervisor 独立       主管奖金是**额外支出**，不从订单佣金里出
    ==================  ==========================================

    所以 ``residual`` 的口径是 ``order - (designer+hr+qc+control)``，
    **不含 supervisor** —— 把它算进去会凭空造出一笔差额。
    """

    total: Decimal = Decimal("0")
    designer: Decimal = Decimal("0")
    hr: Decimal = Decimal("0")
    quality_control: Decimal = Decimal("0")
    supervisor: Decimal = Decimal("0")
    control: Decimal = Decimal("0")

    @property
    def allocated(self) -> Decimal:
        """从订单佣金里分配出去的总金额（不含主管奖金）。"""
        return (self.designer + self.hr + self.quality_control + self.control)

    @property
    def residual(self) -> Decimal:
        """总额减去已分配 —— 应当为 0，非 0 说明上游口径有出入。"""
        return (self.total - self.allocated).quantize(MONEY_EXP)

    @property
    def is_balanced(self) -> bool:
        """四项佣金之和是否等于订单佣金。"""
        return self.residual == Decimal("0.00")

    def as_dict(self) -> dict[str, str]:
        return {
            "total": str(self.total),
            "designer": str(self.designer),
            "hr": str(self.hr),
            "quality_control": str(self.quality_control),
            "supervisor": str(self.supervisor),
            "control": str(self.control),
            "allocated": str(self.allocated.quantize(MONEY_EXP)),
            "residual": str(self.residual),
            "balanced": self.is_balanced,
        }


def extract_upstream_split(order: UpstreamOrder) -> SplitBreakdown:
    """把上游订单的五项佣金抽成分账结构。

    **不重新计算比例** —— 上游已经算好了，直接取。
    OPC 的规则表用于「在 OPC 台账里新建的订单」（没有上游数据时），
    两套口径不要混：混了会对不上账。
    """
    return SplitBreakdown(
        total=to_decimal(order.order_commission),
        designer=to_decimal(order.designer_commission),
        hr=to_decimal(order.hr_commission),
        quality_control=to_decimal(order.quality_control_commission),
        supervisor=to_decimal(order.design_supervisor_bonus),
        control=to_decimal(order.middle_control_commission),
    )


# ---------------------------------------------------------------------------
# 需求合同：把上游的一句话需求补成六段式
# ---------------------------------------------------------------------------


def build_spec_from_upstream(order: UpstreamOrder) -> str:
    """用上游订单的真实字段拼一份六段式需求合同（Markdown）。

    **只用上游真实数据，不编造需求**。上游只有 ``order_desc`` 一句话，
    六段式里其余段落会明确写「上游未提供」，
    由 OPC 的 ``validate_spec`` 报出「信息不足」，让操作者去补 ——
    而不是让模型编一段看着像模像样的假需求。
    """
    lines: list[str] = []
    lines.append(f"# 订单需求单 · {order.sn or order.order_sn}")
    lines.append("")

    lines.append("## 目标")
    desc = order.order_desc.strip()
    lines.append(desc if desc else "（上游未提供需求描述，需补）")
    lines.append("")

    lines.append("## 范围")
    scope_bits = []
    if order.store_name:
        scope_bits.append(f"店铺：{order.store_name}")
    if order.customer_name:
        scope_bits.append(f"客户：{order.customer_name}")
    if order.order_grade:
        scope_bits.append(f"档次：{order.order_grade}")
    lines.append("\n".join(f"- {bit}" for bit in scope_bits) if scope_bits
                 else "（上游未提供范围信息，需补）")
    lines.append("")

    lines.append("## 非目标")
    lines.append("（上游未提供，需人工确认本次不做什么）")
    lines.append("")

    lines.append("## 约束")
    constraint_bits = []
    if order.request_delivery_time:
        constraint_bits.append(f"要求交付时间：{order.request_delivery_time}")
    if order.sample_manuscript_time:
        constraint_bits.append(f"初稿时间：{order.sample_manuscript_time}")
    if order.final_draft_time:
        constraint_bits.append(f"终稿时间：{order.final_draft_time}")
    if order.customer_service:
        constraint_bits.append(f"客服：{order.customer_service}")
    lines.append("\n".join(f"- {bit}" for bit in constraint_bits) if constraint_bits
                 else "（上游未提供约束信息，需补）")
    lines.append("")

    lines.append("## 验收标准")
    accept_bits = []
    if order.end_images:
        accept_bits.append(f"终稿交付物 {len(order.end_images)} 个（见订单附件）")
    if order.source_images:
        accept_bits.append(f"原稿 {len(order.source_images)} 个（见订单附件）")
    if order.issue_desc:
        accept_bits.append(f"上游记录的问题：{order.issue_desc}")
    lines.append("\n".join(f"- {bit}" for bit in accept_bits) if accept_bits
                 else "（上游未提供验收标准，需补）")
    lines.append("")

    lines.append("## 完成定义")
    lines.append("上游标记为「验收成功」且已具名验收后进入结算；"
                 "证据链需满足 红→改→绿 且终稿与红灯同一验收命令。")
    lines.append("")

    return "\n".join(lines)


def extract_terms_for_match(order: UpstreamOrder) -> str:
    """把订单的匹配关键词拼成一段文本，用于撮合相关度排序。

    只用有信息量的字段：需求描述、档次、店铺、客户。
    """
    bits = [order.order_desc, order.order_grade, order.store_name,
            order.customer_name, order.store_account]
    return " ".join(b for b in bits if b).strip()


# ---------------------------------------------------------------------------
# 对账
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ReconcileIssue:
    """一条对账差异。"""

    kind: str          # 类型：commission_mismatch / residual / settlement_gap / ...
    scope: str         # 范围：订单号或结算单号
    message: str       # 人话描述
    upstream: str = "" # 上游值
    opc: str = ""      # OPC 值

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "scope": self.scope, "message": self.message,
                "upstream": self.upstream, "opc": self.opc}


@dataclass(slots=True)
class ReconcileReport:
    """一次对账的完整结果。

    **两种金额口径分开记，不混加**：
    - ``upstream_total_commission``：订单佣金（设计主管视角的接单总额）
    - ``upstream_settlement_commission``：结算单佣金（设计师视角的实发总额）

    两者不是同一个数 —— 混起来加会算出一个根本不存在的金额。
    """

    checked_orders: int = 0
    checked_settlements: int = 0
    issues: list[ReconcileIssue] = field(default_factory=list)
    upstream_total_commission: Decimal = Decimal("0")
    upstream_settlement_commission: Decimal = Decimal("0")
    opc_total_commission: Decimal = Decimal("0")

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def commission_gap(self) -> Decimal:
        """订单佣金口径的差额。"""
        return (self.upstream_total_commission - self.opc_total_commission).quantize(MONEY_EXP)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked_orders": self.checked_orders,
            "checked_settlements": self.checked_settlements,
            "issue_count": len(self.issues),
            "issues": [i.as_dict() for i in self.issues[:200]],
            "upstream_total_commission": str(self.upstream_total_commission),
            "upstream_settlement_commission": str(self.upstream_settlement_commission),
            "opc_total_commission": str(self.opc_total_commission),
            "commission_gap": str(self.commission_gap),
        }


def reconcile_order(order: UpstreamOrder, opc_commission: Decimal | None) -> list[ReconcileIssue]:
    """单张订单对账：上游佣金 vs OPC 台账佣金。

    ``opc_commission`` 为 None 表示 OPC 里还没这条订单 —— 不算差异（只是没同步）。
    """
    issues: list[ReconcileIssue] = []
    if opc_commission is None:
        return issues

    upstream = to_decimal(order.order_commission)
    if upstream != opc_commission:
        issues.append(ReconcileIssue(
            kind="commission_mismatch",
            scope=order.sn or str(order.id),
            message="订单佣金与上游不一致",
            upstream=str(upstream),
            opc=str(opc_commission),
        ))

    split = extract_upstream_split(order)
    if split.residual != Decimal("0.00"):
        issues.append(ReconcileIssue(
            kind="split_residual",
            scope=order.sn or str(order.id),
            message="上游五项佣金之和不等于订单佣金",
            upstream=str(split.total),
            opc=str(split.allocated),
        ))
    return issues


def reconcile_settlement(
    settlement: UpstreamSettlement, opc_commission: Decimal | None
) -> list[ReconcileIssue]:
    """单条结算单对账。"""
    issues: list[ReconcileIssue] = []
    if opc_commission is None:
        return issues

    upstream = to_decimal(settlement.commission)
    if upstream != opc_commission:
        issues.append(ReconcileIssue(
            kind="settlement_commission_mismatch",
            scope=settlement.sn or str(settlement.id),
            message="结算单佣金与上游不一致",
            upstream=str(upstream),
            opc=str(opc_commission),
        ))
    return issues


def build_report(
    orders: Sequence[UpstreamOrder],
    settlements: Sequence[UpstreamSettlement],
    opc_order_commissions: Mapping[str, Decimal],
    opc_settlement_commissions: Mapping[str, Decimal],
) -> ReconcileReport:
    """汇总对账报告。"""
    report = ReconcileReport(
        checked_orders=len(orders),
        checked_settlements=len(settlements),
    )
    for order in orders:
        key = order.sn or str(order.id)
        report.upstream_total_commission += to_decimal(order.order_commission)
        opc_value = opc_order_commissions.get(key)
        if opc_value is not None:
            report.opc_total_commission += opc_value
        report.issues.extend(reconcile_order(order, opc_value))

    for st in settlements:
        key = st.sn or str(st.id)
        # 结算单佣金是**设计师侧实发**，与订单佣金不是同一个口径，
        # 必须分开统计 —— 混在一起加总会算出一个不存在的数。
        report.upstream_settlement_commission += to_decimal(st.commission)
        opc_value = opc_settlement_commissions.get(key)
        report.issues.extend(reconcile_settlement(st, opc_value))
    return report


# ---------------------------------------------------------------------------
# 撮合：给订单挑设计师
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CandidateScore:
    """一个候选设计师的打分明细。"""

    designer: UpstreamDesigner
    score: float
    reasons: list[str] = field(default_factory=list)
    blocked: str = ""   # 非空表示不能派单，值说明原因

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.designer.id,
            "name": self.designer.name,
            "score": round(self.score, 4),
            "reasons": self.reasons,
            "blocked": self.blocked,
        }


def score_designer_for_order(
    order: UpstreamOrder,
    designer: UpstreamDesigner,
    *,
    busy_designer_ids: Iterable[int] = (),
) -> CandidateScore:
    """给单个设计师打分。

    打分维度（都用**上游真实字段**，不臆造）：
    - 档次匹配：设计师档次 vs 订单档次
    - 战区匹配：同战区优先（上游的战区就是业务归属）
    - 结算资格：``allow_settlement=0`` 的一律 blocked —— 派了也结不掉
    - 忙碌度：正在制的单越多，扣分越多
    """
    reasons: list[str] = []
    blocked = ""
    score = 0.0

    if not designer.can_settle:
        blocked = "上游未开放结算权限，不能派单"

    busy = set(int(b) for b in busy_designer_ids)
    if designer.id in busy:
        score -= 3.0
        reasons.append("当前有在制订单，优先级降低")

    if order.order_grade and designer.production_level:
        if order.order_grade == designer.production_level:
            score += 2.0
            reasons.append(f"档次匹配（{designer.production_level}）")
        else:
            score -= 0.5
            reasons.append(f"档次不匹配（订单 {order.order_grade} / 设计师 {designer.production_level}）")

    if order.war_zone_name and designer.war_zone:
        if order.war_zone_name == designer.war_zone:
            score += 1.5
            reasons.append(f"同战区（{designer.war_zone}）")
        else:
            score -= 0.5
            reasons.append(f"跨战区（订单 {order.war_zone_name} / 设计师 {designer.war_zone}）")

    if not designer.alipay_account:
        blocked = blocked or "没有收款账号，结算不了"
    if designer.status != 1:
        blocked = blocked or "设计师已停用"

    return CandidateScore(designer=designer, score=score, reasons=reasons, blocked=blocked)


def rank_designers_for_order(
    order: UpstreamOrder,
    designers: Iterable[UpstreamDesigner],
    *,
    busy_designer_ids: Iterable[int] = (),
    limit: int = 10,
) -> list[CandidateScore]:
    """给订单排出候选设计师列表（可派的排前面）。"""
    scored = [
        score_designer_for_order(order, d, busy_designer_ids=busy_designer_ids)
        for d in designers
    ]
    # 能派的优先，同组内按分数降序
    scored.sort(key=lambda c: (bool(c.blocked), -c.score, c.designer.id))
    return scored[:limit]


def summarize_settlement_types() -> list[dict[str, Any]]:
    """上游三条结算线的说明，给前端下拉用。"""
    return [{"value": k, "label": v} for k, v in SETTLEMENT_TYPES.items()]
