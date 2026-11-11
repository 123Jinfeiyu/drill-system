"""种子数据：建表 + 测试账号 + 一个剧本（系统查询是否重复工单）"""
import asyncio
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.database import AsyncSessionLocal, engine
from app.database import Base
from app.models import Role, Scenario, User


# 剧本对应最初需求中"系统查询是否重复工单"这一知识点
SCENARIO_DUPLICATE_TICKET = {
    "code": "dup-ticket-query",
    "title": "系统查询是否重复工单",
    "customer_persona": (
        "你是张先生，35 岁，互联网公司运维。今天在系统中提交一个故障工单，"
        "但系统提示'可能存在重复工单'，你不清楚是自己之前提交过、还是同事提交了相同的。"
        "你带着轻微焦虑来咨询客服，希望快速弄清楚：到底是不是重复、如果是重复该怎么处理、"
        "如果不是重复为什么系统会提示。你愿意配合提供工单号、提交时间等信息。"
    ),
    "opening": (
        "你好，我刚提交了一个工单，系统弹窗说'可能存在重复工单'，"
        "但我很确定这是我今天第一次提交啊，这是怎么回事？"
    ),
    "knowledge_points": [
        "重复工单判定规则：同主题+同故障对象+提交时间窗 30 分钟内",
        "查询入口：工单中心 > 我的工单 > 重复检测",
        "处理方式：如确为重复，保留最早提交的工单，关闭后续",
        "如非重复：可点击'忽略提示继续提交'，工单进入正常流程",
        "需向用户索取工单号、提交时间、故障对象以便查询",
    ],
    "reference_answer": (
        "1. 先安抚用户，询问工单号、提交时间、故障对象；"
        "2. 进入工单中心查询用户近 30 分钟内的工单；"
        "3. 若确为重复：解释规则，建议关闭后续工单，保留最早的；"
        "4. 若非重复：说明系统基于相似度匹配给出预警，可点击'忽略提示继续提交'；"
        "5. 全程使用规范话术，不直接承诺工单一定不重复。"
    ),
    "difficulty": 2,
    "max_turns": 6,
}


async def seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 学员
        result = await db.execute(select(User).where(User.username == "student01"))
        if not result.scalar_one_or_none():
            db.add(User(
                username="student01",
                hashed_password=hash_password("Test@2025"),
                role=Role.STUDENT,
                display_name="测试学员",
            ))

        # 讲师
        result = await db.execute(select(User).where(User.username == "teacher01"))
        if not result.scalar_one_or_none():
            db.add(User(
                username="teacher01",
                hashed_password=hash_password("Test@2025"),
                role=Role.TEACHER,
                display_name="测试讲师",
            ))

        # 剧本
        result = await db.execute(
            select(Scenario).where(Scenario.code == SCENARIO_DUPLICATE_TICKET["code"])
        )
        if not result.scalar_one_or_none():
            db.add(Scenario(**SCENARIO_DUPLICATE_TICKET))

        await db.commit()

    print("[OK] 种子数据写入完成")
    print("  学员账号: student01 / Test@2025")
    print("  讲师账号: teacher01 / Test@2025")
    print(f"  剧本: {SCENARIO_DUPLICATE_TICKET['title']}")


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    asyncio.run(seed())
