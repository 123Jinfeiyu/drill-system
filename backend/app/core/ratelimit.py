"""登录失败限流（进程内内存实现）。

【P3-2 修复】登录接口原先无任何速率限制，可被暴力爆破。这里做单进程内存计数：
同一客户端 IP 在滑动窗口内失败达到阈值后短时拒绝。

- dev / 单 worker 场景足够；
- 多 worker / 多实例部署需换成 Redis 等共享存储 —— 接口已抽象为
  is_login_blocked / record_login_failure / clear_login_failures 三个函数，便于替换。
"""
import time
from collections import defaultdict, deque

_WINDOW_SECONDS = 60
_MAX_FAILURES = 5
# 防御性上限：异常流量下避免字典无限增长（超出后做一次过期清理）
_MAX_KEYS = 10000

_failures: dict[str, deque[float]] = defaultdict(deque)


def _prune(bucket: deque[float], now: float) -> None:
    while bucket and now - bucket[0] > _WINDOW_SECONDS:
        bucket.popleft()


def _maybe_gc() -> None:
    if len(_failures) <= _MAX_KEYS:
        return
    now = time.monotonic()
    stale = [
        key
        for key, bucket in _failures.items()
        if not bucket or now - bucket[-1] > _WINDOW_SECONDS
    ]
    for key in stale:
        _failures.pop(key, None)


def is_login_blocked(key: str) -> bool:
    """该 key（客户端 IP）当前是否处于封锁状态"""
    bucket = _failures.get(key)
    if not bucket:
        return False
    _prune(bucket, time.monotonic())
    return len(bucket) >= _MAX_FAILURES


def record_login_failure(key: str) -> None:
    """记录一次登录失败"""
    now = time.monotonic()
    bucket = _failures[key]
    _prune(bucket, now)
    bucket.append(now)
    _maybe_gc()


def clear_login_failures(key: str) -> None:
    """登录成功后清空失败计数"""
    _failures.pop(key, None)
