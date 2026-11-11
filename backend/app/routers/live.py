"""实战话术辅助面板 API。

设计取舍（和演练业务不同，这里按「实战」标准要求自己）：

- **读接口一律要求登录**——和知识库保持同一套权限口径。
  写接口分两档：**场景与置顶这类「库结构」仍归讲师**；**话术 CRUD 对任何登录用户开放**——
  实战里「这条话术说错了 / 缺一条新的」最先被坐席本人发现，让他先找讲师等于错误话术
  会一直挂在面板上。同一场录音、常用标、手动排序走的是同一个口径。
  唯一多留的一道闸是**删除**：前端有二次确认，且删除会连带清掉该条录音。
- **``/bootstrap`` 一次给全量**：接起电话那一刻，任何一次额外往返都是当场听得见的卡顿。
- **``/audio-index`` 给录音同事用**：哪些话术还没有真人录音，按使用频次排序。
- **使用计数不加前置步骤**：坐席点一下就播，计数后台记，不要求先「开始通话」。
  实战里多一步就会让人放弃用这个工具。
- **音频 GET 允许 ``?token=``**：``<audio src>`` 带不了请求头。这是唯一为了
  「浏览器原生播放器能直接用」而开的口子，其余接口仍旧只认 Authorization 头。
"""
# 注意：这里**不要**加 ``from __future__ import annotations``。
# 加了之后 ``-> None`` 会变成字符串注解，FastAPI 推断不出「无响应体」，
# 带 status_code=204 的路由会在导入期直接抛 AssertionError（实测踩过）。
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_teacher
from app.core.security import decode_token
from app.database import get_db
from app.models import LiveScene, LiveScript, Role, User
from app.schemas import (
    LiveAudioGapOut,
    LiveBootstrap,
    LiveCommonIn,
    LiveEntryModeIn,
    LiveReorderIn,
    LiveSceneCreate,
    LiveSceneOut,
    LiveScriptCreate,
    LiveScriptOut,
    LiveScriptUpdate,
)
from app.services import live_scripts as live

router = APIRouter(prefix="/api/live", tags=["live-scripts"])


