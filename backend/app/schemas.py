"""Pydantic 请求/响应 schema"""
import re
from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from app.models import MessageRole, Role, SessionStatus


# 【P1-3 修复】SQLite func.now() 存的是"无时区标记的 UTC"，naive datetime 序列化后
# 不带偏移量，前端 new Date() 会当本地时间解析，导致北京时间显示早 8 小时。
# 这里在序列化边界统一补 UTC 时区，API 输出形如 2026-09-06T08:00:00Z（pydantic v2
# 对 UTC 用 Z 后缀，与 +00:00 等价），前端即可正确转为本地时间，存量数据无需迁移。
def _ensure_utc(v: Any) -> Any:
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


UtcDateTime = Annotated[datetime, BeforeValidator(_ensure_utc)]


# ===== Token =====
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    """登录请求：不做密码强度校验（历史账号规则不一，避免误伤），仅限长度上界。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    """【P3-2 修复】注册请求。

    原先 register 直接复用 LoginRequest：无用户名长度上界（超长触发数据库错误返回 500），
    也无密码强度要求。现补：用户名 ≤64；密码 8~72 位且必须同时含字母和数字。
    """

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=72)
    display_name: str | None = Field(default=None, max_length=64)

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, v: str) -> str:
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("密码必须同时包含字母和数字，且长度不少于 8 位")
        return v


# ===== User =====
class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    role: Role

    model_config = ConfigDict(from_attributes=True)


# ===== Scenario =====
class ScenarioOut(BaseModel):
    id: str
    code: str
    title: str
    customer_persona: str
    opening: str
    knowledge_points: list[str]
    reference_answer: str
    difficulty: int
    max_turns: int
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class ScenarioCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=128)
    customer_persona: str
    opening: str
    knowledge_points: list[str] = Field(default_factory=list)
    reference_answer: str = ""
    difficulty: int = Field(default=1, ge=1, le=5)
    max_turns: int = Field(default=5, ge=1, le=20)


class ScenarioUpdate(BaseModel):
    """剧本更新：仅传需要修改的字段"""

    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=128)
    customer_persona: str | None = None
    opening: str | None = None
    knowledge_points: list[str] | None = None
    reference_answer: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    max_turns: int | None = Field(default=None, ge=1, le=20)


class ScenarioBatchCreate(BaseModel):
    scenarios: list[ScenarioCreate] = Field(default_factory=list)


class ScenarioBatchResult(BaseModel):
    created: int
    skipped: int
    skipped_codes: list[str]
    items: list[ScenarioOut]


# ===== Session =====
class SessionCreate(BaseModel):
    scenario_id: str


class SessionOut(BaseModel):
    id: str
    scenario_id: str
    student_id: str
    status: SessionStatus
    current_turn: int
    started_at: UtcDateTime | None
    finished_at: UtcDateTime | None
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class DrillRecordOut(BaseModel):
    """剧本演练记录：真实会话 + 剧本标题 + （如有）评分"""

    id: str
    scenario_id: str
    scenario_title: str
    student_id: str
    student_name: str | None = None
    status: SessionStatus
    current_turn: int
    max_turns: int
    started_at: UtcDateTime | None = None
    finished_at: UtcDateTime | None = None
    created_at: UtcDateTime
    has_score: bool = False
    total: float | None = None
    accuracy: float | None = None
    completeness: float | None = None
    etiquette: float | None = None
    responsiveness: float | None = None
    knowledge_use: float | None = None
    summary: str | None = None
    weak_points: list[str] | None = None

    model_config = ConfigDict(from_attributes=True)


# ===== Message =====
class MessageOut(BaseModel):
    id: str
    role: MessageRole
    content: str
    turn: int
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class StudentReply(BaseModel):
    content: str = Field(min_length=1)


class CustomerReply(BaseModel):
    content: str
    is_finished: bool = False
    next_turn: int


# ===== Score =====
class ScoreOut(BaseModel):
    id: str
    session_id: str
    total: float
    accuracy: float
    completeness: float
    etiquette: float
    responsiveness: float
    knowledge_use: float
    summary: str
    weak_points: list[str]

    model_config = ConfigDict(from_attributes=True)


# ===== Score Summary (dashboard) =====
class ScoreSummaryOut(BaseModel):
    id: str
    session_id: str
    scenario_id: str
    scenario_title: str
    student_id: str | None = None
    student_name: str | None = None
    total: float
    accuracy: float
    completeness: float
    etiquette: float
    responsiveness: float
    knowledge_use: float
    summary: str
    weak_points: list[str]
    current_turn: int
    status: SessionStatus
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


# ===== Knowledge =====
class KnowledgeItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str
    tags: list[str] = Field(default_factory=list)
    source_url: str = ""


class KnowledgeUpdate(BaseModel):
    """【P4-5 修复】知识条目更新：仅传需要修改的字段。

    此前 backend 已新增 PUT /api/knowledge/{id} 路由并 import 本类，但本类缺失，
    导致 `import app.main` 直接 ImportError、后端无法启动；此处补齐。
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    tags: list[str] | None = None
    source_url: str | None = None


