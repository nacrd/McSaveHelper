"""应用作用域的世界只读索引缓存与并发构建协调。"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.services.cache_registry import (
    CachePolicy,
    CacheRegistration,
    CacheRegistry,
    CacheStats,
)
from core.world_index import WorldIndexBuilder, WorldIndexSnapshot


class WorldIndexRegistryClosedError(RuntimeError):
    """索引注册表关闭后继续读取时抛出。"""


@dataclass(frozen=True)
class WorldIndexCacheStats:
    """世界索引缓存的可观测统计。"""

    entries: int
    hits: int
    misses: int
    builds: int
    evictions: int
    inflight: int


class WorldIndexRegistry:
    """按规范化世界路径缓存不可变索引并合并并发构建。"""

    # 每个条目预算为近似元数据占用，用于全局缓存注册表预留。
    ENTRY_BUDGET_BYTES = 256 * 1024
    CACHE_NAME = "world.index"

    def __init__(
        self,
        builder: Optional[WorldIndexBuilder] = None,
        max_entries: int = 8,
        cache_registry: Optional[CacheRegistry] = None,
    ) -> None:
        """创建有界索引注册表。

        Args:
            builder: 可替换扫描器，主要用于测试。
            max_entries: 最多保留的世界快照数量。
            cache_registry: 可选的应用缓存预算注册表。
        """
        if max_entries < 1:
            raise ValueError("世界索引缓存至少保留一个条目")
        self._builder = builder or WorldIndexBuilder()
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, WorldIndexSnapshot] = OrderedDict()
        self._inflight: dict[str, Future[WorldIndexSnapshot]] = {}
        self._closed = False
        self._hits = 0
        self._misses = 0
        self._builds = 0
        self._evictions = 0
        self._cache_registration: Optional[CacheRegistration] = None
        if cache_registry is not None:
            self._cache_registration = cache_registry.register_external(
                self.CACHE_NAME,
                CachePolicy(
                    max_entries,
                    max_entries * self.ENTRY_BUDGET_BYTES,
                ),
                self._cache_stats,
                self.clear,
            )

    def get(
        self,
        world_path: Path | str,
        *,
        force_refresh: bool = False,
    ) -> WorldIndexSnapshot:
        """返回当前快照；文件签名变化时只重建一次。"""
        world = Path(world_path).expanduser().resolve()
        key = os.path.normcase(str(world))
        if not force_refresh:
            cached = self._cached_if_current(key, world)
            if cached is not None:
                return cached
        return self._get_or_build(key, world)

    def _cached_if_current(
        self,
        key: str,
        world: Path,
    ) -> Optional[WorldIndexSnapshot]:
        """比较轻量探针并返回仍有效的 LRU 条目。"""
        with self._lock:
            self._ensure_open_locked()
            cached = self._entries.get(key)
        if cached is None:
            return None
        try:
            probe = self._builder.probe(world)
        except (OSError, ValueError, RuntimeError, FileNotFoundError):
            return None
        with self._lock:
            self._ensure_open_locked()
            current = self._entries.get(key)
            if current is cached and cached.probe == probe:
                self._entries.move_to_end(key)
                self._hits += 1
                return cached
        return None

    def _get_or_build(self, key: str, world: Path) -> WorldIndexSnapshot:
        """选出唯一构建者，其余调用方等待同一 Future。"""
        with self._lock:
            self._ensure_open_locked()
            future = self._inflight.get(key)
            is_builder = future is None
            if future is None:
                future = Future()
                self._inflight[key] = future
                self._misses += 1
        if not is_builder:
            return future.result()
        try:
            snapshot = self._builder.build(world)
            self._publish(key, future, snapshot)
            return snapshot
        except BaseException as exc:
            self._publish_failure(key, future, exc)
            raise

    def _publish(
        self,
        key: str,
        future: Future[WorldIndexSnapshot],
        snapshot: WorldIndexSnapshot,
    ) -> None:
        """发布构建结果并执行 LRU 淘汰。"""
        with self._lock:
            if self._closed:
                error = WorldIndexRegistryClosedError("世界索引注册表已经关闭")
                self._inflight.pop(key, None)
                future.set_exception(error)
                raise error
            self._entries[key] = snapshot
            self._entries.move_to_end(key)
            self._builds += 1
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
                self._evictions += 1
            self._inflight.pop(key, None)
            future.set_result(snapshot)

    def _publish_failure(
        self,
        key: str,
        future: Future[WorldIndexSnapshot],
        error: BaseException,
    ) -> None:
        """将构建异常传播给等待同一世界的调用方。"""
        with self._lock:
            if self._inflight.get(key) is future:
                self._inflight.pop(key, None)
            if not future.done():
                future.set_exception(error)

    def _cache_stats(self) -> CacheStats:
        """向缓存注册表暴露可观测统计。"""
        with self._lock:
            # 世界索引快照大小因存档而异；使用条目预算近似字节占用。
            approx_bytes = len(self._entries) * self.ENTRY_BUDGET_BYTES
            return CacheStats(
                name=self.CACHE_NAME,
                entries=len(self._entries),
                bytes_used=approx_bytes,
                max_entries=self._max_entries,
                max_bytes=self._max_entries * self.ENTRY_BUDGET_BYTES,
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
            )

    def invalidate(self, world_path: Path | str) -> None:
        """显式丢弃一个世界的缓存快照。"""
        key = os.path.normcase(
            str(Path(world_path).expanduser().resolve())
        )
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        """丢弃全部已完成快照，不影响正在构建的调用。"""
        with self._lock:
            self._entries.clear()

    def stats(self) -> WorldIndexCacheStats:
        """返回一致的命中、构建和淘汰统计。"""
        with self._lock:
            return WorldIndexCacheStats(
                entries=len(self._entries),
                hits=self._hits,
                misses=self._misses,
                builds=self._builds,
                evictions=self._evictions,
                inflight=len(self._inflight),
            )

    def close(self) -> None:
        """关闭注册表并唤醒所有等待中的调用方。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._entries.clear()
            futures = tuple(self._inflight.values())
            self._inflight.clear()
            registration = self._cache_registration
            self._cache_registration = None
        for future in futures:
            if not future.done():
                future.set_exception(
                    WorldIndexRegistryClosedError(
                        "世界索引注册表已经关闭"
                    )
                )
        if registration is not None:
            registration.close()

    def _ensure_open_locked(self) -> None:
        """在锁内拒绝关闭后的读取。"""
        if self._closed:
            raise WorldIndexRegistryClosedError("世界索引注册表已经关闭")


__all__ = [
    "WorldIndexCacheStats",
    "WorldIndexRegistry",
    "WorldIndexRegistryClosedError",
]
