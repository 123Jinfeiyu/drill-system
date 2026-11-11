"""数据库连接与会话工厂"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""


engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "dev",
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每请求一个会话"""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """开发期直接建表；生产环境用 alembic 迁移"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # 轻量迁移：为已存在的表补充新列（dev 期方便，生产走 alembic）
    # 【P2-4 修复】此前只补 business_summary 一列，旧库缺 suggestions 列时
    # 查询/插入 practice_scores 直接报错；现在统一走列清单，逐列检查补充
    async with engine.begin() as conn:
        migrations: list[tuple[str, str, str]] = [
            ("practice_scores", "suggestions", "suggestions TEXT DEFAULT ''"),
            ("practice_scores", "business_summary", "business_summary TEXT DEFAULT ''"),
            # L05：CodexFDE 工作台台账字段（旧库缺列时补齐，不改动既有行）
            ("fde_tasks", "spec_issues", "spec_issues TEXT DEFAULT '[]'"),
            ("fde_tasks", "state", "state TEXT DEFAULT 'queued'"),
            ("fde_tasks", "acceptance", "acceptance TEXT DEFAULT 'pending_human_review'"),
            ("fde_tasks", "accepted_by", "accepted_by TEXT"),
            ("fde_tasks", "accepted_at", "accepted_at DATETIME"),
            ("fde_tasks", "depends_on", "depends_on TEXT DEFAULT '[]'"),
            # 实战话术：进场模式 / 常用标签 / 手动排序位（旧库缺列时补齐）
            ("live_scenes", "entry_mode", "entry_mode VARCHAR(16) DEFAULT 'silent'"),
            ("live_scripts", "is_common", "is_common BOOLEAN DEFAULT 0"),
            ("live_scripts", "manual_rank", "manual_rank INTEGER"),
            ("practice_sessions", "channel", "channel TEXT DEFAULT 'practice'"),
            ("practice_messages", "script_id", "script_id TEXT"),
            ("practice_messages", "via", "via TEXT DEFAULT 'free'"),
            # 结算系统：互通桥接的幂等键（从上游导入时按上游 ID 去重）
            ("sl_designers", "upstream_id", "upstream_id VARCHAR(32) DEFAULT ''"),
            ("sl_orders", "upstream_id", "upstream_id VARCHAR(32) DEFAULT ''"),
        ]
        for table, col, ddl in migrations:
            try:
                res = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
                cols = {row[1] for row in res}
                if col not in cols:
                    await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")
            except Exception:
                # 迁移失败不阻断启动（表可能刚由 create_all 建立，无需补列）
                pass

    # 【结算系统】删列迁移：`sl_orders.draft_no` 与 `order_no` 存的是同一件事
    # （都是「订单编号」），两个字段各说各话，导致补了编号诊断却仍报缺失。
    # 统一到 `order_no`，把冗余列删掉。
    # SQLite 3.35+ 支持 DROP COLUMN；旧版本会报错，此时保留旧列也不影响运行。
    async with engine.begin() as conn:
        try:
            res = await conn.exec_driver_sql("PRAGMA table_info(sl_orders)")
            if "draft_no" in {row[1] for row in res}:
                await conn.exec_driver_sql("ALTER TABLE sl_orders DROP COLUMN draft_no")
        except Exception:
            # 旧版 SQLite 不支持 DROP COLUMN —— 列留着但代码不再使用，
            # 不影响正确性，不该因此阻断启动。
            pass
