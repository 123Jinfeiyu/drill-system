"""实战话术辅助面板的服务层。

四件事，都很小，但都踩在「实战容错」上：

1. **音频三级判定**——录音是**陆续补的**，不是一次性齐活。所以判定不做缓存、每次都重新看：
   ``磁盘文件（专业录音） → 库内录音（当场试录） → 浏览器合成（兜底）``。
   把 ``<code>.mp3`` 丢进目录、或在页面里当场录一条，刷新即生效，不需要重启、不需要重新导入。

2. **一次拉全量**——``bootstrap()`` 把场景和话术一口气给前端。接起电话那一刻多一次
   往返就是当场听得见的卡顿，全量约 200 条只有几十 KB，没必要省。

3. **待录音清单**——哪些话术还没有真人录音、按使用频次排序，直接交给录音同事。
   「先上线、后补录音」这条路线要能跑通，这份清单是关键。

4. **当场录音**——`save_recording()` 把浏览器录到的字节收进 ``live_recordings``。
   字节**进库不进文件系统**：实测发现托管/容器环境下磁盘是临时的，而库是随仓库走的那一份，
   录音放库里才不会被下一次部署冲掉。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LiveRecording, LiveScene, LiveScript

# ---------------------------------------------------------------------------
# 话务动线：坐席接起电话到挂断，实际会走过的阶段
# ---------------------------------------------------------------------------
PHASES: tuple[tuple[str, str], ...] = (
    ("opening", "通话开始"),
    ("support", "通用支撑"),
    ("business", "业务处理"),
    ("closing", "通话收尾"),
)
PHASE_LABEL = dict(PHASES)
PHASE_ORDER = {key: i for i, (key, _) in enumerate(PHASES)}

# 音频文件扩展名，按优先级尝试；录音同事给什么格式都能直接放进来。
# .webm/.mp4 是浏览器 MediaRecorder 的产物，留在这里是为了「导出试录文件再批量覆盖」也走得通。
AUDIO_EXTS: tuple[str, ...] = (".mp3", ".wav", ".m4a", ".ogg", ".aac", ".webm", ".mp4")

# 录音目录：默认 backend/audio/live，可用 LIVE_AUDIO_DIR 覆盖
_DEFAULT_AUDIO_DIR = Path(__file__).resolve().parents[2] / "audio" / "live"
AUDIO_URL_PREFIX = "/audio/live"

# 单条录音上限：一条话术最长十几秒，8MB 已经宽松到不可能被正常使用撞到，
# 但足以挡住「传了个 200MB 文件把库撑爆」这种事。
MAX_RECORDING_BYTES = 8 * 1024 * 1024

# 允许的音频 MIME（浏览器 MediaRecorder 因内核不同给出的组合）
ALLOWED_RECORDING_MIME: tuple[str, ...] = (
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/aac",
    "audio/m4a",
)


def audio_dir() -> Path:
    from app.config import settings

    raw = (settings.live_audio_dir or "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_AUDIO_DIR


def resolve_audio(code: str, audio_file: str | None) -> tuple[str | None, str]:
    """按话术的 code 找录音文件。

    返回 ``(audio_url, audio_name)``；找不到文件时 url 为 ``None``，
    由前端降级为浏览器实时合成。

    ``audio_file`` 是覆盖项（比如录音同事给的文件名不合 code 规范时），
    留空则按 ``<code>.<ext>`` 约定推导。
    """
    directory = audio_dir()
    names: list[str] = []
    if audio_file:
        names.append(audio_file)
    names.extend(f"{code}{ext}" for ext in AUDIO_EXTS)
    for name in names:
        try:
            if (directory / name).is_file():
                return f"{AUDIO_URL_PREFIX}/{name}", name
        except OSError:
            continue
    return None, ""


def script_audio(script: LiveScript) -> tuple[str, str | None, str]:
    """给一条话术判定音频状态，返回 ``(status, url, name)``。

    三级，顺序即优先级：

    1. ``file``  —— 磁盘上有 ``<code>.<ext>``（专业/批量录音，谁拷进来算谁的）
    2. ``record``—— 库里有一条当场录的（``/api/live/scripts/<id>/audio``，要带令牌播）
    3. ``tts``   —— 都没有，前端实时合成兜底

    磁盘优先是有意的：专业录音一旦就位，自动盖过当场试录，不需要先删什么。
    """
    url, name = resolve_audio(script.code, script.audio_file)
    if url:
        return "file", url, name
    recording = getattr(script, "recording", None)
    if recording is not None:
        return "record", f"/api/live/scripts/{script.id}/audio", f"{script.code}{recording.ext}"
    return "tts", None, ""


def script_payload(script: LiveScript) -> dict[str, Any]:
    status, url, name = script_audio(script)
    recording = getattr(script, "recording", None)
    size = 0
    try:
        # size 是普通列，deferred 的只有 data，所以这里不会把字节读上来
        size = int(recording.size or 0) if recording is not None else 0
    except (TypeError, ValueError):
        size = 0
    return {
        "id": script.id,
        "scene_id": script.scene_id,
        "code": script.code,
        "label": script.label or "",
        "text": script.text,
        "auto_play": bool(script.auto_play),
        "sort_order": script.sort_order,
        "is_common": bool(script.is_common),
        "manual_rank": script.manual_rank,
        "tags": list(script.tags or []),
        "use_count": script.use_count or 0,
        "audio_status": status,
        "has_audio": status != "tts",
        "audio_url": url,
        "audio_name": name,
        "recording_size": size,
        "recording_duration_ms": int(recording.duration_ms or 0) if recording is not None else 0,
        "recorded_by": (recording.recorded_by_name or recording.recorded_by) if recording else "",
        "recorded_at": recording.updated_at.isoformat() if recording is not None and recording.updated_at else "",
    }


def script_sort_key(script: LiveScript) -> tuple[int, int, int, int, str]:
    """话术在场景内的展示顺序。

    手动排过序的（``manual_rank`` 非 NULL）恒排最前、彼此按位次升序——
    这就是坐席要的 Top1 / Top2；其余按**热度**（use_count 降序）自动排，
    种子导入的 sort_order 只作同热度时的稳定次序。
    """
    rank = script.manual_rank
    return (
        0 if rank is not None else 1,
        rank or 0,
        -(script.use_count or 0),
        script.sort_order,
        script.code,
    )


def scene_sort_key(scene: LiveScene) -> tuple[int, int, int, str]:
    """排序：收藏置顶 → 阶段 → 人工顺序 → 名称。

    收藏能盖过阶段顺序，是为了「这个客户正好问这个」——当场找得到比排序整齐重要。
    """
    return (
        0 if scene.pinned else 1,
        PHASE_ORDER.get(scene.phase, len(PHASES)),
        scene.sort_order,
        scene.name,
    )


def scene_payload(scene: LiveScene, *, with_scripts: bool = True) -> dict[str, Any]:
    scripts = sorted(scene.scripts or [], key=script_sort_key)
    out = [script_payload(s) for s in scripts] if with_scripts else []
    recorded = sum(1 for s in out if s["has_audio"])
    return {
        "id": scene.id,
        "code": scene.code,
        "name": scene.name,
        "phase": scene.phase,
        "source": scene.source,
        "description": scene.description or "",
        "sort_order": scene.sort_order,
        "pinned": bool(scene.pinned),
        "entry_mode": scene.entry_mode or "silent",
        "script_count": len(scripts),
        "recorded_count": recorded,
        "scripts": out,
    }


async def list_scenes(db: AsyncSession, *, include_inactive: bool = False) -> list[LiveScene]:
    stmt = select(LiveScene).order_by(LiveScene.sort_order, LiveScene.name)
    if not include_inactive:
        stmt = stmt.where(LiveScene.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def bootstrap(db: AsyncSession) -> dict[str, Any]:
    """一次性返回实战面板所需的全部数据。"""
    scenes = await list_scenes(db)
    scenes.sort(key=scene_sort_key)
    payload = [scene_payload(scene) for scene in scenes]

    script_total = sum(item["script_count"] for item in payload)
    recorded_total = sum(item["recorded_count"] for item in payload)

    counts: dict[str, int] = {}
    for scene in scenes:
        counts[scene.phase] = counts.get(scene.phase, 0) + 1
    phases = [
        {"key": key, "label": label, "scene_count": counts.get(key, 0)}
        for key, label in PHASES
    ]
    return {
        "phases": phases,
        "scenes": payload,
        "script_total": script_total,
        "recorded_total": recorded_total,
        "audio_enabled": True,
        "tts_fallback": True,
    }


async def get_scene_detail(db: AsyncSession, scene_id: str) -> dict[str, Any] | None:
    scene = await db.get(LiveScene, scene_id)
    if scene is None:
        return None
    return scene_payload(scene)


def _match_score(script: LiveScript, q: str) -> int:
    """搜索相关度：快捷码精确 > 码前缀 > 标题 > 码包含 > 正文。

    坐席最常按快捷码找（培训里就是这么教的），所以 code 优先级最高。
    这个函数只管排序，能不能匹配由 SQL 的 LIKE 决定。
    """
    code = (script.code or "").lower()
    label = (script.label or "").lower()
    text = (script.text or "").lower()
    if code == q:
        return 0
    if code.startswith(q):
        return 1
    if q in label:
        return 2
    if q in code:
        return 3
    if q in text:
        return 4
    return 5


async def search_scripts(db: AsyncSession, q: str, *, limit: int = 30) -> list[dict[str, Any]]:
    """按快捷码 / 标题 / 正文 / 场景名搜索话术。"""
    needle = (q or "").strip()
    if not needle:
        return []
    like = f"%{needle}%"
    stmt = (
        select(LiveScript)
        .join(LiveScene, LiveScript.scene_id == LiveScene.id)
        .where(
            or_(
                LiveScript.code.like(like),
                LiveScript.label.like(like),
                LiveScript.text.like(like),
                LiveScene.name.like(like),
            )
        )
        .limit(max(limit * 3, 60))
    )
    result = await db.execute(stmt)
    scripts = list(result.scalars().all())
    lowered = needle.lower()
    scripts.sort(key=lambda s: (_match_score(s, lowered), -(s.use_count or 0), s.sort_order))
    scenes = await list_scenes(db)
    scene_names = {s.id: s.name for s in scenes}

    out: list[dict[str, Any]] = []
    for script in scripts[:limit]:
        item = script_payload(script)
        item["scene_name"] = scene_names.get(script.scene_id, "")
        out.append(item)
    return out


async def next_code(db: AsyncSession, scene_id: str) -> str:
    """给新增话术生成一个不冲突的 code（同时就是录音文件名）。"""
    result = await db.execute(select(LiveScript.code).where(LiveScript.scene_id == scene_id))
    existing = {row[0] for row in result.all()}
    index = 1
    while True:
        candidate = f"c{index:03d}"
        if candidate not in existing:
            return candidate
        index += 1


async def record_use(db: AsyncSession, script: LiveScript) -> LiveScript:
    """记一次使用。

    只加计数、不建会话表——实战场景里坐席没空先「开始通话」再点话术，
    任何前置步骤都会让人放弃使用。计数够支撑「高频话术优先」和待录音清单排序。
    """
    script.use_count = (script.use_count or 0) + 1
    script.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(script)
    return script


async def audio_gaps(db: AsyncSession, *, limit: int = 500) -> dict[str, Any]:
    """待录音清单：把还没有真人录音的话术按使用频次排出来。

    ``reason`` 区分两种情况：
    - ``missing``：从来没有录音
    - ``override``：配了 audio_file 覆盖项但文件其实不存在（通常是文件名写错了）
    """
    scenes = await list_scenes(db)
    items: list[dict[str, Any]] = []
    for scene in scenes:
        for script in scene.scripts or []:
            status, _url, _name = script_audio(script)
            if status != "tts":
                continue
            items.append(
                {
                    "code": script.code,
                    "scene_name": scene.name,
                    "label": script.label or "",
                    "text": script.text,
                    "use_count": script.use_count or 0,
                    "reason": "override" if script.audio_file else "missing",
                }
            )
    items.sort(key=lambda item: (-item["use_count"], item["scene_name"], item["code"]))
    total = len(items)
    missing = sum(1 for item in items if item["reason"] == "missing")
    return {
        "total": total,
        "missing": missing,
        "override_broken": total - missing,
        "items": items[:limit],
    }


async def summary(db: AsyncSession) -> dict[str, Any]:
    scenes = await list_scenes(db)
    script_total = await db.scalar(select(func.count()).select_from(LiveScript)) or 0
    recorded = 0
    from_file = 0
    from_recording = 0
    for scene in scenes:
        for script in scene.scripts or []:
            status = script_audio(script)[0]
            if status == "tts":
                continue
            recorded += 1
            if status == "file":
                from_file += 1
            else:
                from_recording += 1
    return {
        "scenes": len(scenes),
        "scripts": int(script_total),
        "recorded": recorded,
        "recorded_from_file": from_file,
        "recorded_from_db": from_recording,
        "pending_recording": int(script_total) - recorded,
        "audio_dir": str(audio_dir()),
    }


# ---------------------------------------------------------------------------
# 常用标签 / 进场模式 / 手动排序：坐席自己的面板偏好
# ---------------------------------------------------------------------------
async def get_scene(db: AsyncSession, scene_id: str) -> LiveScene | None:
    """取场景并**显式预载 scripts**。

    不能靠 ``db.get``：实测它的关系预载不保证生效，之后在 async 会话里
    访问 ``scene.scripts`` 会触发同步懒加载，直接 MissingGreenlet 崩 500。
    """
    result = await db.execute(
        select(LiveScene)
        .where(LiveScene.id == scene_id)
        .options(selectinload(LiveScene.scripts))
    )
    return result.scalar_one_or_none()


# 有意对任何登录用户开放（与当场录音同一口径）：这是坐席接电话时用的面板，
# 「觉得这条常用」的判断只能来自坐席本人，让他先找讲师等于这功能不会被用。
async def set_entry_mode(db: AsyncSession, scene: LiveScene, *, mode: str) -> LiveScene:
    """切换场景进场模式。只认 ``silent`` / ``auto``（router 层已校验，这里再兜一道）。"""
    scene.entry_mode = mode if mode in ("silent", "auto") else "silent"
    await db.commit()
    return scene


async def set_common(db: AsyncSession, script: LiveScript, *, is_common: bool) -> LiveScript:
    """打/摘「常用」标签。"""
    script.is_common = bool(is_common)
    await db.commit()
    await db.refresh(script)
    return script


async def reorder_script(db: AsyncSession, script: LiveScript, *, position: int) -> LiveScene | None:
    """把手动画术插到手动榜单第 ``position`` 位（1 起）；``0`` = 清掉它的位次。

    只动「手动榜单」里的位次：其余话术仍按热度自动排。
    插到中间时，原本在它后面的位次整体 +1，Top1/Top2 的语义是稳定的。
    """
    scene = await get_scene(db, script.scene_id)
    if scene is None:
        return None
    if position <= 0:
        script.manual_rank = None
    else:
        ranked = sorted(
            (s for s in (scene.scripts or []) if s.id != script.id and s.manual_rank is not None),
            key=lambda s: s.manual_rank or 0,
        )
        idx = max(0, min(position - 1, len(ranked)))
        for s in ranked[idx:]:
            s.manual_rank = (s.manual_rank or 0) + 1
        script.manual_rank = idx + 1
    await db.commit()
    return scene


# ---------------------------------------------------------------------------
# 当场录音：浏览器录 → 进库
# ---------------------------------------------------------------------------
def normalize_mime(raw: str) -> str:
    """把 ``audio/webm;codecs=opus`` 这类带参数的 MIME 收敛成裸类型。"""
    return (raw or "").split(";")[0].strip().lower()


def ext_for_mime(mime: str) -> str:
    """按 MIME 给个扩展名。

    ``.webm`` 是 Chrome/Edge/Firefox 的 MediaRecorder 默认产物；
    Safari 走 ``audio/mp4``。扩展名只用于展示与导出命名，播放靠 MIME。
    """
    return {
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mp4": ".mp4",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/aac": ".aac",
        "audio/m4a": ".m4a",
    }.get(mime, ".webm")


async def get_recording(db: AsyncSession, script_id: str) -> LiveRecording | None:
    result = await db.execute(
        select(LiveRecording).where(LiveRecording.script_id == script_id)
    )
    return result.scalar_one_or_none()


async def recording_bytes(db: AsyncSession, script_id: str) -> tuple[bytes, str] | None:
    """取音频字节。

    直接查 ``data`` 列而不是走 ORM 属性——``data`` 是 deferred 列，
    在 async 会话里顺手访问会触发一次隐藏的懒加载（那是同步 IO）。
    """
    result = await db.execute(
        select(LiveRecording.data, LiveRecording.mime).where(
            LiveRecording.script_id == script_id
        )
    )
    row = result.first()
    if row is None or row[0] is None:
        return None
    return bytes(row[0]), (row[1] or "audio/webm")


async def save_recording(
    db: AsyncSession,
    script: LiveScript,
    *,
    data: bytes,
    mime: str,
    duration_ms: int,
    recorded_by: str,
    recorded_by_name: str,
) -> LiveRecording:
    """存/覆盖一条当场录音（一个话术只有一条，重录即替换）。

    注意挂载方式：新建时走 ``script.recording = existing`` 而不是 ``LiveRecording(script_id=...)``。
    因为调用方的 ``script`` 是同一个会话里取出来的，身份映射里它的 ``recording`` 还是旧值
    （``None``），只写 FK 不会让这个已加载的关系刷新，接口就会返回「上传成功但状态仍是 tts」。
    挂到关系上，两边同时正确。
    """
    existing = await get_recording(db, script.id)
    clean_mime = normalize_mime(mime) or "audio/webm"
    ext = ext_for_mime(clean_mime)
    if existing is None:
        existing = LiveRecording()
        script.recording = existing
        db.add(existing)
    existing.mime = clean_mime
    existing.ext = ext
    existing.size = len(data)
    existing.duration_ms = max(0, int(duration_ms or 0))
    existing.recorded_by = recorded_by
    existing.recorded_by_name = recorded_by_name
    existing.updated_at = datetime.now()
    existing.data = data
    await db.commit()
    return existing


async def delete_recording(db: AsyncSession, script: LiveScript) -> bool:
    """删掉当场录音。返回是否真的删了（没有录音时返回 False）。"""
    existing = await get_recording(db, script.id)
    if existing is None:
        return False
    await db.delete(existing)
    await db.commit()
    return True
