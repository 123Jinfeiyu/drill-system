"""设计师结算系统 · 规则核心。

这个模块只放**规则**，不放流程：佣金比例怎么算、什么条件下能结算、
订单状态怎么流转、哪些字段必填、异常怎么识别、删除允不允许。
全部是纯函数，不依赖数据库、不依赖 FastAPI —— 规则只有一份实现，
单测、HTTP 路由、命令行三方共用。

规则来源是《数字结算系统操作指南》课件画面，逐条对应：
- 模块二：录入设计师信息（必填项、战区/HR 留空、临时密码）
- 模块三：登记新订单（客户ID、佣金 50%-70%、订单编号后补、订单类型）
- 模块四：订单流程管理（节点一补编号、节点二两类截图）
- 模块五：异常处理（六类异常、退款删除规则）
- 模块六：设计师结算条件（60 天有效期、每月 8-9 号窗口、主动触发）

三条纪律：

1. **规则不写死在路由里**。路由只调这里，规则改动只改一个文件。
2. **金额一律 Decimal**。上游给的是字符串，float 在结算场景会差一分钱，
   而一分钱在结算场景就是事故。
3. **拒绝要给出可执行的下一步**，不能只说「不合法」。课件里反复强调
   「查看系统提示的具体报错原因」，所以每条 issue 都带建议动作。
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.core import timeutil

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 设计师佣金比例下限（课件：通常 50%）
COMMISSION_RATE_MIN = Decimal("0.50")

#: 设计师佣金比例上限（课件：最高 70%，超出需变动协议）
COMMISSION_RATE_MAX = Decimal("0.70")

#: 订单接单后多久内还能进入结算（课件：接单时间需在两个月内）
SETTLE_VALID_DAYS = 60

#: 每月开放结算的日期（课件：每月 8 日-9 日开放结算）
SETTLE_WINDOW_DAYS: tuple[int, ...] = (8, 9)

#: 每月统一打款日（课件：每月 15 号为统一打款日）
PAYOUT_DAY = 15

#: 派单员需在每月此日之前提醒设计师（课件：每月 7 日前提醒）
REMIND_DAY = 7

#: 金额保留两位
MONEY_EXP = Decimal("0.01")

#: 订单编号格式：至少 6 位，允许数字与字母（真系统订单号是 20 位数字，
#: 但课件只说「确保编号唯一对应」，所以这里只做**非空 + 基本格式**校验，
#: 不做长度硬限制 —— 硬限制会把合法但特殊的编号挡在门外）。
ORDER_NO_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,64}$")

#: 客户 ID 只做非空 + 去空白校验。
#:
#: **刻意不做模糊匹配** —— 课件反复强调「务必与名称完全一致，
#: 避免错别字或字符，否则无法关联到对应客户信息」。
#: 系统若偷偷帮用户「纠正」客户 ID，错误就会被永久固化，反倒更糟。
CUSTOMER_ID_PATTERN = re.compile(r"^.{2,128}$")


# ---------------------------------------------------------------------------
# 订单状态机
# ---------------------------------------------------------------------------

#: 本地订单状态。
#:
#: **与上游真实状态字典一一对应**，这样两套系统才能真正互通：
#: 上游 ``/settlement/order/list`` 返回的 ``status`` 字段是
#: 1初稿制作中 / 2终稿制作中 / 3已交付 / 4验收中 / 5验收成功 /
#: 6问题待处理 / 7问题处理中 / 8问题待审核 / 9已完结。
#: 本地多一个 ``pending_design``（设计待定），因为课件要求
#: 「订单登记后先派单再开工」，这一步上游没有单独状态。
ORDER_STATES: tuple[str, ...] = (
    "pending_design",   # 设计待定（待派单）
    "drafting",         # 初稿制作中
    "finalizing",       # 终稿制作中
    "pending_audit",    # 待审核（已交付，等验收）
    "settleable",       # 可结算（验收通过）
    "settling",         # 结算中
    "settled",          # 已结算
    "rejected",         # 审核驳回（回到 finalizing 改终稿）
    "canceled",         # 已取消
)

#: 主线状态（漏斗按这个顺序展示）
ORDER_MAINLINE: tuple[str, ...] = (
    "pending_design", "drafting", "finalizing",
    "pending_audit", "settleable", "settling", "settled",
)

#: 允许的流转。跳阶段一律不允许 —— 结算前面必须先验收。
ORDER_TRANSITIONS: Mapping[str, tuple[str, ...]] = {
    "pending_design": ("drafting", "canceled"),
    "drafting": ("finalizing", "pending_design", "canceled"),
    "finalizing": ("pending_audit", "drafting", "canceled"),
    "pending_audit": ("settleable", "rejected", "canceled"),
    "rejected": ("finalizing", "canceled"),
    "settleable": ("settling", "pending_audit", "canceled"),
    "settling": ("settled", "settleable"),
    "settled": (),
    "canceled": (),
}

#: 本地状态 → 上游 ``status`` 字典值。
#:
#: 互通时按这张表双向翻译。注意上游 3已交付 与 4验收中 在本地
#: 都落在 ``pending_audit``（本地是「已交付待验收」一个状态，
#: 上游把「已交付」和「验收中」拆成两态），上游 6/7 问题处理
#: 与 8 问题待审核 都落在 ``finalizing``（本地是「终稿返工中」）。
UPSTREAM_STATUS_TO_LOCAL: Mapping[int, str] = {
    1: "drafting",        # 初稿制作中
    2: "finalizing",      # 终稿制作中
    3: "pending_audit",   # 已交付
    4: "pending_audit",   # 验收中
    5: "settleable",      # 验收成功
    6: "finalizing",      # 问题待处理 → 终稿返工
    7: "finalizing",      # 问题处理中 → 终稿返工
    8: "finalizing",      # 问题待审核 → 终稿返工
    9: "settled",         # 已完结
}

#: 上游状态 → 本地状态（反向表）
LOCAL_TO_UPSTREAM_STATUS: Mapping[str, int] = {
    "pending_design": 1,   # 本地独有，回写时按「初稿制作中」处理
    "drafting": 1,
    "finalizing": 2,
    "pending_audit": 3,
    "settleable": 5,
    "settling": 5,         # 结算中上游仍是「验收成功」
    "settled": 9,
    "rejected": 6,         # 驳回对应「问题待处理」
    "canceled": 9,
}

#: 上游 ``status`` 字典的中文名（实测自结算端 ``$status`` 数组）。
#:
#: 与 ``app.services.trcipg_client.UPSTREAM_ORDER_STATUS`` 内容一致，
#: 这里单独存一份，是为了让**规则层不依赖上游适配器** ——
#: 规则层可以被单测直接调用，不该为了取几个标签把网络层拖进来。
UPSTREAM_STATUS_LABELS: Mapping[int, str] = {
    1: "初稿制作中",
    2: "终稿制作中",
    3: "已交付",
    4: "验收中",
    5: "验收成功",
    6: "问题待处理",
    7: "问题处理中",
    8: "问题待审核",
    9: "已完结",
}

STATE_LABELS: Mapping[str, str] = {
    "pending_design": "设计待定",
    "drafting": "初稿制作中",
    "finalizing": "终稿制作中",
    "pending_audit": "待审核",
    "settleable": "可结算",
    "settling": "结算中",
    "settled": "已结算",
    "rejected": "审核驳回",
    "canceled": "已取消",
}

#: 订单类型（课件：个人接单 / 内部协作 / 外部合作）
ORDER_TYPES: Mapping[str, str] = {
    "personal": "个人接单",
    "internal": "内部协作",
    "external": "外部合作",
}

#: 制作水平（真系统 teamMembers.production_level 的值域）
PRODUCTION_LEVELS: tuple[str, ...] = (
    "首席档次", "高端档次", "精美档次",
    "标准档次", "一般档次", "简单档次",
)

#: 性别
GENDERS: Mapping[int, str] = {0: "未知", 1: "男", 2: "女"}

#: 招聘来源（真系统 teamMembers.recruitment_source 的常见值）
RECRUITMENT_SOURCES: tuple[str, ...] = (
    "其他", "BOSS直聘", "智联招聘", "前程无忧",
    "猎聘", "内推", "学生兼职", "转介绍",
)


def state_label(state: str) -> str:
    return STATE_LABELS.get(state, state)


def next_states(state: str) -> tuple[str, ...]:
    return ORDER_TRANSITIONS.get(state, ())


def can_transition(src: str, dst: str) -> bool:
    return dst in next_states(src)


def is_terminal(state: str) -> bool:
    return state in ("settled", "canceled")


def order_type_label(value: str) -> str:
    return ORDER_TYPES.get(value, value)


def local_state_from_upstream(status: int) -> str:
    """上游 ``status`` → 本地状态。

    未知状态一律落 ``pending_audit``（保守处理）：
    宁可让订单停住等人看一眼，也不要猜成「已完结」把账结错。
    """
    return UPSTREAM_STATUS_TO_LOCAL.get(int(status or 0), "pending_audit")


def upstream_status_from_local(state: str) -> int:
    """本地状态 → 上游 ``status``。"""
    return LOCAL_TO_UPSTREAM_STATUS.get(str(state or ""), 3)


def local_state_label(state: str) -> str:
    """本地状态的中文名（对外输出一份，避免各处自己拼）。"""
    return state_label(state)


# ---------------------------------------------------------------------------
# 金额工具
# ---------------------------------------------------------------------------


def to_decimal(value: Any, default: Decimal | None = None) -> Decimal | None:
    """把任意输入安全转成 Decimal。

    - None / 空串 → default
    - 带 ¥ 与千分位逗号的字符串 → 剥掉再转
    - 非法值 → default（**不抛异常**，脏数据不该让整个页面挂掉）
    """
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        # float 已经丢了精度，只能尽量还原；真正该避免的是上游传 float
        return Decimal(str(value))
    text = str(value).strip().replace("¥", "").replace(",", "").replace("元", "")
    if text.startswith("+"):
        text = text[1:]
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return default


def quantize_money(value: Decimal) -> Decimal:
    """金额统一保留两位，四舍五入（ROUND_HALF_UP）。"""
    return value.quantize(MONEY_EXP, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 佣金核算
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CommissionResult:
    """一次佣金核算的结果。"""

    ok: bool
    amount: Decimal = Decimal("0")
    rate: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "amount": str(self.amount),
            "rate": str(self.rate),
            "commission": str(self.commission),
            "issues": list(self.issues),
        }


def validate_commission_rate(rate: Any) -> list[str]:
    """校验佣金比例是否在 [50%, 70%]。

    课件原话：「通常为整体项目金额的 50%，最高上限为 70%，
    超出比例须有变动协议，需重新核算」——
    所以越界是**硬拒绝**，不是提醒。
    """
    issues: list[str] = []
    value = to_decimal(rate)
    if value is None:
        return ["佣金比例未填写"]
    if value <= 0:
        return ["佣金比例必须大于 0"]
    if value < COMMISSION_RATE_MIN:
        issues.append(
            f"佣金比例 {value * 100:.0f}% 低于下限 {COMMISSION_RATE_MIN * 100:.0f}%，"
            "请按整体项目金额的 50% 重新核算"
        )
    if value > COMMISSION_RATE_MAX:
        issues.append(
            f"佣金比例 {value * 100:.0f}% 超出上限 {COMMISSION_RATE_MAX * 100:.0f}%，"
            "超出部分须有变动协议，请重新核算后再提交"
        )
    return issues


def calc_commission(amount: Any, rate: Any) -> CommissionResult:
    """按金额与比例算设计师佣金，同时做比例校验。

    比例越界 → ``ok=False`` 且**不产出金额**。
    这点很重要：越界的比例算出来的钱也是错的，
    宁可不算，也不要算出一个看着能用的错数。
    """
    issues = validate_commission_rate(rate)
    amount_dec = to_decimal(amount, Decimal("0")) or Decimal("0")
    rate_dec = to_decimal(rate, Decimal("0")) or Decimal("0")
    if issues:
        return CommissionResult(ok=False, amount=amount_dec, rate=rate_dec,
                                commission=Decimal("0"), issues=issues)
    commission = quantize_money(amount_dec * rate_dec)
    return CommissionResult(ok=True, amount=amount_dec, rate=rate_dec,
                            commission=commission, issues=[])


# ---------------------------------------------------------------------------
# 设计师录入校验（模块二）
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FieldIssue:
    """一条字段级问题。"""

    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


def validate_designer(payload: Mapping[str, Any]) -> list[FieldIssue]:
    """校验设计师录入表单。

    课件必填项：「姓名、花名、手机号、支付宝账户、性别、招聘来源、
    制作水平及登录密码」。

    课件核心注意：「所属战区」和「所属HR」字段**保持为空，切勿填写任何内容**
    —— 所以这两项不是「必填」，而是「**必须为空**」，非空直接报错。
    """
    issues: list[FieldIssue] = []

    required = {
        "name": "姓名",
        "nickname": "花名",
        "phone": "手机号",
        "alipay_account": "支付宝账户",
        "recruitment_source": "招聘来源",
        "production_level": "制作水平",
        "password": "登录密码",
    }
    for key, label in required.items():
        value = str(payload.get(key) or "").strip()
        if not value:
            issues.append(FieldIssue(key, f"{label}为必填项，请填写"))
        elif key == "password" and len(value) < 6:
            issues.append(FieldIssue(key, "登录密码不能少于 6 位"))

    phone = str(payload.get("phone") or "").strip()
    if phone and not re.fullmatch(r"1[3-9]\d{9}", phone):
        issues.append(FieldIssue("phone", "手机号格式不正确，应为 11 位数字"))

    alipay = str(payload.get("alipay_account") or "").strip()
    if alipay and len(alipay) < 4:
        issues.append(FieldIssue("alipay_account", "支付宝账户过短，请核对收款账号"))

    gender = payload.get("gender")
    if gender is not None and str(gender) not in ("0", "1", "2"):
        issues.append(FieldIssue("gender", "性别取值无效"))

    level = str(payload.get("production_level") or "").strip()
    if level and level not in PRODUCTION_LEVELS:
        issues.append(FieldIssue(
            "production_level",
            f"制作水平取值「{level}」不在标准档次列表内，请确认"
        ))

    source = str(payload.get("recruitment_source") or "").strip()
    if source and source not in RECRUITMENT_SOURCES:
        issues.append(FieldIssue(
            "recruitment_source",
            f"招聘来源「{source}」不在标准来源列表内，可用："
            + "、".join(RECRUITMENT_SOURCES)
        ))

    # 课件核心注意：所属战区 / 所属HR 必须留空
    war_zone = str(payload.get("war_zone") or "").strip()
    if war_zone:
        issues.append(FieldIssue(
            "war_zone",
            "「所属战区」必须保持为空，切勿填写任何内容。请清空后重新提交"
        ))
    hr_id = str(payload.get("hr_id") or "").strip()
    if hr_id:
        issues.append(FieldIssue(
            "hr_id",
            "「所属HR」必须保持为空，切勿填写任何内容。请清空后重新提交"
        ))

    return issues


# ---------------------------------------------------------------------------
# 订单登记校验（模块三）
# ---------------------------------------------------------------------------


def validate_order(payload: Mapping[str, Any]) -> list[FieldIssue]:
    """校验订单登记表单。

    课件模块三的字段要求：
    - 客户 ID：必填，与平台名称完全一致
    - 所属战区：必填（订单归属的企业或战区标识）
    - 对接客服：必填（真实姓名）
    - 订单类型：必填三选一
    - 订单金额：必填
    - 佣金比例：必填且 50%-70%
    - 交付时间：必填
    - 订单编号：**不必填**（初稿完成后补录）
    """
    issues: list[FieldIssue] = []

    customer_id = str(payload.get("customer_id") or "").strip()
    if not customer_id:
        issues.append(FieldIssue(
            "customer_id",
            "客户 ID 是订单追溯的唯一凭证，必须填写，且要与平台名称完全一致"
        ))
    elif not CUSTOMER_ID_PATTERN.fullmatch(customer_id):
        issues.append(FieldIssue("customer_id", "客户 ID 格式无效"))

    if not str(payload.get("war_zone") or "").strip():
        issues.append(FieldIssue("war_zone", "所属战区为必填项，请选择订单归属的战区"))

    if not str(payload.get("customer_service") or "").strip():
        issues.append(FieldIssue("customer_service", "对接客服为必填项，请填写真实姓名"))

    order_type = str(payload.get("order_type") or "").strip()
    if not order_type:
        issues.append(FieldIssue(
            "order_type", "订单类型为必填项：个人接单 / 内部协作 / 外部合作"
        ))
    elif order_type not in ORDER_TYPES:
        issues.append(FieldIssue(
            "order_type", f"订单类型「{order_type}」无效，可选："
            + "、".join(ORDER_TYPES.values())
        ))

    amount = to_decimal(payload.get("order_amount"))
    if amount is None or amount <= 0:
        issues.append(FieldIssue("order_amount", "订单金额必须大于 0"))

    if not str(payload.get("deliver_date") or "").strip():
        issues.append(FieldIssue("deliver_date", "交付时间为必填项，这是订单排期与考核的依据"))

    # 佣金比例
    rate_issues = validate_commission_rate(payload.get("commission_rate"))
    for text in rate_issues:
        issues.append(FieldIssue("commission_rate", text))

    # 订单编号可以不填，但要校验格式（填了就必须合法）
    order_no = str(payload.get("order_no") or "").strip()
    if order_no and not ORDER_NO_PATTERN.fullmatch(order_no):
        issues.append(FieldIssue(
            "order_no",
            "订单编号格式不正确（至少 6 位，仅限字母数字下划线短横），"
            "请找客服确认后再填写"
        ))

    return issues


# ---------------------------------------------------------------------------
# 状态流转门禁（模块四）
# ---------------------------------------------------------------------------


def check_transition(order: Mapping[str, Any], to_state: str) -> list[str]:
    """校验一次状态流转是否允许，并检查该节点的必填材料。

    模块四两个节点：
    - 节点一（初稿完成 → 终稿制作中）：必须已填**订单编号**
    - 节点二（终稿完成 → 待审核）：必须上传**两类截图**
      （终稿通过聊天记录截图 + 交付文件截图）

    **编号只有一个字段** ``order_no``。早期版本这里另设了 ``draft_no``，
    跟 ``order_no`` 存的是同一件事（都是「订单编号」），
    结果就是补了编号、诊断却仍报「缺少订单编号」——
    两个字段各说各话，规则永远对不上。现在统一到 ``order_no``。
    """
    issues: list[str] = []
    src = str(order.get("state") or "")

    if not can_transition(src, to_state):
        allowed = "、".join(state_label(s) for s in next_states(src))
        issues.append(
            f"不能从「{state_label(src)}」直接流转到「{state_label(to_state)}」，"
            f"当前只能流转到：{allowed or '（终态，无出路）'}"
        )
        return issues

    if to_state == "finalizing":
        # 节点一：初稿完成后更新订单编号
        order_no = str(order.get("order_no") or "").strip()
        if not order_no:
            issues.append(
                "进入「终稿制作中」前必须填写订单编号："
                "请联系客服获取专属编号后填写，初稿确认前不得留空"
            )
        elif not ORDER_NO_PATTERN.fullmatch(order_no):
            issues.append("订单编号格式不正确，请核对后重新填写")

    if to_state == "pending_audit":
        # 节点二：终稿完成后的交付验收 —— 两类截图缺一不可
        chat = str(order.get("chat_screenshot") or "").strip()
        file_shot = str(order.get("file_screenshot") or "").strip()
        if not chat:
            issues.append(
                "进入「待审核」前必须上传「终稿通过」的聊天记录截图，"
                "这是终稿验收的必要材料"
            )
        if not file_shot:
            issues.append(
                "进入「待审核」前必须上传交付文件截图"
                "（需包含群名、成员、交付画面）"
            )

    if to_state == "settleable":
        # 审核通过 → 可结算，但要检查结算前置条件
        issues.extend(check_settle_eligibility(order))

    return issues


# ---------------------------------------------------------------------------
# 结算条件（模块六）
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SettleWindow:
    """当前是否处于结算窗口。"""

    open: bool
    today: str
    open_days: list[int]
    next_open: str
    days_until_open: int
    payout_day: int
    days_until_payout: int
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "open": self.open,
            "today": self.today,
            "open_days": list(self.open_days),
            "next_open": self.next_open,
            "days_until_open": self.days_until_open,
            "payout_day": self.payout_day,
            "days_until_payout": self.days_until_payout,
            "message": self.message,
        }


def parse_date(value: Any) -> date | None:
    """把各种日期输入解析成 date。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    return None


