"""AI 客户扮演 service"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.timeutil import utcnow
from app.models import DrillSession, Message, MessageRole, SessionStatus
from app.schemas import CustomerReply
from app.services.knowledge import search_knowledge
from app.services.prompts import build_customer_messages
from app.services.reply_engine import generate_reply_text


async def get_session_history(
    db: AsyncSession, session_id: str
) -> list[dict[str, str]]:
    """获取对话历史，转成 LLM messages 格式"""
    result = await db.execute(
        Message.__table__.select()
        .where(Message.session_id == session_id)
        # 【P1-3 修复】排序补次级键：created_at 精度只到秒，同一秒内写入的多条消息
        # 顺序可能不稳定；按轮次、再按角色（customer < student，与实际产生顺序一致）稳定排序
        .order_by(Message.created_at, Message.turn, Message.role)
    )
    rows = result.mappings().all()
    history: list[dict[str, str]] = []
    for r in rows:
        # customer -> assistant，student -> user
        role = "assistant" if r["role"] == MessageRole.CUSTOMER.value else "user"
        history.append({"role": role, "content": r["content"]})
    return history


async def generate_customer_reply(
    db: AsyncSession,
    session: DrillSession,
    student_reply: str,
) -> CustomerReply:
    """学员发话后，生成 AI 客户的下一句回复"""
    # 1. 学员回复先入库
    # 【P1-2 修复】改为单事务：学员消息只 flush 不 commit，直到客户回复生成成功后
    # 与客户消息、轮次推进一起提交。此前先 commit 学员消息再调 LLM，一旦 LLM 超时/报错，
    # 学员消息已落库但回复缺失，学员重发同一句话会导致消息重复入库并污染对话上下文。
    # LLM 抛异常时整个事务随请求结束回滚（get_db 关闭未提交会话），重发不会重复。
    student_msg = Message(
        session_id=session.id,
        role=MessageRole.STUDENT,
        content=student_reply,
        turn=session.current_turn,
    )
    db.add(student_msg)
    await db.flush()  # 同事务内 flush 后，下方历史查询即可读到该消息（autoflush 已关闭）

    # 2. 构造对话历史
    history = await get_session_history(db, session.id)
    remaining = max(0, session.scenario.max_turns - session.current_turn)

    # 2.1 检索知识库，注入到客户扮演 prompt（仅作业务背景，不让客户透露知识库存在）
    kb_items = await search_knowledge(db, f"{session.scenario.title} {student_reply}", top_k=3)
    knowledge = [{"title": k.title, "content": k.content} for k in kb_items]

    messages = build_customer_messages(
        persona=session.scenario.customer_persona,
        opening=session.scenario.opening,
        history=history,
        student_reply=student_reply,
        remaining_turns=remaining,
        scenario_title=session.scenario.title,
        knowledge=knowledge,
    )

    # 3. 调用 LLM 生成回复 + 统一后处理
    # 【P2-1 修复】JSON 结束信号解析、空回复兜底、角色口吻清洗、KS 错位重试等
    # 与 practice_agent 重复的逻辑收敛到 reply_engine.generate_reply_text
    reply_text, is_finished = await generate_reply_text(
        messages, model=settings.model_customer
    )

    if remaining <= 0:
        is_finished = True

    # 4. 客户回复入库 + 推进轮次
    customer_msg = Message(
        session_id=session.id,
        role=MessageRole.CUSTOMER,
        content=reply_text,
        turn=session.current_turn + 1,
    )
    db.add(customer_msg)
    session.current_turn += 1
    if is_finished or session.current_turn >= session.scenario.max_turns:
        session.status = SessionStatus.FINISHED
        # 【P1-3 修复】datetime.utcnow() 已弃用，统一改用 timeutil.utcnow()
        session.finished_at = utcnow()

    # 【P1-2 修复】此处一次性提交：学员消息 + 客户消息 + 轮次/状态推进原子生效
    await db.commit()
    await db.refresh(session)

    return CustomerReply(
        content=reply_text,
        is_finished=is_finished,
        next_turn=session.current_turn,
    )
