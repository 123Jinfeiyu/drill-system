"""OPC 一人公司系统 · 种子数据。

幂等：可反复重跑，不产生重复数据。

重跑时**保护人工状态**：设计师的 ``status`` / 佣金比例、店铺的结算周期不��覆盖，
只有「种子定义」本身（名字、标签、默认比例）以本脚本为准。

用法：
    python -X utf8 seed_opc.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import select  # noqa: E402

from app.database import AsyncSessionLocal, init_db  # noqa: E402
from app.models import OpcDesigner, OpcSplitRule, OpcStore  # noqa: E402

# --------------------------------------------------------------------------- 分账规则
# 默认口径照搬总后台的结构：设计师拿大头，HR 与品控各拿一小部分，
# 剩下的是中控/公司留存。**比例只在这里定义一次**，规则表是唯一真相来源。
SEED_RULES = [
    {"scope": "designer", "rate": "0.70", "basis": "total",
     "remark": "设计师佣金（接单佣金）"},
    {"scope": "hr", "rate": "0.10", "basis": "total",
     "remark": "HR 佣金"},
    {"scope": "quality_control", "rate": "0.08", "basis": "total",
     "remark": "品控佣金"},
    {"scope": "supervisor", "rate": "0.02", "basis": "total",
     "remark": "设计主管奖金（按奖金基数算时可调）"},
    {"scope": "control", "rate": "0.05", "basis": "total",
     "remark": "中控金额"},
]

# --------------------------------------------------------------------------- 设计师
SEED_DESIGNERS = [
    {"name": "林小满", "phone": "13800000001", "production_level": "资深",
     "design_tags": "女装 连衣裙 电商主图 唯品会", "war_zone": "华东战区",
     "alipay_name": "林小满", "alipay_account": "linxiaoman@example.com",
     "commission_rate": "0.70", "note": "女装类目出图快，改稿配合度高"},
    {"name": "周野", "phone": "13800000002", "production_level": "资深",
     "design_tags": "运动鞋 户外 详情页 品牌视觉", "war_zone": "华北战区",
     "alipay_name": "周野", "alipay_account": "zhouye@example.com",
     "commission_rate": "0.70", "note": "运动户外类目主力"},
    {"name": "苏念", "phone": "13800000003", "production_level": "中级",
     "design_tags": "美妆 护肤品 详情页 排版", "war_zone": "华东战区",
     "alipay_name": "苏念", "alipay_account": "sunian@example.com",
     "commission_rate": "0.68", "note": "美妆类目擅长，文字排版稳"},
    {"name": "陈墨", "phone": "13800000004", "production_level": "中级",
     "design_tags": "数码 3C 耳机 主图 白底图", "war_zone": "华南战区",
     "alipay_name": "陈墨", "alipay_account": "chenmo@example.com",
     "commission_rate": "0.68", "note": "白底图批量出图效率高"},
    {"name": "何岸", "phone": "13800000005", "production_level": "初级",
     "design_tags": "童装 卡通 手绘 插画", "war_zone": "华北战区",
     "alipay_name": "何岸", "alipay_account": "hean@example.com",
     "commission_rate": "0.65", "note": "新人，多带教"},
]

# --------------------------------------------------------------------------- 店铺
SEED_STORES = [
    {"name": "唯品会-女装旗舰店", "url": "https://www.vip.com",
     "customer_name": "女装事业部", "manager": "本人",
     "commission": "0", "settlement_days": 30,
     "remark": "女装类目主店，订单量最大"},
    {"name": "唯品会-运动户外专营店", "url": "https://www.vip.com",
     "customer_name": "运动事业部", "manager": "本人",
     "commission": "0", "settlement_days": 30,
     "remark": "运动类目"},
    {"name": "唯品会-美妆集合店", "url": "https://www.vip.com",
     "customer_name": "美妆事业部", "manager": "本人",
     "commission": "0", "settlement_days": 45,
     "remark": "美妆类目，结算周期 45 天"},
]


async def seed() -> None:
    await init_db()

    async with AsyncSessionLocal() as db:
        # ---- 分账规则 ----
        for item in SEED_RULES:
            existing = (await db.execute(
                select(OpcSplitRule).where(OpcSplitRule.scope == item["scope"])
            )).scalar_one_or_none()
            if existing:
                # 保护人工调过的比例：只在还是默认值时才覆盖
                if str(existing.rate) == "0" or existing.rate is None:
                    existing.rate = item["rate"]
                continue
            db.add(OpcSplitRule(**item))

        # ---- 设计师 ----
        for item in SEED_DESIGNERS:
            existing = (await db.execute(
                select(OpcDesigner).where(OpcDesigner.name == item["name"])
            )).scalar_one_or_none()
            if existing:
                # 保护人工状态：status 与佣金比例不覆盖
                for field in ("phone", "production_level", "design_tags",
                              "war_zone", "alipay_name", "alipay_account", "note"):
                    setattr(existing, field, item[field])
                continue
            db.add(OpcDesigner(**item))

        # ---- 店铺 ----
        for item in SEED_STORES:
            existing = (await db.execute(
                select(OpcStore).where(OpcStore.name == item["name"])
            )).scalar_one_or_none()
            if existing:
                for field in ("url", "customer_name", "manager", "remark"):
                    setattr(existing, field, item[field])
                # 结算周期是人工可调的，不覆盖
                continue
            db.add(OpcStore(**item))

        await db.commit()

        rules = (await db.execute(select(OpcSplitRule))).scalars().all()
        designers = (await db.execute(select(OpcDesigner))).scalars().all()
        stores = (await db.execute(select(OpcStore))).scalars().all()

    print("OPC 种子数据就绪：")
    print(f"  分账规则 {len(rules)} 条")
    for r in rules:
        print(f"    - {r.scope:<18} {r.rate}")
    print(f"  设计师 {len(designers)} 位")
    print(f"  店铺 {len(stores)} 家")


if __name__ == "__main__":
    asyncio.run(seed())
