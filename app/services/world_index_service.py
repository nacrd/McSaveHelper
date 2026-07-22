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
from core.world_index import (
    WorldIndexBuilder,
    WorldIndexProbe,
    WorldIndexSnapshot,
)


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


@dataclass
class _InflightBuild:
    """一个世界索引构建及其失效世代。"""

    future: Future[WorldIndexSnapshot]
    epoch: int


@dataclass(frozen=True)
class _CacheInspection:
    """A cached snapshot and the probe already observed for it."""

    snapshot: WorldIndexSnapshot
    probe: WorldIndexProbe
    is_current: bool


class WorldIndexRegistry:
    """按规范化世界路径缓存不可变索引并合并并发构建。"""

    # 每个条目预算为近似元数据占用，用于全局缓存注册表预留。
    ENTRY_BUDGET_BYTES = 4 * 1024 * 1024
    CACHE_NAME = "world.index"

    def __init__(
        self,
        builder: Optional[WorldIndexBuilder] = None,
        max_entries: int = 8,
        max_bytes: Optional[int] = None,
        cache_registry: Optional[CacheRegistry] = None,
    ) -> None:
        """创建有界索引注册表。

        Args:
            builder: 可替换扫描器，主要用于测试。
            max_entries: 最多保留的世界快照数量。
            max_bytes: 快照估算字节总上限；缺省按条目预算计算。
            cache_registry: 可选的应用缓存预算注册表。
        """
        if max_entries < 1:
            raise ValueError("世界索引缓存至少保留一个条目")
        selected_max_bytes = (
            max_entries * self.ENTRY_BUDGET_BYTES
            if max_bytes is None
            else max_bytes
        )
        if selected_max_bytes < 1:
            raise ValueError("世界索引缓存字节上限必须至少为 1")
        self._builder = builder or WorldIndexBuilder()
        self._max_entries = max_entries
        self._max_bytes = selected_max_bytes
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, WorldIndexSnapshot] = OrderedDict()
        self._entry_sizes: dict[str, int] = {}
        self._bytes_used = 0
        self._inflight: dict[str, _InflightBuild] = {}
        self._epochs: dict[str, int] = {}
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
                    self._max_bytes,
                ),
                self._cache_stats,
                self.clear,
            )
            cache_registry.register_world_invalidator(
                self.CACHE_NAME,
                self._invalidate_normalized_key,
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
        inspection: Optional[_CacheInspection] = None
        if not force_refresh:
            inspection = self._inspect_cached(key, world)
            if inspection is not None and inspection.is_current:
                return inspection.snapshot
        return self._get_or_build(
            key,
            world,
            force_rebuild=force_refresh,
            observed=inspection,
        )

    def refresh(
        self,
        world_path: Path | str,
    ) -> WorldIndexSnapshot:
        """检查探针并合并并发的增量刷新。"""
        return self.get(world_path)

    def _inspect_cached(
        self,
        key: str,
        world: Path,
    ) -> Optional[_CacheInspection]:
        """Probe one cached entry once and return a reusable inspection."""
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
                return _CacheInspection(cached, probe, True)
            if current is cached:
                return _CacheInspection(cached, probe, False)
        return None

    def _get_or_build(
        self,
        key: str,
        world: Path,
        *,
        force_rebuild: bool = False,
        observed: Optional[_CacheInspection] = None,
    ) -> WorldIndexSnapshot:
        """选出唯一构建者，其余调用方等待同一 Future。"""
        with self._lock:
            self._ensure_open_locked()
            inflight = self._inflight.get(key)
            is_builder = inflight is None
            previous = self._entries.get(key)
            current_probe = (
                observed.probe
                if observed is not None and observed.snapshot is previous
                else None
            )
            if inflight is None:
                inflight = _InflightBuild(
                    future=Future(),
                    epoch=self._epochs.get(key, 0),
                )
                self._inflight[key] = inflight
                self._misses += 1
        if not is_builder:
            return inflight.future.result()
        while True:
            try:
                if previous is not None and not force_rebuild:
                    snapshot = self._builder.refresh(
                        previous,
                        current_probe=current_probe,
                    )
                else:
                    snapshot = self._builder.build(world)
                if self._publish(key, inflight, snapshot):
                    return snapshot
                current_probe = None
            except BaseException as exc:
                self._publish_failure(key, inflight, exc)
                raise

    def _publish(
        self,
        key: str,
        inflight: _InflightBuild,
        snapshot: WorldIndexSnapshot,
    ) -> bool:
        """发布当前世代结果；旧世代结果丢弃并由构建者重试。"""
        with self._lock:
            if self._closed:
                error = WorldIndexRegistryClosedError("世界索引注册表已经关闭")
                self._inflight.pop(key, None)
                if not inflight.future.done():
                    inflight.future.set_exception(error)
                raise error
            current_epoch = self._epochs.get(key, 0)
            if current_epoch != inflight.epoch:
                inflight.epoch = current_epoch
                return False
            previous_size = self._entry_sizes.pop(key, 0)
            self._bytes_used -= previous_size
            snapshot_size = self._estimate_snapshot_bytes(snapshot)
            self._entries[key] = snapshot
            self._entry_sizes[key] = snapshot_size
            self._bytes_used += snapshot_size
            self._entries.move_to_end(key)
            self._builds += 1
            while self._cache_over_budget_locked():
                old_key, _snapshot = self._entries.popitem(last=False)
                self._bytes_used -= self._entry_sizes.pop(old_key, 0)
                self._evictions += 1
            self._inflight.pop(key, None)
            self._epochs.pop(key, None)
            inflight.future.set_result(snapshot)
            return True

    def _publish_failure(
        self,
        key: str,
        inflight: _InflightBuild,
        error: BaseException,
    ) -> None:
        """将构建异常传播给等待同一世界的调用方。"""
        with self._lock:
            if self._inflight.get(key) is inflight:
                self._inflight.pop(key, None)
            if not inflight.future.done():
                inflight.future.set_exception(error)

    def _cache_stats(self) -> CacheStats:
        """向缓存注册表暴露可观测统计。"""
        with self._lock:
            return CacheStats(
                name=self.CACHE_NAME,
                entries=len(self._entries),
                bytes_used=self._bytes_used,
                max_entries=self._max_entries,
                max_bytes=self._max_bytes,
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
            )

    def invalidate(self, world_path: Path | str) -> None:
        """显式丢弃一个世界的缓存快照。"""
        key = os.path.normcase(
            str(Path(world_path).expanduser().resolve())
        )
        self._invalidate_normalized_key(key)

    def _invalidate_normalized_key(self, key: str) -> None:
        """按已规范化世界键丢弃缓存（供 CacheRegistry.invalidate_world）。"""
        with self._lock:
            self._entries.pop(key, None)
            self._bytes_used -= self._entry_sizes.pop(key, 0)
            if key in self._inflight:
                self._epochs[key] = self._epochs.get(key, 0) + 1
            else:
                self._epochs.pop(key, None)

    def clear(self) -> None:
        """丢弃快照并让正在构建的调用重新生成当前世代结果。"""
        with self._lock:
            self._entries.clear()
            self._entry_sizes.clear()
            self._bytes_used = 0
            for key in self._inflight:
                self._epochs[key] = self._epochs.get(key, 0) + 1

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
            self._entry_sizes.clear()
            self._bytes_used = 0
            futures = tuple(item.future for item in self._inflight.values())
            self._inflight.clear()
            self._epochs.clear()
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

    def _cache_over_budget_locked(self) -> bool:
        """Return whether entry count or estimated memory exceeds its limit."""
        return (
            len(self._entries) > self._max_entries
            or self._bytes_used > self._max_bytes
        )

    @staticmethod
    def _estimate_snapshot_bytes(snapshot: WorldIndexSnapshot) -> int:
        """Conservatively estimate retained metadata and path strings."""
        total = 1024
        total += sum(
            128 + len(stamp.relative_path) * 2
            for stamp in snapshot.probe.files
        )
        total += sum(
            192 + len(player_id) * 2 + len(str(path)) * 2
            for player_id, path in snapshot.player_files
        )
        for paths in (
            snapshot.region_files,
            snapshot.data_files,
            snapshot.stats_files,
            snapshot.advancement_files,
        ):
            total += sum(128 + len(str(path)) * 2 for path in paths)
        total += sum(
            160 + len(player_id) * 2 + len(name) * 2
            for player_id, name in snapshot.usercache
        )
        total += sum(
            256
            + len(dimension.id) * 2
            + len(dimension.name) * 2
            + len(str(dimension.region_dir)) * 2
            + len(dimension.region_files) * 16
            for dimension in snapshot.dimensions
        )
        return total


__all__ = [
    "WorldIndexCacheStats",
    "WorldIndexRegistry",
    "WorldIndexRegistryClosedError",
]
