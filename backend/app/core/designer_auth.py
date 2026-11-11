"""设计师端鉴权依赖。

**为什么设计师端要单独一套鉴权？**

课件里设计师是「用手机号 + 派单员设的临时密码」登录结算端的，
跟平台的账号体系是两回事 —— 平台这边一个设计师都没有。

所以设计师端**不能**复用平台的 ``get_current_user``（那会要求
设计师在 ``users`` 表里存在）。这里给设计师端一套独立令牌：

- 令牌用**同一个 JWT 密钥**签发，但 payload 里带 ``scope="designer"``
- 平台令牌 scope 是 ``"platform"``（或缺省），两边**互不通用**
- 身份只从令牌里取，**不接受**请求头里明文传 designer_id ——
  明文传 ID 等于谁都能查别人的订单和收益

这样派单员令牌和设计师令牌**互相冒充不了**，也不会像现在这样
「两个凭证都得有」把人堵在门外。
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import extract_token
from app.core.security import decode_token
from app.database import get_db
from app.models import SlDesigner

# 设计师端也用标准 OAuth2 通道取令牌（auto_error=False 走多通道兜底）
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/settle/auth/login", auto_error=False)

#: 设计师令牌的 scope 标记
DESIGNER_SCOPE = "designer"

#: 设计师端专用的备用请求头。
#:
#: **刻意不放进** ``deps.FALLBACK_HEADERS`` —— 那个列表是平台令牌的通道，
#: 混进去会让平台鉴权也开始接受设计师令牌。两套令牌必须互不通用。
DESIGNER_FALLBACK_HEADERS = ("x-designer-token",)


async def get_current_designer(
    request: Request,
    header_token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> SlDesigner:
    """取当前登录的设计师。

    令牌无效 / 不是设计师令牌 / 设计师已停用 —— 分别给不同的提示，
    因为处理动作完全不同（重新登录 vs 联系派单员）。
    """
    token = extract_token(request, header_token, DESIGNER_FALLBACK_HEADERS)
    payload = decode_token(token) if token else None
    if not payload or payload.get("scope") != DESIGNER_SCOPE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录设计师端",
            headers={"WWW-Authenticate": "Bearer"},
        )

    designer_id = str(payload.get("sub") or "")
    if not designer_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无法验证凭据"
        )

    designer = await db.get(SlDesigner, designer_id)
    if designer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="设计师档案不存在"
        )
    if designer.status != "active":
        raise HTTPException(status_code=403, detail="该账号已停用，请联系派单员")
    return designer
