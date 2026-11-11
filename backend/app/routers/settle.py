"""设计师结算系统 · 双角色路由。

两套角色共用一套库，**靠接口区分**，不靠前端隐藏按钮：

- **派单员端** ``/api/settle/admin/*``
  录设计师、登订单、管流程、审验收、结算管理、异常诊断、数据看板
- **设计师端** ``/api/settle/me/*``
  我的订单、一键结算、收益明细、改密码

为什么不让设计师用系统原有的 ``users`` 表登录？
因为课件里的设计师是**用手机号+派单员设的临时密码**登录结算端的，
跟平台的账号体系是两回事。所以这里给设计师单独一套
「手机号 + 密码」登录（``/api/settle/auth/login``），
派单员仍走平台原有的登录。

结算发起权**只在设计师端**：课件明确「必须主动点击『一键结算』按钮，
系统才会自动完成结算操作」，所以派单员端**没有**发起结算的接口，
只有「标记已打款」。
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.designer_auth import get_current_designer
from app.core.security import create_designer_token, hash_password, verify_password
from app.core import timeutil
from app.core.timeutil import utcnow
from app.database import get_db
from app.models import (SlDesigner, SlLog, SlOrder, SlSettlement, User)
from app.services import settle_ledger as ledger
from app.services import settle_bridge as bridge
from app.services.trcipg_client import (
    TrcipgClient,
    UpstreamBlockedError,
    UpstreamError,
)

router = APIRouter(prefix="/api/settle", tags=["settle"])


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _actor(user: User) -> str:
    return user.display_name or user.username


def _dec(value: Any) -> Decimal:
    result = ledger.to_decimal(value, Decimal("0"))
    return result if result is not None else Decimal("0")


async def _log(db: AsyncSession, *, kind: str, actor: str, detail: str,
               order_id: str | None = None, designer_id: str | None = None,
               from_state: str | None = None, to_state: str | None = None) -> None:
    """写一条操作留痕。"""
    db.add(SlLog(kind=kind, actor=actor, detail=detail, order_id=order_id,
                 designer_id=designer_id, from_state=from_state, to_state=to_state))


def _designer_out(d: SlDesigner) -> dict[str, Any]:
    return {
        "id": d.id, "name": d.name, "nickname": d.nickname, "phone": d.phone,
        # 有值 = 从总系统导入的；空 = 本地手工录入的
        "upstream_id": d.upstream_id,
        "alipay_account": d.alipay_account, "alipay_name": d.alipay_name,
        "gender": d.gender, "gender_label": ledger.GENDERS.get(d.gender, "未知"),
        "recruitment_source": d.recruitment_source,
        "production_level": d.production_level,
        "war_zone": d.war_zone, "hr_id": d.hr_id,
        "must_change_password": d.must_change_password,
        "status": d.status, "note": d.note,
        "created_at": d.created_at.isoformat() if d.created_at else "",
    }


def _order_out(o: SlOrder) -> dict[str, Any]:
    return {
        "id": o.id, "order_no": o.order_no, "customer_id": o.customer_id,
        # 有值 = 从总系统导入的；空 = 本地手工登记的
        "upstream_id": o.upstream_id,
        "war_zone": o.war_zone, "customer_service": o.customer_service,
        "designer_id": o.designer_id, "designer_name": o.designer_name,
        "order_type": o.order_type, "order_type_label": ledger.order_type_label(o.order_type),
        "service_type": o.service_type,
        "order_amount": str(o.order_amount or 0),
        "commission_rate": str(o.commission_rate or 0),
        "designer_commission": str(o.designer_commission or 0),
        "requirement": o.requirement, "note": o.note,
        "deliver_date": o.deliver_date, "order_date": o.order_date,
        "state": o.state, "state_label": ledger.state_label(o.state),
        "chat_screenshot": o.chat_screenshot, "file_screenshot": o.file_screenshot,
        "audit_status": o.audit_status, "audit_remark": o.audit_remark,
        "created_at": o.created_at.isoformat() if o.created_at else "",
        "updated_at": o.updated_at.isoformat() if o.updated_at else "",
    }


def _settlement_out(s: SlSettlement) -> dict[str, Any]:
    return {
        "id": s.id, "order_id": s.order_id, "designer_id": s.designer_id,
        "designer_name": s.designer_name, "commission": str(s.commission or 0),
        "period": s.period, "status": s.status, "invalid_reason": s.invalid_reason,
        "alipay_account": s.alipay_account, "alipay_name": s.alipay_name,
        "pay_date": s.pay_date, "flow_no": s.flow_no,
        "paid_at": s.paid_at.isoformat() if s.paid_at else "",
        "created_at": s.created_at.isoformat() if s.created_at else "",
    }


# ===========================================================================
# 字典与窗口
# ===========================================================================


@router.get("/meta")
async def settle_meta(_: User = Depends(get_current_user)) -> dict[str, Any]:
    """全部字典 + 当前结算窗口。前端启动时拉一次。"""
    data = ledger.dictionaries()
    data["window"] = ledger.settle_window().as_dict()
    return data


@router.get("/window")
async def settle_window(_: User = Depends(get_current_user)) -> dict[str, Any]:
    """当前结算窗口（每月 8-9 号开放）。"""
    return ledger.settle_window().as_dict()


# ===========================================================================
# 派单员端
# ===========================================================================


@router.get("/admin/dashboard")
async def admin_dashboard(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """派单员业务看板。

    课件业务看板的三件事：**实时追踪每一笔业绩**、**实时对账**、
    **高效结算**。所以这里给：漏斗、本月业绩、待提醒清单、结算窗口倒计时。
    """
    orders = (await db.execute(select(SlOrder))).scalars().all()
    designers = (await db.execute(select(SlDesigner))).scalars().all()
    settlements = (await db.execute(select(SlSettlement))).scalars().all()

    today = timeutil.today()
    period = today.strftime("%Y-%m")

    order_dicts = [_order_out(o) for o in orders]
    month_orders = [o for o in order_dicts if o["order_date"].startswith(period)]

    month_amount = sum((_dec(o["order_amount"]) for o in month_orders), Decimal("0"))
    month_commission = sum((_dec(o["designer_commission"]) for o in month_orders), Decimal("0"))

    pending_audit = [o for o in order_dicts if o["state"] == "pending_audit"]
    settleable = [o for o in order_dicts if o["state"] == "settleable"]
    draft_missing = [o for o in order_dicts
                     if not o["order_no"] and o["state"] != "pending_design"]

    summary = ledger.settlement_summary([_settlement_out(s) for s in settlements])
    reminds = ledger.remind_designers(order_dicts, [_designer_out(d) for d in designers], today)

    return {
        "funnel": ledger.order_funnel(order_dicts),
        "period": period,
        "month_order_count": len(month_orders),
        "month_amount": str(ledger.quantize_money(month_amount)),
        "month_commission": str(ledger.quantize_money(month_commission)),
        "designer_count": len(designers),
        "active_designer_count": sum(1 for d in designers if d.status == "active"),
        "pending_audit_count": len(pending_audit),
        "settleable_count": len(settleable),
        "settleable_amount": str(ledger.quantize_money(
            sum((_dec(o["designer_commission"]) for o in settleable), Decimal("0")))),
        "draft_missing_count": len(draft_missing),
        "remind_designers": reminds,
        "window": ledger.settle_window(today).as_dict(),
        "settlement_summary": summary,
    }


# ---------- 设计师档案 ----------


@router.get("/admin/designers")
async def admin_list_designers(
    keyword: str = "",
    status: str = "",
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """设计师列表。"""
    stmt = select(SlDesigner)
    if status:
        stmt = stmt.where(SlDesigner.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    out = [_designer_out(d) for d in rows]
    if keyword:
        key = keyword.strip().lower()
        out = [d for d in out
               if key in d["name"].lower() or key in d["nickname"].lower()
               or key in d["phone"]]
    # 顺带挂上订单数，前端不用再查一次
    #
    # 【坑】``for o in await db.execute(...)`` 迭代出来的是 **Row 元组**，
    # 不是 ORM 对象 —— 访问 o.designer_id 会抛 AttributeError → 500。
    # 必须先 ``.scalars()`` 拿到真正的 SlOrder 实例。
    counts: dict[str, int] = {}
    order_rows = (await db.execute(select(SlOrder))).scalars().all()
    for o in order_rows:
        if o.designer_id:
            counts[o.designer_id] = counts.get(o.designer_id, 0) + 1
    for item in out:
        item["order_count"] = counts.get(item["id"], 0)
    return out


@router.post("/admin/designers")
async def admin_create_designer(
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """录入设计师（模块二）。

    校验全部交给规则层，**这里不重复实现任何校验逻辑**。
    """
    issues = ledger.validate_designer(payload)
    if issues:
        raise HTTPException(status_code=422, detail={
            "message": "设计师信息填写有误，请按提示逐项修正",
            "issues": [i.as_dict() for i in issues],
        })

    phone = str(payload["phone"]).strip()
    exists = (await db.execute(
        select(SlDesigner).where(SlDesigner.phone == phone)
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(
            status_code=409,
            detail=f"手机号 {phone} 已存在（{exists.name}），请勿重复录入")

    designer = SlDesigner(
        name=str(payload["name"]).strip(),
        nickname=str(payload["nickname"]).strip(),
        phone=phone,
        alipay_account=str(payload["alipay_account"]).strip(),
        alipay_name=str(payload.get("alipay_name") or payload["name"]).strip(),
        gender=int(payload.get("gender") or 0),
        recruitment_source=str(payload["recruitment_source"]).strip(),
        production_level=str(payload["production_level"]).strip(),
        password_hash=hash_password(str(payload["password"])),
        # 课件：「密码建议设置为临时密码，通知设计师后要求其首次登录时修改」
        must_change_password=bool(payload.get("must_change_password", True)),
        war_zone="",
        hr_id="",
        status="active",
        note=str(payload.get("note") or ""),
    )
    db.add(designer)
    await db.flush()
    await _log(db, kind="designer", actor=_actor(user),
               detail=f"录入设计师 {designer.name}（{designer.nickname}）"
                      f"，手机号 {designer.phone}，收款账号 {designer.alipay_account}",
               designer_id=designer.id)
    await db.commit()
    await db.refresh(designer)
    return _designer_out(designer)


@router.patch("/admin/designers/{designer_id}")
async def admin_update_designer(
    designer_id: str,
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """改设计师信息（可改收款账号、状态、改密）。"""
    designer = await db.get(SlDesigner, designer_id)
    if designer is None:
        raise HTTPException(status_code=404, detail="设计师不存在")

    # 战区 / HR 一旦录入就不允许再写（课件要求留空）
    for guarded in ("war_zone", "hr_id"):
        if str(payload.get(guarded) or "").strip():
            raise HTTPException(
                status_code=422,
                detail=f"「{guarded}」必须保持为空，课件明确要求切勿填写任何内容")

    for key in ("name", "nickname", "alipay_account", "alipay_name",
                "recruitment_source", "production_level", "note"):
        if key in payload:
            setattr(designer, key, str(payload[key] or "").strip())
    if "gender" in payload:
        designer.gender = int(payload["gender"] or 0)
    if "status" in payload:
        designer.status = str(payload["status"])
    if payload.get("password"):
        designer.password_hash = hash_password(str(payload["password"]))
        designer.must_change_password = True

    await _log(db, kind="designer", actor=_actor(user),
               detail=f"修改设计师 {designer.name} 的信息", designer_id=designer.id)
    await db.commit()
    await db.refresh(designer)
    return _designer_out(designer)


@router.delete("/admin/designers/{designer_id}")
async def admin_delete_designer(
    designer_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """删除设计师。有在制订单或未结算单的一律不许删。"""
    designer = await db.get(SlDesigner, designer_id)
    if designer is None:
        raise HTTPException(status_code=404, detail="设计师不存在")

    orders = (await db.execute(
        select(SlOrder).where(SlOrder.designer_id == designer_id)
    )).scalars().all()
    active = [o for o in orders if o.state not in ("settled", "canceled")]
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"该设计师名下还有 {len(active)} 笔未完结订单，无法删除。"
                   "请先处理完订单或改为「停用」")
    settlements = (await db.execute(
        select(SlSettlement).where(SlSettlement.designer_id == designer_id)
    )).scalars().all()
    if settlements:
        raise HTTPException(
            status_code=409,
            detail=f"该设计师有 {len(settlements)} 条结算记录，无法删除。"
                   "请改为「停用」保留历史")

    await _log(db, kind="designer", actor=_actor(user),
               detail=f"删除设计师 {designer.name}", designer_id=designer_id)
    await db.delete(designer)
    await db.commit()
    return {"ok": True}


# ---------- 订单 ----------


@router.get("/admin/orders")
async def admin_list_orders(
    state: str = "",
    designer_id: str = "",
    keyword: str = "",
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """订单列表。"""
    stmt = select(SlOrder)
    if state:
        stmt = stmt.where(SlOrder.state == state)
    if designer_id:
        stmt = stmt.where(SlOrder.designer_id == designer_id)
    rows = (await db.execute(stmt.order_by(SlOrder.created_at.desc()))).scalars().all()
    out = [_order_out(o) for o in rows]
    if keyword:
        key = keyword.strip().lower()
        out = [o for o in out
               if key in o["order_no"].lower() or key in o["customer_id"].lower()
               or key in o["designer_name"].lower() or key in o["customer_service"].lower()]
    return out


@router.get("/admin/orders/{order_id}")
async def admin_order_detail(
    order_id: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """订单详情 + 留痕 + 异常诊断。"""
    order = await db.get(SlOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    logs = (await db.execute(
        select(SlLog).where(SlLog.order_id == order_id)
        .order_by(SlLog.created_at.desc())
    )).scalars().all()
    settlements = (await db.execute(
        select(SlSettlement).where(SlSettlement.order_id == order_id)
    )).scalars().all()
    deletable, delete_reason = ledger.check_deletable(_order_out(order))
    return {
        "order": _order_out(order),
        "logs": [{
            "id": lg.id, "kind": lg.kind, "actor": lg.actor, "detail": lg.detail,
            "from_state": lg.from_state, "to_state": lg.to_state,
            "created_at": lg.created_at.isoformat() if lg.created_at else "",
        } for lg in logs],
        "settlements": [_settlement_out(s) for s in settlements],
        "exceptions": ledger.diagnose_order(_order_out(order)),
        "deletable": deletable,
        "delete_reason": delete_reason,
        "next_states": list(ledger.next_states(order.state)),
    }


@router.post("/admin/orders")
async def admin_create_order(
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """登记新订单（模块三）。"""
    issues = ledger.validate_order(payload)
    if issues:
        raise HTTPException(status_code=422, detail={
            "message": "订单信息填写有误，请按提示逐项修正",
            "issues": [i.as_dict() for i in issues],
        })

    calc = ledger.calc_commission(payload.get("order_amount"), payload.get("commission_rate"))
    if not calc.ok:
        raise HTTPException(status_code=422, detail={
            "message": "佣金核算不通过", "issues": calc.issues,
        })

    designer_id = str(payload.get("designer_id") or "").strip() or None
    designer_name = ""
    if designer_id:
        designer = await db.get(SlDesigner, designer_id)
        if designer is None:
            raise HTTPException(status_code=422, detail="指定的设计师不存在")
        designer_name = designer.name

    order_date = str(payload.get("order_date") or "").strip() or timeutil.today().isoformat()
    order = SlOrder(
        order_no=str(payload.get("order_no") or "").strip(),
        customer_id=str(payload["customer_id"]).strip(),
        war_zone=str(payload["war_zone"]).strip(),
        customer_service=str(payload["customer_service"]).strip(),
        designer_id=designer_id,
        designer_name=designer_name,
        order_type=str(payload["order_type"]).strip(),
        service_type=str(payload.get("service_type") or "").strip(),
        order_amount=calc.amount,
        commission_rate=calc.rate,
        designer_commission=calc.commission,
        requirement=str(payload.get("requirement") or ""),
        note=str(payload.get("note") or ""),
        deliver_date=str(payload["deliver_date"]).strip(),
        order_date=order_date,
        # 登记完只是「设计待定」，派单是**下一个独立动作**。
        # 早期版本直接落 drafting，把派单这一步吞掉了 ——
        # 结果是订单跳过了「谁来做」这一环，也绕过了派单时的门禁。
        state="pending_design",
        audit_status="pending",
        created_by=user.id,
    )
    db.add(order)
    await db.flush()
    await _log(db, kind="order", actor=_actor(user),
               detail=f"登记订单 客户={order.customer_id} 金额={order.order_amount} "
                      f"佣金比例={order.commission_rate} 设计师={order.designer_name or '待定'}",
               order_id=order.id, designer_id=designer_id)
    await db.commit()
    await db.refresh(order)
    return _order_out(order)


@router.patch("/admin/orders/{order_id}")
async def admin_update_order(
    order_id: str,
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """改订单信息（含补录订单编号、上传两类截图）。"""
    order = await db.get(SlOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")

    # 金额或比例改了要重算佣金
    new_amount = _dec(payload.get("order_amount", order.order_amount))
    new_rate = _dec(payload.get("commission_rate", order.commission_rate))
    if "order_amount" in payload or "commission_rate" in payload:
        calc = ledger.calc_commission(new_amount, new_rate)
        if not calc.ok:
            raise HTTPException(status_code=422, detail={
                "message": "佣金核算不通过", "issues": calc.issues,
            })
        order.order_amount = calc.amount
        order.commission_rate = calc.rate
        order.designer_commission = calc.commission

    for key in ("order_no", "customer_id", "war_zone", "customer_service",
                "service_type", "requirement", "note", "deliver_date",
                "order_date", "chat_screenshot", "file_screenshot"):
        if key in payload:
            setattr(order, key, str(payload[key] or "").strip())

    if "designer_id" in payload:
        did = str(payload["designer_id"] or "").strip() or None
        if did:
            designer = await db.get(SlDesigner, did)
            if designer is None:
                raise HTTPException(status_code=422, detail="指定的设计师不存在")
            order.designer_id = did
            order.designer_name = designer.name
        else:
            order.designer_id = None
            order.designer_name = ""

    if "order_type" in payload:
        order.order_type = str(payload["order_type"]).strip()

    await _log(db, kind="order", actor=_actor(user),
               detail="更新订单信息", order_id=order.id)
    await db.commit()
    await db.refresh(order)
    return _order_out(order)


@router.post("/admin/orders/{order_id}/transition")
async def admin_transition(
    order_id: str,
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """状态流转（模块四的两个节点都在这里）。

    门禁全部交给规则层：初稿要编号、终稿要两类截图、可结算要过有效期。

    派单（``pending_design → drafting``）要带 ``designer_id`` ——
    「设计待定」这一态的整个意义就是「还没定人」，直接开工等于跳过了派单。
    """
    order = await db.get(SlOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")

    to_state = str(payload.get("to_state") or "").strip()
    detail = str(payload.get("detail") or "").strip()

    # 派单：订单必须落到某个设计师头上才能开工。
    # 派单时没指定就用订单上已有的 —— 登记订单时就选好设计师是常见做法，
    # 不该被拦住。
    if to_state == "drafting" and order.state == "pending_design":
        designer_id = str(payload.get("designer_id") or order.designer_id or "").strip()
        if not designer_id:
            raise HTTPException(
                status_code=422,
                detail="派单前必须指定承接的设计师，请先在订单详情里选择设计师"
            )
        designer = await db.get(SlDesigner, designer_id)
        if designer is None:
            raise HTTPException(status_code=422, detail="指定的设计师不存在")
        if designer.status != "active":
            raise HTTPException(
                status_code=422,
                detail=f"设计师「{designer.name}」已停用，无法派单，请换人"
            )
        order.designer_id = designer.id
        order.designer_name = designer.name

    # 允许在流转时顺手补材料（节点一填编号、节点二传截图）
    for key in ("order_no", "chat_screenshot", "file_screenshot"):
        if payload.get(key):
            setattr(order, key, str(payload[key]).strip())

    issues = ledger.check_transition(_order_out(order), to_state)
    if issues:
        raise HTTPException(status_code=422, detail={
            "message": "无法完成该操作，请按提示补齐材料",
            "issues": issues,
        })

    old_state = order.state
    order.state = to_state
    if to_state == "pending_audit":
        order.audit_status = "pending"
    elif to_state == "settleable":
        order.audit_status = "approved"
    elif to_state == "rejected":
        order.audit_status = "rejected"
        order.audit_remark = detail

    await _log(db, kind="transition", actor=_actor(user),
               detail=detail or f"状态流转：{ledger.state_label(old_state)} → "
                                f"{ledger.state_label(to_state)}",
               order_id=order.id, designer_id=order.designer_id,
               from_state=old_state, to_state=to_state)
    await db.commit()
    await db.refresh(order)
    return _order_out(order)


@router.post("/admin/orders/{order_id}/audit")
async def admin_audit(
    order_id: str,
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """审核（通过 → 可结算；驳回 → 回到制作中）。"""
    order = await db.get(SlOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.state != "pending_audit":
        raise HTTPException(
            status_code=409,
            detail=f"当前状态「{ledger.state_label(order.state)}」不在待审核中，无法审核")

    action = str(payload.get("action") or "").strip()
    remark = str(payload.get("remark") or "").strip()

    if action == "approve":
        issues = ledger.check_settle_eligibility(_order_out(order))
        if issues:
            raise HTTPException(status_code=422, detail={
                "message": "无法通过审核", "issues": issues,
            })
        order.state = "settleable"
        order.audit_status = "approved"
        order.audit_remark = remark
        await _log(db, kind="audit", actor=_actor(user),
                   detail=f"审核通过：{remark}" if remark else "审核通过",
                   order_id=order.id, designer_id=order.designer_id,
                   from_state="pending_audit", to_state="settleable")
    elif action == "reject":
        order.state = "rejected"
        order.audit_status = "rejected"
        order.audit_remark = remark or "未填写驳回原因"
        await _log(db, kind="audit", actor=_actor(user),
                   detail=f"审核驳回：{order.audit_remark}",
                   order_id=order.id, designer_id=order.designer_id,
                   from_state="pending_audit", to_state="rejected")
    else:
        raise HTTPException(status_code=422, detail="审核动作无效，只能是 approve 或 reject")

    await db.commit()
    await db.refresh(order)
    return _order_out(order)


@router.delete("/admin/orders/{order_id}")
async def admin_delete_order(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """删除订单。按课件规则：制作中可直接删，已交付必须联系客服。"""
    order = await db.get(SlOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    deletable, reason = ledger.check_deletable(_order_out(order))
    if not deletable:
        raise HTTPException(status_code=409, detail=reason)

    await _log(db, kind="order", actor=_actor(user),
               detail=f"删除订单 {order.order_no or order.id}",
               order_id=order.id, designer_id=order.designer_id)
    await db.delete(order)
    await db.commit()
    return {"ok": True}


@router.get("/admin/orders/{order_id}/diagnose")
async def admin_diagnose(
    order_id: str,
    expected_amount: str = "",
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """异常诊断（模块五）：六大常见异常逐条识别 + 处理方案。"""
    order = await db.get(SlOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    issues = ledger.diagnose_order(_order_out(order), expected_amount or None)
    return {"order_id": order_id, "issues": issues, "case_count": len(issues)}


# ---------- 结算管理（派单员侧只有「标记打款」）----------


@router.get("/admin/settlements")
async def admin_list_settlements(
    status: str = "",
    period: str = "",
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """结算单列表。"""
    stmt = select(SlSettlement)
    if status:
        stmt = stmt.where(SlSettlement.status == status)
    if period:
        stmt = stmt.where(SlSettlement.period == period)
    rows = (await db.execute(stmt.order_by(SlSettlement.created_at.desc()))).scalars().all()
    return [_settlement_out(s) for s in rows]


@router.post("/admin/settlements/{settlement_id}/pay")
async def admin_pay_settlement(
    settlement_id: str,
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """标记已打款。

    **派单员端没有「发起结算」的接口** —— 课件要求结算必须由设计师主动触发。
    这里只做「钱已经转了」的记录。
    """
    settlement = await db.get(SlSettlement, settlement_id)
    if settlement is None:
        raise HTTPException(status_code=404, detail="结算单不存在")
    if settlement.status == "paid":
        raise HTTPException(status_code=409, detail="该结算单已标记为打款")
    if settlement.status == "invalid":
        raise HTTPException(status_code=409,
                            detail=f"该结算单已失效：{settlement.invalid_reason}")

    flow_no = str(payload.get("flow_no") or "").strip()
    if not flow_no:
        raise HTTPException(status_code=422, detail="请填写打款流水号，这是对账凭证")

    settlement.status = "paid"
    settlement.flow_no = flow_no
    settlement.paid_at = utcnow()
    settlement.pay_date = str(payload.get("pay_date") or "").strip() or timeutil.today().isoformat()
    order = await db.get(SlOrder, settlement.order_id)
    if order is not None:
        order.state = "settled"
        await _log(db, kind="settle", actor=_actor(user),
                   detail=f"标记已打款 流水号={flow_no}",
                   order_id=order.id, designer_id=settlement.designer_id,
                   from_state=order.state, to_state="settled")
    await db.commit()
    await db.refresh(settlement)
    return _settlement_out(settlement)


# ===========================================================================
# 设计师端（独立登录：手机号 + 密码）
# ===========================================================================


@router.post("/auth/login")
async def designer_login(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """设计师登录结算端。

    课件关键前置条件：「设计师账号必须由派单平台在总后台『团队管理』模块
    完成录入后，才能生成并获取登录权限。未完成录入操作，设计师将无法
    登录结算端系统」。

    所以登录失败时要说清是「没录入」还是「密码错」——
    这两种情况的处理动作完全不同。
    """
    phone = str(payload.get("phone") or "").strip()
    password = str(payload.get("password") or "")

    if not phone or not password:
        raise HTTPException(status_code=400, detail="请输入手机号与密码")

    designer = (await db.execute(
        select(SlDesigner).where(SlDesigner.phone == phone)
    )).scalar_one_or_none()
    if designer is None:
        raise HTTPException(
            status_code=403,
            detail="该手机号尚未开通结算端权限。请联系派单员在总后台"
                   "「团队管理」中先完成设计师信息录入，再登录结算端")
    if designer.status != "active":
        raise HTTPException(status_code=403, detail="该账号已停用，请联系派单员")
    if not verify_password(password, designer.password_hash):
        raise HTTPException(status_code=401, detail="手机号或密码不正确")

    return {
        "designer_id": designer.id,
        "name": designer.name,
        "nickname": designer.nickname,
        "must_change_password": designer.must_change_password,
        # 真正的签名令牌 —— 不是明文 ID。
        # 明文 ID 等于谁都能查别人的订单和收益。
        "token": create_designer_token(designer.id),
        "token_type": "Bearer",
    }


@router.get("/me/profile")
async def me_profile(
    designer: SlDesigner = Depends(get_current_designer),
) -> dict[str, Any]:
    """当前登录设计师的信息。前端用它渲染头像与昵称。"""
    return {
        "designer_id": designer.id,
        "name": designer.name,
        "nickname": designer.nickname,
        "must_change_password": designer.must_change_password,
        "alipay_account": designer.alipay_account,
        "alipay_name": designer.alipay_name,
    }


@router.get("/me/orders")
async def me_orders(
    designer: SlDesigner = Depends(get_current_designer),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """我的订单 —— 实时查看名下订单进度。"""
    rows = (await db.execute(
        select(SlOrder).where(SlOrder.designer_id == designer.id)
        .order_by(SlOrder.created_at.desc())
    )).scalars().all()
    out = []
    for o in rows:
        item = _order_out(o)
        # 设计师端不给看客服内部备注，只给需求与进度
        item.pop("note", None)
        out.append(item)
    return out


@router.get("/me/settleable")
async def me_settleable(
    designer: SlDesigner = Depends(get_current_designer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """一键结算页面数据。

    课件：结算入口仅每月 8 日-9 日开放，且必须设计师主动点击才发起。
    所以这个接口**只列单，不发起结算**。
    """
    did = designer.id
    today = timeutil.today()
    rows = (await db.execute(
        select(SlOrder).where(SlOrder.designer_id == did)
        .order_by(SlOrder.created_at.desc())
    )).scalars().all()
    order_dicts = [_order_out(o) for o in rows]
    candidates = ledger.settle_eligible_orders(order_dicts, today)

    # 已经结算过的单要排除掉，不能重复发起
    done = (await db.execute(
        select(SlSettlement).where(SlSettlement.designer_id == did)
    )).scalars().all()
    done_order_ids = {s.order_id for s in done if s.status != "invalid"}

    window = ledger.settle_window(today)
    eligible = [c for c in candidates if c["eligible"] and c["order_id"] not in done_order_ids]
    blocked = [c for c in candidates if c["order_id"] in done_order_ids]

    return {
        "window": window.as_dict(),
        "eligible": eligible,
        "blocked": blocked,
        "total_commission": str(ledger.quantize_money(
            sum((_dec(c["commission"]) for c in eligible), Decimal("0")))),
        "count": len(eligible),
    }


@router.post("/me/settle")
async def me_settle(
    payload: dict[str, Any],
    designer: SlDesigner = Depends(get_current_designer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """一键结算 —— **设计师主动触发**。

    两条硬门禁：
    1. 必须在每月 8-9 号的结算窗口内
    2. 订单接单时间必须在两个月有效期内

    不满足就明确说为什么，不给含糊的失败。
    """
    did = designer.id
    today = timeutil.today()

    window = ledger.settle_window(today)
    if not window.open:
        raise HTTPException(status_code=409, detail=window.message)

    order_ids = payload.get("order_ids")
    if not isinstance(order_ids, list) or not order_ids:
        raise HTTPException(status_code=422, detail="请至少选择一笔订单")

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for raw_id in order_ids:
        order = await db.get(SlOrder, str(raw_id))
        if order is None or order.designer_id != did:
            skipped.append({"order_id": str(raw_id), "reason": "订单不存在或不属于你"})
            continue
        if order.state != "settleable":
            skipped.append({"order_id": order.order_no or order.id,
                            "reason": f"当前状态「{ledger.state_label(order.state)}」，不可结算"})
            continue
        issues = ledger.check_settle_eligibility(_order_out(order), today)
        if issues:
            skipped.append({"order_id": order.order_no or order.id,
                            "reason": issues[0]})
            continue
        exists = (await db.execute(
            select(SlSettlement).where(
                SlSettlement.order_id == order.id,
                SlSettlement.status != "invalid",
            )
        )).scalars().first()
        if exists:
            skipped.append({"order_id": order.order_no or order.id,
                            "reason": "该订单已发起过结算，不能重复发起"})
            continue

        settlement = SlSettlement(
            order_id=order.id,
            designer_id=did,
            designer_name=designer.name,
            commission=order.designer_commission,
            period=today.strftime("%Y-%m"),
            status="pending",
            # 收款账号做快照 —— 打款时设计师可能已经改账号了
            alipay_account=designer.alipay_account,
            alipay_name=designer.alipay_name or designer.name,
            pay_date="",
        )
        db.add(settlement)
        await db.flush()
        order.state = "settling"
        await _log(db, kind="settle", actor=designer.name,
                   detail=f"设计师发起一键结算 金额={settlement.commission} 结算期={settlement.period}",
                   order_id=order.id, designer_id=did,
                   from_state="settleable", to_state="settling")
        created.append(_settlement_out(settlement))

    await db.commit()
    return {"created": created, "skipped": skipped, "window": window.as_dict()}


@router.get("/me/settlements")
async def me_settlements(
    designer: SlDesigner = Depends(get_current_designer),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """收益明细 —— 历史结算记录。"""
    rows = (await db.execute(
        select(SlSettlement).where(SlSettlement.designer_id == designer.id)
        .order_by(SlSettlement.created_at.desc())
    )).scalars().all()
    return [_settlement_out(s) for s in rows]


@router.post("/me/password")
async def me_change_password(
    payload: dict[str, Any],
    designer: SlDesigner = Depends(get_current_designer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """修改密码。临时密码首次登录后必须改。"""
    old_password = str(payload.get("old_password") or "")
    new_password = str(payload.get("new_password") or "")
    if not verify_password(old_password, designer.password_hash):
        raise HTTPException(status_code=401, detail="原密码不正确")
    if len(new_password) < 6:
        raise HTTPException(status_code=422, detail="新密码不能少于 6 位")

    designer.password_hash = hash_password(new_password)
    designer.must_change_password = False
    await _log(db, kind="designer", actor=designer.name,
               detail="修改登录密码", designer_id=designer.id)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 与总系统（上游）互通
# ---------------------------------------------------------------------------
#
# 这一段是「两系统互通」真正落地的地方。
#
# **只读、单向**：从上游拉数据进本地，不回写。上游是生产系统，
# 本地结算系统是它的下游视图 —— 任何写回上游的动作都不做。
#
# 桥接的翻译逻辑全在 ``services/settle_bridge.py``，
# 路由层只负责调上游 + 落库 + 把结果说清楚。

#: 上游总后台账号密码的环境变量名（只从环境变量读，不落库不进日志）
ENV_UPSTREAM_USERNAME = "TRCIPG_USERNAME"
ENV_UPSTREAM_PASSWORD = "TRCIPG_PASSWORD"


def _upstream_client() -> TrcipgClient:
    """构造上游客户端。

    凭据只从环境变量读 —— 上游是生产系统，凭据泄露的代价远大于多写几行代码。

    **例外**：设了 ``SETTLE_FAKE_UPSTREAM=1`` 就走本地假数据源。
    这是给演示/教学/回归测试用的 —— 上游不是随时能连的，
    而「两系统互通」这条链路必须能随时完整跑一遍。
    """
    if bridge.fake_upstream_enabled():
        return bridge.FakeUpstreamClient()  # type: ignore[return-value]

    username = os.getenv(ENV_UPSTREAM_USERNAME, "").strip()
    password = os.getenv(ENV_UPSTREAM_PASSWORD, "").strip()
    if not username or not password:
        raise HTTPException(
            status_code=400,
            detail=f"未配置上游账号：请设置环境变量 {ENV_UPSTREAM_USERNAME} "
                   f"与 {ENV_UPSTREAM_PASSWORD}",
        )
    return TrcipgClient(username, password)


def _upstream_configured() -> bool:
    """上游是否可用（配了凭据，或开了假数据源）。"""
    if bridge.fake_upstream_enabled():
        return True
    username = os.getenv(ENV_UPSTREAM_USERNAME, "").strip()
    password = os.getenv(ENV_UPSTREAM_PASSWORD, "").strip()
    return bool(username and password)


@router.get("/admin/bridge/status")
async def bridge_status(
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """互通状态：上游有没有配凭据、能不能连。"""
    fake = bridge.fake_upstream_enabled()
    configured = _upstream_configured()
    result: dict[str, Any] = {
        "configured": configured,
        "mode": "只读 · 单向导入 · 不回写",
        "hint": (
            "当前使用本地演示数据源（假上游），可完整演示互通流程"
            if fake else
            ("已配置上游账号，可从总系统导入设计师与订单"
             if configured else
             f"未配置上游账号：请设置环境变量 {ENV_UPSTREAM_USERNAME} 与 "
             f"{ENV_UPSTREAM_PASSWORD}")
        ),
    }
    if fake:
        result["reachable"] = True
        result["demo_mode"] = True
        result["designer_total"] = len(bridge.fake_designers())
        result["checked_at"] = timeutil.utcnow().isoformat()
        return result

    if not configured:
        return result

    try:
        client = _upstream_client()
        designers, total = await client.list_designer_detail(page=1, num=1)
        result["reachable"] = True
        result["designer_total"] = total
        result["checked_at"] = timeutil.utcnow().isoformat()
    except UpstreamBlockedError as exc:
        result["reachable"] = False
        result["error"] = f"上游临时拦截，稍后重试：{exc}"
    except UpstreamError as exc:
        result["reachable"] = False
        result["error"] = f"上游调用失败：{exc}"
    except Exception as exc:  # noqa: BLE001 —— 网络异常五花八门，别漏给前端
        result["reachable"] = False
        result["error"] = f"连接上游失败：{exc}"
    return result


@router.get("/admin/bridge/preview")
async def bridge_preview(
    kind: str = Query("designers", pattern="^(designers|orders)$"),
    limit: int = Query(20, ge=1, le=200),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """导入前预览：先看看上游有什么、能不能导，再决定导不导。"""
    client = _upstream_client()
    try:
        if kind == "designers":
            rows, total = await client.list_designer_detail(page=1, num=limit)
            items = []
            for src in rows:
                row = bridge.designer_to_local(src)
                issues = bridge.check_designer_importable(row)
                items.append({
                    "upstream_id": row["upstream_id"],
                    "name": row["name"],
                    "nickname": row["nickname"],
                    "phone": row["phone"],
                    "alipay_account": row["alipay_account"],
                    "production_level": row["production_level"],
                    "importable": not issues,
                    "issues": issues,
                })
            return {"kind": kind, "total": total, "items": items}

        # 订单：上游 order/list 只返回已完工的单，全量要走结算单
        rows, total = await client.list_orders(page=1, num=limit, status=5)
        items = []
        for src in rows:
            row = bridge.order_to_local(src)
            issues = bridge.check_order_importable(row)
            items.append({
                "upstream_id": row["upstream_id"],
                "order_no": row["order_no"],
                "designer_name": row["designer_name"],
                "order_amount": str(row["order_amount"]),
                "commission": str(row["designer_commission"]),
                "commission_rate": str(row["commission_rate"]),
                "upstream_status": src.status,
                "upstream_status_label": src.status_label,
                "local_state": row["state"],
                "local_state_label": ledger.state_label(row["state"]),
                "importable": not issues,
                "issues": issues,
            })
        return {"kind": kind, "total": total, "items": items}
    except UpstreamBlockedError as exc:
        raise HTTPException(status_code=503, detail=f"上游临时拦截，稍后重试：{exc}",
                            headers={"Retry-After": "60"}) from exc
    except UpstreamError as exc:
        raise HTTPException(status_code=502, detail=f"上游调用失败：{exc}") from exc


@router.post("/admin/bridge/import")
async def bridge_import(
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """从上游导入设计师 / 订单。

    **幂等**：按上游 ID 去重，重复点导入不会产生第二条记录。
    导入的单会带上「有哪些问题」的清单，比例越界这类事不藏着。
    """
    kind = str(payload.get("kind") or "designers").strip()
    limit = int(payload.get("limit") or 50)
    limit = max(1, min(limit, 200))
    only_valid = bool(payload.get("only_valid", True))
    password = str(payload.get("password") or "temp123456").strip() or "temp123456"

    client = _upstream_client()
    try:
        if kind == "designers":
            rows, _total = await client.list_designer_detail(page=1, num=limit)
            result = await bridge.import_designers(
                db, rows, password=password, only_valid=only_valid)
        elif kind == "orders":
            rows, _total = await client.list_orders(page=1, num=limit, status=5)
            result = await bridge.import_orders(db, rows, only_valid=only_valid)
        else:
            raise HTTPException(status_code=422,
                                detail="kind 只能是 designers 或 orders")
    except UpstreamBlockedError as exc:
        raise HTTPException(status_code=503, detail=f"上游临时拦截，稍后重试：{exc}",
                            headers={"Retry-After": "60"}) from exc
    except UpstreamError as exc:
        raise HTTPException(status_code=502, detail=f"上游调用失败：{exc}") from exc

    await _log(db, kind="bridge", actor=_actor(user),
               detail=f"从上游导入 {kind}：新增 {result.created_count}，"
                      f"跳过 {result.skipped_count}")
    await db.commit()
    return {"kind": kind, **result.as_dict()}
