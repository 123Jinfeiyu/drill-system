"""OPC 一人公司系统 · 订单台账路由。

设计边界（照搬 FDE 工作台那条，别越界）：
- 本路由**不执行任何交付动作**。它只接收「已经发生过的交付记录」并作出判断。
  真正的出图/验收在工作台之外完成，工作台负责的是**证据诚信**。
- 规则全部来自 ``app.services.opc_ledger``，路由只做持久化与编排，不自己发明判定。
"""
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.timeutil import utcnow
from app.database import get_db
from app.models import (OpcDelivery, OpcDesigner, OpcEvent, OpcOrder,
                         OpcSplitRule, OpcStore, User)
from app.schemas_opc import (OpcAcceptIn, OpcAssignIn, OpcClaimIn,
                             OpcDeliveryCreate, OpcDeliveryOut,
                             OpcEventOut, OpcGateOut, OpcOrderCreate,
                             OpcOrderDetailOut, OpcOrderEdit, OpcOrderOut,
                             OpcRepairLoopOut, OpcSpecValidateIn,
                             OpcSpecValidateOut, OpcTransitionIn)
from app.services import opc_ledger as ledger

router = APIRouter(prefix="/api/opc/orders", tags=["opc-orders"])


# --------------------------------------------------------------------------- 内部
def _actor(user: User) -> str:
    return user.display_name or user.username


async def _get_order(db: AsyncSession, order_id: str) -> OpcOrder:
    order = (await db.execute(
        select(OpcOrder).where(OpcOrder.id == order_id)
    )).scalar_one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")
    return order


async def _deliveries(db: AsyncSession, order_id: str) -> list[OpcDelivery]:
    rows = await db.execute(
        select(OpcDelivery)
        .where(OpcDelivery.order_id == order_id)
        .order_by(OpcDelivery.observed_at, OpcDelivery.created_at)
    )
    return list(rows.scalars())


async def _events(db: AsyncSession, order_id: str) -> list[OpcEvent]:
    rows = await db.execute(
        select(OpcEvent)
        .where(OpcEvent.order_id == order_id)
        .order_by(OpcEvent.created_at, OpcEvent.id)
    )
    return list(rows.scalars())


async def _log(db: AsyncSession, order: OpcOrder, kind: str, actor: str,
               detail: str, from_state: str | None = None,
               to_state: str | None = None) -> OpcEvent:
    """追加一条事件。事件只追加不覆盖 —— 这是证据链能成立的前提。"""
    ev = OpcEvent(
        order_id=order.id,
        kind=kind,
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        detail=detail,
    )
    db.add(ev)
    await db.flush()
    return ev


async def _depends(db: AsyncSession, order: OpcOrder) -> list[dict]:
    """把 depends_on 里的订单编号解析成门禁需要的上下文。"""
    codes = list(order.depends_on or [])
    if not codes:
        return []
    rows = await db.execute(
        select(OpcOrder).where(OpcOrder.order_sn.in_(codes))
    )
    by_sn = {o.order_sn: o for o in rows.scalars()}
    return [
        {"code": code, "acceptance": (by_sn[code].acceptance if code in by_sn else None)}
        for code in codes
    ]


async def _split_rules(db: AsyncSession) -> list[OpcSplitRule]:
    rows = await db.execute(select(OpcSplitRule).order_by(OpcSplitRule.scope))
    return list(rows.scalars())


