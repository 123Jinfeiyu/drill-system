"""评分 service"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.timeutil import utcnow
from app.models import DrillSession, Message, MessageRole, Score, SessionStatus
from app.services.knowledge import search_knowledge
from app.services.llm_client import llm_client
from app.services.prompts import build_scorer_messages
# 【P2-1 修复】评分容错助手（_clamp/_coerce_number/_extract_score/_pick 及别名表）
# 原先在本文件内，practice_agent 有一份缺嵌套容错的重复实现，统一收敛到 score_utils
from app.services.score_utils import (
    SUMMARY_ALIASES,
    WEAK_ALIASES,
    extract_score,
    pick,
    unwrap,
)


async def _load_dialog(db: AsyncSession, session_id: str) -> list[dict[str, str]]:
    """加载对话记录转成 LLM 可读格式"""
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        # 【P1-3 修复】排序补次级键：created_at 精度只到秒，同一秒内写入的多条消息
        # 顺序可能不稳定；按轮次、再按角色（customer < student）保证评分对话顺序稳定
        .order_by(Message.created_at, Message.turn, Message.role)
    )
    msgs = result.scalars().all()
    return [
        {
            "role": "客户" if m.role == MessageRole.CUSTOMER else "学员",
            "content": m.content,
        }
        for m in msgs
    ]


# 【P2-1 修复】_clamp/_coerce_number/_unwrap/_extract_score/_pick 及别名表
# 已移至 score_utils.py，本文件改为从那里导入


async def _upsert_score(
    db: AsyncSession,
    session: DrillSession,
    *,
    total: float,
    accuracy: float,
    completeness: float,
    etiquette: float,
    responsiveness: float,
    knowledge_use: float,
    summary: str,
    weak_points: list[str],
) -> Score:
    """幂等写入评分：同一 session 已有记录则更新，否则新增。"""
    def _apply(score: Score) -> None:
        score.total = total
        score.accuracy = accuracy
        score.completeness = completeness
        score.etiquette = etiquette
        score.responsiveness = responsiveness
        score.knowledge_use = knowledge_use
        score.summary = summary
        score.weak_points = weak_points

    existing = (
        await db.execute(select(Score).where(Score.session_id == session.id))
    ).scalar_one_or_none()
    score = existing
    if score is None:
        score = Score(
            session_id=session.id,
            total=total,
            accuracy=accuracy,
            completeness=completeness,
            etiquette=etiquette,
            responsiveness=responsiveness,
            knowledge_use=knowledge_use,
            summary=summary,
            weak_points=weak_points,
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
            await db.execute(select(Score).where(Score.session_id == session.id))
        ).scalar_one()
        _apply(score)
        await db.commit()
    await db.refresh(score)
    return score


async def score_session(db: AsyncSession, session: DrillSession) -> Score:
    """对一次演练会话评分"""
    # 1. 先确保会话状态为 FINISHED
    if session.status != SessionStatus.FINISHED:
        session.status = SessionStatus.FINISHED
        # 【P1-3 修复】datetime.utcnow() 已弃用，统一改用 timeutil.utcnow()
        session.finished_at = utcnow()
        await db.commit()

    # 2. 加载对话记录
    dialog = await _load_dialog(db, session.id)
    if not dialog:
        return await _upsert_score(
            db,
            session,
            total=0.0,
            accuracy=0.0,
            completeness=0.0,
            etiquette=0.0,
            responsiveness=0.0,
            knowledge_use=0.0,
            summary="无对话记录，无法评分",
            weak_points=["未进行任何对话"],
        )

    # 2.1 检索知识库，注入到评分 prompt（作为业务背景参考）
    kb_items = await search_knowledge(db, session.scenario.title, top_k=3)
    knowledge = [{"title": k.title, "content": k.content} for k in kb_items]

    # 3. 调用 DeepSeek 评分（强制 JSON 输出）
    messages = build_scorer_messages(
        scenario_title=session.scenario.title,
        knowledge_points=session.scenario.knowledge_points,
        reference_answer=session.scenario.reference_answer,
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
        raw = unwrap(raw) if isinstance(raw, dict) else {}
    except HTTPException:
        # 兜底降级：模型输出非法 JSON 时，不阻断评分流程，给出中性结果
        raw = {}

    # 4. 容错提取 + 范围校验
    accuracy = extract_score(raw, "accuracy")
    completeness = extract_score(raw, "completeness")
    etiquette = extract_score(raw, "etiquette")
    responsiveness = extract_score(raw, "responsiveness")
    knowledge_use = extract_score(raw, "knowledge_use")
    total = round(
        (accuracy + completeness + etiquette + responsiveness + knowledge_use) / 5, 2
    )

    summary_val = pick(raw, SUMMARY_ALIASES, default="")
    summary = str(summary_val)[:1000]
    if not summary:
        summary = "本次演练暂无法生成详细评语（评分模型输出异常）；各维度按中性值处理，建议重试评分。"
        total = total or 0.0

    weak_raw = pick(raw, WEAK_ALIASES, default=[])
    if not isinstance(weak_raw, list):
        weak_raw = [weak_raw]
    weak_points = [str(p)[:100] for p in weak_raw][:5]
    if not weak_points:
        weak_points = ["评分模型输出异常，未能识别薄弱点"]

    # 5. 幂等入库
    return await _upsert_score(
        db,
        session,
        total=total,
        accuracy=accuracy,
        completeness=completeness,
        etiquette=etiquette,
        responsiveness=responsiveness,
        knowledge_use=knowledge_use,
        summary=summary,
        weak_points=weak_points,
    )
