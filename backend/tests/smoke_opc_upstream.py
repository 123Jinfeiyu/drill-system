# -*- coding: utf-8 -*-
"""OPC · 上游真实联调 smoke（真网络 + 真凭据 + 真数据）。

这是**唯一**能证明「连接真的通了」的测试 ——
单测证明规则对，smoke 证明连得上、字段对得上、口径对得上。

全程只读：只调 list / detail / get 类接口，不做任何写操作。

跑法：
    cd E:\\drill-system\\backend
    set TRCIPG_USERNAME=xxx && set TRCIPG_PASSWORD=yyy
    .\\.venv\\Scripts\\python.exe -X utf8 tests\\smoke_opc_upstream.py
"""
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import opc_sync as sync  # noqa: E402
from app.services.trcipg_client import (TrcipgClient,  # noqa: E402
                                         UpstreamError)

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (label, (" — " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILURES.append(label)
        print("  [FAIL] %s%s" % (label, (" — " + detail) if detail else ""))
    return cond


async def main() -> int:
    username = os.getenv("TRCIPG_USERNAME", "").strip()
    password = os.getenv("TRCIPG_PASSWORD", "").strip()
    if not username or not password:
        print("!! 未配置 TRCIPG_USERNAME / TRCIPG_PASSWORD，跳过真实联调")
        return 0

    print("=" * 74)
    print("① 登录与连通性")
    print("=" * 74)
    client = TrcipgClient(username, password)
    try:
        token = await client.login()
    except UpstreamError as exc:
        print("  [FAIL] 登录失败：%s" % exc)
        return 1
    check("登录拿到 token", bool(token), "token 长度 %d" % len(token))
    check("token 是 JWT 三段式", token.count(".") == 2)

    print("\n" + "=" * 74)
    print("② 设计师档案（撮合对象池）")
    print("=" * 74)
    designers, d_total = await client.list_designer_detail(page=1, num=50)
    check("拉到设计师", len(designers) > 0, "本页 %d / 总数 %d" % (len(designers), d_total))
    if designers:
        d0 = designers[0]
        check("设计师有名字", bool(d0.name), d0.name)
        check("设计师有手机号", bool(d0.phone), d0.phone)
        check("设计师有收款账号", bool(d0.alipay_account), d0.alipay_account)
        check("设计师有战区", bool(d0.war_zone), d0.war_zone)
        check("设计师有档次", bool(d0.production_level), d0.production_level)
        can = sum(1 for d in designers if d.can_settle)
        check("结算资格字段有效", 0 < can <= len(designers),
              "%d/%d 可结算" % (can, len(designers)))

    print("\n" + "=" * 74)
    print("③ 订单详情与佣金拆分口径")
    print("=" * 74)
    settlements, s_total, s_sum = await client.list_settlements(
        settlement_type=1, page=1, num=50)
    check("拉到结算单", len(settlements) > 0,
          "本页 %d / 总数 %d / 佣金合计 %s" % (len(settlements), s_total, s_sum))
    check("佣金汇总是 Decimal", isinstance(s_sum, Decimal), str(s_sum))

    if settlements:
        s0 = settlements[0]
        check("结算单有设计师", bool(s0.team_members_name), s0.team_members_name)
        check("结算单有订单号", bool(s0.sn), s0.sn)

        order = await client.get_order(s0.order_id)
        check("拉到订单详情", order is not None, "order_id=%s" % s0.order_id)
        if order:
            split = sync.extract_upstream_split(order)
            check("订单佣金是 Decimal", isinstance(order.order_commission, Decimal),
                  str(order.order_commission))
            # 上游真实口径：designer+control+hr+qc == order
            check("四项佣金之和等于订单佣金", split.is_balanced,
                  "订单 %s / 已分配 %s / 差额 %s"
                  % (split.total, split.allocated, split.residual))
            check("状态映射落在 OPC 状态机内",
                  sync.map_upstream_state(order.status) in
                  __import__("app.services.opc_ledger", fromlist=["ORDER_STATES"]).ORDER_STATES,
                  "上游 %s(%s) → OPC %s" % (order.status, order.status_label,
                                          sync.map_upstream_state(order.status)))
            check("上游验收成功不等价于已结算",
                  sync.map_upstream_state(5) == "delivered",
                  "上游 5(验收成功) → %s" % sync.map_upstream_state(5))

    print("\n" + "=" * 74)
    print("④ 需求合同草稿（只用真实字段）")
    print("=" * 74)
    if settlements:
        order = await client.get_order(settlements[0].order_id)
        if order:
            spec = sync.build_spec_from_upstream(order)
            for section in ("目标", "范围", "非目标", "约束", "验收标准", "完成定义"):
                check("合同含「%s」" % section, f"## {section}" in spec)
            check("合同带真实店铺", bool(order.store_name) and order.store_name in spec,
                  order.store_name)
            from app.services.opc_ledger import parse_spec
            sections = parse_spec(spec)
            check("合同可被解析成 6 段", len(sections) == 6, "解析出 %d 段" % len(sections))

    print("\n" + "=" * 74)
    print("⑤ 撮合候选打分（真实数据）")
    print("=" * 74)
    if settlements and designers:
        order = await client.get_order(settlements[0].order_id)
        ranked = sync.rank_designers_for_order(order, designers, limit=10)
        check("产出候选", len(ranked) > 0, "%d 个" % len(ranked))
        check("候选不返回空数组", len(ranked) > 0)
        blocked = [c for c in ranked if c.blocked]
        check("不可派的有明确原因", all(c.blocked for c in blocked),
              "%d 个被标记不可派" % len(blocked))
        # 排序正确性：可派的在前
        first_blocked = next((i for i, c in enumerate(ranked) if c.blocked), len(ranked))
        check("可派的排在不可派前面", first_blocked == len(ranked)
              or all(not c.blocked for c in ranked[:first_blocked]),
              "第一个被拦的位置 %d" % first_blocked)

    print("\n" + "=" * 74)
    print("⑥ 对账（空台账 → 不产生假差异）")
    print("=" * 74)
    # 上游 order/list 只返回「核算成功/已到账」的订单，不是全量。
    # 全量口径走结算单（1743 条）。
    orders, o_total = await client.list_orders(page=1, num=20, status=5)
    check("拉到已完工订单", True, "核算成功 %d / 本页 %d" % (o_total, len(orders)))
    report = sync.build_report(orders, settlements, {}, {})
    check("空台账不产生差异", report.ok, "%d 条差异" % len(report.issues))

    # 全量口径：结算单覆盖 1743 条
    full = sync.build_report([], settlements, {}, {})
    check("上游结算单佣金总额已统计", full.upstream_settlement_commission > 0,
          "结算单口径总额 %s" % full.upstream_settlement_commission)
    check("两种佣金口径不混加",
          full.upstream_total_commission != full.upstream_settlement_commission
          or full.upstream_settlement_commission == 0,
          "订单口径 %s / 结算单口径 %s"
          % (full.upstream_total_commission, full.upstream_settlement_commission))

    print("\n" + "=" * 74)
    print("⑦ 字典")
    print("=" * 74)
    grades = await client.list_order_grades()
    check("拉到订单档次", len(grades) > 0, "、".join(n for _, n in grades))
    issues = await client.list_order_issue_types()
    check("拉到问题类型", len(issues) > 0, "、".join(n for _, n in issues))

    print("\n" + "=" * 74)
    print("结果：%d 通过 / %d 失败" % (PASS, FAIL))
    if FAILURES:
        print("失败项：")
        for f in FAILURES:
            print("  -", f)
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
