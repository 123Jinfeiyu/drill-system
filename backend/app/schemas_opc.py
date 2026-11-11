"""OPC 一人公司系统 · 请求/响应 schema。

与 FDE 现有 schema 分开成独立文件，避免把两套业务的字段混在一个文件里
（fde 的 schema 已经有 660 行，再塞 OPC 会变成一个谁都不敢动的巨型文件）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 需求单
# ---------------------------------------------------------------------------
class OpcSpecValidateIn(BaseModel):
    """需求单结构校验请求。"""

    spec_snapshot: str = ""


class OpcSpecValidateOut(BaseModel):
    """需求单结构校验结果。``issues`` 为空表示结构合格。"""

    ok: bool
    issues: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 订单
# ---------------------------------------------------------------------------
class OpcOrderCreate(BaseModel):
    """创建订单。``spec_snapshot`` 存的是**创建当时**的需求单原文。"""

    order_sn: str
    title: str = ""
    store_id: str | None = None
    store_name: str = ""
    designer_id: str | None = None
    designer_name: str = ""
    order_grade: str = ""
    order_type: str = ""
    order_commission: Any = 0
    request_delivery_time: str = ""
    sample_manuscript_time: str = ""
    final_draft_time: str = ""
    remark: str = ""
    spec_snapshot: str = ""
    depends_on: list[str] = Field(default_factory=list)


class OpcOrderEdit(BaseModel):
    """编辑订单。传哪个字段改哪个；未传的字段保持原样。"""

    title: str | None = None
    store_id: str | None = None
    store_name: str | None = None
    designer_id: str | None = None
    designer_name: str | None = None
    order_grade: str | None = None
    order_type: str | None = None
    order_commission: Any = None
    request_delivery_time: str | None = None
    sample_manuscript_time: str | None = None
    final_draft_time: str | None = None
    remark: str | None = None
    spec_snapshot: str | None = None


class OpcOrderOut(BaseModel):
    """订单列表项。"""

    id: str
    order_sn: str
    title: str
    store_name: str
    designer_name: str
    order_grade: str
    order_type: str
    order_commission: str
    request_delivery_time: str
    state: str
    state_label: str
    acceptance: str
    spec_issues: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OpcDeliveryOut(BaseModel):
    """交付证据。"""

    id: str
    phase: str
    phase_label: str
    command_text: str
    output: str
    return_code: int
    observed_at: datetime | None = None


class OpcEventOut(BaseModel):
    """订单事件。"""

    id: str
    kind: str
    from_state: str | None = None
    to_state: str | None = None
    actor: str
    detail: str
    created_at: datetime | None = None


class OpcGateOut(BaseModel):
    """结算门禁判定结果。"""

    allowed: bool
    code: int
    reason: str
    blockers: list[str] = Field(default_factory=list)
    evidence_complete: bool
    accepted: bool
    state: str


class OpcRepairLoopOut(BaseModel):
    """返工回路投影。"""

    max_rounds: int
    rounds: int
    status: str
    reason: str
    can_continue: bool
    history: list[dict[str, Any]] = Field(default_factory=list)
    handoff: dict[str, Any] | None = None


class OpcOrderDetailOut(BaseModel):
    """订单详情：订单本体 + 证据链 + 事件 + 门禁 + 返工 + 交付摘要。"""

    order: OpcOrderOut
    spec_snapshot: str
    deliveries: list[OpcDeliveryOut] = Field(default_factory=list)
    events: list[OpcEventOut] = Field(default_factory=list)
    chain: dict[str, Any] = Field(default_factory=dict)
    gate: OpcGateOut
    repair_loop: OpcRepairLoopOut
    summary: dict[str, Any] = Field(default_factory=dict)
    split: dict[str, Any] = Field(default_factory=dict)
    money: list[dict[str, Any]] = Field(default_factory=list)


class OpcDeliveryCreate(BaseModel):
    """追加一条交付证据。"""

    phase: Literal["red", "diff", "green", "observation"]
    command_text: str = ""
    output: str = ""
    return_code: int = 0
    observed_at: datetime | None = None


class OpcTransitionIn(BaseModel):
    """人工流转订单状态。"""

    to_state: str
    detail: str = ""


class OpcAcceptIn(BaseModel):
    """具名验收。``actor`` 为空时用当前登录用户。"""

    actor: str = ""
    note: str = ""


class OpcAssignIn(BaseModel):
    """派单：把订单指给某个设计师。"""

    designer_id: str
    detail: str = ""


class OpcClaimIn(BaseModel):
    """设计师接单。"""

    designer_id: str
    detail: str = ""


# ---------------------------------------------------------------------------
# 设计师 / 店铺
# ---------------------------------------------------------------------------
class OpcDesignerIn(BaseModel):
    """设计师档案。"""

    name: str
    phone: str = ""
    alipay_account: str = ""
    alipay_name: str = ""
    production_level: str = ""
    design_tags: str = ""
    war_zone: str = ""
    hr_id: str = ""
    quality_control_id: str = ""
    commission_rate: Any = 0
    status: str = "active"
    note: str = ""


class OpcDesignerOut(BaseModel):
    id: str
    name: str
    phone: str
    alipay_account: str
    alipay_name: str
    production_level: str
    design_tags: str
    war_zone: str
    hr_id: str
    quality_control_id: str
    commission_rate: str
    status: str
    note: str
    order_count: int = 0
    active_count: int = 0


class OpcStoreIn(BaseModel):
    """店铺档案。"""

    name: str
    url: str = ""
    customer_name: str = ""
    manager: str = ""
    commission: Any = 0
    settlement_days: int = 0
    remark: str = ""


class OpcStoreOut(BaseModel):
    id: str
    name: str
    url: str
    customer_name: str
    manager: str
    commission: str
    settlement_days: int
    remark: str
    order_count: int = 0


# ---------------------------------------------------------------------------
# 结算
# ---------------------------------------------------------------------------
class OpcSettlementOut(BaseModel):
    id: str
    order_id: str
    order_sn: str
    designer_name: str
    commission: str
    settlement_type: str
    settlement_days: int
    status: str
    alipay_account: str
    alipay_name: str
    upstream_settlement_time: str
    paid_at: datetime | None = None
    paid_by: str | None = None
    remark: str
    created_at: datetime | None = None


class OpcSettlementPayIn(BaseModel):
    """标记已打款。"""

    actor: str = ""
    upstream_settlement_time: str = ""
    remark: str = ""


class OpcSettlementGenerateIn(BaseModel):
    """一键生成结算单。可指定订单；不指定则把「已交付」的订单全生成。"""

    order_ids: list[str] = Field(default_factory=list)
    settlement_type: str = "monthly"


# ---------------------------------------------------------------------------
# 分账规则
# ---------------------------------------------------------------------------
class OpcSplitRuleIn(BaseModel):
    scope: str
    rate: Any = 0
    basis: str = "total"
    enabled: bool = True
    remark: str = ""


class OpcSplitRuleOut(BaseModel):
    id: str
    scope: str
    scope_label: str
    rate: str
    basis: str
    enabled: bool
    remark: str


class OpcSplitPreviewIn(BaseModel):
    """分账试算。"""

    total: Any = 0
    basis: Any = None


# ---------------------------------------------------------------------------
# 撮合
# ---------------------------------------------------------------------------
class OpcMatchOut(BaseModel):
    """撮合看板。"""

    pending: list[OpcOrderOut] = Field(default_factory=list)
    active: list[OpcOrderOut] = Field(default_factory=list)
    pending_review: list[OpcOrderOut] = Field(default_factory=list)
    pending_settle: list[OpcOrderOut] = Field(default_factory=list)
    designers: list[OpcDesignerOut] = Field(default_factory=list)
    recommendation: str = ""


class OpcRecommendOut(BaseModel):
    """单个订单的候选人推荐。"""

    order_id: str
    requirement: str
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    reason: str = ""
    source: str = "rule"


class OpcDashboardOut(BaseModel):
    """撮合看板总览。"""

    funnel: list[dict[str, Any]] = Field(default_factory=list)
    total_orders: int = 0
    total_amount: str = "0"
    active_amount: str = "0"
    pending_settle_amount: str = "0"
    designer_count: int = 0
    store_count: int = 0
    settlement_pending_count: int = 0
    settlement_paid_amount: str = "0"
    designer_ranking: list[dict[str, Any]] = Field(default_factory=list)
    store_ranking: list[dict[str, Any]] = Field(default_factory=list)


class OpcMetaOut(BaseModel):
    """前端启动要用的元信息：状态机、阶段名、分账口径、需求单模板。"""

    states: list[dict[str, str]] = Field(default_factory=list)
    mainline: list[str] = Field(default_factory=list)
    #: 每个状态允许去的状态（状态机的唯一来源在后端，前端只读不算）
    transitions: dict[str, list[str]] = Field(default_factory=dict)
    scope_labels: dict[str, str] = Field(default_factory=dict)
    phase_labels: dict[str, str] = Field(default_factory=dict)
    spec_template: str = ""
    spec_sections: list[str] = Field(default_factory=list)


class OpcUpstreamDesignerOut(BaseModel):
    """上游设计师档案（只读拉取结果）。"""

    id: int = 0
    name: str = ""
    nickname: str = ""
    phone: str = ""
    alipay_account: str = ""
    war_zone: str = ""
    production_level: str = ""
    recruitment_source: str = ""
    hr_name: str = ""
    quality_control_name: str = ""
    design_supervisor_name: str = ""
    #: 上游是否允许该设计师参与结算（allow_settlement=1）
    can_settle: bool = False
    status: int = 1


class OpcSyncReportOut(BaseModel):
    """上游同步结果报告。"""

    upstream_orders: int = 0
    upstream_designers: int = 0
    upstream_settlements: int = 0
    upstream_commission_sum: str = "0"
    created: dict[str, int] = Field(default_factory=dict)
    updated: dict[str, int] = Field(default_factory=dict)
    #: 是否真的落库了（False = 只预览）
    wrote: bool = False
    settlement_type: int = 1
    settlement_type_label: str = ""
