"""OPC 一人公司系统 · 撮合、结算与档案路由。

与 ``opc_orders`` 分开成两个文件：订单台账是主线、结算与撮合是辅线，
一个文件塞两件事以后没人敢动。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.timeutil import utcnow
from app.database import get_db
from app.models import (OpcDelivery, OpcDesigner, OpcEvent, OpcOrder,
                         OpcSettlement, OpcSplitRule, OpcStore, User)
from app.schemas_opc import (OpcDashboardOut, OpcDesignerIn, OpcDesignerOut,
                             OpcMatchOut, OpcMetaOut, OpcRecommendOut,
                             OpcSettlementGenerateIn, OpcSettlementOut,
                             OpcSettlementPayIn, OpcSplitPreviewIn,
                             OpcSplitRuleIn, OpcSplitRuleOut, OpcStoreIn,
                             OpcStoreOut)
from app.services import opc_ledger as ledger

router = APIRouter(prefix="/api/opc", tags=["opc-ops"])


def _actor(user: User) -> str:
    return user.display_name or user.username


def _designer_out(d: OpcDesigner, order_count: int = 0, active_count: int = 0) -> OpcDesignerOut:
    return OpcDesignerOut(
        id=d.id, name=d.name, phone=d.phone,
        alipay_account=d.alipay_account, alipay_name=d.alipay_name,
        production_level=d.production_level, design_tags=d.design_tags,
        war_zone=d.war_zone, hr_id=d.hr_id, quality_control_id=d.quality_control_id,
        commission_rate=str(d.commission_rate or 0), status=d.status, note=d.note,
        order_count=order_count, active_count=active_count,
    )


def _store_out(s: OpcStore, order_count: int = 0) -> OpcStoreOut:
    return OpcStoreOut(
        id=s.id, name=s.name, url=s.url, customer_name=s.customer_name,
        manager=s.manager, commission=str(s.commission or 0),
        settlement_days=s.settlement_days, remark=s.remark, order_count=order_count,
    )


def _order_out(order: OpcOrder):
    from app.schemas_opc import OpcOrderOut
    return OpcOrderOut(
        id=order.id, order_sn=order.order_sn, title=order.title,
        store_name=order.store_name, designer_name=order.designer_name,
        order_grade=order.order_grade, order_type=order.order_type,
        order_commission=str(order.order_commission or 0),
        request_delivery_time=order.request_delivery_time,
        state=order.state, state_label=ledger.state_label(order.state),
        acceptance=order.acceptance, spec_issues=list(order.spec_issues or []),
        created_at=order.created_at, updated_at=order.updated_at,
    )


def _settlement_out(s: OpcSettlement) -> OpcSettlementOut:
    return OpcSettlementOut(
        id=s.id, order_id=s.order_id, order_sn=s.order_sn,
        designer_name=s.designer_name, commission=str(s.commission or 0),
        settlement_type=s.settlement_type, settlement_days=s.settlement_days,
        status=s.status, alipay_account=s.alipay_account, alipay_name=s.alipay_name,
        upstream_settlement_time=s.upstream_settlement_time,
        paid_at=s.paid_at, paid_by=s.paid_by, remark=s.remark, created_at=s.created_at,
    )


# --------------------------------------------------------------------------- 元信息
@router.get("/meta", response_model=OpcMetaOut)
async def meta(_: User = Depends(get_current_user)):
    """前端启动要用的元信息。

    **状态机的可去状态也在这里下发** —— 前端不该自己抄一份流转表，
    抄了就会出现「前端能点到、后端拒绝」的不一致。
    """
    return OpcMetaOut(
        states=[{"value": s, "label": ledger.state_label(s)} for s in ledger.ORDER_STATES],
        mainline=list(ledger.ORDER_MAINLINE),
        transitions={s: list(ledger.next_states(s)) for s in ledger.ORDER_STATES},
        scope_labels=dict(ledger.SPLIT_SCOPE_LABELS),
        phase_labels=dict(ledger.PHASE_LABELS),
        spec_template=ledger.SPEC_TEMPLATE,
        spec_sections=list(ledger.SPEC_SECTIONS),
    )


# --------------------------------------------------------------------------- 设计师
@router.get("/designers", response_model=list[OpcDesignerOut])
async def list_designers(status: str = "",
                         db: AsyncSession = Depends(get_db),
                         _: User = Depends(get_current_user)):
    """设计师列表，附带接单统计。"""
    stmt = select(OpcDesigner)
    if status:
        stmt = stmt.where(OpcDesigner.status == status)
    rows = await db.execute(stmt.order_by(OpcDesigner.created_at.desc()))
    designers = list(rows.scalars())

    counts: dict[str, tuple[int, int]] = {}
    all_orders = await db.execute(select(OpcOrder))
    for o in all_orders.scalars():
        if not o.designer_name:
            continue
        total, active = counts.get(o.designer_name, (0, 0))
        counts[o.designer_name] = (total + 1, active + (1 if ledger.is_active(o.state) else 0))
    return [_designer_out(d, *counts.get(d.name, (0, 0))) for d in designers]


@router.post("/designers", response_model=OpcDesignerOut, status_code=201)
async def create_designer(payload: OpcDesignerIn,
                          db: AsyncSession = Depends(get_db),
                          _: User = Depends(get_current_user)):
    """新增设计师。"""
    exists = (await db.execute(
        select(OpcDesigner).where(OpcDesigner.name == payload.name)
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(400, f"设计师已存在：{payload.name}")
    d = OpcDesigner(
        name=payload.name, phone=payload.phone,
        alipay_account=payload.alipay_account, alipay_name=payload.alipay_name,
        production_level=payload.production_level, design_tags=payload.design_tags,
        war_zone=payload.war_zone, hr_id=payload.hr_id,
        quality_control_id=payload.quality_control_id,
        commission_rate=ledger.to_decimal(payload.commission_rate, ledger.Decimal("0")),
        status=payload.status, note=payload.note,
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return _designer_out(d)


@router.patch("/designers/{designer_id}", response_model=OpcDesignerOut)
async def edit_designer(designer_id: str, payload: OpcDesignerIn,
                        db: AsyncSession = Depends(get_db),
                        _: User = Depends(get_current_user)):
    """编辑设计师档案。"""
    d = (await db.execute(
        select(OpcDesigner).where(OpcDesigner.id == designer_id)
    )).scalar_one_or_none()
    if not d:
        raise HTTPException(404, "设计师不存在")
    for field in ("name", "phone", "alipay_account", "alipay_name",
                  "production_level", "design_tags", "war_zone", "hr_id",
                  "quality_control_id", "status", "note"):
        setattr(d, field, getattr(payload, field))
    d.commission_rate = ledger.to_decimal(payload.commission_rate, d.commission_rate)
    await db.commit()
    await db.refresh(d)
    return _designer_out(d)


@router.delete("/designers/{designer_id}")
async def delete_designer(designer_id: str,
                          db: AsyncSession = Depends(get_db),
                          _: User = Depends(get_current_user)):
    """删除设计师。有在制订单的不允许删 —— 否则订单上的归属就悬空了。"""
    d = (await db.execute(
        select(OpcDesigner).where(OpcDesigner.id == designer_id)
    )).scalar_one_or_none()
    if not d:
        raise HTTPException(404, "设计师不存在")
    active = (await db.execute(
        select(OpcOrder).where(
            OpcOrder.designer_id == designer_id,
            OpcOrder.state.in_(ledger.ACTIVE_STATES),
        )
    )).scalars().all()
    if active:
        raise HTTPException(
            400,
            f"设计师 {d.name} 还有 {len(active)} 个在制订单，不能删除；"
            f"可以先把状态改成「停用」。",
        )
    await db.delete(d)
    await db.commit()
    return {"ok": True, "message": f"设计师 {d.name} 已删除"}


# --------------------------------------------------------------------------- 店铺
@router.get("/stores", response_model=list[OpcStoreOut])
async def list_stores(db: AsyncSession = Depends(get_db),
                      _: User = Depends(get_current_user)):
    """店铺列表。"""
    rows = await db.execute(select(OpcStore).order_by(OpcStore.created_at.desc()))
    stores = list(rows.scalars())
    counts: dict[str, int] = {}
    all_orders = await db.execute(select(OpcOrder))
    for o in all_orders.scalars():
        if o.store_name:
            counts[o.store_name] = counts.get(o.store_name, 0) + 1
    return [_store_out(s, counts.get(s.name, 0)) for s in stores]


@router.post("/stores", response_model=OpcStoreOut, status_code=201)
async def create_store(payload: OpcStoreIn,
                       db: AsyncSession = Depends(get_db),
                       _: User = Depends(get_current_user)):
    """新增店铺。"""
    s = OpcStore(
        name=payload.name, url=payload.url, customer_name=payload.customer_name,
        manager=payload.manager,
        commission=ledger.to_decimal(payload.commission, ledger.Decimal("0")),
        settlement_days=payload.settlement_days, remark=payload.remark,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return _store_out(s)


@router.patch("/stores/{store_id}", response_model=OpcStoreOut)
async def edit_store(store_id: str, payload: OpcStoreIn,
                     db: AsyncSession = Depends(get_db),
                     _: User = Depends(get_current_user)):
    """编辑店铺。"""
    s = (await db.execute(
        select(OpcStore).where(OpcStore.id == store_id)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "店铺不存在")
    for field in ("name", "url", "customer_name", "manager", "settlement_days", "remark"):
        setattr(s, field, getattr(payload, field))
    s.commission = ledger.to_decimal(payload.commission, s.commission)
    await db.commit()
    await db.refresh(s)
    return _store_out(s)


@router.delete("/stores/{store_id}")
async def delete_store(store_id: str,
                       db: AsyncSession = Depends(get_db),
                       _: User = Depends(get_current_user)):
    """删除店铺。有订单的不允许删。"""
    s = (await db.execute(
        select(OpcStore).where(OpcStore.id == store_id)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "店铺不存在")
    used = (await db.execute(
        select(OpcOrder).where(OpcOrder.store_id == store_id)
    )).scalars().all()
    if used:
        raise HTTPException(400, f"店铺 {s.name} 还有 {len(used)} 个订单，不能删除")
    await db.delete(s)
    await db.commit()
    return {"ok": True, "message": f"店铺 {s.name} 已删除"}


# --------------------------------------------------------------------------- 撮合
@router.get("/match/board", response_model=OpcMatchOut)
async def match_board(db: AsyncSession = Depends(get_db),
                      _: User = Depends(get_current_user)):
    """撮合看板：待派单 / 在制 / 待验收 / 待结算 四块 + 候选人。"""
    orders = list((await db.execute(select(OpcOrder))).scalars())
    designers = list((await db.execute(
        select(OpcDesigner).where(OpcDesigner.status == "active")
    )).scalars())

    pending = [o for o in orders if o.state == "pending_assign"]
    active = [o for o in orders if ledger.is_active(o.state) and o.state != "pending_review"]
    review = [o for o in orders if o.state == "pending_review"]
    settle = [o for o in orders if o.state in ("delivered", "pending_settle")]

    # 推荐：拿待派单订单的需求单文本算相关度
    reason = ""
    if pending:
        top = pending[0]
        requirement = ledger.parse_spec(top.spec_snapshot).get("目标", "") or top.title
        reason = ledger.fallback_recommendation(requirement, designers)

    return OpcMatchOut(
        pending=[_order_out(o) for o in pending],
        active=[_order_out(o) for o in active],
        pending_review=[_order_out(o) for o in review],
        pending_settle=[_order_out(o) for o in settle],
        designers=[_designer_out(d) for d in designers],
        recommendation=reason,
    )


@router.get("/match/recommend", response_model=OpcRecommendOut)
async def recommend(order_id: str,
                    db: AsyncSession = Depends(get_db),
                    _: User = Depends(get_current_user)):
    """给指定订单推荐设计师。

    走大模型时用 LLM 给出理由；**没配 key 时自动降级为本地关键词相关度**，
    候选池绝不返回空数组（空数组对界面毫无意义）。
    """
    order = (await db.execute(
        select(OpcOrder).where(OpcOrder.id == order_id)
    )).scalar_one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")

    designers = list((await db.execute(
        select(OpcDesigner).where(OpcDesigner.status == "active")
    )).scalars())

    parsed = ledger.parse_spec(order.spec_snapshot)
    requirement = " ".join(filter(None, [
        parsed.get("目标", ""), parsed.get("范围", ""), order.title,
    ]))

    source = "rule"
    reason = ledger.fallback_recommendation(requirement, designers)
    candidates: list[dict] = []

    # 尝试走 LLM（失败不报错，静默降级）
    try:
        from app.services.llm_client import llm_client
        result = await llm_client.recommend_designers(requirement, designers)
        if result:
            source = "llm"
            reason = result.get("reason") or reason
            candidates = result.get("candidates") or []
    except Exception:
        # 没配 key、超时、返回格式不对 —— 一律降级，不让功能挂掉
        source = "rule"

    if not candidates:
        ranked = ledger.rank_candidates(requirement, designers, limit=10)
        candidates = [
            {
                "designer_id": getattr(item["designer"], "id", ""),
                "name": item["name"],
                "score": item["score"],
                "design_tags": getattr(item["designer"], "design_tags", ""),
                "production_level": getattr(item["designer"], "production_level", ""),
                "reason": "",
            }
            for item in ranked
        ]

    return OpcRecommendOut(
        order_id=order.id,
        requirement=requirement,
        candidates=candidates,
        reason=reason,
        source=source,
    )


# --------------------------------------------------------------------------- 结算
@router.get("/settlements", response_model=list[OpcSettlementOut])
async def list_settlements(status: str = "",
                           db: AsyncSession = Depends(get_db),
                           _: User = Depends(get_current_user)):
    """结算单列表。"""
    stmt = select(OpcSettlement)
    if status:
        stmt = stmt.where(OpcSettlement.status == status)
    rows = await db.execute(stmt.order_by(OpcSettlement.created_at.desc()))
    return [_settlement_out(s) for s in rows.scalars()]


@router.post("/settlements/generate")
async def generate_settlements(payload: OpcSettlementGenerateIn,
                               db: AsyncSession = Depends(get_db),
                               user: User = Depends(get_current_user)):
    """一键生成结算单。

    只给**已具名验收且通过结算门禁**的订单生成。门禁不过的订单会被跳过并在
    返回结果里说明原因 —— 不能为了「一键」就把不该结的钱结出去。

    返回 ``{"created": [...], "skipped": [...]}`` —— 两段分开返回，
    不把「跳过说明」硬塞进结算单列表里（那会让响应类型变得没法声明）。
    """
    if payload.order_ids:
        orders = list((await db.execute(
            select(OpcOrder).where(OpcOrder.id.in_(payload.order_ids))
        )).scalars())
    else:
        orders = list((await db.execute(
            select(OpcOrder).where(OpcOrder.state.in_(("delivered", "pending_settle")))
        )).scalars())

    rules = list((await db.execute(select(OpcSplitRule))).scalars())
    created: list[OpcSettlement] = []
    skipped: list[dict] = []

    for order in orders:
        exists = (await db.execute(
            select(OpcSettlement).where(OpcSettlement.order_id == order.id)
        )).scalar_one_or_none()
        if exists:
            skipped.append({"order_sn": order.order_sn, "reason": "已生成过结算单"})
            continue

        deliveries = list((await db.execute(
            select(OpcDelivery).where(OpcDelivery.order_id == order.id)
        )).scalars())
        chain = ledger.chain_summary(deliveries)
        gate = ledger.evaluate_gate(
            state=order.state,
            evidence_complete=chain["evidence_complete"],
            acceptance=order.acceptance,
            designer=order.designer_name,
            reviewer=order.accepted_by,
        )
        if not gate["allowed"]:
            skipped.append({"order_sn": order.order_sn, "reason": gate["reason"]})
            continue

        split = ledger.split_commission(order.order_commission, rules)
        designer_share = split["shares"].get("designer")
        amount = designer_share if designer_share is not None else ledger.to_decimal(
            order.order_commission, ledger.Decimal("0"))

        designer = None
        if order.designer_id:
            designer = (await db.execute(
                select(OpcDesigner).where(OpcDesigner.id == order.designer_id)
            )).scalar_one_or_none()

        store = None
        if order.store_id:
            store = (await db.execute(
                select(OpcStore).where(OpcStore.id == order.store_id)
            )).scalar_one_or_none()

        st = OpcSettlement(
            order_id=order.id,
            order_sn=order.order_sn,
            designer_name=order.designer_name,
            commission=ledger.quantize_money(amount or ledger.Decimal("0")),
            settlement_type=payload.settlement_type,
            settlement_days=store.settlement_days if store else 0,
            status="pending",
            alipay_account=designer.alipay_account if designer else "",
            alipay_name=designer.alipay_name if designer else "",
        )
        db.add(st)
        created.append(st)

        order.state = "pending_settle"
        ev = OpcEvent(
            order_id=order.id, kind="transition",
            from_state="delivered", to_state="pending_settle",
            actor=_actor(user), detail="生成结算单，进入待结算",
        )
        db.add(ev)

    await db.commit()
    for s in created:
        await db.refresh(s)

    return {
        "created": [_settlement_out(s) for s in created],
        "skipped": skipped,
    }


@router.post("/settlements/{settlement_id}/pay", response_model=OpcSettlementOut)
async def pay_settlement(settlement_id: str, payload: OpcSettlementPayIn,
                         db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """标记已打款。系统只做记录，实际转账走支付宝手工操作。"""
    st = (await db.execute(
        select(OpcSettlement).where(OpcSettlement.id == settlement_id)
    )).scalar_one_or_none()
    if not st:
        raise HTTPException(404, "结算单不存在")
    if st.status == "paid":
        raise HTTPException(400, "该结算单已标记为已打款")

    st.status = "paid"
    st.paid_at = utcnow()
    st.paid_by = payload.actor or _actor(user)
    st.upstream_settlement_time = payload.upstream_settlement_time
    if payload.remark:
        st.remark = payload.remark

    order = (await db.execute(
        select(OpcOrder).where(OpcOrder.id == st.order_id)
    )).scalar_one_or_none()
    if order:
        order.state = "settled"
        db.add(OpcEvent(
            order_id=order.id, kind="transition",
            from_state="pending_settle", to_state="settled",
            actor=st.paid_by, detail="结算完成",
        ))

    await db.commit()
    await db.refresh(st)
    return _settlement_out(st)


@router.get("/settlements/summary")
async def settlement_summary(db: AsyncSession = Depends(get_db),
                              _: User = Depends(get_current_user)):
    """结算汇总：待结算笔数与金额、已打款金额。"""
    rows = list((await db.execute(select(OpcSettlement))).scalars())
    pending = [s for s in rows if s.status != "paid"]
    paid = [s for s in rows if s.status == "paid"]
    return {
        "pending_count": len(pending),
        "pending_amount": str(sum((s.commission or 0) for s in pending)),
        "paid_count": len(paid),
        "paid_amount": str(sum((s.commission or 0) for s in paid)),
        "by_designer": [
            {
                "designer_name": name,
                "count": len(items),
                "amount": str(sum((s.commission or 0) for s in items)),
            }
            for name, items in _group(pending).items()
        ],
    }


def _group(items: list[OpcSettlement]) -> dict[str, list[OpcSettlement]]:
    out: dict[str, list[OpcSettlement]] = {}
    for s in items:
        out.setdefault(s.designer_name or "未指定", []).append(s)
    return out


# --------------------------------------------------------------------------- 分账规则
@router.get("/rules", response_model=list[OpcSplitRuleOut])
async def list_rules(db: AsyncSession = Depends(get_db),
                     _: User = Depends(get_current_user)):
    """分账规则列表。"""
    rows = await db.execute(select(OpcSplitRule).order_by(OpcSplitRule.scope))
    return [
        OpcSplitRuleOut(
            id=r.id, scope=r.scope,
            scope_label=ledger.SPLIT_SCOPE_LABELS.get(r.scope, r.scope),
            rate=str(r.rate or 0), basis=r.basis, enabled=r.enabled, remark=r.remark,
        )
        for r in rows.scalars()
    ]


@router.post("/rules", response_model=OpcSplitRuleOut, status_code=201)
async def save_rule(payload: OpcSplitRuleIn,
                     db: AsyncSession = Depends(get_db),
                     _: User = Depends(get_current_user)):
    """新增或更新一条分账规则（按 scope 唯一）。"""
    if payload.scope not in ledger.SPLIT_SCOPES:
        raise HTTPException(400, f"未知的分账口径：{payload.scope}")
    existing = (await db.execute(
        select(OpcSplitRule).where(OpcSplitRule.scope == payload.scope)
    )).scalar_one_or_none()
    rate = ledger.to_decimal(payload.rate, ledger.Decimal("0"))
    if rate is not None and rate < 0:
        raise HTTPException(400, "比例不能为负数")
    if rate is not None and rate > 1:
        raise HTTPException(400, "比例必须在 0 到 1 之间（0.6 表示 60%）")

    if existing:
        existing.rate = rate
        existing.basis = payload.basis
        existing.enabled = payload.enabled
        existing.remark = payload.remark
        rule = existing
    else:
        rule = OpcSplitRule(
            scope=payload.scope, rate=rate, basis=payload.basis,
            enabled=payload.enabled, remark=payload.remark,
        )
        db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return OpcSplitRuleOut(
        id=rule.id, scope=rule.scope,
        scope_label=ledger.SPLIT_SCOPE_LABELS.get(rule.scope, rule.scope),
        rate=str(rule.rate or 0), basis=rule.basis,
        enabled=rule.enabled, remark=rule.remark,
    )


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str,
                      db: AsyncSession = Depends(get_db),
                      _: User = Depends(get_current_user)):
    """删除一条分账规则。"""
    rule = (await db.execute(
        select(OpcSplitRule).where(OpcSplitRule.id == rule_id)
    )).scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "规则不存在")
    await db.delete(rule)
    await db.commit()
    return {"ok": True, "message": "规则已删除"}


@router.post("/rules/preview")
async def preview_split(payload: OpcSplitPreviewIn,
                        db: AsyncSession = Depends(get_db),
                        _: User = Depends(get_current_user)):
    """分账试算：按当前规则算一笔，看各角色分到多少。"""
    rules = list((await db.execute(select(OpcSplitRule))).scalars())
    result = ledger.split_commission(payload.total, rules, basis=payload.basis)
    return {
        "total": str(result["total"]),
        "basis": str(result["basis"]),
        "rows": ledger.split_summary(result),
        "issues": result["issues"],
    }


# --------------------------------------------------------------------------- 看板
@router.get("/dashboard", response_model=OpcDashboardOut)
async def dashboard(db: AsyncSession = Depends(get_db),
                    _: User = Depends(get_current_user)):
    """撮合看板总览：漏斗、金额、排名。"""
    orders = list((await db.execute(select(OpcOrder))).scalars())
    designers = list((await db.execute(select(OpcDesigner))).scalars())
    stores = list((await db.execute(select(OpcStore))).scalars())
    settlements = list((await db.execute(select(OpcSettlement))).scalars())

    total_amount = sum((o.order_commission or 0) for o in orders)
    active_amount = sum(
        (o.order_commission or 0) for o in orders if ledger.is_active(o.state)
    )
    pending_settle = [
        o for o in orders if o.state in ("delivered", "pending_settle")
    ]

    # 设计师排名（按在制订单金额）
    by_designer: dict[str, Decimal] = {}
    for o in orders:
        if not o.designer_name:
            continue
        by_designer[o.designer_name] = (
            by_designer.get(o.designer_name, ledger.Decimal("0")) + (o.order_commission or 0)
        )
    designer_ranking = [
        {"name": name, "amount": str(amount),
         "count": len([o for o in orders if o.designer_name == name])}
        for name, amount in sorted(by_designer.items(), key=lambda x: -x[1])[:10]
    ]

    by_store: dict[str, Decimal] = {}
    for o in orders:
        if not o.store_name:
            continue
        by_store[o.store_name] = (
            by_store.get(o.store_name, ledger.Decimal("0")) + (o.order_commission or 0)
        )
    store_ranking = [
        {"name": name, "amount": str(amount),
         "count": len([o for o in orders if o.store_name == name])}
        for name, amount in sorted(by_store.items(), key=lambda x: -x[1])[:10]
    ]

    paid = [s for s in settlements if s.status == "paid"]

    return OpcDashboardOut(
        funnel=ledger.order_funnel(orders),
        total_orders=len(orders),
        total_amount=str(total_amount),
        active_amount=str(active_amount),
        pending_settle_amount=str(sum((o.order_commission or 0) for o in pending_settle)),
        designer_count=len(designers),
        store_count=len(stores),
        settlement_pending_count=len([s for s in settlements if s.status != "paid"]),
        settlement_paid_amount=str(sum((s.commission or 0) for s in paid)),
        designer_ranking=designer_ranking,
        store_ranking=store_ranking,
    )
