"""OPC · 上游系统适配器（数字教育平台总后台 /roleapi 族）。

这个模块是 OPC 与既有内部系统之间的**唯一出口**。
所有对上游的 HTTP 调用都收口在这里，OPC 其它模块只认这里返回的 dataclass，
不认上游的原始字段名 —— 上游改字段名时，只需要改这一个文件。

上游实测事实（2026-10-23 逆向 + 只读实测，非猜测）：

- **前端域名不是 API 主机**。``uni.trcipg.com.cn`` / ``uni-c.trcipg.com.cn``
  只是静态壳，真正的 API 主机是 ``https://ppt2api.trcipg.com.cn``。
- **token 走请求头** ``token``，不是 ``Authorization``。
- **登录是明文 POST**（前端 ``loginRSA:false``），入口 ``/roleapi/login/index``，
  入参 ``{"username": ..., "password": ...}``，返回 ``data.token``。
- **结算端 ``/settlement/*`` 是另一套后端**：拿总后台的 token 去调会得到
  ``请不要非法访问`` 或 404。本模块因此**只对接总后台 ``/roleapi/*``**，
  结算端留给 :mod:`app.services.opc_settle_client` 单独处理。
- **订单列表有隐藏筛选**：前端 queryForm 实际会带上
  ``is_del`` / ``order_type`` / ``status`` / ``user_status``，
  少传会返回 0 条而不是报错，排查时极难定位。
- **结算单列表必须带 ``type``**：1=普通结算 2=HR结算 3=品控结算，
  不带直接返回 ``请选择结算单类型``。
- **佣金是字符串**，形如 ``"35.00"``，必须 Decimal 转换，禁浮点。

只读边界：本模块只调用 list / detail / get 类接口，
**不实现任何写操作**（add / edit / del / settle 一律不提供）——
OPC 定位是「台账 + 撮合 + 对账」，不是替管理员去改上游数据。
"""

from __future__ import annotations

import asyncio
import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 上游 API 主机（前端域名只是静态壳，别搞混）
UPSTREAM_BASE = "https://ppt2api.trcipg.com.cn"

#: 总后台前端地址，用于拼 Referer / Origin
ADMIN_ORIGIN = "https://uni.trcipg.com.cn"

#: 结算端前端地址
SETTLE_ORIGIN = "https://uni-c.trcipg.com.cn"

#: 请求超时（秒）。上游偶尔慢，给宽一点。
UPSTREAM_TIMEOUT = 30

#: 登录失败重试次数（含首次）。上游偶发 5xx，重试能救。
LOGIN_RETRY = 3

#: 单次业务请求重试次数
REQUEST_RETRY = 2

#: 重试间隔基数（秒），实际间隔 = BASE * 2**n
RETRY_BASE_DELAY = 0.6

#: 相邻两次请求的最小间隔（秒）。
#:
#: **这不是保守，是必需** —— 2026-10-23 实测：连续高频拉取后，
#: 上游会把整个域名对我们断开（``RemoteDisconnected``，curl 也 000），
#: DNS 正常但 TCP 不通，只能等对方解封。
#: 一次完整同步大约 6 个请求，按 0.4 秒间隔完全够用，
#: 又不会把上游打到拉黑。
MIN_REQUEST_INTERVAL = 0.4

