"""Base64 source cache for canvas top-view tiles."""
from __future__ import annotations

import base64
from collections import OrderedDict
import threading
from typing import Callable, Optional, Tuple

from app.services.cache_registry import (
    CachePolicy,
    CacheRegistration,
    CacheRegistry,
    CacheStats,
)

RegionCoord = Tuple[int, int]
TileLoader = Callable[[RegionCoord], Optional[bytes]]


class TileSourceCache:
    """Cache canvas-ready base64 strings by service generation."""

    MAX_ENTRIES: int = 4096
    MAX_BYTES: int = 16 * 1024 * 1024

    CACHE_NAME_PREFIX = "map.tile-source."

    def __init__(self, cache_registry: Optional[CacheRegistry] = None) -> None:
        """创建空的瓦片源缓存。"""
        self._lock = threading.RLock()
        self._generation = -1
        self._sources: OrderedDict[RegionCoord, Tuple[int, str]] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._closed = False
        self._name = f"{self.CACHE_NAME_PREFIX}{id(self)}"
        self._registration: Optional[CacheRegistration] = None
        if cache_registry is not None:
            self._registration = cache_registry.register_external(
                self._name,
                CachePolicy(
                    max_entries=self.MAX_ENTRIES,
                    max_bytes=self.MAX_BYTES,
                ),
                self.stats,
                self.clear,
            )

    def get(
        self,
        coord: RegionCoord,
        *,
        generation: int,
        version: int = 0,
        load_tile: TileLoader,
    ) -> Optional[str]:
        """Return a cached/encoded tile, invalidating on generation change."""
        with self._lock:
            if self._closed:
                return None
            if generation != self._generation:
                self._sources.clear()
                self._bytes = 0
                self._generation = generation
            cached = self._sources.get(coord)
            if cached is not None and cached[0] == version:
                self._sources.move_to_end(coord)
                self._hits += 1
                return cached[1]
            self._misses += 1
            if cached is not None:
                self._sources.pop(coord, None)
                self._bytes -= len(cached[1])
        raw = load_tile(coord)
        if not raw:
            return None
        source = base64.b64encode(raw).decode("ascii")
        with self._lock:
            if self._closed or generation != self._generation:
                return None
            current = self._sources.get(coord)
            if current is not None:
                if current[0] > version:
                    return current[1]
                self._sources.pop(coord, None)
                self._bytes -= len(current[1])
            self._sources[coord] = (version, source)
            self._bytes += len(source)
            while (
                len(self._sources) > self.MAX_ENTRIES
                or self._bytes > self.MAX_BYTES
            ) and self._sources:
                _old_coord, (_version, old_source) = self._sources.popitem(
                    last=False
                )
                self._bytes -= len(old_source)
                self._evictions += 1
        return source

    def clear(self) -> None:
        """清空全部缓存条目。"""
        with self._lock:
            self._sources.clear()
            self._bytes = 0
            self._generation = -1

    def stats(self) -> CacheStats:
        """返回注册表可消费的缓存统计快照。"""
        with self._lock:
            return CacheStats(
                name=self._name,
                entries=len(self._sources),
                bytes_used=self._bytes,
                max_entries=self.MAX_ENTRIES,
                max_bytes=self.MAX_BYTES,
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
            )

    def close(self) -> None:
        """释放缓存并注销应用预算；可重复调用。"""
        with self._lock:
            registration = self._registration
            self._registration = None
            self._closed = True
            self._sources.clear()
            self._bytes = 0
            self._generation = -1
        if registration is not None:
            registration.close()
