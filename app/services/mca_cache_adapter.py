"""把进程级 MCA 地表缓存纳入应用统一预算。"""
from __future__ import annotations

import threading

from app.services.cache_registry import (
    CachePolicy,
    CacheRegistration,
    CacheRegistry,
    CacheStats,
)
from core.mca.surface import (
    CHUNK_DECODE_CACHE_MAX_BYTES,
    CHUNK_DECODE_CACHE_MAX_ENTRIES,
    chunk_decode_cache_bytes,
    chunk_decode_cache_evictions,
    chunk_decode_cache_hits,
    chunk_decode_cache_misses,
    chunk_decode_cache_size,
    clear_chunk_decode_cache,
    invalidate_chunk_decode_cache_for_world,
)


MCA_CHUNK_CACHE_NAME = "mca.chunk"
_OWNERS_LOCK = threading.Lock()
_owners = 0


def register_mca_chunk_cache(
    cache_registry: CacheRegistry,
) -> CacheRegistration:
    """为一个应用注册一次共享 MCA 解码缓存。

    Args:
        cache_registry: 由应用持有的聚合缓存预算。

    Returns:
        生命周期由 ``cache_registry`` 持有的注册凭据。
    """
    global _owners
    with _OWNERS_LOCK:
        _owners += 1
    registration: CacheRegistration | None = None
    try:
        registration = cache_registry.register_external(
            MCA_CHUNK_CACHE_NAME,
            CachePolicy(
                CHUNK_DECODE_CACHE_MAX_ENTRIES,
                CHUNK_DECODE_CACHE_MAX_BYTES,
            ),
            _chunk_decode_cache_stats,
            clear_chunk_decode_cache,
            on_close=_release_mca_chunk_cache,
        )
        cache_registry.register_world_invalidator(
            MCA_CHUNK_CACHE_NAME,
            _invalidate_mca_world,
        )
        return registration
    except (RuntimeError, ValueError):
        if registration is not None:
            registration.close()
        else:
            _release_mca_chunk_cache()
        raise


def _invalidate_mca_world(world_path: str) -> None:
    """仅删除来源于已替换世界的 MCA 解码缓存。"""
    invalidate_chunk_decode_cache_for_world(world_path)


def _release_mca_chunk_cache() -> None:
    """仅在最后一个应用注册表关闭后清理进程状态。"""
    global _owners
    should_clear = False
    with _OWNERS_LOCK:
        if _owners > 0:
            _owners -= 1
        should_clear = _owners == 0
    if should_clear:
        clear_chunk_decode_cache()


def _chunk_decode_cache_stats() -> CacheStats:
    """按缓存实现的真实上限返回当前使用量。"""
    return CacheStats(
        name=MCA_CHUNK_CACHE_NAME,
        entries=chunk_decode_cache_size(),
        bytes_used=chunk_decode_cache_bytes(),
        max_entries=CHUNK_DECODE_CACHE_MAX_ENTRIES,
        max_bytes=CHUNK_DECODE_CACHE_MAX_BYTES,
        hits=chunk_decode_cache_hits(),
        misses=chunk_decode_cache_misses(),
        evictions=chunk_decode_cache_evictions(),
    )


__all__ = ["MCA_CHUNK_CACHE_NAME", "register_mca_chunk_cache"]
