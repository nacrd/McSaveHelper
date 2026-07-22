"""Register the process-level MCA surface cache with the application budget."""
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
    chunk_decode_cache_size,
    clear_chunk_decode_cache,
)


MCA_CHUNK_CACHE_NAME = "mca.chunk"
_OWNERS_LOCK = threading.Lock()
_owners = 0


def register_mca_chunk_cache(
    cache_registry: CacheRegistry,
) -> CacheRegistration:
    """Register the shared MCA decode cache exactly once for the application.

    Args:
        cache_registry: Application-owned aggregate cache budget.

    Returns:
        Registration owned by ``cache_registry`` for its full lifetime.
    """
    global _owners
    with _OWNERS_LOCK:
        _owners += 1
    try:
        return cache_registry.register_external(
            MCA_CHUNK_CACHE_NAME,
            CachePolicy(
                CHUNK_DECODE_CACHE_MAX_ENTRIES,
                CHUNK_DECODE_CACHE_MAX_BYTES,
            ),
            _chunk_decode_cache_stats,
            clear_chunk_decode_cache,
            on_close=_release_mca_chunk_cache,
        )
    except (RuntimeError, ValueError):
        with _OWNERS_LOCK:
            _owners -= 1
        raise


def _release_mca_chunk_cache() -> None:
    """Clear process state only after the last application registry closes."""
    global _owners
    should_clear = False
    with _OWNERS_LOCK:
        if _owners > 0:
            _owners -= 1
        should_clear = _owners == 0
    if should_clear:
        clear_chunk_decode_cache()


def _chunk_decode_cache_stats() -> CacheStats:
    """Return current usage using the cache implementation's real limits."""
    return CacheStats(
        name=MCA_CHUNK_CACHE_NAME,
        entries=chunk_decode_cache_size(),
        bytes_used=chunk_decode_cache_bytes(),
        max_entries=CHUNK_DECODE_CACHE_MAX_ENTRIES,
        max_bytes=CHUNK_DECODE_CACHE_MAX_BYTES,
        hits=0,
        misses=0,
        evictions=0,
    )


__all__ = ["MCA_CHUNK_CACHE_NAME", "register_mca_chunk_cache"]
