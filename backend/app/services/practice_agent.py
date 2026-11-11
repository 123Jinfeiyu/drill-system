"""Q&A 演练场 service：动态生成客户人设、推进对话、评分"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.timeutil import utcnow
from app.models import (
    PracticeMessage,
    PracticeScore,
    PracticeSession,
    MessageRole,
    SessionStatus,
)
from app.schemas import (
    PracticeCategoryOut,
    PracticeReplyOut,
)
from app.services.knowledge import search_knowledge
from app.services.llm_client import llm_client
from app.services.prompts import (
    build_practice_customer_messages,
    build_practice_persona_messages,
    build_practice_scorer_messages,
)
# 【P2-1 修复】回复后处理与评分容错助手原先在本文件内与 customer_agent/scorer
# 各重复一份，统一收敛到 reply_engine / score_utils
from app.services.reply_engine import generate_reply_text
from app.services.score_utils import (
    BUSINESS_ALIASES,
    SUGGESTION_ALIASES,
    SUMMARY_ALIASES,
    WEAK_ALIASES,
    extract_score,
    pick,
)

PRACTICE_CATEGORIES: list[PracticeCategoryOut] = [
    PracticeCategoryOut(
        key="member",
        label="会员相关",
        description="会员退费、权益咨询、捆绑销售质疑、自动扣费、先用后付等会员业务场景",
        tags=["会员", "退费", "捆绑", "先用后付", "自动扣费", "权益"],
    ),
    PracticeCategoryOut(
        key="rate",
        label="利率与资方",
        description="利率质疑、资方查询、综合费用合规、已结清要求退费、利息减免等场景",
        tags=["利率", "资方", "费用", "合规", "减免", "退息费"],
    ),
    PracticeCategoryOut(
        key="overdue",
        label="逾期与催收",
        description="逾期影响、协商减免、暴力催收投诉、延期还款、爆通讯录等催收场景",
        tags=["逾期", "催收", "减免", "延期", "暴力催收", "通讯录"],
    ),
    PracticeCategoryOut(
        key="repayment",
        label="还款问题",
        description="重复扣款、对公还款、账单未更新、还款失败等还款相关场景",
        tags=["还款", "扣款", "对公", "账单", "重复扣费"],
    ),
    PracticeCategoryOut(
        key="complaint",
        label="投诉与外投",
        description="投诉客服、外投处理、舆情投诉、黑猫/12315/银保监会等投诉场景",
        tags=["投诉", "外投", "舆情", "黑猫", "12315", "银保监会"],
    ),
    PracticeCategoryOut(
        key="settlement",
        label="结清与退费",
        description="结清费用异议、提前结清减免、退息费、退费协商等结清相关场景",
        tags=["结清", "退费", "提前结清", "减免", "协商"],
    ),
    PracticeCategoryOut(
        key="audit",
        label="审核与订单",
        description="审核时效、取消订单、催放款等订单审核相关场景",
        tags=["审核", "订单", "放款", "取消", "时效"],
    ),
    PracticeCategoryOut(
        key="credentials",
        label="凭证与合同",
        description="结清证明、发票开具、调取合同、非注册号码进线等场景",
        tags=["结清证明", "发票", "合同", "调取", "非注册号码"],
    ),
]

CATEGORY_MAP = {c.key: c for c in PRACTICE_CATEGORIES}


def get_categories() -> list[PracticeCategoryOut]:
    return PRACTICE_CATEGORIES


def get_category(key: str) -> PracticeCategoryOut | None:
    return CATEGORY_MAP.get(key)


async def _search_kb(db: AsyncSession, query: str, top_k: int = 3):
    items = await search_knowledge(db, query, top_k=top_k)
    return [{"title": k.title, "content": k.content} for k in items]


async def generate_persona(
    db: AsyncSession,
    category_key: str,
    difficulty: int,
) -> tuple[str, str]:
    """生成客户人设和开场白"""
    cat = get_category(category_key)
    if not cat:
        cat = PRACTICE_CATEGORIES[0]

    knowledge = await _search_kb(db, cat.label, top_k=5)
    messages = build_practice_persona_messages(
        category=cat.label,
        category_desc=cat.description,
        difficulty=difficulty,
        knowledge=knowledge,
    )
    try:
        raw = await llm_client.chat_json(
            messages=messages,
            model=settings.model_customer,
            temperature=0.9,
            max_tokens=700,
        )
    except Exception:
        # 兜底：人设/开场白生成失败时不阻断创建会话
        raw = {}
    persona = str(raw.get("persona", "")).strip() if isinstance(raw, dict) else ""
    opening = str(raw.get("opening", "")).strip() if isinstance(raw, dict) else ""
    if not persona or not opening:
        persona = persona or f"一位咨询{cat.label}业务的客户，情绪{'激动' if difficulty >= 3 else '平和'}"
        opening = opening or f"您好，我想咨询一下{cat.label}的问题"
    return persona, opening


async def get_practice_history(
    db: AsyncSession, session_id: str
) -> list[dict[str, str]]:
    """获取演练场对话历史"""
    result = await db.execute(
        PracticeMessage.__table__.select()
        .where(PracticeMessage.session_id == session_id)
        # 【P1-3 修复】排序补次级键：created_at 精度只到秒，同一秒内写入的多条消息
        # 顺序可能不稳定；按轮次、再按角色（customer < student）稳定排序
        .order_by(PracticeMessage.created_at, PracticeMessage.turn, PracticeMessage.role)
    )
    rows = result.mappings().all()
    history: list[dict[str, str]] = []
    for r in rows:
        role = "assistant" if r["role"] == MessageRole.CUSTOMER.value else "user"
        history.append({"role": role, "content": r["content"]})
    return history


async def generate_customer_reply(
    db: AsyncSession,
    session: PracticeSession,
    student_reply: str,
    *,
    script_id: str | None = None,
    via: str = "free",
) -> PracticeReplyOut:
    """学员发话后，生成 AI 客户的下一句回复。

    ``script_id``/``via``：模拟进线（live_sim）里点「话术」回复时传入，
    落库到 PracticeMessage 上，供通话小结统计「本次用了哪些话术」。
    演练场打字的回复不传，行为与从前完全一致。
    """
    # 【P1-2 修复】改为单事务：学员消息只 flush 不 commit，直到客户回复生成成功后
    # 与客户消息、轮次推进一起提交。此前先 commit 学员消息再调 LLM，一旦 LLM 超时/报错，
    # 学员消息已落库但回复缺失，学员重发同一句话会导致消息重复入库并污染对话上下文。
    # LLM 抛异常时整个事务随请求结束回滚（get_db 关闭未提交会话），重发不会重复。
    student_msg = PracticeMessage(
        session_id=session.id,
        role=MessageRole.STUDENT,
        content=student_reply,
        turn=session.current_turn,
        script_id=script_id,
        via=via,
    )
    db.add(student_msg)
    await db.flush()  # 同事务内 flush 后，下方历史查询即可读到该消息（autoflush 已关闭）

    history = await get_practice_history(db, session.id)
    remaining = max(0, session.max_turns - session.current_turn)
    cat = get_category(session.category)
    kb_query = f"{cat.label if cat else session.category} {student_reply}"
    knowledge = await _search_kb(db, kb_query, top_k=3)

    messages = build_practice_customer_messages(
        persona=session.persona,
        category=cat.label if cat else session.category,
        history=history,
        student_reply=student_reply,
        remaining_turns=remaining,
        difficulty=session.difficulty,
        knowledge=knowledge,
    )

    # 【P2-1 修复】JSON 结束信号解析、空回复兜底、角色口吻清洗、KS 错位重试等
    # 与 customer_agent 重复的逻辑收敛到 reply_engine.generate_reply_text
    reply_text, is_finished = await generate_reply_text(
        messages, model=settings.model_customer
    )

    if remaining <= 0:
        is_finished = True

    customer_msg = PracticeMessage(
        session_id=session.id,
        role=MessageRole.CUSTOMER,
        content=reply_text,
        turn=session.current_turn + 1,
    )
    db.add(customer_msg)
    session.current_turn += 1
    if is_finished or session.current_turn >= session.max_turns:
        session.status = SessionStatus.FINISHED
        # 【P1-3 修复】datetime.utcnow() 已弃用，统一改用 timeutil.utcnow()
        session.finished_at = utcnow()

    # 【P1-2 修复】此处一次性提交：学员消息 + 客户消息 + 轮次/状态推进原子生效
    await db.commit()
    await db.refresh(session)

    return PracticeReplyOut(
        content=reply_text,
        is_finished=is_finished,
        next_turn=session.current_turn,
    )


# 【P2-1 修复】_clamp/_coerce_number/_extract_score/_pick 及别名表已移至
# score_utils.py（取 scorer 的完整容错实现），本文件改为从那里导入


async def score_practice_session(
    db: AsyncSession, session: PracticeSession
) -> PracticeScore:
    """对一次演练场会话评分"""
    if session.status != SessionStatus.FINISHED:
        session.status = SessionStatus.FINISHED
        # 【P1-3 修复】datetime.utcnow() 已弃用，统一改用 timeutil.utcnow()
        session.finished_at = utcnow()
        await db.commit()

    result = await db.execute(
        select(PracticeMessage)
        .where(PracticeMessage.session_id == session.id)
        # 【P1-3 修复】评分读对话同样补排序次级键，保证评分时对话顺序稳定
        .order_by(PracticeMessage.created_at, PracticeMessage.turn, PracticeMessage.role)
    )
    msgs = result.scalars().all()
    dialog = [
        {"role": "客户" if m.role == MessageRole.CUSTOMER else "客服", "content": m.content}
        for m in msgs
    ]
    if not dialog:
        return await _upsert_practice_score(
            db, session,
            total=0.0, accuracy=0.0, completeness=0.0, etiquette=0.0,
            responsiveness=0.0, knowledge_use=0.0,
            summary="无对话记录，无法评分",
            weak_points=["未进行任何对话"],
            suggestions="请重新开始演练，与客户进行至少一轮对话后再评分",
        )

    cat = get_category(session.category)
    knowledge = await _search_kb(db, cat.label if cat else session.category, top_k=3)

    messages = build_practice_scorer_messages(
        category=cat.label if cat else session.category,
        persona=session.persona,
        dialog=dialog,
        knowledge=knowledge,
    )
    try:
        raw = await llm_client.chat_json(
            messages=messages,
            model=settings.model_scorer,
            temperature=0.2,
            max_tokens=1100,
        )
        if not isinstance(raw, dict):
            raw = {}
    except Exception:
        # 兜底降级：模型输出非法 JSON 时不阻断评分流程
        raw = {}

    if not isinstance(raw, dict):
        raw = {}

    accuracy = extract_score(raw, "accuracy")
    completeness = extract_score(raw, "completeness")
    etiquette = extract_score(raw, "etiquette")
    responsiveness = extract_score(raw, "responsiveness")
    knowledge_use = extract_score(raw, "knowledge_use")
    total = round(
        (accuracy + completeness + etiquette + responsiveness + knowledge_use) / 5, 2
    )

    summary = str(pick(raw, SUMMARY_ALIASES, default=""))[:2000]
    if not summary:
        summary = "本次演练暂无法生成详细评语（评分模型输出异常）；各维度按中性值处理，建议重试评分。"
    weak_raw = pick(raw, WEAK_ALIASES, default=[])
    if not isinstance(weak_raw, list):
        weak_raw = [weak_raw]
    weak_points = [str(p)[:100] for p in weak_raw][:5] or ["评分模型输出异常，未能识别薄弱点"]
    suggestions = str(pick(raw, SUGGESTION_ALIASES, default=""))[:2000]
    business_summary = str(pick(raw, BUSINESS_ALIASES, default=""))[:1000]
    # 本地小模型可能把提示词说明原样作为输出，视为无效并丢弃
    if "客服工单式一句话" in business_summary or not business_summary.strip():
        business_summary = ""

    return await _upsert_practice_score(
        db, session,
        total=total, accuracy=accuracy, completeness=completeness,
        etiquette=etiquette, responsiveness=responsiveness,
        knowledge_use=knowledge_use,
        summary=summary, weak_points=weak_points, suggestions=suggestions,
        business_summary=business_summary,
    )


async def _upsert_practice_score(
    db: AsyncSession,
    session: PracticeSession,
    *,
    total: float,
    accuracy: float,
    completeness: float,
    etiquette: float,
    responsiveness: float,
    knowledge_use: float,
    summary: str,
    weak_points: list[str],
    suggestions: str,
    business_summary: str = "",
) -> PracticeScore:
    """幂等写入评分"""
    def _apply(score: PracticeScore) -> None:
        score.total = total
        score.accuracy = accuracy
        score.completeness = completeness
        score.etiquette = etiquette
        score.responsiveness = responsiveness
        score.knowledge_use = knowledge_use
        score.summary = summary
        score.weak_points = weak_points
        score.suggestions = suggestions
        score.business_summary = business_summary

    existing = (
        await db.execute(
            select(PracticeScore).where(PracticeScore.session_id == session.id)
        )
    ).scalar_one_or_none()
    score = existing
    if score is None:
        score = PracticeScore(
            session_id=session.id,
            total=total, accuracy=accuracy, completeness=completeness,
            etiquette=etiquette, responsiveness=responsiveness,
            knowledge_use=knowledge_use, summary=summary,
            weak_points=weak_points, suggestions=suggestions,
            business_summary=business_summary,
        )
        db.add(score)
    else:
        _apply(score)
    try:
        await db.commit()
    except IntegrityError:
        # 【P2-5 修复】并发评分竞态：两个请求同时通过"已有评分"检查后各自插入，
        # 后提交者触发 session_id 唯一约束。回滚后改读已有行做更新，保证幂等
        await db.rollback()
        score = (
            await db.execute(
                select(PracticeScore).where(PracticeScore.session_id == session.id)
            )
        ).scalar_one()
        _apply(score)
        await db.commit()
    await db.refresh(score)
    return score


async def get_hints(
    db: AsyncSession, session: PracticeSession
) -> list[dict[str, Any]]:
    """获取当前对话的知识库提示"""
    history = await get_practice_history(db, session.id)
    last_customer_msgs = [h for h in history if h["role"] == "assistant"][-3:]
    query = " ".join(h["content"] for h in last_customer_msgs)
    if not query:
        cat = get_category(session.category)
        query = cat.label if cat else session.category
    items = await search_knowledge(db, query, top_k=5)
    return [
        {"title": k.title, "content": k.content[:300], "tags": k.tags}
        for k in items
    ]
