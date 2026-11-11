"""FastAPI 入口"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import (auth, fde, knowledge, live, live_calls, opc_ops,
                          opc_orders, opc_upstream, practice, scenarios,
                          sessions, settle)
from app.services import live_scripts
from app.services.llm_client import llm_client


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 启动时自动建表（开发期用，生产用 alembic 迁移）
    await init_db()
    # Ollama 本地模型预热(常驻 30 分钟),减少学员首个请求的冷启动等待
    await llm_client.warmup()
    yield


app = FastAPI(
    title="AI 智能客服演练系统",
    description="团队培训客服演练平台：AI 扮演客户 + 多维评分",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(scenarios.router)
app.include_router(sessions.router)
app.include_router(knowledge.router)
app.include_router(practice.router)
app.include_router(fde.router)
app.include_router(opc_orders.router)
app.include_router(opc_ops.router)
app.include_router(opc_upstream.router)
app.include_router(settle.router)
app.include_router(live.router)
app.include_router(live_calls.router)


# ===== 实战话术录音目录 =====
# 录音由录音同事按 <快捷码>.mp3 命名丢进来即可生效，不需要重启或重新导入。
# 目录不存在时先建出来：让同事一眼看到「该往哪放」，而不是对着报错猜路径。
_live_audio_dir = live_scripts.audio_dir()
_live_audio_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    live_scripts.AUDIO_URL_PREFIX,
    StaticFiles(directory=str(_live_audio_dir)),
    name="live-audio",
)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "env": settings.app_env}