class KnowledgeItemOut(BaseModel):
    id: str
    title: str
    content: str
    tags: list[str]
    source_url: str
    created_at: UtcDateTime
    model_config = ConfigDict(from_attributes=True)


class KnowledgeImportUrl(BaseModel):
    url: str
    title: str = ""
    tags: list[str] = Field(default_factory=list)


class KnowledgeBatchImportUrl(BaseModel):
    urls: list[KnowledgeImportUrl] = Field(default_factory=list)


class KnowledgeImportFailure(BaseModel):
    url: str
    error: str


class KnowledgeBatchImportResult(BaseModel):
    succeeded: int
    failed: int
    failures: list[KnowledgeImportFailure]
    items: list[KnowledgeItemOut]


# ===== Practice (Q&A 演练场) =====
class PracticeCategoryOut(BaseModel):
    key: str
    label: str
    description: str
    tags: list[str]


class PracticeSessionCreate(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    difficulty: int = Field(default=2, ge=1, le=5)
    max_turns: int = Field(default=8, ge=3, le=20)


class PracticeSessionOut(BaseModel):
    id: str
    student_id: str
    category: str
    difficulty: int
    persona: str
    opening: str
    max_turns: int
    status: SessionStatus
    current_turn: int
    channel: str = "practice"
    started_at: UtcDateTime | None
    finished_at: UtcDateTime | None
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class PracticeMessageOut(BaseModel):
    id: str
    role: MessageRole
    content: str
    turn: int
    script_id: str | None = None
    via: str = "free"
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class PracticeReplyCreate(BaseModel):
    content: str = Field(min_length=1)


class LiveCallSimulateIn(BaseModel):
    """模拟客户进线：业务分类 + 难度。category 缺省随机挑一个。"""

    category: str | None = None
    difficulty: int = Field(default=2, ge=1, le=5)


class LiveCallScriptIn(BaseModel):
    """模拟通话里点话术回复客户"""

    script_id: str = Field(min_length=1)


class LiveCallFreeReplyIn(BaseModel):
    """模拟通话里自由输入回复（话术覆盖不了时兜底）"""

    content: str = Field(min_length=1, max_length=2000)


class PracticeReplyOut(BaseModel):
    content: str
    is_finished: bool = False
    next_turn: int


class PracticeScoreOut(BaseModel):
    id: str
    session_id: str
    total: float
    accuracy: float
    completeness: float
    etiquette: float
    responsiveness: float
    knowledge_use: float
    summary: str
    weak_points: list[str]
    suggestions: str
    business_summary: str = ""

    model_config = ConfigDict(from_attributes=True)


class PracticeHintOut(BaseModel):
    title: str
    content: str
    tags: list[str]


class PracticeScoreSummaryOut(BaseModel):
    id: str
    session_id: str
    category: str
    student_id: str | None = None
    student_name: str | None = None
    total: float
    accuracy: float
    completeness: float
    etiquette: float
    responsiveness: float
    knowledge_use: float
    summary: str
    weak_points: list[str]
    suggestions: str
    business_summary: str = ""
    current_turn: int
    status: SessionStatus
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


# ===== CodexFDE Workbench =====
class FdeProjectCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    purpose: str = ""
    path: str = ""


class FdeProjectOut(FdeProjectCreate):
    id: str
    owner_id: str
    created_at: UtcDateTime
    model_config = ConfigDict(from_attributes=True)


class FdeTaskCreate(BaseModel):
    project_id: str
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    request: str = ""
    spec_snapshot: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)


class FdeTaskOut(BaseModel):
    id: str
    project_id: str
    project_name: str
    code: str
    title: str
    request: str
    spec_snapshot: str
    spec_hash: str
    spec_issues: list[str] = Field(default_factory=list)
    state: str
    state_label: str
    acceptance: str
    accepted_by: str | None = None
    accepted_at: UtcDateTime | None = None
    depends_on: list[str] = Field(default_factory=list)
    created_by: str
    created_at: UtcDateTime


class FdeEvidenceCreate(BaseModel):
    phase: str = Field(pattern="^(red|diff|green|observation)$")
    command_text: str = Field(min_length=1)
    output: str = Field(min_length=1)
    return_code: int
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("观察时间必须带时区")
        return value


class FdeEvidenceOut(BaseModel):
    id: str
    task_id: str
    phase: str
    command_text: str
    output: str
    output_hash: str
    return_code: int
    observed_at: UtcDateTime
    created_at: UtcDateTime
    model_config = ConfigDict(from_attributes=True)


class FdeEventOut(BaseModel):
    id: str
    task_id: str
    kind: str
    from_state: str | None = None
    to_state: str | None = None
    actor: str
    detail: str
    created_at: UtcDateTime
    model_config = ConfigDict(from_attributes=True)


class FdeSpecValidateIn(BaseModel):
    spec_snapshot: str


class FdeSpecValidateOut(BaseModel):
    ok: bool
    issues: list[str]
    sections: dict[str, str]
    missing: list[str]
    template: str


