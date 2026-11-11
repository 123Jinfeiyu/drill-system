"""SQLAlchemy ORM 模型"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class Role(str, enum.Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"


class SessionStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    CANCELED = "canceled"


class MessageRole(str, enum.Enum):
    CUSTOMER = "customer"
    STUDENT = "student"
    SYSTEM = "system"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.STUDENT)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Scenario(Base):
    """演练剧本：客户人设、开场白、考察点、参考答案"""

    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128))
    customer_persona: Mapped[str] = mapped_column(Text)
    opening: Mapped[str] = mapped_column(Text)
    knowledge_points: Mapped[list] = mapped_column(JSON, default=list)
    reference_answer: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    max_turns: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DrillSession(Base):
    """一次演练会话"""

    __tablename__ = "drill_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(32), ForeignKey("scenarios.id"))
    student_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus), default=SessionStatus.PENDING
    )
    current_turn: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    scenario: Mapped[Scenario] = relationship(lazy="selectin")
    student: Mapped[User] = relationship(lazy="selectin")


class Message(Base):
    """演练对话消息"""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("drill_sessions.id"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    turn: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Score(Base):
    """演练评分"""

    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("drill_sessions.id"), unique=True
    )
    total: Mapped[float] = mapped_column(Float, default=0.0)
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    completeness: Mapped[float] = mapped_column(Float, default=0.0)
    etiquette: Mapped[float] = mapped_column(Float, default=0.0)
    responsiveness: Mapped[float] = mapped_column(Float, default=0.0)
    knowledge_use: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str] = mapped_column(Text, default="")
    weak_points: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class KnowledgeItem(Base):
    """知识库条目：聚币分期业务知识，供 AI 客户/评分检索注入"""
    __tablename__ = "knowledge_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ===== Q&A 演练场 =====
class PracticeSession(Base):
    """Q&A 演练场会话：AI 动态生成客户人设，学员自由练习"""

    __tablename__ = "practice_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    difficulty: Mapped[int] = mapped_column(Integer, default=2)
    persona: Mapped[str] = mapped_column(Text, default="")
    opening: Mapped[str] = mapped_column(Text, default="")
    max_turns: Mapped[int] = mapped_column(Integer, default=8)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus), default=SessionStatus.PENDING
    )
    current_turn: Mapped[int] = mapped_column(Integer, default=0)
    # 会话来源：practice=演练场（打字练习）；live_sim=模拟进线（点话术回复客户）。
    # 演练场列表按这个过滤，两边的记录互不污染。
    channel: Mapped[str] = mapped_column(String(16), default="practice")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    student: Mapped[User] = relationship(lazy="selectin")


class PracticeMessage(Base):
    """演练场对话消息"""

    __tablename__ = "practice_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("practice_sessions.id"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    turn: Mapped[int] = mapped_column(Integer, default=0)
    # 模拟进线里，坐席点「话术」回复时记录用的是哪条话术（快捷码库的 id）；
    # via = script（点话术）/ free（自由输入）。演练场打字的回复不带这些。
    script_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    via: Mapped[str] = mapped_column(String(16), default="free")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PracticeScore(Base):
    """演练场评分"""

    __tablename__ = "practice_scores"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("practice_sessions.id"), unique=True
    )
    total: Mapped[float] = mapped_column(Float, default=0.0)
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    completeness: Mapped[float] = mapped_column(Float, default=0.0)
    etiquette: Mapped[float] = mapped_column(Float, default=0.0)
    responsiveness: Mapped[float] = mapped_column(Float, default=0.0)
    knowledge_use: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str] = mapped_column(Text, default="")
    weak_points: Mapped[list] = mapped_column(JSON, default=list)
    suggestions: Mapped[str] = mapped_column(Text, default="")
    business_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ===== CodexFDE 工作台 =====
class FdeProject(Base):
    """受控交付项目；独立于客服演练业务数据。"""
    __tablename__ = "fde_projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str] = mapped_column(Text, default="")
    path: Mapped[str] = mapped_column(String(500), default="")
    owner_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FdeTask(Base):
    """一个可追溯的交付事项，保存创建时的需求快照。

    关键区分（对应 CodexFDE L01/L04）：
    - ``spec_issues`` 为空只说明需求**结构**合格，不代表需求想清楚了；
    - ``state`` 是 L04 状态机的位置，只允许沿 ``fde_ledger.TRANSITIONS`` 流转；
    - ``acceptance`` 与 ``state`` 是两件事：证据齐全（程序判断）不等于
      已被具名接受（人的判断），后者永远不由程序自动置位。
    - ``status`` 是遗留列，仅为兼容早期库存在，写入时与 ``state`` 保持同步。
    """
    __tablename__ = "fde_tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(32), ForeignKey("fde_projects.id"), index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    request: Mapped[str] = mapped_column(Text, default="")
    spec_snapshot: Mapped[str] = mapped_column(Text)
    spec_hash: Mapped[str] = mapped_column(String(64))
    spec_issues: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String(32), default="queued")
    status: Mapped[str] = mapped_column(String(32), default="in_progress")  # 遗留列，与 state 同步
    acceptance: Mapped[str] = mapped_column(String(32), default="pending_human_review")
    accepted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    project: Mapped[FdeProject] = relationship(lazy="selectin")


class FdeEvidence(Base):
    """任务的原始运行证据，不覆盖既有记录。"""
    __tablename__ = "fde_evidences"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(32), ForeignKey("fde_tasks.id"), index=True)
    phase: Mapped[str] = mapped_column(String(16))  # red / diff / green / observation
    command_text: Mapped[str] = mapped_column(Text)
    output: Mapped[str] = mapped_column(Text)
    output_hash: Mapped[str] = mapped_column(String(64))
    return_code: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FdeTaskEvent(Base):
    """任务事件日志：状态流转、复验、签收、证据追加都留痕，只追加不覆盖。

    对应 CodexFDE L04 的事件链（queued→spec_ready→executing→evaluating→review），
    以及「失败请求不得抹掉既有记录」这条边界。
    """
    __tablename__ = "fde_task_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(32), ForeignKey("fde_tasks.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # spec / evidence / transition / evaluate / acceptance / gate
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ===== 实战话术（坐席接听真实来电时的辅助面板）=====
class LiveScene(Base):
    """实战场景：一次真实来电里的一个话务环节（开场 / 安抚 / 会员退费 / 结束语…）。

    与 ``Scenario``（演练剧本）的区别：剧本是给学员练的，带人设、开场白、考察点、参考答案；
    实战场景是给在岗坐席用的，只说一件事——「客户现在问这个，我该怎么答」。
    两者业务上不相干，故独立建表，不共用。
    """

    __tablename__ = "live_scenes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    # 话务动线阶段：opening 开场 / support 通用支撑 / business 业务处理 / closing 收尾
    phase: Mapped[str] = mapped_column(String(16), default="business", index=True)
    # 素材来源：quick 一线快捷码库 / business 业务话术库 / faq 常见问题
    source: Mapped[str] = mapped_column(String(16), default="quick", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    # 进场模式（坐席自己的面板偏好，任何登录用户可改）：
    #   silent —— 进场景不出声（默认，不打扰）
    #   auto   —— 进场景自动播「常用」标记的第一条；没打标记就不播
    entry_mode: Mapped[str] = mapped_column(String(16), default="silent")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    scripts: Mapped[list["LiveScript"]] = relationship(
        back_populates="scene", cascade="all, delete-orphan", lazy="selectin"
    )


class LiveScript(Base):
    """单条实战话术。

    ``code`` 同时是**音频文件键**：默认在 ``backend/audio/live/<code>.mp3`` 找录音，
    找不到就看 ``LiveRecording``（系统内当场录的那条），再没有才降级为浏览器实时合成
    （音色不如真人，但保证当场能用）。这样「先上线、后补录音」不必改任何代码。
    """

    __tablename__ = "live_scripts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scene_id: Mapped[str] = mapped_column(String(32), ForeignKey("live_scenes.id"), index=True)
    code: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(200), default="")  # 可读短标题（业务库的「问题场景」）
    text: Mapped[str] = mapped_column(Text)
    # 录音文件名覆盖项；留空则按 <code>.mp3 约定推导
    audio_file: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 打开场景时是否自动播报（一般每个场景只有开场第一条为真）。
    # 注意：真正决定进场播不播的是场景的 entry_mode；这个字段只保留给种子数据标记开场语。
    auto_play: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # 「常用」标签：entry_mode=auto 的场景，进场只自动播打了这个标签的第一条
    is_common: Mapped[bool] = mapped_column(Boolean, default=False)
    # 手动排序位（Top1/Top2…）。NULL = 没手动排过 → 按热度（use_count）排；
    # 排过序的恒排在没排过的前面，且彼此按位次升序。
    manual_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    scene: Mapped[LiveScene] = relationship(back_populates="scripts", lazy="selectin")
    # selectin 预取的是「有没有录音」这件事（列表页要用），字节载荷另有 deferred 列兜着，
    # 不会因为列场景板就把几百 KB 音频全读进内存。
    recording: Mapped["LiveRecording | None"] = relationship(
        back_populates="script",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )


class LiveRecording(Base):
    """系统内当场录的一条话术配音（坐席/讲师自己录，浏览器录完直接传上来）。

    与「把 mp3 拷进 ``backend/audio/live/``」是两条互补的路子：

    - **批量/专业录音**：拷文件，按 ``<code>.<ext>`` 命名。先上线后补录走这条。
    - **当场试录**：存这里，字节进库、随 ``drill.db`` 一起走，不依赖文件系统。
      实战反馈「这条话术得改个字」时不用等录音棚排期。

    音频判定顺序是 **磁盘文件 → 本表 → 浏览器合成**，所以专业录音一旦到位会自然
    盖过试录，不需要先删掉什么。``data`` 是 deferred 列：只有真正取音频时才读字节。
    """

    __tablename__ = "live_recordings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    script_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("live_scripts.id"), unique=True, index=True
    )
    mime: Mapped[str] = mapped_column(String(80), default="audio/webm")
    ext: Mapped[str] = mapped_column(String(12), default=".webm")
    size: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    recorded_by: Mapped[str] = mapped_column(String(64), default="")  # 用户名
    recorded_by_name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    script: Mapped[LiveScript] = relationship(back_populates="recording")


# ===== 一人公司 OPC · 设计师接单撮合台账 =====
# 独立于客服演练业务数据，与 fde_* 两套台账并存互不干扰。
#
# 设计要点（对齐 CodexFDE L01/L04 的方法论，业务域换成「设计师接单撮合」）：
# - 订单保存**创建时的需求单快照**（spec_snapshot + spec_hash + spec_issues），
#   后续改需求不改历史快照，否则「当时约定的是什么」就再也说不清了；
# - ``state`` 是订单状态机的位置，只允许沿 ``opc_ledger.ORDER_TRANSITIONS`` 流转；
# - ``acceptance`` 与 ``state`` 是两件事：证据齐全（程序判断）不等于
#   已被具名验收（人的判断），后者永远不由程序自动置位；
# - 交付物与事件**只追加不覆盖** —— 这是证据链能成立的前提。


class OpcStore(Base):
    """店铺（甲方/需求来源）。"""

    __tablename__ = "opc_stores"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), index=True)
    url: Mapped[str] = mapped_column(String(500), default="")
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    manager: Mapped[str] = mapped_column(String(64), default="")
    commission: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    settlement_days: Mapped[int] = mapped_column(Integer, default=0)
    remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    orders: Mapped[list["OpcOrder"]] = relationship(back_populates="store")


class OpcDesigner(Base):
    """设计师（接单方）。带佣金比例与归属关系。"""

    __tablename__ = "opc_designers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    #: 上游系统的设计师 ID（``teamMembers.id``）。
    #:
    #: **这是同步的唯一键** —— 实测上游 300 条里有 3 个手机号重复
    #: （同一人多条档案），拿手机号做键会撞上 ``MultipleResultsFound``，
    #: 拿上游 ID 才是真的唯一。
    upstream_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    phone: Mapped[str] = mapped_column(String(32), default="")
    alipay_account: Mapped[str] = mapped_column(String(128), default="")
    alipay_name: Mapped[str] = mapped_column(String(64), default="")
    production_level: Mapped[str] = mapped_column(String(32), default="")
    design_tags: Mapped[str] = mapped_column(String(255), default="")
    war_zone: Mapped[str] = mapped_column(String(64), default="")
    hr_id: Mapped[str] = mapped_column(String(64), default="")
    quality_control_id: Mapped[str] = mapped_column(String(64), default="")
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(24), default="active")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    orders: Mapped[list["OpcOrder"]] = relationship(back_populates="designer")


class OpcOrder(Base):
    """一张订单。保存创建时的需求单快照。

    与 ``FdeTask`` 的对应关系：
    - ``spec_snapshot`` ↔ FDE 的需求合同快照
    - ``state``        ↔ FDE 的状态机位置
    - ``acceptance``   ↔ FDE 的具名接受
    """

    __tablename__ = "opc_orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    #: 上游订单 ID（``order.id``）。同步时用它做幂等键。
    upstream_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    order_sn: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    store_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("opc_stores.id"), nullable=True, index=True
    )
    store_name: Mapped[str] = mapped_column(String(128), default="")
    designer_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("opc_designers.id"), nullable=True, index=True
    )
    designer_name: Mapped[str] = mapped_column(String(64), default="")
    order_grade: Mapped[str] = mapped_column(String(32), default="")
    order_type: Mapped[str] = mapped_column(String(32), default="")
    order_commission: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    request_delivery_time: Mapped[str] = mapped_column(String(32), default="")
    sample_manuscript_time: Mapped[str] = mapped_column(String(32), default="")
    final_draft_time: Mapped[str] = mapped_column(String(32), default="")
    remark: Mapped[str] = mapped_column(Text, default="")

    spec_snapshot: Mapped[str] = mapped_column(Text, default="")
    spec_hash: Mapped[str] = mapped_column(String(64), default="")
    spec_issues: Mapped[list] = mapped_column(JSON, default=list)

    state: Mapped[str] = mapped_column(String(32), default="pending_assign", index=True)
    acceptance: Mapped[str] = mapped_column(String(32), default="pending_human_review")
    accepted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    depends_on: Mapped[list] = mapped_column(JSON, default=list)

    created_by: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    store: Mapped[OpcStore | None] = relationship(back_populates="orders")
    designer: Mapped[OpcDesigner | None] = relationship(back_populates="orders")
    deliveries: Mapped[list["OpcDelivery"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    events: Mapped[list["OpcEvent"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OpcDelivery(Base):
    """订单的原始交付证据，不覆盖既有记录。

    phase 语义照搬 FDE 的证据链：
    - ``red``         初稿不合格（return_code != 0）
    - ``diff``        返工改动（return_code == 0）
    - ``green``       终稿合格（return_code == 0，必须与红灯同一命令）
    - ``observation`` 观察记录（不参与链完整性判定）
    """

    __tablename__ = "opc_deliveries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("opc_orders.id"), index=True)
    phase: Mapped[str] = mapped_column(String(16))
    command_text: Mapped[str] = mapped_column(Text, default="")
    output: Mapped[str] = mapped_column(Text, default="")
    output_hash: Mapped[str] = mapped_column(String(64), default="")
    return_code: Mapped[int] = mapped_column(Integer, default=0)
    observed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    order: Mapped[OpcOrder] = relationship(back_populates="deliveries")


class OpcEvent(Base):
    """订单事件日志：状态流转、复验、验收、证据追加都留痕，只追加不覆盖。"""

    __tablename__ = "opc_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("opc_orders.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # spec/delivery/transition/evaluate/acceptance/gate
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    order: Mapped[OpcOrder] = relationship(back_populates="events")


class OpcSettlement(Base):
    """结算单。系统只做记录与对账，实际打款走支付宝手工操作。"""

    __tablename__ = "opc_settlements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("opc_orders.id"), index=True)
    order_sn: Mapped[str] = mapped_column(String(64), default="", index=True)
    designer_name: Mapped[str] = mapped_column(String(64), default="")
    commission: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    settlement_type: Mapped[str] = mapped_column(String(32), default="monthly")
    settlement_days: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    alipay_account: Mapped[str] = mapped_column(String(128), default="")
    alipay_name: Mapped[str] = mapped_column(String(64), default="")
    upstream_settlement_time: Mapped[str] = mapped_column(String(32), default="")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OpcSplitRule(Base):
    """分账规则。比例**只从这张表读**，代码里不写死任何比例。

    scope 取值见 ``opc_ledger.SPLIT_SCOPES``。
    """

    __tablename__ = "opc_split_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scope: Mapped[str] = mapped_column(String(32), index=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0"))
    basis: Mapped[str] = mapped_column(String(32), default="total")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


# ===========================================================================
# 设计师结算系统（sl_ 前缀）
#
# 依据《数字结算系统操作指南》课件画面设计，是给派单员与设计师**本地使用**
# 的一套轻量结算系统：派单员录设计师、登订单、管流程；设计师看订单、
# 点一键结算、查收益。
#
# 与 OPC 一人公司系统的关系：两套并存，各管各的域。
# OPC 管「需求合同 + 证据链 + 分账规则」，结算系统管「订单登记 + 流程节点 +
# 结算条件」。两者共享同一套用户与鉴权。
# ===========================================================================


class SlDesigner(Base):
    """设计师档案（模块二：录入设计师信息）。

    关键约束：
    - ``war_zone`` / ``hr_id`` **必须留空** —— 课件明确要求「切勿填写任何内容」
    - ``must_change_password`` —— 派单员设的是临时密码，设计师首次登录须改密
    - ``password_hash`` 存哈希，**不存明文**
    """

    __tablename__ = "sl_designers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    #: 上游团队成员 ID —— 从上游导入时的幂等键。
    #: 上游手机号**不唯一**（实测 1437 人里有 3 个手机号重复），
    #: 拿手机号做键会撞上 UniqueConstraint，所以只能拿上游 ID。
    upstream_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    #: 花名 —— 课件必填项
    nickname: Mapped[str] = mapped_column(String(64), default="")
    #: 手机号即**登录账号**
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    #: 支付宝账户 —— 收款凭证，课件强调「务必仔细核对」
    alipay_account: Mapped[str] = mapped_column(String(128), default="")
    alipay_name: Mapped[str] = mapped_column(String(64), default="")
    gender: Mapped[int] = mapped_column(Integer, default=0)
    recruitment_source: Mapped[str] = mapped_column(String(64), default="")
    #: 制作水平（档次）
    production_level: Mapped[str] = mapped_column(String(64), default="")
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    #: 所属战区 —— 课件要求留空
    war_zone: Mapped[str] = mapped_column(String(64), default="")
    #: 所属 HR —— 课件要求留空
    hr_id: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    orders: Mapped[list["SlOrder"]] = relationship(back_populates="designer")
    settlements: Mapped[list["SlSettlement"]] = relationship(back_populates="designer")


class SlOrder(Base):
    """订单（模块三：登记新订单；模块四：流程管理）。

    金额字段用 ``Numeric`` + ``Decimal`` —— 结算场景禁浮点。
    """

    __tablename__ = "sl_orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    #: 上游订单 ID —— 从上游导入时的幂等键（重复导入会跳过而不是产生第二条）
    upstream_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    #: 订单编号 —— 初稿完成后补录，交付前必须填
    order_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    #: 客户 ID —— 订单追溯的唯一凭证
    customer_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    #: 所属战区
    war_zone: Mapped[str] = mapped_column(String(64), default="", index=True)
    #: 对接客服真实姓名
    customer_service: Mapped[str] = mapped_column(String(64), default="")
    designer_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("sl_designers.id"), nullable=True, index=True
    )
    designer_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    #: 订单类型：personal / internal / external
    order_type: Mapped[str] = mapped_column(String(24), default="personal", index=True)
    #: 服务类型（如 PPT 定制）
    service_type: Mapped[str] = mapped_column(String(64), default="")
    order_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    #: 设计师佣金比例，规则层硬校验 [0.50, 0.70]
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"))
    #: 设计师佣金 = 金额 × 比例
    designer_commission: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    #: 任务要求（需求、风格、数量）
    requirement: Mapped[str] = mapped_column(Text, default="")
    #: 备注（特殊要求、交付节点）
    note: Mapped[str] = mapped_column(Text, default="")
    #: 交付时间
    deliver_date: Mapped[str] = mapped_column(String(32), default="")
    #: 接单时间 —— 结算有效期从这天算 60 天
    order_date: Mapped[str] = mapped_column(String(32), default="", index=True)
    state: Mapped[str] = mapped_column(String(32), default="pending_design", index=True)
    #: 终稿通过聊天记录截图（模块四节点二）
    chat_screenshot: Mapped[str] = mapped_column(String(500), default="")
    #: 交付文件截图（模块四节点二）
    file_screenshot: Mapped[str] = mapped_column(String(500), default="")
    #: 审核状态：pending / approved / rejected
    audit_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    audit_remark: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    designer: Mapped[SlDesigner | None] = relationship(back_populates="orders")
    settlements: Mapped[list["SlSettlement"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    logs: Mapped[list["SlLog"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class SlSettlement(Base):
    """结算单。系统只做记录与对账，实际打款走支付宝手工操作。"""

    __tablename__ = "sl_settlements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("sl_orders.id"), index=True)
    designer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("sl_designers.id"), index=True
    )
    designer_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    commission: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    #: 结算期 YYYY-MM
    period: Mapped[str] = mapped_column(String(16), default="", index=True)
    #: pending 待打款 / paid 已打款 / invalid 已失效
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    invalid_reason: Mapped[str] = mapped_column(String(255), default="")
    #: 收款账号快照 —— 打款时用，不能读设计师当前值（可能已改）
    alipay_account: Mapped[str] = mapped_column(String(128), default="")
    alipay_name: Mapped[str] = mapped_column(String(64), default="")
    #: 打款日期（默认每月 15 号）
    pay_date: Mapped[str] = mapped_column(String(32), default="")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: 打款流水号
    flow_no: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    order: Mapped[SlOrder] = relationship(back_populates="settlements")
    designer: Mapped[SlDesigner] = relationship(back_populates="settlements")


class SlLog(Base):
    """操作留痕。**只追加不覆盖** —— 这是结算场景可追溯的前提。

    每一次录入、流转、审核、结算、异常处理都记一笔。
    """

    __tablename__ = "sl_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    order_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("sl_orders.id"), nullable=True, index=True
    )
    designer_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("sl_designers.id"), nullable=True, index=True
    )
    #: 类型：designer / order / transition / audit / settle / exception
    kind: Mapped[str] = mapped_column(String(24), index=True)
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    order: Mapped[SlOrder | None] = relationship(back_populates="logs")
