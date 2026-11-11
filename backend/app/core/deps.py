"""FastAPI 依赖注入：当前用户 + 角色校验

**令牌为什么有这么多条通道**（这是实测逼出来的，不是过度设计）：

标准做法只认 ``Authorization: Bearer <jwt>``。但在托管/网关环境下，实测该请求头
会被网关**整条丢掉**——同一个令牌放进查询参数能通过鉴权，放进请求头就 401
「无法验证凭据」。只认一种通道的后果不是「少个功能」，而是**整套登录在线上直接不可用**。

所以这里按固定优先级依次尝试，任何一条命中即可：

1. ``Authorization: Bearer <jwt>``  —— 标准通道，本地开发走这条
2. ``X-Auth-Token: <jwt>``           —— 自定义头（部分网关只吃标准头）
3. ``drill_token`` Cookie            —— 前端登录时同步写入，网关通常不动 Cookie
4. ``?token=<jwt>`` 查询参数          —— ``<audio src>`` 这类带不了请求头的场景本来就要用

安全性没有因此变松：**四条通道校验的是同一个签名令牌**，签名不对照样 401。
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.database import get_db
from app.models import Role, User

# auto_error=False：头缺失时不在这里抛错，交给 extract_token 走其余通道
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# 前端写入的 Cookie 名，与 client.ts 的 TOKEN_KEY 保持一致
TOKEN_COOKIE = "drill_token"

# 备用请求头（小写，Starlette 的 headers 不区分大小写）
FALLBACK_HEADERS = ("x-auth-token", "x-access-token")


def extract_token(request: Request, header_token: str | None,
                  extra_headers: tuple[str, ...] = ()) -> str | None:
    """按优先级从请求里取令牌，取不到返回 None。

    ``extra_headers`` 给**别的令牌体系**用 —— 比如设计师端有自己的
    ``x-designer-token``。刻意不把它塞进全局 ``FALLBACK_HEADERS``：
    那个列表是平台令牌的通道，混进去会让平台鉴权也开始接受设计师令牌。
    """
    if header_token and header_token.strip():
        return header_token.strip()
    for name in FALLBACK_HEADERS:
        value = request.headers.get(name)
        if value and value.strip():
            return value.strip()
    for name in extra_headers:
        value = request.headers.get(name)
        if value and value.strip():
            return value.strip()
    cookie = request.cookies.get(TOKEN_COOKIE)
    if cookie and cookie.strip():
        return cookie.strip()
    query = request.query_params.get("token")
    if query and query.strip():
        return query.strip()
    return None


async def get_current_user(
    request: Request,
    header_token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = extract_token(request, header_token)
    payload = decode_token(token) if token else None
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法验证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


async def require_teacher(current: User = Depends(get_current_user)) -> User:
    if current.role not in (Role.TEACHER, Role.ADMIN):
        raise HTTPException(status_code=403, detail="需要讲师或管理员权限")
    return current


async def require_student(current: User = Depends(get_current_user)) -> User:
    if current.role not in (Role.STUDENT, Role.TEACHER, Role.ADMIN):
        raise HTTPException(status_code=403, detail="无权操作")
    return current


# 【P1-1 修复】会话可见性统一判定：属主本人可看，讲师/管理员可回看任何学员的会话。
# 此前会话详情接口只放行属主（讲师回放必然 403），而 messages/score 接口又完全无校验
# （任何登录用户可越权读取他人对话，IDOR），两类接口统一收敛到这里。
def can_view_session(current: User, owner_id: str) -> bool:
    """当前用户能否查看 owner_id 的会话（详情/对话记录/评分/提示等只读接口）"""
    return current.id == owner_id or current.role in (Role.TEACHER, Role.ADMIN)


def forbid_if_not_viewable(current: User, owner_id: str) -> None:
    """不可查看时抛 403"""
    if not can_view_session(current, owner_id):
        raise HTTPException(status_code=403, detail="无权查看此会话")