def settle_window(today: date | None = None) -> SettleWindow:
    """计算当前结算窗口。

    课件：「系统每月仅在 8 日跟 9 日 开放结算入口，
    这是一个临时的操作窗口，逾期入口将自动关闭」。
    """
    today = today or timeutil.today()
    is_open = today.day in SETTLE_WINDOW_DAYS

    # 找下一个开放日
    next_open = today
    if today.day in SETTLE_WINDOW_DAYS:
        next_open_text = f"{today.year}-{today.month:02d}-{today.day:02d}（今天开放）"
        days_until = 0
    else:
        # 往后找第一个开放日，每往后一天就 +1。
        # 初值必须是 0 —— 写成 1 会把「7 号到 8 号」算成 2 天。
        days_until = 0
        probe = today
        while probe.day not in SETTLE_WINDOW_DAYS:
            probe += timedelta(days=1)
            days_until += 1
        next_open_text = f"{probe.year}-{probe.month:02d}-{probe.day:02d}"

    # 距 15 号打款日
    if today.day <= PAYOUT_DAY:
        days_to_payout = PAYOUT_DAY - today.day
    else:
        next_month_first = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        days_to_payout = (next_month_first - today).days + PAYOUT_DAY - 1

    if is_open:
        message = (f"今天是 {today.month} 月 {today.day} 日，结算窗口开放中，"
                   "可在结算端点击「一键结算」发起")
    else:
        message = (f"结算入口仅每月 {SETTLE_WINDOW_DAYS[0]} 日-{SETTLE_WINDOW_DAYS[-1]} 日开放，"
                   f"当前 {today.month} 月 {today.day} 日未开放，"
                   f"下次开放：{next_open_text}")

    return SettleWindow(
        open=is_open,
        today=today.isoformat(),
        open_days=list(SETTLE_WINDOW_DAYS),
        next_open=next_open_text,
        days_until_open=days_until,
        payout_day=PAYOUT_DAY,
        days_until_payout=days_to_payout,
        message=message,
    )


