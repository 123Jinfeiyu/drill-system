import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models import DrillSession, Message, MessageRole
from app.services.llm_client import llm_client
from app.services.prompts import build_scorer_messages


async def main():
    async with AsyncSessionLocal() as db:
        # pick the most recent session that has messages
        result = await db.execute(
            select(DrillSession).order_by(DrillSession.created_at.desc()).limit(30)
        )
        sessions = result.scalars().all()
        session = None
        for s in sessions:
            mres = await db.execute(
                select(Message).where(Message.session_id == s.id).limit(1)
            )
            if mres.scalars().first() is not None:
                session = s
                break
        if session is None:
            print("NO SESSION WITH MESSAGES FOUND")
            return
        print("SESSION_ID:", session.id)
        print("STATUS:", session.status)

        msgs_result = await db.execute(
            select(Message)
            .where(Message.session_id == session.id)
            .order_by(Message.created_at)
        )
        msgs = msgs_result.scalars().all()
        dialog = [
            {
                "role": "客户" if m.role == MessageRole.CUSTOMER else "学员",
                "content": m.content,
            }
            for m in msgs
        ]

        scenario = session.scenario
        print("SCENARIO_TITLE:", scenario.title)
        print("KNOWLEDGE_POINTS:", scenario.knowledge_points)
        print("REFERENCE_ANSWER:", scenario.reference_answer)
        print("DIALOG_LEN:", len(dialog))
        print("=" * 80)

        messages = build_scorer_messages(
            scenario_title=scenario.title,
            knowledge_points=scenario.knowledge_points,
            reference_answer=scenario.reference_answer,
            dialog=dialog,
        )

        print(">>> CALL 1: with response_format json_object")
        raw_content = await llm_client.chat(
            messages=messages,
            model=settings.model_scorer,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        print("RAW_CONTENT_1 (full):")
        print(raw_content)
        print("=" * 80)

        print(">>> CALL 2: WITHOUT response_format")
        raw_content2 = await llm_client.chat(
            messages=messages,
            model=settings.model_scorer,
            temperature=0.2,
        )
        print("RAW_CONTENT_2 (full):")
        print(raw_content2)
        print("=" * 80)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
