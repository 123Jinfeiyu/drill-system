"""CodexFDE 工作台：需求合同、任务状态机、证据链与责任分离。

设计边界（重要，别越界）：
- 本路由**不执行任何命令**。它只接收「已经发生过的运行输出」并作出判断。
  真正的执行由操作者或其智能体在工作台之外完成，工作台负责的是**证据诚信**。
- 规则全部来自 ``app.services.fde_ledger``，路由只做持久化与编排，不自己发明判定。
"""
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.timeutil import utcnow
from app.database import get_db
from app.models import FdeEvidence, FdeProject, FdeTask, FdeTaskEvent, User
from app.schemas import (FdeAcceptIn, FdeEvidenceCreate, FdeEvidenceOut,
                         FdeEventOut, FdeProjectCreate, FdeProjectOut,
                         FdeSpecValidateIn, FdeSpecValidateOut, FdeTaskCreate,
                         FdeTaskDetail, FdeTaskOut, FdeTransitionIn)
from app.services import fde_ledger as ledger

router = APIRouter(prefix="/api/fde", tags=["codex-fde-workbench"])


# --------------------------------------------------------------------------- 内部
def _actor(user: User) -> str:
    return user.display_name or user.username


async def _get_task(db: AsyncSession, task_id: str) -> FdeTask:
    task = (await db.execute(select(FdeTask).where(FdeTask.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


async def _evidences(db: AsyncSession, task_id: str) -> list[FdeEvidence]:
    rows = await db.execute(
        select(FdeEvidence)
        .where(FdeEvidence.task_id == task_id)
        .order_by(FdeEvidence.observed_at, FdeEvidence.created_at)
    )
    return list(rows.scalars())


async def _events(db: AsyncSession, task_id: str) -> list[FdeTaskEvent]:
    rows = await db.execute(
        select(FdeTaskEvent)
        .where(FdeTaskEvent.task_id == task_id)
        .order_by(FdeTaskEvent.created_at, FdeTaskEvent.id)
    )
    return list(rows.scalars())


async def _depends(db: AsyncSession, task: FdeTask) -> list[dict]:
    """把 depends_on 里的任务编号解析成门禁需要的上下文。"""
    codes = list(task.depends_on or [])
    if not codes:
        return []
    rows = await db.execute(select(FdeTask).where(FdeTask.code.in_(codes)))
    found = {t.code: t for t in rows.scalars()}
    return [
        {
            "code": code,
            "exists": code in found,
            "state": found[code].state if code in found else None,
            "acceptance": found[code].acceptance if code in found else None,
            "title": found[code].title if code in found else None,
        }
        for code in codes
    ]


async def _builder_name(db: AsyncSession, task: FdeTask) -> str:
    """把构建者的主键解析成具名身份。

    若不解析，责任分离就变成「hex 主键 vs 显示名」，恒不相等、形同虚设。
    """
    row = await db.execute(select(User).where(User.id == task.created_by))
    owner = row.scalar_one_or_none()
    return (owner.display_name or owner.username) if owner else task.created_by


async def _log(db: AsyncSession, task: FdeTask, kind: str, actor: str, detail: str,
               from_state: str | None = None, to_state: str | None = None) -> None:
    """只追加，不覆盖——失败或返工的历史同样是证据。"""
    db.add(FdeTaskEvent(task_id=task.id, kind=kind, actor=actor, detail=detail,
                        from_state=from_state, to_state=to_state))


def _task_out(task: FdeTask) -> FdeTaskOut:
    return FdeTaskOut(
        id=task.id, project_id=task.project_id, project_name=task.project.name,
        code=task.code, title=task.title, request=task.request,
        spec_snapshot=task.spec_snapshot, spec_hash=task.spec_hash,
        spec_issues=list(task.spec_issues or []), state=task.state,
        state_label=ledger.STAGE_LABELS.get(task.state, task.state),
        acceptance=task.acceptance, accepted_by=task.accepted_by,
        accepted_at=task.accepted_at, depends_on=list(task.depends_on or []),
        created_by=task.created_by, created_at=task.created_at,
    )


async def _detail(db: AsyncSession, task: FdeTask) -> FdeTaskDetail:
    evidences = await _evidences(db, task.id)
    events = await _events(db, task.id)
    deps = await _depends(db, task)
    chain = ledger.chain_summary(evidences)
    builder_name = await _builder_name(db, task)
    gate = ledger.evaluate_gate(
        state=task.state,
        evidence_complete=chain["evidence_complete"],
        acceptance=task.acceptance,
        builder=builder_name,
        reviewer=task.accepted_by,
        depends_on=[d for d in deps if d["exists"]],
    )
    missing = [d["code"] for d in deps if not d["exists"]]
    if missing:
        gate["allowed"] = False
        gate["code"] = ledger.GATE_BLOCKED
        gate["blockers"] = [f"前置任务不存在：{'、'.join(missing)}"] + gate["blockers"]
        gate["reason"] = "；".join(gate["blockers"])
    repair = ledger.repair_loop_projection(events)
    summary = ledger.delivery_summary(
        code=task.code, title=task.title, state=task.state,
        acceptance=task.acceptance, accepted_by=task.accepted_by,
        accepted_at=task.accepted_at, builder=builder_name,
        spec_snapshot=task.spec_snapshot, evidences=evidences,
        depends_on=[d for d in deps if d["exists"]],
    )
    return FdeTaskDetail(
        **_task_out(task).model_dump(),
        evidences=[FdeEvidenceOut.model_validate(e) for e in evidences],
        events=[FdeEventOut.model_validate(e) for e in events],
        evidence_complete=chain["evidence_complete"],
        issues=chain["issues"],
        chain=chain,
        gate=gate,
        next_states=list(ledger.next_states(task.state)),
        blockers_detail=deps,
        repair_loop=repair,
        delivery_summary=summary,
    )


# --------------------------------------------------------------------------- 元信息
@router.get("/meta")
async def meta(_: User = Depends(get_current_user)) -> dict:
    """工作台自己的口径：章节、状态、门禁原因都在这里对齐。"""
    return {
        "spec_sections": list(ledger.SPEC_SECTIONS),
        "stages": [{"key": s, "label": ledger.STAGE_LABELS[s]} for s in ledger.TASK_STATES],
        "transitions": {k: list(v) for k, v in ledger.TRANSITIONS.items()},
        "terminal_states": list(ledger.TERMINAL_STATES),
        "agent_prefix": ledger.AGENT_PREFIX,
        "evidence_phases": ["red", "diff", "green", "observation"],
        "event_kinds": ["spec", "evidence", "transition", "evaluate", "acceptance", "rejected"],
        "repair_loop_max_rounds": ledger.REPAIR_LOOP_MAX_ROUNDS,
        "delivery_four_elements": ["结果", "证据", "边界", "交接"],
        "principle": "evidence_complete 是程序的判断，acceptance 是人的判断，两者不得互相顶替。",
    }


@router.post("/specs/validate", response_model=FdeSpecValidateOut)
async def validate_spec(payload: FdeSpecValidateIn, _: User = Depends(get_current_user)):
    """需求入口：结构不合格就当场说清缺哪一节，不做静默放行。"""
    issues = ledger.validate_spec(payload.spec_snapshot)
    parsed = ledger.parse_spec(payload.spec_snapshot)
    return FdeSpecValidateOut(
        ok=not issues, issues=issues,
        sections={s: parsed.get(s, "") for s in ledger.SPEC_SECTIONS},
        missing=[s for s in ledger.SPEC_SECTIONS if s not in parsed],
        template=ledger.SPEC_TEMPLATE,
    )


# --------------------------------------------------------------------------- 项目
@router.get("/projects", response_model=list[FdeProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return list((await db.execute(select(FdeProject).order_by(FdeProject.created_at.desc()))).scalars())


@router.post("/projects", response_model=FdeProjectOut, status_code=201)
async def create_project(payload: FdeProjectCreate, db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)):
    if (await db.execute(select(FdeProject).where(FdeProject.code == payload.code))).scalar_one_or_none():
        raise HTTPException(409, "项目编号已存在，原项目不会被覆盖")
    item = FdeProject(**payload.model_dump(), owner_id=user.id)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


# --------------------------------------------------------------------------- 任务
@router.get("/tasks", response_model=list[FdeTaskOut])
async def list_tasks(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = list((await db.execute(select(FdeTask).order_by(FdeTask.created_at.desc()))).scalars())
    return [_task_out(t) for t in rows]


@router.post("/tasks", response_model=FdeTaskOut, status_code=201)
async def create_task(payload: FdeTaskCreate, db: AsyncSession = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """登记任务 = 冻结需求。合同不完整就拒绝进门（L03 的硬边界）。"""
    if not (await db.execute(select(FdeProject).where(FdeProject.id == payload.project_id))).scalar_one_or_none():
        raise HTTPException(404, "项目不存在")
    if (await db.execute(select(FdeTask).where(FdeTask.code == payload.code))).scalar_one_or_none():
        raise HTTPException(409, "任务编号已存在，原任务不会被覆盖")

    issues = ledger.validate_spec(payload.spec_snapshot)
    if issues:
        raise HTTPException(422, {"message": "需求合同不完整，登记被拒绝", "issues": issues})

    for dep_code in payload.depends_on:
        if not (await db.execute(select(FdeTask).where(FdeTask.code == dep_code))).scalar_one_or_none():
            raise HTTPException(422, f"前置任务不存在：{dep_code}")

    item = FdeTask(
        **payload.model_dump(),
        spec_hash=sha256(payload.spec_snapshot.encode()).hexdigest(),
        spec_issues=issues, state="spec_ready", status="spec_ready",
        acceptance=ledger.ACCEPTANCE_PENDING, created_by=user.id,
    )
    db.add(item)
    await db.flush()
    await _log(db, item, "spec", _actor(user),
               f"需求合同校验通过（{len(ledger.SPEC_SECTIONS)} 节齐全），已冻结快照 {item.spec_hash[:12]}…",
               from_state="queued", to_state="spec_ready")
    await db.commit()
    await db.refresh(item)
    await db.refresh(item, ["project"])
    return _task_out(item)


@router.get("/tasks/{task_id}", response_model=FdeTaskDetail)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db),
                   _: User = Depends(get_current_user)):
    return await _detail(db, await _get_task(db, task_id))


@router.get("/tasks/{task_id}/events", response_model=list[FdeEventOut])
async def list_events(task_id: str, db: AsyncSession = Depends(get_db),
                      _: User = Depends(get_current_user)):
    await _get_task(db, task_id)
    return [FdeEventOut.model_validate(e) for e in await _events(db, task_id)]


@router.get("/tasks/{task_id}/gate")
async def get_gate(task_id: str, db: AsyncSession = Depends(get_db),
                   _: User = Depends(get_current_user)):
    """资格门禁：只读，不改状态。拒绝时给出可执行的原因。"""
    detail = await _detail(db, await _get_task(db, task_id))
    return detail.gate


@router.get("/tasks/{task_id}/repair-loop")
async def get_repair_loop(task_id: str, db: AsyncSession = Depends(get_db),
                          _: User = Depends(get_current_user)):
    """L10 有界修复回路：只读投影。判断「还能不能继续修」，从不停住任何流程。

    停止条件只有两个——轮次上限、连续两轮返工原因相同；到达边界时给出
    交接建议，决策权在具名的人（与上游 repair_loop 同一口径）。
    """
    task = await _get_task(db, task_id)
    events = await _events(db, task.id)
    return ledger.repair_loop_projection(events)


@router.post("/tasks/{task_id}/evidences", response_model=FdeEvidenceOut, status_code=201)
async def add_evidence(task_id: str, payload: FdeEvidenceCreate,
                       db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    task = await _get_task(db, task_id)
    data = payload.model_dump()
    data["observed_at"] = data["observed_at"].replace(tzinfo=None)
    item = FdeEvidence(task_id=task_id, **data, output_hash=sha256(payload.output.encode()).hexdigest())
    db.add(item)
    await _log(db, task, "evidence", _actor(user),
               f"追加 {payload.phase} 证据（返回码 {payload.return_code}）：{payload.command_text[:80]}")
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/tasks/{task_id}/evaluate", response_model=FdeTaskDetail)
async def evaluate_task(task_id: str, db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """自动复验：按已记录的证据判定，完整则待人审，不完整则返工。

    注意这里**不重跑命令**——只对已发生的记录作判断。重跑属于执行，不在工作台职责内。
    """
    task = await _get_task(db, task_id)
    if task.state not in ("executing", "evaluating"):
        reason = f"只有 executing/evaluating 状态可以复验（当前：{task.state}）"
        await _log(db, task, "rejected", _actor(user), f"复验被拒：{reason}", from_state=task.state)
        await db.commit()
        raise HTTPException(409, reason)
    chain = ledger.chain_summary(await _evidences(db, task.id))
    source = task.state
    if chain["evidence_complete"]:
        task.state, message = "review", "证据链完整，转入待人审"
    else:
        task.state, message = "rework", "证据链不完整，退回返工：" + "；".join(chain["issues"])
    task.status = task.state
    await _log(db, task, "evaluate", _actor(user), message, from_state=source, to_state=task.state)
    await db.commit()
    await db.refresh(task)
    await db.refresh(task, ["project"])
    return await _detail(db, task)


@router.post("/tasks/{task_id}/transition", response_model=FdeTaskDetail)
async def transition(task_id: str, payload: FdeTransitionIn,
                     db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """受控流转：只允许状态机里的边，跳阶段一律 409。"""
    task = await _get_task(db, task_id)
    if not ledger.can_transition(task.state, payload.target):
        reason = (
            f"非法流转：{task.state} 不能直接到 {payload.target}；"
            f"允许的下一状态为 {list(ledger.next_states(task.state))}"
        )
        # 被拒也要留痕：门禁拦下了什么，本身就是这条任务的历史。
        await _log(db, task, "rejected", payload.actor or _actor(user),
                   f"状态流转被拒：{reason}", from_state=task.state)
        await db.commit()
        raise HTTPException(409, reason)
    actor = payload.actor or _actor(user)
    source = task.state
    task.state = payload.target
    task.status = payload.target
    if payload.target == "accepted":
        task.acceptance = ledger.ACCEPTANCE_ACCEPTED
    await _log(db, task, "transition", actor, payload.note or f"{source} → {payload.target}",
               from_state=source, to_state=payload.target)
    await db.commit()
    await db.refresh(task)
    await db.refresh(task, ["project"])
    return await _detail(db, task)


@router.post("/tasks/{task_id}/accept", response_model=FdeTaskDetail)
async def accept_task(task_id: str, payload: FdeAcceptIn,
                      db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """人工接受：必须由**构建者以外的人**具名完成。程序不会代人签收。"""
    task = await _get_task(db, task_id)
    actor = payload.actor or _actor(user)
    builder = await _builder_name(db, task)
    verdict = ledger.accept_task(task=task, actor=actor, builder=builder)
    if not verdict["ok"]:
        # 自签与机器代签都是真实的被拒事件，必须留在事件链里。
        await _log(db, task, "rejected", actor, f"签收被拒：{verdict['reason']}", from_state=task.state)
        await db.commit()
        raise HTTPException(403, verdict["reason"])
    source = task.state
    task.acceptance = ledger.ACCEPTANCE_ACCEPTED
    task.accepted_by = actor
    task.accepted_at = utcnow()
    task.state = "accepted"
    task.status = "accepted"
    await _log(db, task, "acceptance", actor,
               payload.note or f"由 {actor} 具名接受（构建者：{builder}）",
               from_state=source, to_state="accepted")
    await db.commit()
    await db.refresh(task)
    await db.refresh(task, ["project"])
    return await _detail(db, task)


# --------------------------------------------------------------------------- 台账总览
@router.get("/ledger/summary")
async def ledger_summary(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """给看板用的总览：状态分布、接受分布、待人审清单、前置未接受清单。"""
    tasks = list((await db.execute(select(FdeTask).order_by(FdeTask.created_at))).scalars())
    by_code = {t.code: t for t in tasks}

    states: dict[str, int] = {}
    acceptance: dict[str, int] = {}
    for t in tasks:
        states[t.state] = states.get(t.state, 0) + 1
        acceptance[t.acceptance] = acceptance.get(t.acceptance, 0) + 1

    waiting = []
    blocked = []
    for t in tasks:
        if t.state == "review" and t.acceptance != "accepted":
            waiting.append({"code": t.code, "title": t.title, "created_by": t.created_by})
        for dep_code in (t.depends_on or []):
            dep = by_code.get(dep_code)
            if dep is None or dep.acceptance != "accepted":
                blocked.append({
                    "code": t.code, "title": t.title, "depends_on": dep_code,
                    "dep_state": dep.state if dep else None,
                    "dep_acceptance": dep.acceptance if dep else None,
                })
    return {
        "projects": len(list((await db.execute(select(FdeProject))).scalars())),
        "tasks": len(tasks),
        "states": states,
        "acceptance": acceptance,
        "waiting_human_review": waiting,
        "blocked_by_unaccepted_dependency": blocked,
        "principle": "证据齐全只是程序的结论；能否交付要由具名的人接受。",
    }
