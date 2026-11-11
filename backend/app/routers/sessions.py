"""演练会话路由：创建 / 启动 / 学员回复 / 评分 / 回放"""
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
    DrillSession,
    Message,
    MessageRole,
    Scenario,
    Score,
    SessionStatus,
    User,
)
from app.schemas import (
    CustomerReply,
    DrillRecordOut,
    MessageOut,
    PracticeHintOut,
    ScoreOut,
    ScoreSummaryOut,
    SessionCreate,
    SessionOut,
    StudentReply,
)
from app.services.customer_agent import generate_customer_reply
from app.services.knowledge import search_knowledge
from app.services.scorer import score_session

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=201)
async def create_session(
    payload: SessionCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> DrillSession:
    result = await db.execute(select(Scenario).where(Scenario.id == payload.scenario_id))
    scenario = result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(status_code=404, detail="剧本不存在")
    session = DrillSession(
        scenario_id=scenario.id,
        student_id=current.id,
        status=SessionStatus.PENDING,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("", response_model=list[SessionOut])
async def list_my_sessions(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[DrillSession]:
    """当前用户的会话列表（按创建时间倒序）"""
    result = await db.execute(
        select(DrillSession)
        .where(DrillSession.student_id == current.id)
        .order_by(DrillSession.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/scores/me", response_model=list[ScoreSummaryOut])
async def list_my_scores(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[ScoreSummaryOut]:
    """当前用户的评分列表（仪表盘数据源）"""
    result = await db.execute(
        select(Score, DrillSession, Scenario)
        .join(DrillSession, DrillSession.id == Score.session_id)
        .join(Scenario, Scenario.id == DrillSession.scenario_id)
        .where(DrillSession.student_id == current.id)
        .order_by(Score.created_at.desc())
    )
    rows = result.all()
    out: list[ScoreSummaryOut] = []
    for score, sess, scen in rows:
        out.append(
            ScoreSummaryOut(
                id=score.id,
                session_id=score.session_id,
                scenario_id=scen.id,
                scenario_title=scen.title,
                student_id=current.id,
                student_name=current.display_name or current.username,
                total=score.total,
                accuracy=score.accuracy,
                completeness=score.completeness,
                etiquette=score.etiquette,
                responsiveness=score.responsiveness,
                knowledge_use=score.knowledge_use,
                summary=score.summary,
                weak_points=score.weak_points,
                current_turn=sess.current_turn,
                status=sess.status,
                created_at=score.created_at,
            )
        )
    return out


@router.get("/scores/all", response_model=list[ScoreSummaryOut])
async def list_all_scores(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_teacher),
) -> list[ScoreSummaryOut]:
    """全部学员的评分列表（讲师/管理员仪表盘数据源）"""
    result = await db.execute(
        select(Score, DrillSession, Scenario, User)
        .join(DrillSession, DrillSession.id == Score.session_id)
        .join(Scenario, Scenario.id == DrillSession.scenario_id)
        .join(User, User.id == DrillSession.student_id)
        .order_by(Score.created_at.desc())
    )
    rows = result.all()
    out: list[ScoreSummaryOut] = []
    for score, sess, scen, stu in rows:
        out.append(
            ScoreSummaryOut(
                id=score.id,
                session_id=score.session_id,
                scenario_id=scen.id,
                scenario_title=scen.title,
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
                current_turn=sess.current_turn,
                status=sess.status,
                created_at=score.created_at,
            )
        )
    return out


async def _build_drill_records(
    db: AsyncSession, *filters
) -> list[DrillRecordOut]:
    """剧本演练真实记录：会话 + 剧本标题 + 学员名 + （如有）评分"""
    stmt = (
        select(DrillSession, Scenario, Score, User)
        .join(Scenario, Scenario.id == DrillSession.scenario_id)
        .outerjoin(Score, Score.session_id == DrillSession.id)
        .outerjoin(User, User.id == DrillSession.student_id)
        .order_by(DrillSession.created_at.desc())
    )
    for f in filters:
        if f is not None:
            stmt = stmt.where(f)
    result = await db.execute(stmt)
    out: list[DrillRecordOut] = []
    for sess, scen, score, stu in result.all():
        out.append(
            DrillRecordOut(
                id=sess.id,
                scenario_id=scen.id,
                scenario_title=scen.title,
                student_id=sess.student_id,
                student_name=(stu.display_name or stu.username) if stu else None,
                status=sess.status,
                current_turn=sess.current_turn,
                max_turns=scen.max_turns,
                started_at=sess.started_at,
                finished_at=sess.finished_at,
                created_at=sess.created_at,
                has_score=score is not None,
                total=score.total if score else None,
                accuracy=score.accuracy if score else None,
                completeness=score.completeness if score else None,
                etiquette=score.etiquette if score else None,
                responsiveness=score.responsiveness if score else None,
                knowledge_use=score.knowledge_use if score else None,
                summary=score.summary if score else None,
                weak_points=score.weak_points if score else None,
            )
        )
    return out


@router.get("/records", response_model=list[DrillRecordOut])
async def my_drill_records(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[DrillRecordOut]:
    """当前学员的全部剧本演练记录（含未评分/进行中）"""
    return await _build_drill_records(db, DrillSession.student_id == current.id)


@router.get("/records/all", response_model=list[DrillRecordOut])
async def all_drill_records(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_teacher),
) -> list[DrillRecordOut]:
    """全部学员的剧本演练记录（讲师/管理员）"""
    return await _build_drill_records(db)


@router.post("/{session_id}/start", response_model=CustomerReply)
async def start_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> CustomerReply:
    """启动演练：把剧本开场白作为客户首句推送"""
    result = await db.execute(select(DrillSession).where(DrillSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.student_id != current.id:
        # 【P1-1 修复】演练行为（启动/回复/评分）保持仅属主可操作，不允许他人代练；
        # 只读回放接口的讲师权限放开见下方各 GET 接口。
        raise HTTPException(status_code=403, detail="无权操作此会话")
    if session.status != SessionStatus.PENDING:
        raise HTTPException(status_code=400, detail="会话已启动")

    opening_msg = Message(
        session_id=session.id,
        role=MessageRole.CUSTOMER,
        content=session.scenario.opening,
        turn=1,
    )
    db.add(opening_msg)
    session.status = SessionStatus.IN_PROGRESS
    session.current_turn = 1
    # 【P1-3 修复】datetime.utcnow() 已在 Python 3.13 弃用，统一改用 timeutil.utcnow()
    session.started_at = utcnow()
    await db.commit()
    await db.refresh(session)

    return CustomerReply(
        content=session.scenario.opening,
        is_finished=False,
        next_turn=1,
    )


@router.post("/{session_id}/reply", response_model=CustomerReply)
async def student_reply(
    session_id: str,
    payload: StudentReply,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> CustomerReply:
    """学员回复 -> 触发 AI 客户生成下一句"""
    result = await db.execute(select(DrillSession).where(DrillSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.student_id != current.id:
        # 【P1-1 修复】回复演练保持仅属主可操作（同 start_session）
        raise HTTPException(status_code=403, detail="无权操作此会话")
    if session.status != SessionStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="会话未在进行中")

    return await generate_customer_reply(db, session, payload.content)


@router.post("/{session_id}/cancel", response_model=SessionOut)
async def cancel_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> DrillSession:
    """【P4-3 修复】放弃演练。

    SessionStatus.CANCELED 原先已定义但没有任何入口：学员中途退出后会话永远挂
    in_progress，统计口径被污染。这里提供显式放弃入口，仅属主可操作（与 start/reply/score 一致）。
    """
    result = await db.execute(select(DrillSession).where(DrillSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.student_id != current.id:
        raise HTTPException(status_code=403, detail="无权操作此会话")
    if session.status not in (SessionStatus.PENDING, SessionStatus.IN_PROGRESS):
        raise HTTPException(status_code=400, detail="会话已结束，无法放弃")
    session.status = SessionStatus.CANCELED
    session.finished_at = utcnow()
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/{session_id}/score", response_model=ScoreOut)
async def get_score(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Score:
    """获取已有评分（不重新计算）"""
    # 【P1-1 修复】此接口原先完全没有权限校验，任何登录用户可越权读取他人评分（IDOR）；
    # 现在先加载会话再校验：属主本人或讲师/管理员可读。
    session = (
        await db.execute(select(DrillSession).where(DrillSession.id == session_id))
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    forbid_if_not_viewable(current, session.student_id)
    result = await db.execute(select(Score).where(Score.session_id == session_id))
    score = result.scalar_one_or_none()
    if not score:
        raise HTTPException(status_code=404, detail="尚未评分")
    return score


@router.post("/{session_id}/score", response_model=ScoreOut)
async def score(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """结束并评分"""
    result = await db.execute(select(DrillSession).where(DrillSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.student_id != current.id:
        # 【P1-1 修复】发起评分保持仅属主可操作（同 start_session）
        raise HTTPException(status_code=403, detail="无权操作此会话")
    return await score_session(db, session)


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[Message]:
    """获取对话记录（回放）"""
    # 【P1-1 修复】此接口原先完全没有权限校验，任何登录用户可越权读取他人对话记录（IDOR）；
    # 现在先加载会话再校验：属主本人或讲师/管理员可读。
    session = (
        await db.execute(select(DrillSession).where(DrillSession.id == session_id))
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    forbid_if_not_viewable(current, session.student_id)
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        # 【P1-3 修复】排序补次级键：created_at 相同（同一秒写入）时按轮次、
        # 再按角色（customer < student，与实际产生顺序一致）保证回放顺序稳定
        .order_by(Message.created_at, Message.turn, Message.role)
    )
    return list(result.scalars().all())


@router.get("/{session_id}/hints", response_model=list[PracticeHintOut])
async def get_hints(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[PracticeHintOut]:
    """获取剧本演练的知识提示：按剧本标题 + 最近客户消息检索"""
    result = await db.execute(select(DrillSession).where(DrillSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    # 【P1-1 修复】属主校验放开为"属主或讲师/管理员"——讲师回放学员演练时同样需要知识提示侧栏
    forbid_if_not_viewable(current, session.student_id)

    msgs = (
        await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            # 【P1-3 修复】同 list_messages，补排序次级键保证取"最近 3 条客户消息"顺序稳定
            .order_by(Message.created_at, Message.turn, Message.role)
        )
    ).scalars().all()
    recent_customer = [m.content for m in msgs if m.role == MessageRole.CUSTOMER][-3:]
    query = " ".join(recent_customer) or session.scenario.title
    items = await search_knowledge(db, f"{session.scenario.title} {query}", top_k=5)
    return [
        PracticeHintOut(title=k.title, content=k.content[:300], tags=k.tags)
        for k in items
    ]


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> DrillSession:
    result = await db.execute(select(DrillSession).where(DrillSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    # 【P1-1 修复】原先仅属主可看（讲师回放学员会话必 403，与前端"演练记录-查看"入口矛盾）；
    # 现统一为属主本人或讲师/管理员可看
    forbid_if_not_viewable(current, session.student_id)
    return session
