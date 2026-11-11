"""模拟客户进线：客户"打进来" → 坐席接听 → 点话术=回复客户 → AI 客户继续对话。

设计口径（为什么长这样）：

- **复用演练场引擎而不是另起炉灶**：客户人设生成（`generate_persona`）、客户回复引擎
  （`generate_customer_reply`，含知识库检索/轮次推进/单事务）全部复用 PracticeSession。
  模拟通话和演练场的区别只有两点——回复方式是**点话术**（带 script_id 落库），
  以及入口/界面对准「接一通电话」而不是「开始一次练习」。
- **channel='live_sim'**：演练场列表（/api/practice/sessions）按 channel 过滤，
  两边的记录互不污染；模拟通话不自动评分，想复盘可挂断后调演练场的评分接口。
- **点击话术 = 回复客户**：坐席点话术时，服务端做三件事——
  ① `record_use` 记一次使用（待录音清单排序跟着变）；② 话术正文作为坐席发言进对话；
  ③ AI 客户基于正文生成下一句。录音由前端播给坐席听（三级判定不变），客户"听到"的是文本。
- **LLM 不可用时的行为**：simulate 的 人设/开场白 有兜底（生成失败给默认值，不阻断）；
  use-script/free-reply 的客户回复依赖 LLM，失败会 503——通话面板上提示稍后重试，
  坐席消息不会落库（单事务回滚），不会出现"说了一半没人接话"的脏状态。
"""
import random

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.timeutil import utcnow
from app.database import get_db
from app.models import (
    LiveScript,
    MessageRole,
    PracticeMessage,
    PracticeSession,
    SessionStatus,
    User,
)
from app.schemas import (
    LiveCallFreeReplyIn,
    LiveCallScriptIn,
    LiveCallSimulateIn,
    PracticeMessageOut,
    PracticeReplyOut,
    PracticeSessionOut,
)
from app.services import practice_agent
from app.services.live_scripts import record_use, script_payload

router = APIRouter(prefix="/api/live/calls", tags=["live-call-sim"])


async def _own_session(db: AsyncSession, session_id: str, user: User) -> PracticeSession:
    """取属主是当前用户的模拟通话会话；不存在/不是模拟通话/不是你的，一律挡下。"""
    session = await db.get(PracticeSession, session_id)
    if session is None or session.channel != "live_sim":
        raise HTTPException(status_code=404, detail="模拟通话不存在")
    if session.student_id != user.id:
        raise HTTPException(status_code=403, detail="只能操作自己接的通话")
    return session


@router.post("/simulate", response_model=PracticeSessionOut, status_code=201)
async def simulate_incoming_call(
    payload: LiveCallSimulateIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PracticeSession:
    """模拟一通来电：生成客户人设 + 开场白（还没接，等坐席点接听）。"""
    category = payload.category or random.choice(
        [c.key for c in practice_agent.get_categories()]
    )
    persona, opening = await practice_agent.generate_persona(
        db, category, payload.difficulty
    )
    session = PracticeSession(
        student_id=current.id,
        category=category,
        difficulty=payload.difficulty,
        persona=persona,
        opening=opening,
        max_turns=10,  # 一通电话比打字练习轮次略多
        status=SessionStatus.PENDING,
        channel="live_sim",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("", response_model=list[PracticeSessionOut])
async def list_my_calls(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[PracticeSession]:
    """我的模拟通话记录（新→旧）。"""
    result = await db.execute(
        select(PracticeSession)
        .where(PracticeSession.student_id == current.id)
        .where(PracticeSession.channel == "live_sim")
        .order_by(PracticeSession.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/{call_id}", response_model=list[PracticeMessageOut])
async def get_call_transcript(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[PracticeMessage]:
    """一通模拟通话的完整对话记录（回放用）。"""
    session = await _own_session(db, call_id, current)
    result = await db.execute(
        select(PracticeMessage)
        .where(PracticeMessage.session_id == session.id)
        .order_by(PracticeMessage.created_at, PracticeMessage.turn, PracticeMessage.role)
    )
    return list(result.scalars().all())


@router.post("/{call_id}/answer", response_model=PracticeReplyOut)
async def answer_call(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PracticeReplyOut:
    """接听：PENDING → IN_PROGRESS，客户开场白作为第一条消息进对话流。

    与演练场 /start 同一套动作；区别只是语义叫「接听」，且响应里带不带
    开场白都行——前端接听后会拉一次完整对话记录，这里照演练场口径返回开场白。
    """
    session = await _own_session(db, call_id, current)
    if session.status != SessionStatus.PENDING:
        raise HTTPException(status_code=400, detail="通话不在待接听状态")
    db.add(
        PracticeMessage(
            session_id=session.id,
            role=MessageRole.CUSTOMER,
            content=session.opening,
            turn=1,
        )
    )
    session.status = SessionStatus.IN_PROGRESS
    session.current_turn = 1
    session.started_at = utcnow()
    await db.commit()
    await db.refresh(session)
    return PracticeReplyOut(
        content=session.opening,
        is_finished=False,
        next_turn=1,
    )


@router.post("/{call_id}/use-script", response_model=PracticeReplyOut)
async def use_script_reply(
    call_id: str,
    payload: LiveCallScriptIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PracticeReplyOut:
    """点击话术 = 回复客户。

    话术必须存在；正文作为坐席发言进对话并标记 script_id/via=script；
    同时记一次使用（和实战面板点播放同一套计数）。
    """
    session = await _own_session(db, call_id, current)
    if session.status != SessionStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="通话未接听或已结束")
    script = await db.get(LiveScript, payload.script_id)
    if script is None:
        raise HTTPException(status_code=404, detail="话术不存在")
    await record_use(db, script)  # 点了就是用了：热度与待录音排序同步更新
    return await practice_agent.generate_customer_reply(
        db, session, script.text, script_id=script.id, via="script"
    )


@router.post("/{call_id}/free-reply", response_model=PracticeReplyOut)
async def free_reply(
    call_id: str,
    payload: LiveCallFreeReplyIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PracticeReplyOut:
    """自由输入回复：话术覆盖不了客户问题时，像真实通话那样自己说。"""
    session = await _own_session(db, call_id, current)
    if session.status != SessionStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="通话未接听或已结束")
    return await practice_agent.generate_customer_reply(
        db, session, payload.content, via="free"
    )


@router.post("/{call_id}/hangup", response_model=PracticeSessionOut)
async def hangup(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PracticeSession:
    """挂断通话。"""
    session = await _own_session(db, call_id, current)
    if session.status not in (SessionStatus.PENDING, SessionStatus.IN_PROGRESS):
        raise HTTPException(status_code=400, detail="通话已结束")
    session.status = SessionStatus.FINISHED
    session.finished_at = utcnow()
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/{call_id}/scripts-summary")
async def call_scripts_summary(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    """这通电话用了哪些话术（挂断后的小结数据，纯本地统计不走 LLM）。"""
    await _own_session(db, call_id, current)
    result = await db.execute(
        select(PracticeMessage).where(
            PracticeMessage.session_id == call_id,
            PracticeMessage.via == "script",
        )
    )
    used = []
    for msg in result.scalars().all():
        if not msg.script_id:
            continue
        script = await db.get(LiveScript, msg.script_id)
        if script is None:
            continue
        used.append(
            {
                "script_id": script.id,
                "code": script.code,
                "label": script.label,
                "text": script.text,
                # script_payload 返回的是完整话术字典（含音频信息），前端小结抽屉可直接复用播放逻辑
                "audio": script_payload(script),
            }
        )
    return {"used_count": len(used), "scripts": used}