class FdeTransitionIn(BaseModel):
    target: str
    actor: str = Field(default="", max_length=64)
    note: str = ""


class FdeAcceptIn(BaseModel):
    actor: str = Field(default="", max_length=64)
    note: str = ""


class FdeGateOut(BaseModel):
    allowed: bool
    code: int
    reason: str
    blockers: list[str]
    evidence_complete: bool
    accepted: bool
    state: str


class FdeTaskDetail(FdeTaskOut):
    evidences: list[FdeEvidenceOut]
    events: list[FdeEventOut]
    evidence_complete: bool
    issues: list[str]
    chain: dict
    gate: FdeGateOut
    next_states: list[str]
    blockers_detail: list[dict] = Field(default_factory=list)
    # L10 有界修复回路的只读投影（不改变状态，只判定与交接）
    repair_loop: dict = Field(default_factory=dict)
    # L15 交付摘要（交付四要素：结果/证据/边界/交接 + 可复制的 Markdown）
    delivery_summary: dict = Field(default_factory=dict)


# ===== 实战话术（坐席接听真实来电时的辅助面板）=====
class LiveScriptOut(BaseModel):
    """一条实战话术。

    ``audio_status`` 由服务端在读取时判定，不是数据库字段——录音是陆续补的，
    每加一个 mp3 / 每录一条就该立刻生效，所以每次查询都重新判一次：
    - ``file``  ：磁盘上有 ``<code>.<ext>``，播专业录音
    - ``record``：库里有一条当场录的，走 ``/api/live/scripts/<id>/audio``
    - ``tts``   ：没有录音，前端用浏览器实时合成兜底

    前端只需要看 ``has_audio`` 决定「录音 / 合成」标记，看 ``audio_url`` 播。
    """

    id: str
    scene_id: str
    code: str
    label: str
    text: str
    auto_play: bool
    sort_order: int
    # 「常用」标签：进场模式为 auto 的场景，进场自动播打这个标签的第一条
    is_common: bool = False
    # 手动排序位（Top1/Top2…）；null = 没排过，按热度排
    manual_rank: int | None = None
    tags: list[str] = Field(default_factory=list)
    use_count: int = 0
    audio_status: str = "tts"
    has_audio: bool = False
    audio_url: str | None = None
    audio_name: str = ""
    # 当场录音的元信息（专业录音为 0 / 空）
    recording_size: int = 0
    recording_duration_ms: int = 0
    recorded_by: str = ""
    recorded_at: str = ""


class LiveSceneOut(BaseModel):
    id: str
    code: str
    name: str
    phase: str
    source: str
    description: str
    sort_order: int
    pinned: bool
    # 进场模式：silent 进场不出声（默认）；auto 进场自动播「常用」第一条
    entry_mode: str = "silent"
    script_count: int = 0
    recorded_count: int = 0
    scripts: list[LiveScriptOut] = Field(default_factory=list)


class LiveScriptCreate(BaseModel):
    scene_id: str
    text: str = Field(min_length=1)
    label: str = Field(default="", max_length=200)
    code: str = Field(default="", max_length=48)
    auto_play: bool = False
    sort_order: int = 0
    tags: list[str] = Field(default_factory=list)


class LiveScriptUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1)
    label: str | None = Field(default=None, max_length=200)
    code: str | None = Field(default=None, max_length=48, description="改快捷码；冲突时后端回 409")
    auto_play: bool | None = None
    sort_order: int | None = None
    tags: list[str] | None = None


class LiveSceneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    phase: str = "business"
    source: str = "quick"
    description: str = ""
    sort_order: int = 0


class LiveEntryModeIn(BaseModel):
    """切换场景进场模式：silent 进场不出声；auto 进场自动播「常用」第一条。"""

    mode: str = Field(pattern="^(silent|auto)$")


class LiveCommonIn(BaseModel):
    """打/摘「常用」标签。"""

    is_common: bool


class LiveReorderIn(BaseModel):
    """手动排序（Top1/Top2…）。

    ``position`` 从 1 起，表示插到手动榜单第几位（原有位次顺延）；
    ``0`` 表示把手动的位次清掉，回落到按热度排。
    """

    position: int = Field(ge=0, le=999)


class LivePhaseOut(BaseModel):
    """话务动线的一个阶段（开场 / 通用支撑 / 业务处理 / 收尾）"""

    key: str
    label: str
    scene_count: int


class LiveAudioGapOut(BaseModel):
    """待录音清单的一行：要么从未录，要么文本改过需要重录。"""

    code: str
    scene_name: str
    label: str
    text: str
    use_count: int
    reason: str


class LiveBootstrap(BaseModel):
    """实战面板一次性拉全量。

    刻意不做分页/懒加载：坐席接起电话的那一刻，点开就得立刻有声，
    任何一次额外往返都是当场听得见的卡顿。全量约 200 条、几十 KB。
    """

    phases: list[LivePhaseOut]
    scenes: list[LiveSceneOut]
    script_total: int
    recorded_total: int
    audio_enabled: bool = True
    tts_fallback: bool = True

