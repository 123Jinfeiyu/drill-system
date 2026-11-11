"""剧本管理路由：列表 / 详情 / 创建 / 更新 / 删除（写操作仅讲师+）"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_teacher
from app.database import get_db
from app.models import DrillSession, Scenario, User
from app.schemas import (
    ScenarioBatchCreate,
    ScenarioBatchResult,
    ScenarioCreate,
    ScenarioOut,
    ScenarioUpdate,
)

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


@router.get("", response_model=list[ScenarioOut])
async def list_scenarios(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Scenario]:
    result = await db.execute(select(Scenario).order_by(Scenario.created_at.desc()))
    return list(result.scalars().all())


@router.post("/batch", response_model=ScenarioBatchResult, status_code=201)
async def create_scenarios_batch(
    payload: ScenarioBatchCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_teacher),
) -> ScenarioBatchResult:
    created: list[Scenario] = []
    skipped_codes: list[str] = []
    for item in payload.scenarios:
        existing = await db.execute(select(Scenario).where(Scenario.code == item.code))
        if existing.scalar_one_or_none():
            skipped_codes.append(item.code)
            continue
        s = Scenario(**item.model_dump())
        db.add(s)
        await db.flush()  # get s.id without committing each
        created.append(s)
    await db.commit()
    for s in created:
        await db.refresh(s)
    return ScenarioBatchResult(
        created=len(created),
        skipped=len(skipped_codes),
        skipped_codes=skipped_codes,
        items=created,
    )


@router.get("/{scenario_id}", response_model=ScenarioOut)
async def get_scenario(
    scenario_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Scenario:
    result = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="剧本不存在")
    return s


@router.post("", response_model=ScenarioOut, status_code=201)
async def create_scenario(
    payload: ScenarioCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_teacher),
) -> Scenario:
    result = await db.execute(select(Scenario).where(Scenario.code == payload.code))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="剧本代码已存在")
    s = Scenario(**payload.model_dump())
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


@router.put("/{scenario_id}", response_model=ScenarioOut)
async def update_scenario(
    scenario_id: str,
    payload: ScenarioUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_teacher),
) -> Scenario:
    result = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="剧本不存在")

    data = payload.model_dump(exclude_unset=True)
    new_code = data.get("code")
    if new_code is not None and new_code != s.code:
        dup = await db.execute(
            select(Scenario).where(
                Scenario.code == new_code, Scenario.id != scenario_id
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="剧本代码已存在")

    for field, value in data.items():
        setattr(s, field, value)
    await db.commit()
    await db.refresh(s)
    return s


@router.delete("/{scenario_id}", status_code=204)
async def delete_scenario(
    scenario_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_teacher),
) -> None:
    result = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="剧本不存在")

    used = await db.execute(
        select(func.count())
        .select_from(DrillSession)
        .where(DrillSession.scenario_id == scenario_id)
    )
    count = used.scalar_one()
    if count:
        raise HTTPException(
            status_code=409,
            detail=f"该剧本已被 {count} 个演练会话使用，无法删除（演练历史与评分需保留）",
        )

    await db.delete(s)
    await db.commit()