def check_settle_eligibility(order: Mapping[str, Any],
                             today: date | None = None) -> list[str]:
    """检查一条订单能不能进入结算。

    课件：「订单的接单时间必须是在两个月有效期内，超出该时间内的订单
    无法进入结算流程」。
    """
    issues: list[str] = []
    today = today or timeutil.today()
    order_date = parse_date(order.get("order_date"))
    if order_date is None:
        issues.append("订单缺少接单时间，无法判断结算有效期")
        return issues

    deadline = order_date + timedelta(days=SETTLE_VALID_DAYS)
    if today > deadline:
        issues.append(
            f"订单接单时间 {order_date.isoformat()} 已超过两个月有效期"
            f"（截止 {deadline.isoformat()}），无法进入结算流程。"
            "如需结算请联系客服处理"
        )
    return issues


def settle_eligible_orders(orders: Iterable[Mapping[str, Any]],
                           today: date | None = None) -> list[dict[str, Any]]:
    """筛出可结算的订单，并说明每条为什么行 / 为什么不行。

    返回的每条都带 ``eligible`` 与 ``reasons``，
    前端直接显示，不需要再算一遍。
    """
    today = today or timeutil.today()
    result: list[dict[str, Any]] = []
    for order in orders:
        reasons = check_settle_eligibility(order, today)
        state = str(order.get("state") or "")
        if state != "settleable":
            reasons.append(f"订单当前状态是「{state_label(state)}」，需先审核通过")
        result.append({
            "order_id": order.get("id"),
            "order_no": order.get("order_no"),
            "designer_name": order.get("designer_name"),
            "commission": str(order.get("designer_commission") or "0"),
            "eligible": not reasons,
            "reasons": reasons,
        })
    return result


