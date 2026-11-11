"""单端口发布入口：一个公网端口同时提供 API 与前端页面。

为什么需要它：本项目天然是两段跑——FastAPI 在 8000、Vite dev server 在 8080。
托管沙箱**只给一个公网端口**，所以这里把两段合成一段：
前端构建产物由 FastAPI 兜底托管（SPA 回退），``/api`` 与 ``/audio`` 照旧。

本地开发**不要**用这个入口（那样没有热更新），继续 8000 + 8080 两条腿跑。
它只为托管环境存在。

托管环境与本地不同的几处，都在这个文件里处理掉：

1. **没有 venv**：沙箱用系统 python，缺依赖就现场 ``pip install``。
2. **工作目录不确定**：``drill.db`` / ``.env`` / ``audio/live`` 都按 ``backend`` 相对解析，
   所以先 ``chdir`` 到 backend 再导入应用，否则会在错的目录建一个空库。
3. **上传会过滤掉「构建产物」目录**：实测 ``frontend/dist`` 整个没上传（前端 404、API 正常）。
   所以构建产物在发布包里改名成 ``webapp/``，取个中性名字绕开过滤规则。
4. **数据库文件可能被过滤**：``drill.db`` 缺席时先从 ``backend/seed/app_seed.bin`` 还原快照，
   再退回种子脚本重建。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
# 不叫 dist / build：托管上传会把这几个名字当构建产物过滤掉（实测踩过）
WEBAPP = ROOT / "webapp"
SEED_SNAPSHOT = BACKEND / "seed" / "app_seed.bin"

# 导入名 → pip 包名（不一致的那几个要单独写出来）
REQUIRED: tuple[tuple[str, str], ...] = (
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("sqlalchemy", "sqlalchemy"),
    ("aiosqlite", "aiosqlite"),
    ("pydantic_settings", "pydantic-settings"),
    ("multipart", "python-multipart"),
    ("jose", "python-jose"),
    ("bcrypt", "bcrypt"),
    ("bs4", "beautifulsoup4"),
)

# 静态资源的 SPA 回退要放行这些前缀，别把它们也吞成 index.html
RESERVED_PREFIXES = ("api/", "audio/", "docs", "redoc", "openapi.json", "diag")


def _importable(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def ensure_dependencies() -> None:
    """缺什么装什么。

    先探测一次再决定要不要装——直接无脑跑 ``pip install`` 会让每次冷启动都慢一截。
    """
    missing = [pkg for module, pkg in REQUIRED if not _importable(module)]
    if not missing:
        return
    print(f"[serve_app] 缺依赖 {missing}，执行 pip install -r requirements.txt", flush=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-input",
            "-q",
            "-r",
            str(BACKEND / "requirements.txt"),
        ],
        check=False,
    )


def ensure_database() -> str:
    """保证 ``drill.db`` 存在，返回用了哪条路径（写进 /diag，便于远端诊断）。"""
    db = BACKEND / "drill.db"
    if db.exists() and db.stat().st_size > 0:
        return "present"

    if SEED_SNAPSHOT.exists() and SEED_SNAPSHOT.stat().st_size > 0:
        print(f"[serve_app] drill.db 缺失，从快照 {SEED_SNAPSHOT} 还原", flush=True)
        db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SEED_SNAPSHOT, db)
        return "restored_from_snapshot"

    print("[serve_app] drill.db 与快照都没有，退回种子脚本重建（实战话术会缺数据）", flush=True)
    os.chdir(str(BACKEND))
    for script in ("seed.py", "seed_live_scripts.py"):
        if not (BACKEND / script).exists():
            continue
        result = subprocess.run([sys.executable, "-X", "utf8", script], cwd=str(BACKEND), check=False)
        print(f"[serve_app] {script} 退出码 {result.returncode}", flush=True)
    return "rebuilt_from_scripts"


def mount_frontend(app) -> bool:
    """把前端构建产物挂到根路径，并做 SPA 回退。

    React Router 的 ``/live``、``/practice`` 这类前端路由在服务端没有对应文件，
    浏览器直接刷新会 404，所以兜底返回 ``index.html`` 交给前端路由处理。
    必须**在所有 API 路由注册之后**调用。
    """
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    index = WEBAPP / "index.html"
    if not index.is_file():
        print(f"[serve_app] 警告：{index} 不存在，只有 API 可用（前端没进发布包？）", flush=True)
        return False

    assets = WEBAPP / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="app-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith(RESERVED_PREFIXES):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (WEBAPP / full_path).resolve() if full_path else None
        if candidate is not None and candidate.is_file() and str(candidate).startswith(str(WEBAPP.resolve())):
            return FileResponse(candidate)
        return FileResponse(index)

    print(f"[serve_app] 前端已挂载：{WEBAPP}", flush=True)
    return True


def promote_tokens(app) -> None:
    """把备用通道里的令牌提升到 ``Authorization`` 头。

    **为什么必须在入口层做**：托管网关会改写/注入 ``Authorization`` 头。实测到的现象是
    「同一张令牌放进查询参数能通过鉴权，放进请求头就 401」，于是所有只认请求头的路由
    一律 401——整套登录在线上直接不可用。业务代码里虽然也认四种通道，但发布时后端
    ``app/`` 目录未必每次都被同步到沙箱（本文件倒是每次都在），所以这条桥接放在入口层最稳。

    是**覆盖**而不是「缺了才补」：网关可能塞进来一个它自己的、验不过的 Authorization，
    补空没用。只有真在别处找到令牌才覆盖。
    """
    @app.middleware("http")
    async def promote_token(request, call_next):
        token = (
            request.headers.get("x-auth-token")
            or request.cookies.get("drill_token")
            or request.query_params.get("token")
        )
        if token and token.strip():
            scope = request.scope
            kept = [(k, v) for (k, v) in (scope.get("headers") or []) if k.lower() != b"authorization"]
            kept.append((b"authorization", b"Bearer " + token.strip().encode("latin-1", "ignore")))
            scope["headers"] = kept
        return await call_next(request)


def add_diagnostics(app, db_origin: str) -> None:
    """部署诊断端点。

    存在的理由很具体：托管环境的坑（网关改写请求头、上传过滤构建产物、后端目录不同步）
    **只能从运行中的实例里看出来**，本地怎么测都复现不了。没有这个端点就只能靠猜。
    只暴露布尔、计数与源码指纹，不含任何密钥。

    实现上刻意用**中间件**记录、端点只读全局变量：端点函数带 ``request: Request``
    注解时，FastAPI 会在注册路由时解析类型注解，而 ``Request`` 是在函数内部延迟导入的
    （模块顶层不能导入 fastapi——那时依赖还没装），解析必然失败。中间件签名无注解，绕开这一环。
    """
    last_seen: dict = {"path": "", "authorization": False, "x_auth_token": False,
                       "cookie": False, "query_token": False}

    @app.middleware("http")
    async def record_auth_channels(request, call_next):
        # 只记真实业务请求，/diag 自己的探测不算——否则永远只能看到探测请求带了什么
        if request.url.path != "/diag":
            last_seen.update(
                {
                    "path": request.url.path,
                    "authorization": bool(request.headers.get("authorization")),
                    "x_auth_token": bool(request.headers.get("x-auth-token")),
                    "cookie": bool(request.cookies.get("drill_token")),
                    "query_token": bool(request.query_params.get("token")),
                }
            )
        return await call_next(request)

    @app.get("/diag", include_in_schema=False)
    async def diag(probe: str = "") -> dict:
        """``?probe=<jwt>`` 会就地校验一次签名，用来判断令牌与密钥是否对得上。"""
        index = WEBAPP / "index.html"
        db = BACKEND / "drill.db"
        info: dict = {
            "pid": os.getpid(),
            "python": sys.version.split()[0],
            "cwd": os.getcwd(),
            "app_env": os.environ.get("APP_ENV", ""),
            "db_origin": db_origin,
            "db_exists": db.exists(),
            "db_bytes": db.stat().st_size if db.exists() else 0,
            "webapp_index": index.is_file(),
            # 这一行用来定位「网关到底把哪个请求头送到了应用」
            "last_request_channels": dict(last_seen),
            "env_jwt_secret_set": "JWT_SECRET" in os.environ,
            "backend_files": _backend_fingerprints(),
        }
        if probe.strip():
            try:
                from app.core.security import decode_token

                payload = decode_token(probe.strip())
                info["probe_ok"] = bool(payload)
                info["probe_sub"] = (payload or {}).get("sub", "")
            except Exception as error:
                info["probe_error"] = f"{type(error).__name__}: {error}"
        try:
            from app.config import settings as app_settings

            info["secret_len"] = len(app_settings.jwt_secret or "")
            info["secret_is_default"] = (
                app_settings.jwt_secret == "please-change-this-to-a-random-string"
            )
        except Exception:
            pass
        try:
            from sqlalchemy import func, select

            from app.database import AsyncSessionLocal
            from app.models import LiveScene, LiveScript, User

            async with AsyncSessionLocal() as db_session:
                info["users"] = await db_session.scalar(select(func.count()).select_from(User)) or 0
                info["live_scenes"] = await db_session.scalar(select(func.count()).select_from(LiveScene)) or 0
                info["live_scripts"] = await db_session.scalar(select(func.count()).select_from(LiveScript)) or 0
        except Exception as error:  # 诊断接口自己不能把服务带崩
            info["db_error"] = f"{type(error).__name__}: {error}"
        return info


def _backend_fingerprints() -> dict:
    """后端关键源码的指纹。

    用途单一：判断沙箱里跑的 ``app/`` 到底是不是本次发布包里的那一份。
    上传阶段对后端目录的同步并不保证（实测出现过入口文件是新的、业务代码却像旧的），
    没有这个指纹就只能靠猜。
    """
    import hashlib

    out: dict = {}
    for rel in ("app/core/deps.py", "app/routers/live.py", "app/services/live_scripts.py"):
        path = BACKEND / rel
        if not path.is_file():
            out[rel] = "missing"
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        out[rel] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    deps = BACKEND / "app" / "core" / "deps.py"
    out["deps_has_extract_token"] = deps.is_file() and "def extract_token" in deps.read_text(
        encoding="utf-8", errors="replace"
    )
    return out


def main() -> int:
    # 关掉 SQL 回显：托管环境日志里刷 SQL 既吵又慢
    os.environ.setdefault("APP_ENV", "prod")

    ensure_dependencies()

    # 顺序要紧：先切目录、再挂 sys.path，最后才 import 应用
    os.chdir(str(BACKEND))
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))

    db_origin = ensure_database()

    import uvicorn

    from app.main import app

    # 注册顺序有讲究，两处都踩过：
    # 1) 后注册的中间件在最外层、先执行 → 先装令牌桥接、再装诊断记录，
    #    诊断看到的才是「网关送来的原始通道」，而不是被桥接改写后的样子
    # 2) 诊断路由必须在 SPA 兜底之前注册，否则 /{full_path:path} 会先把 /diag 抢走
    promote_tokens(app)
    add_diagnostics(app, db_origin)
    mount_frontend(app)

    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError:
        print("[serve_app] PORT 必须是整数", file=sys.stderr)
        return 2

    print(f"[serve_app] 监听 0.0.0.0:{port}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
