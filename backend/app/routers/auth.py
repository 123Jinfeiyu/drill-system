"""认证路由：注册 / 登录 / 当前用户"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.ratelimit import (
    clear_login_failures,
    is_login_blocked,
    record_login_failure,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models import Role, User
from app.schemas import LoginRequest, RegisterRequest, Token, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_key(request: Request) -> str:
    """限流维度：客户端 IP。

    若部署在反向代理后，request.client.host 会是代理地址；生产环境应改取
    X-Forwarded-For 首跳并做可信代理校验，此处保持最简单实现。
    """
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=UserOut, status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> User:
    """【P3-2 修复】注册：用户名长度、密码强度由 RegisterRequest 校验（非法返回 422）"""
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = User(
        username=username,
        hashed_password=hash_password(payload.password),
        role=Role.STUDENT,
        display_name=(payload.display_name or username)[:64],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Token:
    # 【P3-2 修复】登录失败限流：同一 IP 60 秒内失败达 5 次即拒绝，阻断暴力爆破
    key = _client_key(request)
    if is_login_blocked(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录失败次数过多，请 60 秒后重试",
            headers={"Retry-After": "60"},
        )

    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        record_login_failure(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    clear_login_failures(key)
    token = create_access_token(user.id, user.role.value)
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current: User = Depends(get_current_user)) -> User:
    return current
