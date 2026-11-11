"""知识库检索：基于 bigram 关键词召回的轻量倒排索引，注入 AI Prompt。

【P4-6 修复】原实现每次调用都把整表载入内存、并为每条记录重建 bigram 集合，
调用频率高（每轮对话都要检索）时是 O(N·L) 的重复计算。现做法：

1. 缓存一份倒排索引：item_id -> (正文 bigram 集合, 标签列表)；查询时仅在内存打分，
   数据库侧只做一次"取 top_k 行"的回表查询。
2. 索引带 TTL 兜底（跨进程/脚本直改数据库时最多 30 秒后自愈）；
   API 的写操作（新增/编辑/删除/URL 导入）通过 invalidate_knowledge_index() 主动失效。
"""
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeItem

_INDEX_TTL_SECONDS = 30

# (构建时间(monotonic), 索引)。asyncio 单线程下整体替换无需加锁。
_cache: tuple[float, dict[str, tuple[set[str], list[str]]]] | None = None


def _bigrams(s: str) -> set[str]:
    s = s or ""
    return {s[i : i + 2] for i in range(len(s) - 1) if not any(ch.isspace() for ch in s[i : i + 2])}


def invalidate_knowledge_index() -> None:
    """知识库发生写入后调用，使索引立即失效（下次查询重建）"""
    global _cache
    _cache = None


async def _get_index(db: AsyncSession) -> dict[str, tuple[set[str], list[str]]]:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _INDEX_TTL_SECONDS:
        return _cache[1]

    rows = (
        await db.execute(
            select(
                KnowledgeItem.id,
                KnowledgeItem.title,
                KnowledgeItem.content,
                KnowledgeItem.tags,
            )
        )
    ).all()
    index: dict[str, tuple[set[str], list[str]]] = {}
    for item_id, title, content, tags in rows:
        index[item_id] = (_bigrams(f"{title} {content}".lower()), list(tags or []))
    _cache = (now, index)
    return index


async def search_knowledge(
    db: AsyncSession, query: str, top_k: int = 3
) -> list[KnowledgeItem]:
    """根据 query 召回最相关的 top_k 条知识。中文用 bigram 重叠 + 标签匹配。"""
    if not query:
        return []
    index = await _get_index(db)
    if not index:
        return []

    q_bigrams = _bigrams(query.lower())
    q_lower = query.lower()
    scored: list[tuple[int, str]] = []
    for item_id, (text_bigrams, tags) in index.items():
        # 标签命中是强信号
        tag_hits = sum(1 for t in tags if t and t.lower() in q_lower)
        bg_hits = len(q_bigrams & text_bigrams) if q_bigrams else 0
        score = tag_hits * 5 + bg_hits
        if score > 0:
            scored.append((score, item_id))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_ids = [item_id for _, item_id in scored[:top_k]]
    if not top_ids:
        return []

    # 只回表取命中的 top_k 行，并按打分顺序还原
    rows = (
        await db.execute(select(KnowledgeItem).where(KnowledgeItem.id.in_(top_ids)))
    ).scalars().all()
    by_id = {row.id: row for row in rows}
    return [by_id[i] for i in top_ids if i in by_id]