# ---------------------------------------------------------------------------
# 读：实战面板
# ---------------------------------------------------------------------------
@router.get("/bootstrap", response_model=LiveBootstrap)
async def bootstrap(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """一次性拉取全部场景与话术（含每条话术的音频状态）。"""
    return await live.bootstrap(db)


@router.get("/scenes", response_model=list[LiveSceneOut])
async def list_scenes(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    scenes = await live.list_scenes(db)
    scenes.sort(key=live.scene_sort_key)
    return [live.scene_payload(scene) for scene in scenes]


@router.get("/scenes/{scene_id}", response_model=LiveSceneOut)
async def get_scene(
    scene_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    detail = await live.get_scene_detail(db, scene_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="场景不存在")
    return detail


@router.get("/search")
async def search(
    q: str = Query(min_length=1, description="快捷码 / 标题 / 正文 / 场景名"),
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    """按关键词找话术。坐席主要输快捷码（如 ``hy2``）。"""
    return await live.search_scripts(db, q, limit=limit)


@router.get("/audio-index")
async def audio_index(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """待录音清单 + 整体录音进度。给录音同事排期用。"""
    gaps = await live.audio_gaps(db)
    return {**await live.summary(db), **gaps}


@router.post("/scripts/{script_id}/use", response_model=LiveScriptOut)
async def mark_used(
    script_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """记一次使用（播放时前端上报）。高频话术会因此在待录音清单里排前面。"""
    script = await db.get(LiveScript, script_id)
    if script is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    updated = await live.record_use(db, script)
    return live.script_payload(updated)


# ---------------------------------------------------------------------------
# 当场录音：浏览器录 → 传上来 → 点一下就播
# ---------------------------------------------------------------------------
def _script_or_404(script: LiveScript | None) -> LiveScript:
    if script is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    return script


@router.post("/scripts/{script_id}/audio", response_model=LiveScriptOut)
async def upload_recording(
    script_id: str,
    file: UploadFile = File(..., description="录到的音频，浏览器 MediaRecorder 产物"),
    duration_ms: int = Form(default=0, description="录制时长（毫秒），只用于展示"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    """上传/覆盖一条当场录音。

    任何登录用户都能录——这条口子是有意开的，见模块 docstring。
    重录即替换（一个话术只留一条），磁盘上的专业录音优先级更高，不受影响。
    """
    script = _script_or_404(await db.get(LiveScript, script_id))
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="音频是空的，没录上声音")
    if len(payload) > live.MAX_RECORDING_BYTES:
        limit_mb = live.MAX_RECORDING_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"单条录音不能超过 {limit_mb} MB")
    mime = live.normalize_mime(file.content_type or "")
    if mime not in live.ALLOWED_RECORDING_MIME:
        raise HTTPException(status_code=415, detail=f"不支持的音频格式：{mime or '未知'}")
    await live.save_recording(
        db,
        script,
        data=payload,
        mime=mime,
        duration_ms=duration_ms,
        recorded_by=current.username,
        recorded_by_name=current.display_name or current.username,
    )
    # save_recording 把新录音挂到了 script.recording 上（会话是 expire_on_commit=False），
    # 所以这里不必再查一次库。
    return live.script_payload(script)


@router.get("/scripts/{script_id}/audio")
async def get_recording_audio(
    script_id: str,
    token: str | None = Query(default=None, description="<audio> 标签带不了请求头，用这个传 JWT"),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """把库里的录音吐给 ``<audio src>``。

    不缓存（``no-store``）：一次重录之后还播到旧声音，比多下一次几百 KB 严重得多。
    """
    raw = (token or "").strip()
    if not raw and authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    payload = decode_token(raw) if raw else None
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法验证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )
    found = await live.recording_bytes(db, script_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="这条话术没有现场录音")
    data, mime = found
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "no-store", "Content-Length": str(len(data))},
    )


@router.delete("/scripts/{script_id}/audio", status_code=204)
async def delete_recording(
    script_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> None:
    """删掉当场录音。上传者本人或讲师可以删。"""
    script = _script_or_404(await db.get(LiveScript, script_id))
    recording = await live.get_recording(db, script_id)
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="这条话术没有现场录音")
    is_owner = recording.recorded_by and recording.recorded_by == current.username
    if not is_owner and current.role not in (Role.TEACHER, Role.ADMIN):
        raise HTTPException(status_code=403, detail="只能删除自己录的那条，或请讲师处理")
    await live.delete_recording(db, script)


# ---------------------------------------------------------------------------
# 写：话术 CRUD 对任何登录用户开放（坐席最清楚哪条说错了/缺哪条）；
# 场景与置顶这类「库结构」仍归讲师。
# ---------------------------------------------------------------------------
@router.post("/scenes", response_model=LiveSceneOut, status_code=201)
async def create_scene(
    payload: LiveSceneCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_teacher),
) -> dict:
    code = f"scene-{uuid.uuid4().hex[:8]}"
    scene = LiveScene(
        code=code,
        name=payload.name,
        phase=payload.phase,
        source=payload.source,
        description=payload.description,
        sort_order=payload.sort_order,
    )
    db.add(scene)
    await db.commit()
    await db.refresh(scene)
    return live.scene_payload(scene)


@router.post("/scenes/{scene_id}/entry-mode", response_model=LiveSceneOut)
async def set_entry_mode(
    scene_id: str,
    payload: LiveEntryModeIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """切换进场模式（任何登录用户可改，这是坐席自己的面板偏好）。

    ``silent``：进场景不出声；``auto``：进场景自动播「常用」标记的第一条。
    """
    scene = await live.get_scene(db, scene_id)
    if scene is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="场景不存在")
    updated = await live.set_entry_mode(db, scene, mode=payload.mode)
    return live.scene_payload(updated)


@router.post("/scripts/{script_id}/common", response_model=LiveScriptOut)
async def set_common(
    script_id: str,
    payload: LiveCommonIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """打/摘「常用」标签（任何登录用户）。auto 进场模式只播打标的第一条。"""
    script = _script_or_404(await db.get(LiveScript, script_id))
    updated = await live.set_common(db, script, is_common=payload.is_common)
    return live.script_payload(updated)


@router.post("/scripts/{script_id}/reorder", response_model=LiveSceneOut)
async def reorder_script(
    script_id: str,
    payload: LiveReorderIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """手动排序（任何登录用户）：``position`` 1 起插进 Top 榜；0 = 退出 Top 榜回热度序。"""
    script = _script_or_404(await db.get(LiveScript, script_id))
    scene = await live.reorder_script(db, script, position=payload.position)
    if scene is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="场景不存在")
    return live.scene_payload(scene)


@router.post("/scenes/{scene_id}/pin", response_model=LiveSceneOut)
async def toggle_pin(
    scene_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_teacher),
) -> dict:
    """置顶/取消置顶。置顶的场景排在阶段顺序之前。"""
    scene = await db.get(LiveScene, scene_id)
    if scene is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="场景不存在")
    scene.pinned = not scene.pinned
    await db.commit()
    await db.refresh(scene)
    return live.scene_payload(scene)


@router.post("/scenes/{scene_id}/scripts", response_model=LiveScriptOut, status_code=201)
async def create_script(
    scene_id: str,
    payload: LiveScriptCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    scene = await db.get(LiveScene, scene_id)
    if scene is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="场景不存在")
    code = (payload.code or "").strip() or await live.next_code(db, scene_id)
    conflict = await db.execute(select(LiveScript.id).where(LiveScript.code == code))
    if conflict.first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"快捷码 {code} 已被占用")
    script = LiveScript(
        scene_id=scene_id,
        code=code,
        label=payload.label,
        text=payload.text,
        auto_play=payload.auto_play,
        sort_order=payload.sort_order,
        tags=payload.tags,
    )
    db.add(script)
    await db.commit()
    await db.refresh(script)
    return live.script_payload(script)


@router.put("/scripts/{script_id}", response_model=LiveScriptOut)
async def update_script(
    script_id: str,
    payload: LiveScriptUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    script = await db.get(LiveScript, script_id)
    if script is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    data = payload.model_dump(exclude_unset=True)
    # code 是全库唯一键（也是录音文件名约定），改它必须查重，冲突回 409
    new_code = (data.get("code") or "").strip() if "code" in data else None
    if new_code is not None:
        if not new_code:
            raise HTTPException(status_code=400, detail="快捷码不能改为空")
        if new_code != script.code:
            conflict = await db.execute(
                select(LiveScript.id).where(LiveScript.code == new_code, LiveScript.id != script_id)
            )
            if conflict.first() is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"快捷码 {new_code} 已被占用")
            data["code"] = new_code
    for field, value in data.items():
        if value is not None:
            setattr(script, field, value)
    await db.commit()
    await db.refresh(script)
    return live.script_payload(script)


@router.delete("/scripts/{script_id}", status_code=204)
async def delete_script(
    script_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> None:
    script = await db.get(LiveScript, script_id)
    if script is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    # 录音挂在这条话术上（FK 非空），必须先删子行，否则 IntegrityError
    await live.delete_recording(db, script)
    await db.delete(script)
    await db.commit()


@router.get("/audio-gaps", response_model=list[LiveAudioGapOut])
async def audio_gaps(
    limit: int = Query(default=200, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    gaps = await live.audio_gaps(db, limit=limit)
    return gaps["items"]
