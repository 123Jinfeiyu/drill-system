"""两系统互通桥接：把上游（总系统）的数据搬进本地结算系统。

**只读、单向、不回写。** 上游是生产系统，本地结算系统只是它的一个下游视图。
桥接层做的事只有一件：**把上游的一条记录翻译成本地的一条记录**。

翻译规则（不是复制，是映射）：

===================  ==========================  ==========================
上游字段              本地字段                    备注
===================  ==========================  ==========================
``teamMembers.id``   ``upstream_id``              幂等键，手机号不唯一
``name``             ``name``                    原样
``nickname``         ``nickname``                花名
``phone``            ``phone``                   **登录账号**，唯一
``alipay_account``   ``alipay_account``          收款凭证
``production_level`` ``production_level``        制作档次
``war_zone``         （**不导入**）              课件要求战区必须留空
``hr_name``          （**不导入**）              课件要求 HR 必须留空
===================  ==========================  ==========================

订单侧：

===================  ==========================  ==========================
上游字段              本地字段                    备注
===================  ==========================  ==========================
``order.id``         ``upstream_id``              幂等键
``order_sn`` / ``sn`` ``order_no``               订单编号
``customer_name``    ``customer_id``             客户追溯凭证
``war_zone_name``    ``war_zone``                上游有值，本地照存
``designer_name``    ``designer_name``           关联到本地设计师
``order_commission`` ``order_amount``            项目总金额
佣金比例              ``commission_rate``          **反推**，见 :func:`_rate_of`
``designer_commission`` ``designer_commission``  设计师佣金
``status``           ``state``                    9 态 → 本地状态机
===================  ==========================  ==========================

**佣金比例是反推出来的** —— 上游只给金额不给比例。
本地规则层要求比例落在 ``[0.50, 0.70]``，反推出来的比例如果越界，
说明这笔单的口径跟本地规则对不上，**这单要标出来让人看，不许悄悄塞进去**。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from app.services import settle_ledger as ledger
from app.services.trcipg_client import UpstreamDesigner, UpstreamOrder

#: 上游订单类型 → 本地订单类型（模块三三选一）
#: 上游 ``order_type`` 实测为 int，0/1/2 分别对应
UPSTREAM_ORDER_TYPE_TO_LOCAL: dict[int, str] = {
    0: "personal",
    1: "internal",
    2: "external",
}

#: 上游 ``designer_type`` → 本地性别（课件只有男女两值）
_UPSTREAM_GENDER: dict[int, int] = {1: 1, 2: 2}


@dataclass(slots=True)
class BridgeResult:
    """一次导入的结果。

    ``created`` / ``skipped`` 分开计数 —— 「导入条」和「为什么没导」，
    两件事都得让派单员看得见，不然数据对不上时会互相怀疑。
    """

    created: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    @property
    def created_count(self) -> int:
        return len(self.created)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "created_count": self.created_count,
            "skipped": self.skipped,
            "skipped_count": self.skipped_count,
        }


# ---------------------------------------------------------------------------
# 单条翻译（纯函数，不碰数据库）
# ---------------------------------------------------------------------------


def _rate_of(order_amount: Decimal, designer_commission: Decimal) -> Decimal | None:
    """反推佣金比例。

    上游只给金额不给比例，本地规则层要求 ``[0.50, 0.70]``。

    **返回 None 表示「比例未知」**，不是 0。两种情况：

    - 金额为 0 → 分母没了，除不出来
    - 佣金为 0 → 上游还没算这笔佣金（规则硬下限是 50%，真实比例不可能是 0），
      这时比例是**未知**，不是 0

    这两种都返回 None —— 拿 0 去填 ``commission_rate`` 会被规则层当成
    「比例 0，越界」，把一笔数据不全的单说成违规单，冤枉人。
    """
    if not order_amount or order_amount <= 0:
        return None
    if not designer_commission or designer_commission <= 0:
        return None
    try:
        rate = (designer_commission / order_amount).quantize(Decimal("0.0001"))
    except Exception:
        return None
    return rate


def designer_to_local(src: UpstreamDesigner) -> dict[str, Any]:
    """上游设计师 → 本地设计师档案的字段映射。

    **战区与 HR 一律不导** —— 课件明确要求这两栏留空，
    上游有值也不带过来，别把上游的组织架构污染进本地台账。

    ``status`` 的判断用上游 ``status`` 字段（0=停用）。
    ``allow_settlement``（是否允许参与结算）单独保留 ——
    上游禁结算的人档案照样能导（他可能还在接单），但要标出来。
    """
    return {
        "upstream_id": str(src.id),
        "name": (src.name or "").strip(),
        "nickname": (src.nickname or "").strip(),
        "phone": (src.phone or "").strip(),
        "alipay_account": (src.alipay_account or "").strip(),
        "alipay_name": (src.name or "").strip(),
        "gender": _UPSTREAM_GENDER.get(int(src.designer_type or 0), 0),
        "recruitment_source": (src.recruitment_source or "").strip(),
        "production_level": (src.production_level or "").strip(),
        # 战区 / hr_id —— 故意不设值，留空
        "status": "active" if int(src.status or 0) != 0 else "disabled",
        "note": (f"上游 allow_settlement={src.allow_settlement}"
                 if not src.can_settle else ""),
    }


def order_to_local(src: UpstreamOrder) -> dict[str, Any]:
    """上游订单 → 本地订单的字段映射。"""
    amount = Decimal(src.order_commission or 0)
    commission = Decimal(src.designer_commission or 0)
    rate = _rate_of(amount, commission)

    # 上游 order_type 是 int，本地是三选一的字符串
    local_type = UPSTREAM_ORDER_TYPE_TO_LOCAL.get(int(src.order_type or 0), "personal")

    # 订单编号：上游同时有 order_sn 和 sn，取先有值的那个
    order_no = (src.order_sn or src.sn or "").strip()

    return {
        "upstream_id": str(src.id),
        "order_no": order_no,
        "customer_id": (src.customer_name or src.store_account or "").strip(),
        "war_zone": (src.war_zone_name or "").strip(),
        "customer_service": (src.customer_service or src.user_name or "").strip(),
        "designer_name": (src.designer_name or "").strip(),
        "order_type": local_type,
        "service_type": (src.order_grade or "").strip(),
        "order_amount": amount,
        "commission_rate": rate if rate is not None else Decimal("0"),
        "designer_commission": commission,
        "requirement": (src.order_desc or "").strip(),
        "note": "",
        "deliver_date": (src.request_delivery_time or "").strip(),
        "order_date": (src.order_time or src.created_at or "").strip()[:10],
        "state": ledger.local_state_from_upstream(int(src.status or 0)),
    }


# ---------------------------------------------------------------------------
# 预检：这条记录能不能导
# ---------------------------------------------------------------------------


def check_designer_importable(row: dict[str, Any]) -> list[str]:
    """检查一条设计师记录能不能导进本地。

    返回**问题清单**，空列表表示可以导。

    「上游禁止结算」也列进来 —— 这人不该参与本地结算，
    但档案可以导（他可能还在接单），所以是**提醒**不是**拦截**。
    """
    issues: list[str] = []
    name = str(row.get("name") or "").strip()
    phone = str(row.get("phone") or "").strip()

    if not name:
        issues.append("设计师姓名为空")
    if not phone:
        issues.append("手机号为空 —— 手机号是登录账号，缺了无法登录结算端")
    elif not (phone.isdigit() and len(phone) == 11):
        issues.append(f"手机号「{phone}」格式不对，应为 11 位数字")
    if row.get("status") == "disabled":
        issues.append("上游已停用该设计师")
    if "allow_settlement=0" in str(row.get("note") or ""):
        issues.append("上游已禁止该设计师参与结算，导入后不要给他派单")
    return issues


def check_order_importable(row: dict[str, Any]) -> list[str]:
    """检查一条订单记录能不能导进本地。

    **越界不拦死，但必须标出来。** 上游的历史单可能是在旧规则下产生的，
    比例低于 50% 是历史遗留，硬拒掉会让台账对不上；
    但也不能悄悄放进去，否则结算时比例对不上会扯皮。
    所以这里只标记，让派单员自己决定。
    """
    issues: list[str] = []
    order_no = str(row.get("order_no") or "").strip()
    if not order_no:
        issues.append("上游没有订单编号（order_sn / sn 都为空）")

    amount = row.get("order_amount")
    commission = row.get("designer_commission")
    try:
        if amount and Decimal(amount) > 0:
            rate = Decimal(str(row.get("commission_rate") or 0))
            problems = ledger.validate_commission_rate(rate)
            if problems:
                issues.append("佣金比例越界：" + "；".join(problems)
                              + f"（反推值 {rate}，上游历史单可能不适用本地规则）")
    except Exception:
        issues.append("佣金比例无法反推，请人工核对金额")

    if commission is not None and Decimal(str(commission)) > 0 and not amount:
        issues.append("有佣金但没有订单金额，比例无法反推")
    return issues


# ---------------------------------------------------------------------------
# 批量导入（要数据库，由路由层调用）
# ---------------------------------------------------------------------------


async def import_designers(
    db: Any,
    rows: Iterable[UpstreamDesigner],
    *,
    password: str = "temp123456",
    only_valid: bool = True,
) -> BridgeResult:
    """把上游设计师导入本地。

    ``only_valid=True`` 时只导没问题的；有问题的进 ``skipped`` 并说明原因。
    重复导入按 ``upstream_id`` 跳过（幂等）。
    """
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.models import SlDesigner

    result = BridgeResult()
    existing_upstream = {
        uid for (uid,) in (await db.execute(
            select(SlDesigner.upstream_id).where(SlDesigner.upstream_id != "")
        )).all()
    }
    existing_phones = {
        p for (p,) in (await db.execute(
            select(SlDesigner.phone).where(SlDesigner.phone != "")
        )).all()
    }

    for src in rows:
        row = designer_to_local(src)
        uid = row["upstream_id"]

        if uid in existing_upstream:
            result.skipped.append({
                "upstream_id": uid,
                "name": row["name"],
                "reason": "已导入过（按上游 ID 去重）",
            })
            continue

        issues = check_designer_importable(row)
        if issues and only_valid:
            result.skipped.append({
                "upstream_id": uid,
                "name": row["name"],
                "reason": "；".join(issues),
            })
            continue

        if row["phone"] in existing_phones:
            result.skipped.append({
                "upstream_id": uid,
                "name": row["name"],
                "reason": f"手机号 {row['phone']} 本地已存在（上游同一人多条档案）",
            })
            continue

        designer = SlDesigner(
            **row,
            password_hash=hash_password(password),
            must_change_password=True,
        )
        db.add(designer)
        await db.flush()

        existing_upstream.add(uid)
        existing_phones.add(row["phone"])
        result.created.append({
            "id": designer.id,
            "upstream_id": uid,
            "name": row["name"],
            "phone": row["phone"],
            "issues": issues,
        })

    return result


async def import_orders(
    db: Any,
    rows: Iterable[UpstreamOrder],
    *,
    only_valid: bool = False,
) -> BridgeResult:
    """把上游订单导入本地。

    订单的幂等键是 ``upstream_id``；设计师按**姓名**匹配本地档案 ——
    上游只给设计师名字，没给本地设计师 ID。
    """
    from sqlalchemy import select

    from app.models import SlDesigner, SlOrder

    result = BridgeResult()
    existing_upstream = {
        uid for (uid,) in (await db.execute(
            select(SlOrder.upstream_id).where(SlOrder.upstream_id != "")
        )).all()
    }
    designers = (await db.execute(select(SlDesigner))).scalars().all()
    by_name: dict[str, SlDesigner] = {}
    for d in designers:
        by_name.setdefault((d.name or "").strip(), d)

    for src in rows:
        row = order_to_local(src)
        uid = row["upstream_id"]

        if uid in existing_upstream:
            result.skipped.append({
                "upstream_id": uid,
                "order_no": row["order_no"],
                "reason": "已导入过（按上游 ID 去重）",
            })
            continue

        issues = check_order_importable(row)
        if issues and only_valid:
            result.skipped.append({
                "upstream_id": uid,
                "order_no": row["order_no"],
                "reason": "；".join(issues),
            })
            continue

        designer = by_name.get(row["designer_name"])
        designer_id = designer.id if designer else None
        if designer is None and row["designer_name"]:
            issues.append(f"本地没有找到设计师「{row['designer_name']}」，"
                          "订单导入后处于「未派单」状态，请先导入设计师")

        order = SlOrder(**row, designer_id=designer_id, audit_status="pending")
        db.add(order)
        await db.flush()

        existing_upstream.add(uid)
        result.created.append({
            "id": order.id,
            "upstream_id": uid,
            "order_no": row["order_no"],
            "state": row["state"],
            "commission": str(row["designer_commission"]),
            "designer_matched": designer is not None,
            "issues": issues,
        })

    return result


# ---------------------------------------------------------------------------
# 本地演示数据源
# ---------------------------------------------------------------------------
#
# 上游是生产系统，不是随时能连的。为了让「两系统互通」这条链路
# 在本地能完整跑通（演示、教学、回归测试），这里提供一份**假上游**：
# 设 ``SETTLE_FAKE_UPSTREAM=1`` 就启用，数据是照着真实上游的字段形状造的。
#
# **假数据故意带了各种问题**（9 位手机号、停用、禁结算、比例越界、
# 查无此人的设计师），这样预览页上的「可否导入 / 问题」两列才有东西可看。
#
# 不设这个环境变量时，一切照常走真实上游。

#: 假上游的启用开关
ENV_FAKE_UPSTREAM = "SETTLE_FAKE_UPSTREAM"


def fake_upstream_enabled() -> bool:
    """是否启用了本地演示数据源。"""
    return os.getenv(ENV_FAKE_UPSTREAM, "").strip().lower() in ("1", "true", "yes", "on")


def fake_designers() -> list[UpstreamDesigner]:
    """假上游的设计师列表 —— 刻意包含各种问题情况。"""
    return [
        UpstreamDesigner(id=90001, name="陈富灿", nickname="小陈",
                         phone="17737706163", alipay_account="17737706163@qq.com",
                         war_zone="独角兽", production_level="标准档次",
                         recruitment_source="其他", hr_name="若暖",
                         allow_settlement=1, status=1, designer_type=1),
        UpstreamDesigner(id=90002, name="林小雨", nickname="小雨",
                         phone="13800138002", alipay_account="13800138002@qq.com",
                         war_zone="", production_level="精英档次",
                         recruitment_source="猎头", hr_name="若暖",
                         allow_settlement=1, status=1, designer_type=2),
        # 手机号只有 9 位 → 格式不对，导不了
        UpstreamDesigner(id=90003, name="赵短号", nickname="短号",
                         phone="123456789", alipay_account="x@y.com",
                         war_zone="", production_level="标准档次",
                         recruitment_source="其他", allow_settlement=1,
                         status=1, designer_type=1),
        # 上游已停用
        UpstreamDesigner(id=90004, name="王离职", nickname="老王",
                         phone="13800138004", alipay_account="w@y.com",
                         war_zone="", production_level="标准档次",
                         recruitment_source="内推", allow_settlement=1,
                         status=0, designer_type=1),
        # 上游禁止结算
        UpstreamDesigner(id=90005, name="孙禁结", nickname="孙",
                         phone="13800138005", alipay_account="s@y.com",
                         war_zone="", production_level="标准档次",
                         recruitment_source="其他", allow_settlement=0,
                         status=1, designer_type=1),
    ]


def fake_orders() -> list[UpstreamOrder]:
    """假上游的订单列表 —— 同样刻意带问题。"""
    return [
        UpstreamOrder(id=80001, sn="SN-2026-001", order_sn="ORD-2026-001",
                      order_desc="按客户模板改 10 页 PPT",
                      customer_name="tb125212883", store_account="tb125212883",
                      war_zone_name="独角兽", designer_id=90001,
                      designer_name="陈富灿", user_name="若暖",
                      customer_service="若暖", order_grade="PPT定制",
                      order_type=0, status=5,
                      order_commission=Decimal("100.00"),
                      designer_commission=Decimal("60.00"),
                      hr_commission=Decimal("20.00"),
                      quality_control_commission=Decimal("10.00"),
                      middle_control_commission=Decimal("10.00"),
                      design_supervisor_bonus=Decimal("5.00"),
                      request_delivery_time="2026-11-01",
                      order_time="2026-10-20", created_at="2026-10-20 10:00:00"),
        UpstreamOrder(id=80002, sn="SN-2026-002", order_sn="ORD-2026-002",
                      order_desc="旧规则下的单，比例低于下限",
                      customer_name="tb999888", designer_id=90001,
                      designer_name="陈富灿", order_grade="PPT定制",
                      order_type=0, status=5,
                      order_commission=Decimal("100.00"),
                      designer_commission=Decimal("30.00"),
                      order_time="2026-10-21", created_at="2026-10-21 09:00:00"),
        UpstreamOrder(id=80003, sn="SN-2026-003", order_sn="ORD-2026-003",
                      order_desc="查无此人的单",
                      customer_name="tb777777", designer_name="不存在的人",
                      order_grade="PPT定制", order_type=0, status=9,
                      order_commission=Decimal("200.00"),
                      designer_commission=Decimal("120.00"),
                      order_time="2026-10-22", created_at="2026-10-22 15:00:00"),
        UpstreamOrder(id=80004, sn="SN-2026-004", order_sn="ORD-2026-004",
                      order_desc="终稿制作中的单",
                      customer_name="tb666666", designer_id=90002,
                      designer_name="林小雨", order_grade="PPT定制",
                      order_type=0, status=2,
                      order_commission=Decimal("300.00"),
                      designer_commission=Decimal("180.00"),
                      order_time="2026-10-23", created_at="2026-10-23 11:00:00"),
    ]


class FakeUpstreamClient:
    """假上游客户端 —— 接口签名跟 :class:`TrcipgClient` 一致。

    存在的意义只有一个：**让互通链路在本地能完整跑通**，
    不必为了演示而依赖生产系统在线。
    """

    async def list_designer_detail(self, page: int = 1, num: int = 50,
                                   member_type: int = 1) -> tuple[list[UpstreamDesigner], int]:
        rows = fake_designers()
        return rows[:num], len(rows)

    async def list_orders(self, page: int = 1, num: int = 50,
                          **kw: Any) -> tuple[list[UpstreamOrder], int]:
        rows = fake_orders()
        return rows[:num], len(rows)