# ---------------------------------------------------------------------------
# 异常诊断（模块五）
# ---------------------------------------------------------------------------

#: 六大常见异常的定义（课件原文）
EXCEPTION_CASES: tuple[tuple[str, str], ...] = (
    ("amount_mismatch", "订单金额不符"),
    ("order_no_missing", "订单号不存在"),
    ("draft_no_missing", "缺少订单编号"),
    ("business_scope", "商务口径单"),
    ("commission_mismatch", "设计师佣金不符"),
    ("draft_unconfirmed", "未确认稿件"),
)


def diagnose_order(order: Mapping[str, Any],
                   expected_amount: Any = None) -> list[dict[str, str]]:
    """诊断一条订单可能存在的异常，返回逐条问题与处理方案。

    课件给的通用处理原则：
    1. 查看系统提示的具体报错原因
    2. 对照解决方案自查是否正确
    3. 疑难问题联系客服或系统管理员

    所以每条问题都带 ``action``（怎么处理）。
    """
    issues: list[dict[str, str]] = []

    def add(kind: str, message: str, action: str) -> None:
        label = dict(EXCEPTION_CASES).get(kind, kind)
        issues.append({"kind": kind, "label": label, "message": message, "action": action})

    # 1. 订单金额不符
    actual = to_decimal(order.get("order_amount"))
    expected = to_decimal(expected_amount)
    if actual is not None and expected is not None and actual != expected:
        add("amount_mismatch",
            f"订单金额 {actual} 与客户确认金额 {expected} 不一致",
            "核对原始需求单；差额需客户确认后修正金额，切勿直接改佣金比例抹平")

    # 2. 订单号不存在
    order_no = str(order.get("order_no") or "").strip()
    if order_no and not ORDER_NO_PATTERN.fullmatch(order_no):
        add("order_no_missing",
            f"订单编号「{order_no}」格式不合法，系统无法定位对应订单",
            "找客服拿真实订单编号后在订单详情页更正")

    # 3. 缺少订单编号
    if not order_no:
        add("draft_no_missing",
            "订单尚未填写编号",
            "初稿完成后在订单详情页补录订单编号；补录前无法提交终稿审核")

    # 4. 商务口径单：内部协作单必须指定归属战区，否则结不了
    if str(order.get("order_type") or "") == "internal" and not str(
            order.get("war_zone") or "").strip():
        add("business_scope",
            "内部协作单未指定归属战区，结算主体无法确定",
            "补选订单归属的战区；内部协作单必须先有归属才能进入结算")

    # 5. 设计师佣金不符
    rate = to_decimal(order.get("commission_rate"))
    if rate is not None and not (COMMISSION_RATE_MIN <= rate <= COMMISSION_RATE_MAX):
        add("commission_mismatch",
            f"佣金比例 {rate * 100:.0f}% 不在 50%-70% 区间内",
            "按 50%-70% 重新核算；确需超出须先拿到变动协议")
    else:
        commission = to_decimal(order.get("designer_commission"))
        if rate is not None and actual is not None and commission is not None:
            expected_commission = quantize_money(actual * rate)
            if commission != expected_commission:
                add("commission_mismatch",
                    f"佣金金额 {commission} 与「金额 × {rate * 100:.0f}%」"
                    f"= {expected_commission} 对不上",
                    "以订单金额和佣金比例为准重新核算佣金")

    # 6. 未确认稿件
    chat = str(order.get("chat_screenshot") or "").strip()
    file_shot = str(order.get("file_screenshot") or "").strip()
    missing: list[str] = []
    if not chat:
        missing.append("终稿通过聊天记录截图")
    if not file_shot:
        missing.append("交付文件截图")
    if missing:
        add("draft_unconfirmed",
            "缺少交付材料：" + "、".join(missing),
            "让设计师补齐两类截图后提交终稿验收")

    return issues


