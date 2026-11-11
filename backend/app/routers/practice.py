"""Q&A 演练场路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    forbid_if_not_viewable,
    get_current_user,
    require_teacher,
)
from app.core.timeutil import utcnow
from app.database import get_db
from app.models import (
    PracticeMessage,
    PracticeScore,
    PracticeSession,
    MessageRole,
    SessionStatus,
    User,
)
from app.schemas import (
    PracticeCategoryOut,
    PracticeHintOut,
    PracticeMessageOut,
    PracticeReplyCreate,
    PracticeReplyOut,
    PracticeScoreOut,
    PracticeScoreSummaryOut,
    PracticeSessionCreate,
    PracticeSessionOut,
)
from app.services.practice_agent import (
    generate_customer_reply,
    generate_persona,
    get_categories,
    get_hints,
    score_practice_session,
)

router = APIRouter(prefix="/api/practice", tags=["practice"])


@router.get("/categories", response_model=list[PracticeCategoryOut])
async def list_categories() -> list[PracticeCategoryOut]:
    """获取演练场业务分类列表"""
    return get_categories()


@router.post("/sessions", response_model=PracticeSessionOut, status_code=201)
async def create_practice_session(
    payload: PracticeSessionCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PracticeSession:
    """创建演练场会话：AI 动态生成客户人设和开场白"""
    persona, opening = await generate_persona(db, payload.category, payload.difficulty)
    session = PracticeSession(
        student_id=current.id,
        category=payload.category,
        difficulty=payload.difficulty,
        persona=persona,
        opening=opening,
        max_turns=payload.max_turns,
        status=SessionStatus.PENDING,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions", response_model=list[PracticeSessionOut])
async def list_my_practice_sessions(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[PracticeSession]:
    """当前用户的演练场会话列表（不含模拟进线，那在 /api/live/calls）"""
    result = await db.execute(
        select(PracticeSession)
        .where(PracticeSession.student_id == current.id)
        .where(PracticeSession.channel == "practice")
        .order_by(PracticeSession.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/sessions/{session_id}", response_model=PracticeSessionOut)
async def get_practice_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PracticeSession:
    result = await db.execute(
        select(PracticeSession).where(PracticeSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="演练会话不存在")
    # 【P1-1 修复】原先仅属主可看（讲师从"演练统计-查看"进入学员回放必 403）；
    # 现统一为属主本人或讲师/管理员可看
    forbid_if_not_viewable(current, session.student_id)
    return session


@router.post("/sessions/{session_id}/start", response_model=PracticeReplyOut)
async def start_practice_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PracticeReplyOut:
    """启动演练：推送 AI 生成的开场白"""
    result = await db.execute(
        select(PracticeSession).where(PracticeSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="演练会话不存在")
    if session.student_id != current.id:
        # 【P1-1 修复】启动演练保持仅属主可操作，不允许他人代练；
        # 只读回放接口的讲师权限放开见各 GET 接口
        raise HTTPException(status_code=403, detail="无权操作此会话")
    if session.status != SessionStatus.PENDING:
        raise HTTPException(status_code=400, detail="会话已启动")

    opening_msg = PracticeMessage(
        session_id=session.id,
        role=MessageRole.CUSTOMER,
        content=session.opening,
        turn=1,
    )
    db.add(opening_msg)
    session.status = SessionStatus.IN_PROGRESS
    session.current_turn = 1
    # 【P1-3 修复】datetime.utcnow() 已在 Python 3.13 弃用，统一改用 timeutil.utcnow()
    session.started_at = utcnow()
    await db.commit()
    await db.refresh(session)

    return PracticeReplyOut(
        content=session.opening,
        is_finished=False,
        next_turn=1,
    )


@router.post("/sessions/{session_id}/reply", response_model=PracticeReplyOut)
async def practice_reply(
    session_id: str,
    payload: PracticeReplyCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PracticeReplyOut:
    """学员回复 -> 触发 AI 客户生成下一句"""
    result = await db.execute(
        select(PracticeSession).where(PracticeSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="演练会话不存在")
    if session.student_id != current.id:
        # 【P1-1 修复】回复演练保持仅属主可操作（同 start 接口）
        raise HTTPException(status_code=403, detail="无权操作此会话")
    if session.status != SessionStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="会话未在进行中")
    return await generate_customer_reply(db, session, payload.content)


@router.post("/sessions/{session_id}/cancel", response_model=PracticeSessionOut)
async def cancel_practice_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PracticeSession:
    """【P4-3 修复】放弃演练场会话（同剧本演练，仅属主可操作）"""
    result = await db.execute(
        select(PracticeSession).where(PracticeSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="演练会话不存在")
    if session.student_id != current.id:
        raise HTTPException(status_code=403, detail="无权操作此会话")
    if session.status not in (SessionStatus.PENDING, SessionStatus.IN_PROGRESS):
        raise HTTPException(status_code=400, detail="会话已结束，无法放弃")
    session.status = SessionStatus.CANCELED
    session.finished_at = utcnow()
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions/{session_id}/messages", response_model=list[PracticeMessageOut])
async def list_practice_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[PracticeMessage]:
    """获取演练场对话记录"""
    # 【P1-1 修复】此接口原先完全没有权限校验，任何登录用户可越权读取他人对话记录（IDOR）；
    # 现在先加载会话再校验：属主本人或讲师/管理员可读
    session = (
        await db.execute(
            select(PracticeSession).where(PracticeSession.id == session_id)
        )
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="演练会话不存在")
    forbid_if_not_viewable(current, session.student_id)
    result = await db.execute(
        select(PracticeMessage)
        .where(PracticeMessage.session_id == session_id)
        # 【P1-3 修复】排序补次级键：created_at 相同时按轮次、再按角色稳定排序
        .order_by(PracticeMessage.created_at, PracticeMessage.turn, PracticeMessage.role)
    )
    return list(result.scalars().all())


@router.get("/sessions/{session_id}/score", response_model=PracticeScoreOut)
async def get_practice_score(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PracticeScore:
    """获取已有评分"""
    # 【P1-1 修复】此接口原先完全没有权限校验，任何登录用户可越权读取他人评分（IDOR）；
    # 现在先加载会话再校验：属主本人或讲师/管理员可读
    session = (
        await db.execute(
            select(PracticeSession).where(PracticeSession.id == session_id)
        )
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="演练会话不存在")
    forbid_if_not_viewable(current, session.student_id)
    result = await db.execute(
        select(PracticeScore).where(PracticeScore.session_id == session_id)
    )
    score = result.scalar_one_or_none()
    if not score:
        raise HTTPException(status_code=404, detail="尚未评分")
    return score


@router.post("/sessions/{session_id}/score", response_model=PracticeScoreOut)
async def score_practice(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """结束并评分"""
    result = await db.execute(
        select(PracticeSession).where(PracticeSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="演练会话不存在")
    if session.student_id != current.id:
        # 【P1-1 修复】发起评分保持仅属主可操作（同 start 接口）
        raise HTTPException(status_code=403, detail="无权操作此会话")
    return await score_practice_session(db, session)


@router.get("/sessions/{session_id}/hints", response_model=list[PracticeHintOut])
async def get_session_hints(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[dict]:
    """获取当前对话的知识库提示"""
    result = await db.execute(
        select(PracticeSession).where(PracticeSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="演练会话不存在")
    # 【P1-1 修复】属主校验放开为"属主或讲师/管理员"——讲师回放学员演练时同样需要知识提示侧栏
    forbid_if_not_viewable(current, session.student_id)
    return await get_hints(db, session)


@router.get("/scores/me", response_model=list[PracticeScoreSummaryOut])
async def list_my_practice_scores(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[PracticeScoreSummaryOut]:
    """当前用户的演练场评分列表"""
    result = await db.execute(
        select(PracticeScore, PracticeSession, User)
        .join(PracticeSession, PracticeSession.id == PracticeScore.session_id)
        .join(User, User.id == PracticeSession.student_id)
        .where(PracticeSession.student_id == current.id)
        .order_by(PracticeScore.created_at.desc())
    )
    rows = result.all()
    out: list[PracticeScoreSummaryOut] = []
    for score, sess, stu in rows:
        out.append(
            PracticeScoreSummaryOut(
                id=score.id,
                session_id=score.session_id,
                category=sess.category,
                student_id=stu.id,
                student_name=stu.display_name or stu.username,
                total=score.total,
                accuracy=score.accuracy,
                completeness=score.completeness,
                etiquette=score.etiquette,
                responsiveness=score.responsiveness,
                knowledge_use=score.knowledge_use,
                summary=score.summary,
                weak_points=score.weak_points,
                suggestions=score.suggestions,
                current_turn=sess.current_turn,
                status=sess.status,
                created_at=score.created_at,
            )
        )
    return out


@router.get("/scores/all", response_model=list[PracticeScoreSummaryOut])
async def list_all_practice_scores(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_teacher),
) -> list[PracticeScoreSummaryOut]:
    """全部学员的演练场评分列表（讲师/管理员）"""
    result = await db.execute(
        select(PracticeScore, PracticeSession, User)
        .join(PracticeSession, PracticeSession.id == PracticeScore.session_id)
        .join(User, User.id == PracticeSession.student_id)
        .order_by(PracticeScore.created_at.desc())
    )
    rows = result.all()
    out: list[PracticeScoreSummaryOut] = []
    for score, sess, stu in rows:
        out.append(
            PracticeScoreSummaryOut(
                id=score.id,
                session_id=score.session_id,
                category=sess.category,
                student_id=stu.id,
                student_name=stu.display_name or stu.username,
                total=score.total,
                accuracy=score.accuracy,
                completeness=score.completeness,
                etiquette=score.etiquette,
                responsiveness=score.responsiveness,
                knowledge_use=score.knowledge_use,
                summary=score.summary,
                weak_points=score.weak_points,
                suggestions=score.suggestions,
                current_turn=sess.current_turn,
                status=sess.status,
                created_at=score.created_at,
            )
        )
    return out
