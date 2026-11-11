"""OPC · 上游同步与对账路由。

这一层回答那个最实际的问题：**「两个系统怎么连起来」**。

连接方式不是「OPC 去改上游」—— 那是越权，也是灾难的来源。
连接方式是 **单向拉取 + 本地台账 + 差异对账**：

    上游总后台 /roleapi/*           OPC 本地库              人
    ─────────────────────         ──────────────         ─────────
    设计师 1467 人      ──拉取──▶  opc_designers     ──▶  撮合派单
    订单  N 单          ──拉取──▶  opc_orders       ──▶  需求合同补全
    结算单 1743 条      ──拉取──▶  opc_settlements  ──▶  对账差异
                                      ▲
                                      └── 比对：上游佣金 vs 台账佣金

写入方向一律**只写 OPC 自己的库**。要改上游（派单、验收、结算），
走 OPC 台账 → 人工在总后台确认 → 再拉回来对账。

鉴权：上游账号密码从环境变量读，**不落数据库、不写日志**。
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database import get_db
from app.models import (OpcDesigner, OpcOrder, OpcSettlement, OpcStore,
                         OpcSplitRule, User)
from app.schemas_opc import OpcSyncReportOut, OpcUpstreamDesignerOut
from app.services import opc_sync as sync
from app.services.trcipg_client import (SETTLEMENT_TYPES, TrcipgClient,
                                         UpstreamBlockedError, UpstreamError)

router = APIRouter(prefix="/api/opc/upstream", tags=["opc-upstream"])

#: 环境变量名（上游总后台账号）
ENV_USERNAME = "TRCIPG_USERNAME"
ENV_PASSWORD = "TRCIPG_PASSWORD"


class UpstreamCredentialsMissing(RuntimeError):
    """没配上游账号密码。"""


def _client() -> TrcipgClient:
    """从环境变量构造上游客户端。

    **账号密码只从环境变量读**，不落数据库、不进日志、不返回给前端 ——
    上游是生产系统，凭据泄露的代价远大于多写几行代码。
    """
    username = os.getenv(ENV_USERNAME, "").strip()
    password = os.getenv(ENV_PASSWORD, "").strip()
    if not username or not password:
        raise UpstreamCredentialsMissing(
            f"未配置上游账号：请设置环境变量 {ENV_USERNAME} 与 {ENV_PASSWORD}"
        )
    return TrcipgClient(username, password)


async def _guard(fn, *args, **kwargs):
    """统一异常翻译：上游错误 → 502，被上游挡 → 503，缺凭据 → 400。"""
    try:
        return await fn(*args, **kwargs)
    except UpstreamCredentialsMissing as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UpstreamBlockedError as exc:
        # 503 + Retry-After：上游临时拦截，不是 OPC 的问题，
        # 让调用方等一会儿再试，别让人以为接口坏了
        raise HTTPException(status_code=503, detail=str(exc),
                            headers={"Retry-After": "60"}) from exc
    except UpstreamError as exc:
        raise HTTPException(status_code=502, detail=f"上游系统调用失败：{exc}") from exc


def _require_credentials() -> None:
    """在构造客户端**之前**检查凭据，把缺凭据转成 400。

    没有这一步，缺凭据会抛成 500 —— 用户看到的是「服务器内部错误」，
    完全不知道是自己没配环境变量。
    """
    username = os.getenv(ENV_USERNAME, "").strip()
    password = os.getenv(ENV_PASSWORD, "").strip()
    if not username or not password:
        raise HTTPException(
            status_code=400,
            detail=f"未配置上游账号：请设置环境变量 {ENV_USERNAME} 与 {ENV_PASSWORD}",
        )


# ---------------------------------------------------------------------------
# 连通性
# ---------------------------------------------------------------------------


@router.get("/status")
async def upstream_status(_: User = Depends(get_current_user)) -> dict[str, Any]:
    """探测上游是否可达。

    **没配凭据时不报 400，而是返回 ``configured: false``** ——
    这个接口的用途就是「看看能不能连上」，
    缺凭据本身就是一个需要展示的状态，不该是错误。
    """
    username = os.getenv(ENV_USERNAME, "").strip()
    password = os.getenv(ENV_PASSWORD, "").strip()
    if not username or not password:
        return {
            "configured": False,
            "reachable": False,
            "base": "https://ppt2api.trcipg.com.cn",
            "hint": f"请设置环境变量 {ENV_USERNAME} 与 {ENV_PASSWORD}",
            "note": "总后台 /roleapi 族；结算端 /settlement 族是另一套后端，需独立凭据",
            "settlement_types": [{"value": k, "label": v} for k, v in SETTLEMENT_TYPES.items()],
        }
    client = TrcipgClient(username, password)
    ok = await client.ping()
    return {
        "configured": True,
        "reachable": ok,
        "base": client.base,
        "hint": "",
        "note": "总后台 /roleapi 族；结算端 /settlement 族是另一套后端，需独立凭据",
        "settlement_types": [{"value": k, "label": v} for k, v in SETTLEMENT_TYPES.items()],
    }


# ---------------------------------------------------------------------------
# 拉取上游数据（只读，不落库）
# ---------------------------------------------------------------------------


@router.get("/designers")
async def upstream_designers(
    member_type: int = Query(1, ge=1, le=3, description="1=设计师 2=HR 3=品控"),
    limit: int = Query(200, ge=1, le=2000),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """拉上游设计师档案（只读）。

    这是撮合的对象池：带收款账号、战区、档次、结算资格。
    """
    _require_credentials()
    client = _client()
    designers, total = await _guard(
        client.list_designer_detail, page=1, num=limit, member_type=member_type
    )
    return {
        "total": total,
        "fetched": len(designers),
        "items": [
            OpcUpstreamDesignerOut(
                id=d.id, name=d.name, nickname=d.nickname, phone=d.phone,
                alipay_account=d.alipay_account, war_zone=d.war_zone,
                production_level=d.production_level,
                recruitment_source=d.recruitment_source,
                hr_name=d.hr_name, quality_control_name=d.quality_control_name,
                design_supervisor_name=d.design_supervisor_name,
                can_settle=d.can_settle, status=d.status,
            ).model_dump()
            for d in designers
        ],
    }


@router.get("/orders")
async def upstream_orders(
    page: int = Query(1, ge=1),
    num: int = Query(50, ge=1, le=500),
    status: int | None = Query(None, description="上游订单状态 1..9"),
    order_type: int | None = Query(None, description="上游订单类型"),
    is_del: int | None = Query(None, description="是否已删除"),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """拉上游订单（只读）。

    **筛选参数必须显式传** —— 少传上游会静默返回 0 条而不是报错。
    """
    _require_credentials()
    client = _client()
    orders, total = await _guard(
        client.list_orders, page=page, num=num,
        status=status, order_type=order_type, is_del=is_del,
    )
    return {
        "total": total,
        "fetched": len(orders),
        "items": [
            {
                "id": o.id, "sn": o.sn, "order_sn": o.order_sn,
                "order_desc": o.order_desc, "customer_name": o.customer_name,
                "store_name": o.store_name, "store_account": o.store_account,
                "designer_name": o.designer_name, "user_name": o.user_name,
                "order_grade": o.order_grade,
                "status": o.status, "status_label": o.status_label,
                "opc_state": sync.map_upstream_state(o.status),
                "order_commission": str(o.order_commission),
                "designer_commission": str(o.designer_commission),
                "middle_control_commission": str(o.middle_control_commission),
                "design_supervisor_bonus": str(o.design_supervisor_bonus),
                "request_delivery_time": o.request_delivery_time,
                "final_draft_time": o.final_draft_time,
                "split": sync.extract_upstream_split(o).as_dict(),
            }
            for o in orders
        ],
    }


@router.get("/orders/{order_id}")
async def upstream_order_detail(
    order_id: int,
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """拉单张上游订单详情（含佣金拆分、原稿/终稿图、问题描述）。

    顺带返回 **OPC 六段式需求合同的草稿** —— 直接用上游真实字段拼的，
    未提供的段落会写明「需补」，由 OPC 的 spec 校验报出信息不足。
    """
    _require_credentials()
    client = _client()
    order = await _guard(client.get_order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"上游订单 {order_id} 不存在")
    split = sync.extract_upstream_split(order)
    return {
        "order": {
            "id": order.id, "sn": order.sn, "order_sn": order.order_sn,
            "order_desc": order.order_desc, "customer_name": order.customer_name,
            "store_name": order.store_name, "store_account": order.store_account,
            "designer_name": order.designer_name, "user_name": order.user_name,
            "hr_name": order.hr_name, "quality_control_name": order.quality_control_name,
            "order_grade": order.order_grade,
            "status": order.status, "status_label": order.status_label,
            "opc_state": sync.map_upstream_state(order.status),
            "designer_settlement_status": order.designer_settlement_status,
            "hr_settlement_status": order.hr_settlement_status,
            "quality_control_settlement_status": order.quality_control_settlement_status,
            "request_delivery_time": order.request_delivery_time,
            "sample_manuscript_time": order.sample_manuscript_time,
            "final_draft_time": order.final_draft_time,
            "order_time": order.order_time,
            "source_images": order.source_images,
            "end_images": order.end_images,
            "sub_order": order.sub_order,
            "issue_desc": order.issue_desc,
            "reject_reason": order.reject_reason,
            "customer_service": order.customer_service,
            "transfer_order_status": order.transfer_order_status,
        },
        "split": split.as_dict(),
        "spec_draft": sync.build_spec_from_upstream(order),
        "match_terms": sync.extract_terms_for_match(order),
    }


@router.get("/settlements")
async def upstream_settlements(
    settlement_type: int = Query(1, ge=1, le=3, description="1=普通 2=HR 3=品控"),
    page: int = Query(1, ge=1),
    num: int = Query(50, ge=1, le=500),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """拉上游结算单（只读）。

    ``settlement_type`` **必传**（1=普通 2=HR 3=品控），不传上游会报错。
    """
    _require_credentials()
    client = _client()
    settlements, total, commission = await _guard(
        client.list_settlements, settlement_type=settlement_type, page=page, num=num
    )
    return {
        "settlement_type": settlement_type,
        "settlement_type_label": SETTLEMENT_TYPES.get(settlement_type, "未知"),
        "total": total,
        "commission_sum": str(commission),
        "items": [
            {
                "id": s.id, "order_id": s.order_id, "sn": s.sn, "order_sn": s.order_sn,
                "team_members_name": s.team_members_name,
                "store_name": s.store_name, "customer_name": s.customer_name,
                "order_grade_name": s.order_grade_name, "war_zone_name": s.war_zone_name,
                "commission": str(s.commission),
                "order_commission": str(s.order_commission),
                "middle_control_commission": str(s.middle_control_commission),
                "settlement_status": s.settlement_status,
                "settlement_status_label": sync.map_settlement_status(s.settlement_status),
                "settlement_time": s.settlement_time,
                "alipay_account": s.alipay_account,
            }
            for s in settlements
        ],
    }


@router.get("/dictionaries")
async def upstream_dictionaries(_: User = Depends(get_current_user)) -> dict[str, Any]:
    """拉上游字典（档次、问题类型），撮合筛选要用。"""
    _require_credentials()
    client = _client()
    grades = await _guard(client.list_order_grades)
    issues = await _guard(client.list_order_issue_types)
    return {
        "order_grades": [{"id": i, "name": n} for i, n in grades],
        "order_issue_types": [{"id": i, "name": n} for i, n in issues],
        "upstream_order_status": [
            {"id": k, "label": v} for k, v in sync.UPSTREAM_TO_OPC_STATE.items()
        ],
    }


# ---------------------------------------------------------------------------
# 落库同步：把上游数据写进 OPC 台账
# ---------------------------------------------------------------------------


@router.post("/sync", response_model=OpcSyncReportOut)
async def sync_from_upstream(
    settlement_type: int = Query(1, ge=1, le=3),
    limit: int = Query(100, ge=1, le=500),
    write: bool = Query(True, description="False=只预览不落库"),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OpcSyncReportOut:
    """把上游数据同步进 OPC 台账。

    **同步是幂等的**：以 ``order_sn`` / 设计师手机号为键 upsert，
    重复跑不会产生重复数据。

    ``write=False`` 时只统计将要写什么，不落库 —— 第一次跑建议先这样试。
    """
    _require_credentials()
    client = _client()
    upstream_orders, order_total = await _guard(
        client.list_orders, page=1, num=limit, status=5, order_type=5, is_del=1
    )
    designers, designer_total = await _guard(client.list_designer_detail, page=1, num=500)
    settlements, settlement_total, commission_sum = await _guard(
        client.list_settlements, settlement_type=settlement_type, page=1, num=limit
    )

    created = {"designers": 0, "orders": 0, "settlements": 0}
    updated = {"designers": 0, "orders": 0, "settlements": 0}

    if write:
        # ---- 设计师 upsert（键：上游 ID）----
        # **不能用手机号当键** —— 实测上游 300 条里有 3 个手机号重复
        # （同一人多条档案），用手机号会撞 MultipleResultsFound。
        for d in designers:
            key = str(d.id)
            existing = (await db.execute(
                select(OpcDesigner).where(OpcDesigner.upstream_id == key)
            )).scalars().first()
            if existing is None:
                existing = OpcDesigner(upstream_id=key, phone=d.phone, name=d.name)
                db.add(existing)
                created["designers"] += 1
            else:
                updated["designers"] += 1
            existing.name = d.name
            existing.phone = d.phone
            existing.alipay_account = d.alipay_account
            existing.alipay_name = d.name
            existing.production_level = d.production_level
            existing.war_zone = d.war_zone
            existing.hr_id = d.hr_name
            existing.quality_control_id = d.quality_control_name
            existing.design_tags = d.design_supervisor_name
            existing.status = "active" if d.can_settle else "blocked"
            existing.note = (
                f"上游ID={d.id}｜战区={d.war_zone}｜档次={d.production_level}"
                f"｜招募来源={d.recruitment_source}｜结算资格={'有' if d.can_settle else '无'}"
            )

        # ---- 订单 upsert（键：上游 ID，order_sn 作为业务编号）----
        for o in upstream_orders:
            key = str(o.id)
            existing = (await db.execute(
                select(OpcOrder).where(OpcOrder.upstream_id == key)
            )).scalars().first()
            if existing is None:
                existing = OpcOrder(
                    upstream_id=key,
                    order_sn=o.order_sn or o.sn or key,
                    title=o.order_desc[:200] or o.sn,
                )
                db.add(existing)
                created["orders"] += 1
            else:
                updated["orders"] += 1
            existing.title = o.order_desc[:200] or o.sn
            existing.store_name = o.store_name
            existing.designer_name = o.designer_name
            existing.order_grade = o.order_grade
            existing.order_type = str(o.order_type)
            existing.order_commission = o.order_commission
            existing.request_delivery_time = o.request_delivery_time
            existing.sample_manuscript_time = o.sample_manuscript_time
            existing.final_draft_time = o.final_draft_time
            existing.remark = (
                f"上游订单ID={o.id}｜客户={o.customer_name}｜收款主体={o.store_account}"
                f"｜中控={o.middle_control_commission}｜主管奖金={o.design_supervisor_bonus}"
                f"｜上游状态={o.status_label}"
            )
            if not existing.spec_snapshot:
                existing.spec_snapshot = sync.build_spec_from_upstream(o)

        await db.commit()

    return OpcSyncReportOut(
        upstream_orders=order_total,
        upstream_designers=designer_total,
        upstream_settlements=settlement_total,
        upstream_commission_sum=str(commission_sum),
        created=created,
        updated=updated,
        wrote=write,
        settlement_type=settlement_type,
        settlement_type_label=SETTLEMENT_TYPES.get(settlement_type, "未知"),
    )


# ---------------------------------------------------------------------------
# 对账
# ---------------------------------------------------------------------------


@router.get("/reconcile")
async def reconcile(
    settlement_type: int = Query(1, ge=1, le=3),
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """对账：上游佣金 vs OPC 台账佣金，**只报告差异，不自动改上游**。

    这是「两个系统连起来」里最值钱的一环 ——
    没有对账，两个系统的数字迟早对不上，而对不上时你不知道差在哪。
    """
    _require_credentials()
    client = _client()
    upstream_orders, _ = await _guard(client.list_orders, page=1, num=limit, status=5)
    settlements, _, _ = await _guard(
        client.list_settlements, settlement_type=settlement_type, page=1, num=limit
    )

    opc_orders = (await db.execute(select(OpcOrder))).scalars().all()
    opc_commissions: dict[str, Any] = {}
    for o in opc_orders:
        opc_commissions[o.order_sn] = o.order_commission

    opc_settlements = (await db.execute(select(OpcSettlement))).scalars().all()
    opc_settle_commissions: dict[str, Any] = {}
    for s in opc_settlements:
        opc_settle_commissions[s.order_sn or s.id] = s.commission

    report = sync.build_report(
        upstream_orders, settlements, opc_commissions, opc_settle_commissions
    )
    return report.as_dict()


# ---------------------------------------------------------------------------
# 上游订单的候选人推荐（撮合）
# ---------------------------------------------------------------------------


@router.get("/orders/{order_id}/candidates")
async def upstream_candidates(
    order_id: int,
    limit: int = Query(10, ge=1, le=50),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """给一张上游订单推荐候选设计师。

    排序维度全用**上游真实字段**：档次匹配、战区匹配、结算资格、在制单数量。
    被上游禁用结算或没有收款账号的会被标 ``blocked``，排在最后且不可派。
    """
    _require_credentials()
    client = _client()
    order = await _guard(client.get_order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"上游订单 {order_id} 不存在")

    upstream_designers, _ = await _guard(client.list_designer_detail, page=1, num=500)

    # 在制单统计：OPC 台账里处于活跃状态的订单
    active = (await db.execute(
        select(OpcOrder).where(OpcOrder.state.notin_(["settled", "canceled"]))
    )).scalars().all()
    busy_ids: set[int] = set()
    for o in active:
        for token in (o.designer_name or "").split():
            for up in upstream_designers:
                if up.name == token:
                    busy_ids.add(up.id)

    ranked = sync.rank_designers_for_order(
        order, upstream_designers, busy_designer_ids=busy_ids, limit=limit
    )
    return {
        "order_sn": order.sn,
        "order_grade": order.order_grade,
        "war_zone": order.war_zone_name,
        "candidates": [c.as_dict() for c in ranked],
        "note": "评分基于上游真实字段：档次匹配 +2、战区匹配 +1.5、在制订单 -3、"
                "档次/战区不匹配 -0.5；被上游禁用结算或无收款账号的一律不可派",
    }