#: 删除规则（课件：按订单状态区分）
#: 制作中 → 可直接删除；已交付 → 需联系客服
#:
#: 「制作中」在本系统里包含初稿制作中与终稿制作中两种 ——
#: 都还没交付，随时可以撤单。已交付及以后一律不许直接删。
DELETABLE_STATES: tuple[str, ...] = (
    "pending_design", "drafting", "finalizing", "rejected",
)


def check_deletable(order: Mapping[str, Any]) -> tuple[bool, str]:
    """能不能直接删除这条订单。

    课件：「制作中：可直接点击『删除订单』；已交付：需联系客服协助处理；
    注意：退款务必小心确认订单状态」。

    所以已过审核的、结算中的、已结算的，一律**不许直接删**。
    """
    state = str(order.get("state") or "")
    if state in DELETABLE_STATES:
        return True, ""
    if state == "pending_audit":
        return False, "订单已提交审核，删除需先撤回审核或联系客服处理"
    if state in ("settleable", "settling", "settled"):
        return False, "订单已进入结算流程，删除会造成账目不平，须联系客服处理"
    return False, f"当前状态「{state_label(state)}」不支持直接删除，请联系客服处理"


# ---------------------------------------------------------------------------
# 看板统计
# ---------------------------------------------------------------------------


