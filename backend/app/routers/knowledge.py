"""知识库管理路由：CRUD + 检索 + 公开URL导入"""
import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_teacher
from app.database import get_db
from app.models import KnowledgeItem, User
from app.schemas import (
    KnowledgeBatchImportResult,
    KnowledgeBatchImportUrl,
    KnowledgeImportFailure,
    KnowledgeImportUrl,
    KnowledgeItemCreate,
    KnowledgeItemOut,
    KnowledgeUpdate,
)
from app.services.knowledge import invalidate_knowledge_index, search_knowledge

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


# ===== URL 抓取（SSRF 防护）=====

# 【P3-1 修复】原先 import_url / import_urls_batch 直接 httpx.get(任意 URL)，
# 可被用来探测内网（127.0.0.1、10.x、172.16-31.x、192.168.x、169.254.x 等）。
_MAX_REDIRECTS = 5


def _reject_non_global(addr: "ipaddress._BaseAddress") -> None:
    """非公网地址（私网/环回/链路本地/保留段/组播）一律拒绝"""
    if not addr.is_global:
        raise HTTPException(status_code=400, detail="不允许访问内网/保留 IP 地址")


async def _validate_public_url(url: str) -> None:
    """【P3-1 修复】仅允许 http/https，且主机必须解析到公网地址。
    注：DNS 解析与实际请求之间存在 TOCTOU（DNS rebinding）残余风险，
    内训系统接受该风险；生产如需严格防护应改用出站代理 + 域名白名单。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="仅支持 http/https 的 URL")
    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="URL 缺少主机名")
    try:
        # 字面 IP 直接判断
        _reject_non_global(ipaddress.ip_address(host))
        return
    except ValueError:
        pass  # 不是 IP 字面量，走 DNS 解析检查
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        # getaddrinfo 是阻塞调用，放线程池避免卡事件循环
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, port, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="域名解析失败")
    if not infos:
        raise HTTPException(status_code=400, detail="域名解析失败")
    for info in infos:
        _reject_non_global(ipaddress.ip_address(info[4][0]))


async def _safe_fetch_text(url: str) -> str:
    """【P3-1 修复】带 SSRF 校验的抓取：follow_redirects=False，重定向逐跳重新校验"""
    current = url
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0), follow_redirects=False
    ) as client:
        for _ in range(_MAX_REDIRECTS):
            await _validate_public_url(current)
            resp = await client.get(current)
            if resp.is_redirect:
                if resp.next_request is None:
                    raise HTTPException(status_code=400, detail="重定向缺少目标地址")
                current = str(resp.next_request.url)  # httpx 已解析为绝对 URL
                continue
            resp.raise_for_status()
            return resp.text
    raise HTTPException(status_code=400, detail="重定向次数过多")


def _html_to_text(html: str, fallback_title: str) -> tuple[str, str]:
    """HTML 转纯文本：优先 bs4，未安装时用 regex 兜底。返回 (title, content)。"""
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = m.group(1).strip()[:200] if m else fallback_title
        stripped = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
        stripped = re.sub(r"<style[^>]*>.*?</style>", " ", stripped, flags=re.IGNORECASE | re.DOTALL)
        stripped = re.sub(r"<noscript[^>]*>.*?</noscript>", " ", stripped, flags=re.IGNORECASE | re.DOTALL)
        stripped = re.sub(r"<[^>]+>", " ", stripped)
        lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        return title, "\n".join(lines)[:8000]
    soup = BeautifulSoup(html, "html.parser")
    t = soup.title.string.strip() if soup.title and soup.title.string else fallback_title
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return t, "\n".join(lines)[:8000]


@router.get("", response_model=list[KnowledgeItemOut])
async def list_knowledge(
    # 【P4-4 修复】分页参数：默认不传返回全量（向后兼容），前端当前用表格客户端分页
    skip: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[KnowledgeItem]:
    stmt = select(KnowledgeItem).order_by(KnowledgeItem.created_at.desc())
    if skip:
        stmt = stmt.offset(skip)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=KnowledgeItemOut, status_code=201)
async def create_knowledge(payload: KnowledgeItemCreate, db: AsyncSession = Depends(get_db), _: User = Depends(require_teacher)) -> KnowledgeItem:
    item = KnowledgeItem(**payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    # 【P4-6 修复】写入后立即失效检索索引
    invalidate_knowledge_index()
    return item


@router.put("/{item_id}", response_model=KnowledgeItemOut)
async def update_knowledge(
    item_id: str,
    payload: KnowledgeUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_teacher),
) -> KnowledgeItem:
    """【P4-5 修复】知识条目编辑：原先只有新增/删除，改错字只能删了重建"""
    result = await db.execute(select(KnowledgeItem).where(KnowledgeItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    # 【P4-6 修复】写入后立即失效检索索引
    invalidate_knowledge_index()
    return item


@router.get("/search", response_model=list[KnowledgeItemOut])
async def search(q: str, top_k: int = 3, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)) -> list[KnowledgeItem]:
    return await search_knowledge(db, q, top_k=top_k)


@router.post("/import-url", response_model=KnowledgeItemOut, status_code=201)
async def import_url(payload: KnowledgeImportUrl, db: AsyncSession = Depends(get_db), _: User = Depends(require_teacher)) -> KnowledgeItem:
    # 【P3-1 修复】抓取改为带 SSRF 校验的 _safe_fetch_text（协议白名单 + 私网拦截 + 逐跳重定向校验）
    try:
        html = await _safe_fetch_text(payload.url)
        title, content = _html_to_text(html, payload.url)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"抓取失败: {e}") from e
    if not payload.title:
        title = payload.title or title
    item = KnowledgeItem(title=(payload.title or title)[:200], content=content, tags=payload.tags, source_url=payload.url)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    # 【P4-6 修复】写入后立即失效检索索引
    invalidate_knowledge_index()
    return item


@router.post("/import-urls", response_model=KnowledgeBatchImportResult, status_code=201)
async def import_urls_batch(
    payload: KnowledgeBatchImportUrl,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_teacher),
) -> KnowledgeBatchImportResult:
    items: list[KnowledgeItem] = []
    failures: list[KnowledgeImportFailure] = []
    for entry in payload.urls:
        url = entry.url.strip()
        if not url:
            continue
        try:
            # 【P3-1 修复】批量导入同样走 SSRF 校验抓取（原先硬依赖 bs4 且无任何校验）
            html = await _safe_fetch_text(url)
            title, content = _html_to_text(html, url)
            item = KnowledgeItem(title=(entry.title or title)[:200], content=content, tags=entry.tags, source_url=url)
            db.add(item)
            await db.flush()
            items.append(item)
        except Exception as e:
            failures.append(KnowledgeImportFailure(url=url, error=str(e)[:200]))
    await db.commit()
    # 【P4-6 修复】批量导入后立即失效检索索引
    invalidate_knowledge_index()
    for it in items:
        await db.refresh(it)
    return KnowledgeBatchImportResult(succeeded=len(items), failed=len(failures), failures=failures, items=items)


@router.delete("/{item_id}", status_code=204)
async def delete_knowledge(item_id: str, db: AsyncSession = Depends(get_db), _: User = Depends(require_teacher)) -> None:
    result = await db.execute(select(KnowledgeItem).where(KnowledgeItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    await db.delete(item)
    await db.commit()
    # 【P4-6 修复】删除后立即失效检索索引
    invalidate_knowledge_index()