#: 上游订单状态字典（结算端 ``$status`` 数组，实测得来）
UPSTREAM_ORDER_STATUS: dict[int, str] = {
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

#: 结算单类型（前端 ``type`` 参数实测）
SETTLEMENT_TYPES: dict[int, str] = {
    1: "普通结算",
    2: "HR结算",
    3: "品控结算",
}

#: 团队成员类型（前端 ``getAllTeamMembersList({type})`` 实测）
TEAM_MEMBER_TYPES: dict[int, str] = {
    1: "设计师",
    2: "HR",
    3: "品控",
}


class UpstreamError(RuntimeError):
    """上游调用失败（网络、鉴权、业务报错都归到这里）。"""


class UpstreamBlockedError(UpstreamError):
    """上游把我们的来源挡在外面了（连接被直接掐断，��不是业务报错）。

    2026-10-23 实测：连续高频拉取后，上游会返回
    ``RemoteDisconnected: Remote end closed connection without response``，
    **整个域名都连不上**（curl 也是 000），DNS 解析正常。
    这是上游的防护策略，不是代码问题 —— 所以单列一个异常类型，
    让前端能显示「上游暂时拒绝访问，请稍后再试」，
    而不是笼统的「调用失败」让人以为是 OPC 自己坏了。
    """


#: 命中这些关键字就判定为「被上游挡了」，而不是普通网络抖动
BLOCKED_SIGNATURES: tuple[str, ...] = (
    "RemoteDisconnected",
    "Remote end closed connection",
    "Connection reset",
    "Connection aborted",
    "SSLError",
)


# ---------------------------------------------------------------------------
# 数据结构：OPC 内部只认这些
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UpstreamDesigner:
    """上游「团队成员」表里的一条，即设计师档案。"""

    id: int
    name: str
    nickname: str = ""
    phone: str = ""
    alipay_account: str = ""
    war_zone: str = ""
    production_level: str = ""
    recruitment_source: str = ""
    hr_name: str = ""
    quality_control_name: str = ""
    design_supervisor_name: str = ""
    allow_settlement: int = 0
    status: int = 1
    designer_type: int = 1

    @property
    def can_settle(self) -> bool:
        """上游是否允许该设计师参与结算。

        ``allow_settlement`` 实测为 1/0，0 表示被禁用 ——
        这类人**不能**被撮合派单，否则钱结不掉。
        """
        return self.allow_settlement == 1


@dataclass(slots=True)
class UpstreamOrder:
    """上游订单。字段名已从上游的 snake_case 归一。"""

    id: int
    sn: str
    order_sn: str = ""
    order_desc: str = ""
    customer_name: str = ""
    store_id: int | None = None
    store_name: str = ""
    store_account: str = ""
    store_account_id: int | None = None
    war_zone_name: str = ""
    designer_id: int | None = None
    designer_name: str = ""
    user_id: int | None = None
    user_name: str = ""
    hr_id: int | None = None
    hr_name: str = ""
    quality_control_id: int | None = None
    quality_control_name: str = ""
    order_grade: str = ""
    order_type: int = 0
    status: int = 0
    designer_settlement_status: int = 0
    hr_settlement_status: int = 0
    quality_control_settlement_status: int = 0
    user_status: int = 0
    order_commission: Decimal = Decimal("0")
    designer_commission: Decimal = Decimal("0")
    hr_commission: Decimal = Decimal("0")
    quality_control_commission: Decimal = Decimal("0")
    middle_control_commission: Decimal = Decimal("0")
    design_supervisor_bonus: Decimal = Decimal("0")
    request_delivery_time: str = ""
    sample_manuscript_time: str = ""
    final_draft_time: str = ""
    order_time: str = ""
    created_at: str = ""
    source_images: list[str] = field(default_factory=list)
    end_images: list[str] = field(default_factory=list)
    sub_order: list[dict[str, Any]] = field(default_factory=list)
    issue_desc: str = ""
    reject_reason: str = ""
    customer_service: str = ""
    transfer_order_status: int = 0

    @property
    def status_label(self) -> str:
        return UPSTREAM_ORDER_STATUS.get(self.status, f"未知({self.status})")


@dataclass(slots=True)
class UpstreamSettlement:
    """上游结算单（设计师佣金维度）。"""

    id: int = 0
    order_id: int = 0
    settlement_order_id: int | None = None
    sn: str = ""
    order_sn: str = ""
    team_members_id: int | None = None
    team_members_name: str = ""
    store_name: str = ""
    customer_name: str = ""
    order_grade_name: str = ""
    war_zone_name: str = ""
    commission: Decimal = Decimal("0")
    order_commission: Decimal = Decimal("0")
    middle_control_commission: Decimal = Decimal("0")
    settlement_status: int = 0
    settlement_time: str = ""
    order_time: str = ""
    order_status: int = 0
    alipay_account: str = ""
    request_delivery_time: str = ""
    final_draft_time: str = ""


@dataclass(slots=True)
class UpstreamStore:
    """上游店铺 / 收款主体（点律账号）。"""

    id: int
    name: str = ""
    account: str = ""
    customer_name: str = ""
    url: str = ""


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """把上游的字符串金额安全转成 Decimal。

    上游金额一律是 ``"35.00"`` 这种字符串，**绝不能走 float** ——
    35.10 在 float 下变成 35.099999999999998，分账就会差一分钱。
    """
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return default


def _as_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class TrcipgClient:
    """总后台 API 客户端。

    用法::

        async with TrcipgClient(username, password) as client:
            orders = await client.list_orders(limit=50)

    **线程/协程安全**：token 缓存在实例上，自动续期；
    401 会清空 token 重新登录并重放一次请求。
    """

    def __init__(
        self,
        username: str,
        password: str,
        base: str = UPSTREAM_BASE,
        origin: str = ADMIN_ORIGIN,
    ) -> None:
        self.username = username
        self.password = password
        self.base = base.rstrip("/")
        self.origin = origin
        self._token: str | None = None
        #: 上一次请求的时间戳，用于限流
        self._last_request_at: float = 0.0
        #: 限流锁 —— 多个协程共用一个 client 时不能并发打上游
        self._throttle = asyncio.Lock()
        # 自签证书的内网 API：关校验（与前端浏览器行为一致）
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    # ---------------- 底层 HTTP ----------------

    async def _post(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        retry: int = REQUEST_RETRY,
    ) -> Any:
        """POST 一个上游接口，返回解析后的 JSON。

        失败时抛 :class:`UpstreamError`，**不返回 None** —— 上游挂了就要让调用方知道，
        静默吞掉会让人以为「同步完了但没数据」，那是排查噩梦。
        """
        last_err = ""
        for attempt in range(retry + 1):
            try:
                await self._throttle_wait()
                return await asyncio.to_thread(self._post_sync, path, payload)
            except UpstreamError as exc:
                last_err = str(exc)
                # 401 → 清 token 重登一次（不计入普通重试次数）
                if "401" in last_err and self._token:
                    self._token = None
                    await self.login()
                    continue
                # 被上游挡了 → 退避更久再试，但别无限重试
                if isinstance(exc, UpstreamBlockedError):
                    if attempt < retry:
                        await asyncio.sleep(RETRY_BASE_DELAY * (2 ** (attempt + 2)))
                        continue
                    raise
                if attempt < retry:
                    await asyncio.sleep(RETRY_BASE_DELAY * (2**attempt))
        raise UpstreamError(f"{path} 调用失败：{last_err}")

    async def _throttle_wait(self) -> None:
        """限流：保证相邻两次请求至少隔 :data:`MIN_REQUEST_INTERVAL` 秒。

        **必须串行** —— 上游的防护是按请求密度算的，并发打过去等于自伤。
        """
        async with self._throttle:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            if self._last_request_at and elapsed < MIN_REQUEST_INTERVAL:
                await asyncio.sleep(MIN_REQUEST_INTERVAL - elapsed)
            self._last_request_at = time.monotonic()

    def _post_sync(self, path: str, payload: dict[str, Any] | None) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(self.base + path, data=body, method="POST")
        req.add_header("Content-Type", "application/json;charset=UTF-8")
        req.add_header("Accept", "application/json, text/plain, */*")
        req.add_header("Origin", self.origin)
        req.add_header("Referer", self.origin + "/")
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0")
        if self._token:
            req.add_header("token", self._token)
        try:
            with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT, context=self._ssl_ctx) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", "replace")[:200]
            raise UpstreamError(f"HTTP {exc.code} {body_text}") from exc
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if any(sig in message for sig in BLOCKED_SIGNATURES):
                raise UpstreamBlockedError(
                    f"上游拒绝访问（{message}）——多半是请求太频繁被临时拦截，稍后再试"
                ) from exc
            raise UpstreamError(message) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise UpstreamError(f"返回不是 JSON：{raw[:200]}") from exc

        code = data.get("code")
        if code not in (200, 0, "200", "0"):
            raise UpstreamError(f"业务报错 code={code} message={data.get('message')}")
        return data.get("data")

    # ---------------- 登录 ----------------

    async def login(self) -> str:
        """登录并缓存 token。返回 token。"""
        last_err = ""
        for attempt in range(LOGIN_RETRY):
            try:
                await self._throttle_wait()
                data = await asyncio.to_thread(self._login_sync)
                token = (data or {}).get("token")
                if not token:
                    raise UpstreamError("登录返回里没有 token")
                self._token = token
                return token
            except UpstreamError as exc:
                last_err = str(exc)
                if attempt < LOGIN_RETRY - 1:
                    await asyncio.sleep(RETRY_BASE_DELAY * (2**attempt))
        raise UpstreamError(f"登录失败：{last_err}")

    def _login_sync(self) -> Any:
        payload = {"username": self.username, "password": self.password}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base + "/roleapi/login/index", data=body, method="POST")
        req.add_header("Content-Type", "application/json;charset=UTF-8")
        req.add_header("Accept", "application/json, text/plain, */*")
        req.add_header("Origin", self.origin)
        req.add_header("Referer", self.origin + "/")
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0")
        try:
            with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT, context=self._ssl_ctx) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise UpstreamError(f"HTTP {exc.code}") from exc
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if any(sig in message for sig in BLOCKED_SIGNATURES):
                raise UpstreamBlockedError(
                    f"上游拒绝访问（{message}）——多半是请求太频繁被临时拦截，稍后再试"
                ) from exc
            raise UpstreamError(message) from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise UpstreamError(f"登录返回不是 JSON：{raw[:200]}") from exc
        if parsed.get("code") not in (200, 0, "200", "0"):
            raise UpstreamError(f"登录失败：{parsed.get('message')}")
        return parsed.get("data")

    async def _ensure_login(self) -> None:
        if not self._token:
            await self.login()

    async def __aenter__(self) -> "TrcipgClient":
        await self._ensure_login()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        self._token = None

    # ---------------- 设计师 ----------------

    async def list_designers(self, member_type: int = 1) -> list[UpstreamDesigner]:
        """拉团队成员（设计师档案）。

        ``member_type``：1=设计师 2=HR 3=品控。
        上游返回的是完整档案（含 war_zone / production_level / 收款账号）。
        """
        await self._ensure_login()
        data = await self._post("/roleapi/teamMembers/getAllTeamMembersList",
                                 {"type": member_type})
        return [self._to_designer(row) for row in (data or [])]

    async def list_designer_detail(self, page: int = 1, num: int = 50,
                                   member_type: int = 1) -> tuple[list[UpstreamDesigner], int]:
        """拉团队成员**详情**列表（带收款账号、战区、档次等完整字段）。

        与 :meth:`list_designers` 的区别：后者只给精简字段（id/name/nickname），
        这个才带 ``alipay_account`` / ``war_zone_name`` / ``allow_settlement``，
        撮合需要的就是这份。返回 ``(列表, 总数)``。
        """
        await self._ensure_login()
        data = await self._post("/roleapi/teamMembers/list", {
            "page": page, "num": num, "type": member_type, "designer_type": member_type,
        })
        if not isinstance(data, dict):
            return [], 0
        rows = data.get("data") or []
        return [self._to_designer(row) for row in rows], int(data.get("total") or 0)

    @staticmethod
    def _to_designer(row: dict[str, Any]) -> UpstreamDesigner:
        return UpstreamDesigner(
            id=int(row.get("id") or 0),
            name=_as_str(row.get("name")),
            nickname=_as_str(row.get("nickname")),
            phone=_as_str(row.get("phone")),
            alipay_account=_as_str(row.get("alipay_account")),
            war_zone=_as_str(row.get("war_zone_name")),
            production_level=_as_str(row.get("production_level_name")),
            recruitment_source=_as_str(row.get("recruitment_source_name")),
            hr_name=_as_str(row.get("hr_name")),
            quality_control_name=_as_str(row.get("quality_control_name")),
            design_supervisor_name=_as_str(row.get("design_supervisor_name")),
            allow_settlement=int(row.get("allow_settlement") or 0),
            # 【修复】原来写的是 int(row.get("status") or 1) ——
            # 上游 status=0（停用/离职）会被 or 1 兜成 1，
            # 结果永远测不出「已停用」。这里改成显式判 None。
            status=int(row["status"]) if row.get("status") is not None else 1,
            designer_type=int(row.get("designer_type") or 1),
        )

    # ---------------- 订单 ----------------

    async def list_orders(
        self,
        page: int = 1,
        num: int = 50,
        *,
        status: int | None = None,
        order_type: int | None = None,
        is_del: int | None = None,
        user_status: str | None = None,
        order_time_start: str = "",
        order_time_end: str = "",
    ) -> tuple[list[UpstreamOrder], int]:
        """拉**已完工**订单列表（上游「接单佣金」页面）。

        .. warning::
           **这个接口不是「全部订单」** —— 前端筛选器只有两个选项：
           ``status=5``（核算成功）与 ``status=9``（已到账），
           也就是「已经算完账的订单」。

           想拿全量订单要走 :meth:`list_settlements`（1743 条结算单）
           或者逐单 :meth:`get_order`。这是上游的设计，不是 bug。

        **必须显式传 ``status``** —— 不传会返回 0 条且不报错，
        排查时极难定位。

        返回 ``(订单列表, 总数)``。
        """
        await self._ensure_login()
        payload: dict[str, Any] = {"page": page, "num": num, "order_time": []}
        if status is not None:
            payload["status"] = status
        else:
            # 上游前端默认就是「核算成功」，这里跟随默认，
            # 不传 status 会被上游静默判成空结果
            payload["status"] = 5
        if order_type is not None:
            payload["order_type"] = order_type
        if is_del is not None:
            payload["is_del"] = is_del
        if user_status is not None:
            payload["user_status"] = user_status
        if order_time_start:
            payload["order_time_start"] = order_time_start
        if order_time_end:
            payload["order_time_end"] = order_time_end
        data = await self._post("/roleapi/order/list", payload)
        if not isinstance(data, dict):
            return [], 0
        rows = data.get("data") or []
        return [self._to_order(row) for row in rows], int(data.get("total") or 0)

    async def get_order(self, order_id: int) -> UpstreamOrder | None:
        """拉单张订单详情（含佣金拆分、源图/终稿、问题描述）。

        详情比列表全得多：佣金五项拆分、``source_images`` / ``end_images``、
        ``issue_desc``、``transfer_order_status`` 只有详情里才有。
        """
        await self._ensure_login()
        data = await self._post("/roleapi/order/detail", {"id": order_id})
        if not isinstance(data, dict) or not data:
            return None
        return self._to_order(data)

    @staticmethod
    def _to_order(row: dict[str, Any]) -> UpstreamOrder:
        store_account = row.get("store_account") or {}
        if not isinstance(store_account, dict):
            store_account = {}
        return UpstreamOrder(
            id=int(row.get("id") or 0),
            sn=_as_str(row.get("sn")),
            order_sn=_as_str(row.get("order_sn")),
            order_desc=_as_str(row.get("order_desc")),
            customer_name=_as_str(row.get("customer_name")),
            store_id=_as_int(row.get("store_id")),
            store_name=_as_str(row.get("store_name")),
            store_account=_as_str(store_account.get("account") or row.get("store_account_name")),
            store_account_id=_as_int(row.get("store_account_id")),
            war_zone_name=_as_str(row.get("war_zone_name")),
            designer_id=_as_int(row.get("designer_id")),
            designer_name=_as_str(row.get("designer_name")),
            user_id=_as_int(row.get("user_id")),
            user_name=_as_str(row.get("user_name")),
            hr_id=_as_int(row.get("hr_id")),
            hr_name=_as_str(row.get("hr_name")),
            quality_control_id=_as_int(row.get("quality_control_id")),
            quality_control_name=_as_str(row.get("quality_control_name")),
            order_grade=_as_str(row.get("order_grade_name")),
            order_type=int(row.get("order_type") or 0),
            status=int(row.get("status") or 0),
            designer_settlement_status=int(row.get("designer_settlement_status") or 0),
            hr_settlement_status=int(row.get("hr_settlement_status") or 0),
            quality_control_settlement_status=int(row.get("quality_control_settlement_status") or 0),
            user_status=int(row.get("user_status") or 0),
            order_commission=to_decimal(row.get("order_commission")),
            designer_commission=to_decimal(row.get("designer_commission")),
            hr_commission=to_decimal(row.get("hr_commission")),
            quality_control_commission=to_decimal(row.get("quality_control_commission")),
            middle_control_commission=to_decimal(row.get("middle_control_commission")),
            design_supervisor_bonus=to_decimal(row.get("design_supervisor_bonus")),
            request_delivery_time=_as_str(row.get("request_delivery_time")),
            sample_manuscript_time=_as_str(row.get("sample_manuscript_time")),
            final_draft_time=_as_str(row.get("final_draft_time")),
            order_time=_as_str(row.get("order_time")),
            created_at=_as_str(row.get("created_at")),
            source_images=list(row.get("source_images") or []),
            end_images=list(row.get("end_images") or []),
            sub_order=list(row.get("sub_order") or []),
            issue_desc=_as_str(row.get("issue_desc")),
            reject_reason=_as_str(row.get("reject_reason")),
            customer_service=_as_str(row.get("customer_service")),
            transfer_order_status=int(row.get("transfer_order_status") or 0),
        )

    # ---------------- 结算单 ----------------

    async def list_settlements(
        self,
        settlement_type: int = 1,
        page: int = 1,
        num: int = 50,
    ) -> tuple[list[UpstreamSettlement], int, Decimal]:
        """拉结算单。

        ``settlement_type`` **必传**（1=普通 2=HR 3=品控），不传上游直接报
        ``请选择结算单类型``。
        返回 ``(列表, 总数, 佣金汇总)``。
        """
        await self._ensure_login()
        data = await self._post("/roleapi/settlementOrder/list", {
            "page": page, "num": num, "type": settlement_type,
        })
        if not isinstance(data, dict):
            return [], 0, Decimal("0")
        rows = data.get("data") or []
        total = int(data.get("total") or 0)
        total_commission = to_decimal(data.get("commission"))
        return ([self._to_settlement(row) for row in rows], total, total_commission)

    @staticmethod
    def _to_settlement(row: dict[str, Any]) -> UpstreamSettlement:
        return UpstreamSettlement(
            id=int(row.get("settlement_order_id") or row.get("id") or 0),
            order_id=int(row.get("order_id") or 0),
            settlement_order_id=_as_int(row.get("settlement_order_id")),
            sn=_as_str(row.get("sn")),
            order_sn=_as_str(row.get("order_sn")),
            team_members_id=_as_int(row.get("team_members_id")),
            team_members_name=_as_str(row.get("team_members_name")),
            store_name=_as_str(row.get("store_name")),
            customer_name=_as_str(row.get("customer_name")),
            order_grade_name=_as_str(row.get("order_grade_name")),
            war_zone_name=_as_str(row.get("war_zone_name")),
            commission=to_decimal(row.get("commission")),
            order_commission=to_decimal(row.get("order_commission")),
            middle_control_commission=to_decimal(row.get("middle_control_commission")),
            settlement_status=int(row.get("settlement_status") or 0),
            settlement_time=_as_str(row.get("settlement_time")),
            order_time=_as_str(row.get("order_time")),
            order_status=int(row.get("order_status") or 0),
            alipay_account=_as_str(row.get("alipay_account")),
            request_delivery_time=_as_str(row.get("request_delivery_time")),
            final_draft_time=_as_str(row.get("final_draft_time")),
        )

    # ---------------- 店铺与字典 ----------------

    async def list_stores(self) -> list[UpstreamStore]:
        """拉店铺列表。"""
        await self._ensure_login()
        data = await self._post("/roleapi/store/getSelectList", {})
        return [self._to_store(row) for row in (data or [])]

    @staticmethod
    def _to_store(row: dict[str, Any]) -> UpstreamStore:
        return UpstreamStore(
            id=int(row.get("id") or 0),
            name=_as_str(row.get("name")),
            account=_as_str(row.get("account")),
            customer_name=_as_str(row.get("customer_name")),
            url=_as_str(row.get("url")),
        )

    async def list_order_grades(self) -> list[tuple[int, str]]:
        """拉订单档次字典（首席/精美/标准…），撮合要用档次做筛选。"""
        await self._ensure_login()
        data = await self._post("/roleapi/orderGrade/getSelectList", {})
        return [(int(r.get("id") or 0), _as_str(r.get("name"))) for r in (data or [])]

    async def list_order_issue_types(self) -> list[tuple[int, str]]:
        """拉订单问题类型字典（超时完成/金额不符…）。"""
        await self._ensure_login()
        data = await self._post("/roleapi/orderIssueType/getSelectList", {})
        return [(int(r.get("id") or 0), _as_str(r.get("name"))) for r in (data or [])]

    async def list_design_supervisor_settlements(
        self, page: int = 1, num: int = 50
    ) -> tuple[list[dict[str, Any]], int]:
        """拉「设计主管奖金」结算单（含中控金额与订单佣金汇总）。

        这是上游另一条结算线：设计师佣金走 ``settlementOrder``，
        主管奖金走 ``designSettlement``，两条线金额口径不同，不能混。
        """
        await self._ensure_login()
        data = await self._post("/roleapi/designSettlement/list", {"page": page, "num": num})
        if not isinstance(data, dict):
            return [], 0
        return list(data.get("data") or []), int(data.get("total") or 0)

    async def ping(self) -> bool:
        """连通性探测：能登录就算通。"""
        try:
            await self.login()
            return True
        except UpstreamError:
            return False