def order_funnel(orders: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """订单漏斗：每个状态的订单数与金额。"""
    buckets: dict[str, dict[str, Any]] = {}
    for state in ORDER_MAINLINE:
        buckets[state] = {"state": state, "label": state_label(state),
                          "count": 0, "amount": Decimal("0")}
    for order in orders:
        state = str(order.get("state") or "")
        if state not in buckets:
            continue
        buckets[state]["count"] += 1
        buckets[state]["amount"] += to_decimal(order.get("order_amount"), Decimal("0")) or Decimal("0")
    rows = []
    for state in ORDER_MAINLINE:
        row = buckets[state]
        row["amount"] = str(quantize_money(row["amount"]))
        rows.append(row)
    return rows


def remind_designers(
    orders: Sequence[Mapping[str, Any]],
    designers: Sequence[Mapping[str, Any]],
    today: date | None = None,
) -> list[dict[str, Any]]:
    """算「待提醒设计师」清单。

    课件：「务必在每月 7 日前向团队设计师单独结算窗口（8-9 日），
    提醒大家准时登录系统完成操作，避免因错过时间导致佣金结算延迟或失效」。

    规则：名下有**可结算但未结算**订单的设计师，都要提醒。
    """
    today = today or timeutil.today()
    designer_map = {str(d.get("id")): d for d in designers}

    pending: dict[str, dict[str, Any]] = {}
    for order in orders:
        if str(order.get("state") or "") != "settleable":
            continue
        did = str(order.get("designer_id") or "")
        if not did:
            continue
        entry = pending.setdefault(did, {
            "designer_id": did,
            "designer_name": str(order.get("designer_name") or ""),
            "phone": str((designer_map.get(did) or {}).get("phone") or ""),
            "order_count": 0,
            "commission": Decimal("0"),
            "earliest_order_date": "",
            "expired": False,
        })
        entry["order_count"] += 1
        entry["commission"] += to_decimal(order.get("designer_commission"), Decimal("0")) or Decimal("0")
        order_date = str(order.get("order_date") or "")
        if order_date and (not entry["earliest_order_date"] or order_date < entry["earliest_order_date"]):
            entry["earliest_order_date"] = order_date
        if check_settle_eligibility(order, today):
            entry["expired"] = True

    rows = []
    for entry in pending.values():
        entry["commission"] = str(quantize_money(entry["commission"]))
        # 越早的越早提醒 —— 按最早接单时间排
        rows.append(entry)
    rows.sort(key=lambda r: (r["earliest_order_date"] or "9999", r["designer_name"]))
    return rows


def settlement_summary(settlements: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """结算汇总：待打款 / 已打款金额与笔数。"""
    pending_count = 0
    pending_amount = Decimal("0")
    paid_count = 0
    paid_amount = Decimal("0")
    invalid_count = 0
    by_designer: dict[str, dict[str, Any]] = {}

    for row in settlements:
        status = str(row.get("status") or "")
        amount = to_decimal(row.get("commission"), Decimal("0")) or Decimal("0")
        if status == "paid":
            paid_count += 1
            paid_amount += amount
        elif status == "invalid":
            invalid_count += 1
        else:
            pending_count += 1
            pending_amount += amount
        name = str(row.get("designer_name") or "")
        entry = by_designer.setdefault(name, {"designer_name": name, "count": 0,
                                               "amount": Decimal("0")})
        entry["count"] += 1
        entry["amount"] += amount

    rows = []
    for entry in by_designer.values():
        entry["amount"] = str(quantize_money(entry["amount"]))
        rows.append(entry)
    rows.sort(key=lambda r: Decimal(r["amount"]), reverse=True)

    return {
        "pending_count": pending_count,
        "pending_amount": str(quantize_money(pending_amount)),
        "paid_count": paid_count,
        "paid_amount": str(quantize_money(paid_amount)),
        "invalid_count": invalid_count,
        "by_designer": rows,
    }


# ---------------------------------------------------------------------------
# 字典（前端下拉用）
# ---------------------------------------------------------------------------


def dictionaries() -> dict[str, Any]:
    """全部字典，一次给全，前端不用到处问。"""
    return {
        "states": [{"value": s, "label": state_label(s)} for s in ORDER_STATES],
        "mainline": list(ORDER_MAINLINE),
        "transitions": {s: list(next_states(s)) for s in ORDER_STATES},
        "order_types": [{"value": k, "label": v} for k, v in ORDER_TYPES.items()],
        "production_levels": list(PRODUCTION_LEVELS),
        "genders": [{"value": k, "label": v} for k, v in GENDERS.items()],
        "recruitment_sources": list(RECRUITMENT_SOURCES),
        "commission_rate": {
            "min": str(COMMISSION_RATE_MIN),
            "max": str(COMMISSION_RATE_MAX),
            "text": f"通常为整体项目金额的 {COMMISSION_RATE_MIN * 100:.0f}%，"
                    f"最高上限 {COMMISSION_RATE_MAX * 100:.0f}%，"
                    "超出部分须有变动协议，需重新核算",
        },
        "settle_valid_days": SETTLE_VALID_DAYS,
        "settle_window_days": list(SETTLE_WINDOW_DAYS),
        "payout_day": PAYOUT_DAY,
        "remind_day": REMIND_DAY,
        "exception_cases": [{"value": k, "label": v} for k, v in EXCEPTION_CASES],
        # 上游状态字典 —— 互通时前端要能把两边对上
        "upstream_statuses": [
            {"value": k, "label": v, "local_state": local_state_from_upstream(k)}
            for k, v in UPSTREAM_STATUS_LABELS.items()
        ],
    }