def _order_out(order: OpcOrder) -> OpcOrderOut:
    return OpcOrderOut(
        id=order.id,
        order_sn=order.order_sn,
        title=order.title,
        store_name=order.store_name,
        designer_name=order.designer_name,
        order_grade=order.order_grade,
        order_type=order.order_type,
        order_commission=str(order.order_commission or 0),
        request_delivery_time=order.request_delivery_time,
        state=order.state,
        state_label=ledger.state_label(order.state),
        acceptance=order.acceptance,
        spec_issues=list(order.spec_issues or []),
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def _delivery_out(d: OpcDelivery) -> OpcDeliveryOut:
    return OpcDeliveryOut(
        id=d.id,
        phase=d.phase,
        phase_label=ledger.PHASE_LABELS.get(d.phase, d.phase),
        command_text=d.command_text,
        output=d.output,
        return_code=d.return_code,
        observed_at=d.observed_at,
    )


def _event_out(e: OpcEvent) -> OpcEventOut:
    return OpcEventOut(
        id=e.id,
        kind=e.kind,
        from_state=e.from_state,
        to_state=e.to_state,
        actor=e.actor,
        detail=e.detail,
        created_at=e.created_at,
    )


# --------------------------------------------------------------------------- 需求单
@router.post("/specs/validate", response_model=OpcSpecValidateOut)
async def validate_spec(payload: OpcSpecValidateIn,
                        _: User = Depends(get_current_user)):
    """校验需求单结构。结构合格 ≠ 需求想清楚了 —— 界面要分开呈现。"""
    issues = ledger.validate_spec(payload.spec_snapshot)
    return OpcSpecValidateOut(ok=not issues, issues=issues)


# --------------------------------------------------------------------------- 列表 / 创建
@router.get("", response_model=list[OpcOrderOut])
async def list_orders(
    state: str = "",
    designer: str = "",
    store: str = "",
    keyword: str = "",
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """订单列表。支持按状态/设计师/店铺/关键词过滤。"""
    stmt = select(OpcOrder)
    if state:
        stmt = stmt.where(OpcOrder.state == state)
    if designer:
        stmt = stmt.where(OpcOrder.designer_name.like(f"%{designer}%"))
    if store:
        stmt = stmt.where(OpcOrder.store_name.like(f"%{store}%"))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            OpcOrder.order_sn.like(like)
            | OpcOrder.title.like(like)
            | OpcOrder.designer_name.like(like)
            | OpcOrder.store_name.like(like)
        )
    rows = await db.execute(stmt.order_by(OpcOrder.created_at.desc()))
    return [_order_out(o) for o in rows.scalars()]


@router.post("", response_model=OpcOrderOut, status_code=201)
async def create_order(payload: OpcOrderCreate,
                        db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """创建订单。需求单原文作为**快照**存入，之后改动不改这份快照。"""
    exists = (await db.execute(
        select(OpcOrder).where(OpcOrder.order_sn == payload.order_sn)
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(400, f"订单编号已存在：{payload.order_sn}")

    issues = ledger.validate_spec(payload.spec_snapshot)
    store_name = payload.store_name
    if payload.store_id and not store_name:
        store = (await db.execute(
            select(OpcStore).where(OpcStore.id == payload.store_id)
        )).scalar_one_or_none()
        store_name = store.name if store else ""

    designer_name = payload.designer_name
    if payload.designer_id and not designer_name:
        d = (await db.execute(
            select(OpcDesigner).where(OpcDesigner.id == payload.designer_id)
        )).scalar_one_or_none()
        designer_name = d.name if d else ""

    order = OpcOrder(
        order_sn=payload.order_sn,
        title=payload.title,
        store_id=payload.store_id,
        store_name=store_name,
        designer_id=payload.designer_id,
        designer_name=designer_name,
        order_grade=payload.order_grade,
        order_type=payload.order_type,
        order_commission=ledger.to_decimal(payload.order_commission, ledger.Decimal("0")),
        request_delivery_time=payload.request_delivery_time,
        sample_manuscript_time=payload.sample_manuscript_time,
        final_draft_time=payload.final_draft_time,
        remark=payload.remark,
        spec_snapshot=payload.spec_snapshot,
        spec_hash=sha256(payload.spec_snapshot.encode("utf-8")).hexdigest(),
        spec_issues=issues,
        state="pending_assign",
        acceptance=ledger.ACCEPTANCE_PENDING,
        depends_on=list(payload.depends_on or []),
        created_by=user.id,
    )
    db.add(order)
    await db.flush()
    await _log(db, order, "spec", _actor(user),
               f"创建订单，需求单结构{'合格' if not issues else '有问题'}", to_state="pending_assign")
    await db.commit()
    await db.refresh(order)
    return _order_out(order)


@router.get("/{order_id}", response_model=OpcOrderDetailOut)
async def get_order(order_id: str,
                    db: AsyncSession = Depends(get_db),
                    _: User = Depends(get_current_user)):
    """订单详情：一次给全证据链、事件、门禁、返工投影、交付摘要。"""
    order = await _get_order(db, order_id)
    deliveries = await _deliveries(db, order_id)
    events = await _events(db, order_id)
    depends = await _depends(db, order)

    chain = ledger.chain_summary(deliveries)
    gate = ledger.evaluate_gate(
        state=order.state,
        evidence_complete=chain["evidence_complete"],
        acceptance=order.acceptance,
        designer=order.designer_name,
        reviewer=order.accepted_by,
        depends_on=depends,
    )
    loop = ledger.repair_loop_projection(events)

    rules = await _split_rules(db)
    split = ledger.split_commission(order.order_commission, rules)
    summary = ledger.delivery_summary(
        code=order.order_sn,
        title=order.title,
        state=order.state,
        acceptance=order.acceptance,
        accepted_by=order.accepted_by,
        accepted_at=order.accepted_at,
        designer=order.designer_name,
        spec_snapshot=order.spec_snapshot,
        deliveries=deliveries,
        depends_on=depends,
        commission=order.order_commission,
        split=split,
    )

    return OpcOrderDetailOut(
        order=_order_out(order),
        spec_snapshot=order.spec_snapshot,
        deliveries=[_delivery_out(d) for d in deliveries],
        events=[_event_out(e) for e in events],
        chain=chain,
        gate=OpcGateOut(**gate),
        repair_loop=OpcRepairLoopOut(**loop),
        summary=summary,
        split={k: (str(v) if isinstance(v, ledger.Decimal) else v)
               for k, v in split.items() if k != "shares"},
        money=summary.get("money") or [],
    )


@router.patch("/{order_id}", response_model=OpcOrderOut)
async def edit_order(order_id: str, payload: OpcOrderEdit,
                     db: AsyncSession = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """编辑订单。需求单若被改动，会重新校验并更新快照哈希。"""
    order = await _get_order(db, order_id)
    data = payload.model_dump(exclude_unset=True)

    if "order_commission" in data and data["order_commission"] is not None:
        order.order_commission = ledger.to_decimal(data["order_commission"], order.order_commission)

    if "store_id" in data and data["store_id"]:
        store = (await db.execute(
            select(OpcStore).where(OpcStore.id == data["store_id"])
        )).scalar_one_or_none()
        if store:
            order.store_name = store.name

    if "designer_id" in data and data["designer_id"]:
        d = (await db.execute(
            select(OpcDesigner).where(OpcDesigner.id == data["designer_id"])
        )).scalar_one_or_none()
        if d:
            order.designer_name = d.name

    for field in ("title", "store_name", "designer_name", "order_grade", "order_type",
                  "request_delivery_time", "sample_manuscript_time",
                  "final_draft_time", "remark"):
        if field in data and data[field] is not None:
            setattr(order, field, data[field])

    if "spec_snapshot" in data and data["spec_snapshot"] is not None:
        order.spec_snapshot = data["spec_snapshot"]
        order.spec_hash = sha256(data["spec_snapshot"].encode("utf-8")).hexdigest()
        order.spec_issues = ledger.validate_spec(data["spec_snapshot"])
        await _log(db, order, "spec", _actor(user), "更新需求单快照")

    await db.commit()
    await db.refresh(order)
    return _order_out(order)


@router.delete("/{order_id}")
async def delete_order(order_id: str,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """删除订单。只有还没进履约的（待派单）才允许删 —— 已接单的删了会丢证据链。"""
    order = await _get_order(db, order_id)
    if order.state not in ("pending_assign", "canceled"):
        raise HTTPException(
            400,
            f"订单已进入履约（{ledger.state_label(order.state)}），不能删除；"
            f"如需终止请流转到「已取消」。",
        )
    await db.delete(order)
    await db.commit()
    return {"ok": True, "message": f"订单 {order.order_sn} 已删除"}


# --------------------------------------------------------------------------- 派单 / 接单
@router.post("/{order_id}/assign", response_model=OpcOrderDetailOut)
async def assign_order(order_id: str, payload: OpcAssignIn,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """派单：把订单指给某个设计师，状态 → 已派单。"""
    order = await _get_order(db, order_id)
    if order.state != "pending_assign":
        raise HTTPException(400, f"只有「待派单」的订单可以派单（当前：{ledger.state_label(order.state)}）")

    designer = (await db.execute(
        select(OpcDesigner).where(OpcDesigner.id == payload.designer_id)
    )).scalar_one_or_none()
    if not designer:
        raise HTTPException(404, "设计师不存在")
    if designer.status != "active":
        raise HTTPException(400, f"设计师 {designer.name} 当前不可接单（状态：{designer.status}）")

    order.designer_id = designer.id
    order.designer_name = designer.name
    old = order.state
    order.state = "assigned"
    await _log(db, order, "transition", _actor(user),
               payload.detail or f"派单给 {designer.name}",
               from_state=old, to_state="assigned")
    await db.commit()
    return await get_order(order_id, db, user)


@router.post("/{order_id}/claim", response_model=OpcOrderDetailOut)
async def claim_order(order_id: str, payload: OpcClaimIn,
                      db: AsyncSession = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """设计师接单：状态 → 已接单。"""
    order = await _get_order(db, order_id)
    if order.state != "assigned":
        raise HTTPException(400, f"只有「已派单」的订单可以接单（当前：{ledger.state_label(order.state)}）")

    designer = (await db.execute(
        select(OpcDesigner).where(OpcDesigner.id == payload.designer_id)
    )).scalar_one_or_none()
    if not designer:
        raise HTTPException(404, "设计师不存在")

    order.designer_id = designer.id
    order.designer_name = designer.name
    old = order.state
    order.state = "taken"
    await _log(db, order, "transition", _actor(user),
               payload.detail or f"{designer.name} 接单",
               from_state=old, to_state="taken")
    await db.commit()
    return await get_order(order_id, db, user)


# --------------------------------------------------------------------------- 交付证据
@router.post("/{order_id}/deliveries", response_model=OpcOrderDetailOut,
             status_code=201)
async def add_delivery(order_id: str, payload: OpcDeliveryCreate,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """追加一条交付证据。证据**只追加不覆盖**。"""
    order = await _get_order(db, order_id)
    observed = payload.observed_at or utcnow()
    delivery = OpcDelivery(
        order_id=order.id,
        phase=payload.phase,
        command_text=payload.command_text,
        output=payload.output,
        output_hash=sha256(payload.output.encode("utf-8")).hexdigest(),
        return_code=payload.return_code,
        observed_at=observed,
    )
    db.add(delivery)
    await db.flush()
    await _log(db, order, "delivery", _actor(user),
               f"追加证据：{ledger.PHASE_LABELS.get(payload.phase, payload.phase)}"
               f"（命令：{payload.command_text or '未填'}，返回码：{payload.return_code}）")
    await db.commit()
    return await get_order(order_id, db, user)


# --------------------------------------------------------------------------- 复验
@router.post("/{order_id}/evaluate", response_model=OpcOrderDetailOut)
async def evaluate_order(order_id: str,
                          db: AsyncSession = Depends(get_db),
                          user: User = Depends(get_current_user)):
    """自动复验：按证据链判定能不能进验收。

    证据链不完整 → 状态退回「初稿制作中」，并记录退回原因（供返工回路比对）。
    证据链完整 → 状态推进到「待验收」。

    **不自动验收**。程序只判断证据够不够，验收是人的判断。
    """
    order = await _get_order(db, order_id)
    deliveries = await _deliveries(db, order_id)
    chain = ledger.chain_summary(deliveries)

    old = order.state
    if chain["evidence_complete"]:
        if order.state in ("drafting", "finalizing"):
            order.state = "pending_review"
            await _log(db, order, "evaluate", _actor(user),
                       "复验通过：证据链完整（红→改→绿，同一命令），进入待验收",
                       from_state=old, to_state=order.state)
    else:
        if order.state in ("drafting", "finalizing", "pending_review"):
            order.state = "drafting"
            detail = "退回返工：" + "；".join(chain["issues"])
            await _log(db, order, "evaluate", _actor(user), detail,
                       from_state=old, to_state="drafting")
    await db.commit()
    return await get_order(order_id, db, user)


# --------------------------------------------------------------------------- 人工流转
@router.post("/{order_id}/transition", response_model=OpcOrderDetailOut)
async def transition_order(order_id: str, payload: OpcTransitionIn,
                           db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """人工流转订单状态。跳阶段一律拒绝。"""
    order = await _get_order(db, order_id)
    src, dst = order.state, payload.to_state
    if not ledger.can_transition(src, dst):
        allowed = "、".join(ledger.state_label(s) for s in ledger.next_states(src)) or "（无）"
        raise HTTPException(
            400,
            f"不允许从「{ledger.state_label(src)}」流转到「{ledger.state_label(dst)}」。"
            f"当前可去：{allowed}",
        )
    order.state = dst
    await _log(db, order, "transition", _actor(user),
               payload.detail or f"人工流转到 {ledger.state_label(dst)}",
               from_state=src, to_state=dst)
    await db.commit()
    return await get_order(order_id, db, user)


# --------------------------------------------------------------------------- 具名验收
@router.post("/{order_id}/accept", response_model=OpcOrderDetailOut)
async def accept_order(order_id: str, payload: OpcAcceptIn,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """具名验收。只有人签，且设计师不能签自己的稿。"""
    order = await _get_order(db, order_id)
    actor = payload.actor or _actor(user)
    result = ledger.accept_order(order=order, actor=actor, designer=order.designer_name)
    if not result["ok"]:
        raise HTTPException(400, result["reason"])

    old = order.state
    order.acceptance = ledger.ACCEPTANCE_ACCEPTED
    order.accepted_by = actor
    order.accepted_at = utcnow()
    if old == "pending_review":
        order.state = "delivered"
    await _log(db, order, "acceptance", actor,
               payload.note or result["reason"],
               from_state=old, to_state=order.state)
    await db.commit()
    return await get_order(order_id, db, user)


# --------------------------------------------------------------------------- 门禁 / 返工 / 摘要
@router.get("/{order_id}/gate", response_model=OpcGateOut)
async def get_gate(order_id: str,
                   db: AsyncSession = Depends(get_db),
                   _: User = Depends(get_current_user)):
    """结算门禁判定。"""
    order = await _get_order(db, order_id)
    deliveries = await _deliveries(db, order_id)
    chain = ledger.chain_summary(deliveries)
    gate = ledger.evaluate_gate(
        state=order.state,
        evidence_complete=chain["evidence_complete"],
        acceptance=order.acceptance,
        designer=order.designer_name,
        reviewer=order.accepted_by,
        depends_on=await _depends(db, order),
    )
    return OpcGateOut(**gate)


@router.get("/{order_id}/repair-loop", response_model=OpcRepairLoopOut)
async def get_repair_loop(order_id: str,
                          db: AsyncSession = Depends(get_db),
                          _: User = Depends(get_current_user)):
    """返工回路投影（只读，不改任何状态）。"""
    order = await _get_order(db, order_id)
    events = await _events(db, order_id)
    return OpcRepairLoopOut(**ledger.repair_loop_projection(events))


@router.get("/{order_id}/summary")
async def get_summary(order_id: str,
                      db: AsyncSession = Depends(get_db),
                      _: User = Depends(get_current_user)):
    """交付四要素摘要 + 可直接贴进交接单的 Markdown。"""
    order = await _get_order(db, order_id)
    deliveries = await _deliveries(db, order_id)
    depends = await _depends(db, order)
    rules = await _split_rules(db)
    split = ledger.split_commission(order.order_commission, rules)
    summary = ledger.delivery_summary(
        code=order.order_sn,
        title=order.title,
        state=order.state,
        acceptance=order.acceptance,
        accepted_by=order.accepted_by,
        accepted_at=order.accepted_at,
        designer=order.designer_name,
        spec_snapshot=order.spec_snapshot,
        deliveries=deliveries,
        depends_on=depends,
        commission=order.order_commission,
        split=split,
    )
    return summary
