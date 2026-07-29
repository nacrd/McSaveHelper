"""应用作用域缓存预算、LRU 淘汰与统一可观测注册表。"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Generic, Hashable, Optional, TypeVar


KeyT = TypeVar("KeyT", bound=Hashable)
ValueT = TypeVar("ValueT")

DEFAULT_CACHE_BUDGET_BYTES = 256 * 1024 * 1024
WorldInvalidator = Callable[[str], None]


@dataclass(frozen=True)
class CachePolicy:
    """单个缓存分区的条目与字节预算。"""

    max_entries: int
    max_bytes: int

    def __post_init__(self) -> None:
        """拒绝无界或无效预算。"""
        if self.max_entries < 1:
            raise ValueError("缓存条目上限必须至少为 1")
        if self.max_bytes < 1:
            raise ValueError("缓存字节上限必须至少为 1")


@dataclass(frozen=True)
class CacheStats:
    """一个缓存分区的运行统计快照。"""

    name: str
    entries: int
    bytes_used: int
    max_entries: int
    max_bytes: int
    hits: int
    misses: int
    evictions: int


@dataclass(frozen=True)
class CacheRegistryStats:
    """应用缓存注册表聚合统计。"""

    budget_bytes: int
    bytes_used: int
    regions: tuple[CacheStats, ...]


class CacheRegistration:
    """可关闭的外部缓存注册凭据。

    外部缓存仍由其原始所有者维护；注册凭据只负责在该所有者释放时
    注销统计和预算预留，避免短生命周期视图留下陈旧的缓存分区。
    """

    def __init__(self, registry: "CacheRegistry", name: str) -> None:
        """绑定注册表与已经验证的分区名称。"""
        self._registry = registry
        self._name = name
        self._lock = threading.Lock()
        self._closed = False

    def close(self) -> None:
        """注销外部缓存；可重复调用。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._registry.unregister(self._name)


class CacheRegion(Generic[KeyT, ValueT]):
    """线程安全的有界 LRU 缓存分区。"""

    def __init__(
        self,
        name: str,
        policy: CachePolicy,
        on_close: Callable[[str], None],
    ) -> None:
        """创建一个由注册表拥有名称的缓存分区。"""
        self._name = name
        self._policy = policy
        self._on_close = on_close
        self._lock = threading.Lock()
        self._items: OrderedDict[KeyT, tuple[ValueT, int]] = OrderedDict()
        self._bytes_used = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._closed = False

    def get(self, key: KeyT) -> Optional[ValueT]:
        """读取值并提升其 LRU 优先级。"""
        with self._lock:
            item = self._items.get(key)
            if item is None:
                self._misses += 1
                return None
            self._items.move_to_end(key)
            self._hits += 1
            return item[0]

    def put(self, key: KeyT, value: ValueT, size_bytes: int) -> tuple[KeyT, ...]:
        """写入值并返回因预算淘汰的键。

        Args:
            key: 可哈希缓存键。
            value: 缓存值。
            size_bytes: 值占用的近似字节数。

        Returns:
            因本次写入被淘汰的键，按淘汰顺序排列。
        """
        if size_bytes < 0:
            raise ValueError("缓存条目大小不能为负数")
        with self._lock:
            self._ensure_open_locked()
            previous = self._items.pop(key, None)
            if previous is not None:
                self._bytes_used -= previous[1]
            self._items[key] = (value, size_bytes)
            self._bytes_used += size_bytes
            evicted: list[KeyT] = []
            while self._over_budget_locked() and self._items:
                old_key, (_, old_size) = self._items.popitem(last=False)
                self._bytes_used -= old_size
                self._evictions += 1
                evicted.append(old_key)
            return tuple(evicted)

    def remove(self, key: KeyT) -> Optional[ValueT]:
        """移除一个键并返回其值；不存在时返回 None。"""
        with self._lock:
            item = self._items.pop(key, None)
            if item is None:
                return None
            self._bytes_used -= item[1]
            return item[0]

    def clear(self) -> None:
        """清空所有条目但保留统计计数。"""
        with self._lock:
            self._items.clear()
            self._bytes_used = 0

    def stats(self) -> CacheStats:
        """返回分区统计快照。"""
        with self._lock:
            return CacheStats(
                name=self._name,
                entries=len(self._items),
                bytes_used=self._bytes_used,
                max_entries=self._policy.max_entries,
                max_bytes=self._policy.max_bytes,
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
            )

    def close(self) -> None:
        """清理数据并从注册表注销；可重复调用。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._items.clear()
            self._bytes_used = 0
        self._on_close(self._name)

    def _over_budget_locked(self) -> bool:
        return (
            len(self._items) > self._policy.max_entries
            or self._bytes_used > self._policy.max_bytes
        )

    def _ensure_open_locked(self) -> None:
        if self._closed:
            raise RuntimeError(f"缓存分区已关闭: {self._name}")


ExternalStats = Callable[[], CacheStats]
ExternalClear = Callable[[], None]


@dataclass(frozen=True)
class _ExternalCache:
    """Callbacks and budget reserved for one externally owned cache."""

    policy: CachePolicy
    stats: ExternalStats
    clear: ExternalClear
    on_close: ExternalClear


class CacheRegistry:
    """管理应用缓存分区并聚合内置与外部缓存统计。"""

    def __init__(self, budget_bytes: int = DEFAULT_CACHE_BUDGET_BYTES) -> None:
        """创建总内存预算受限的注册表。"""
        if budget_bytes < 1:
            raise ValueError("缓存总预算必须至少为 1")
        self._budget_bytes = budget_bytes
        self._lock = threading.Lock()
        self._regions: dict[str, CacheRegion[Any, Any]] = {}
        self._external: dict[str, _ExternalCache] = {}
        self._world_invalidators: dict[str, WorldInvalidator] = {}
        self._closed = False

    def create_region(
        self,
        name: str,
        policy: CachePolicy,
    ) -> CacheRegion[Any, Any]:
        """注册一个拥有独立预算的内存缓存分区。"""
        normalized = name.strip()
        if not normalized:
            raise ValueError("缓存分区名称不能为空")
        with self._lock:
            self._ensure_open_locked()
            if normalized in self._regions or normalized in self._external:
                raise ValueError(f"缓存分区已注册: {normalized}")
            self._ensure_budget_locked(policy.max_bytes)
            region: CacheRegion[Any, Any] = CacheRegion(
                normalized,
                policy,
                self._remove_region,
            )
            self._regions[normalized] = region
            return region

    def register_external(
        self,
        name: str,
        policy: CachePolicy,
        stats: ExternalStats,
        clear: ExternalClear,
        *,
        on_close: Optional[ExternalClear] = None,
    ) -> CacheRegistration:
        """注册不可直接托管、但可统计和清理的缓存适配器。

        Args:
            name: 缓存分区名称。
            policy: 条目数与字节预算。
            stats: 当前统计回调。
            clear: 显式全局清理时调用。
            on_close: 注销或注册表关闭时调用；缺省复用 ``clear``。

        Returns:
            可幂等注销该外部缓存的注册凭据。
        """
        normalized = name.strip()
        if not normalized:
            raise ValueError("外部缓存名称不能为空")
        with self._lock:
            self._ensure_open_locked()
            if normalized in self._regions or normalized in self._external:
                raise ValueError(f"缓存分区已注册: {normalized}")
            self._ensure_budget_locked(policy.max_bytes)
            self._external[normalized] = _ExternalCache(
                policy=policy,
                stats=stats,
                clear=clear,
                on_close=on_close or clear,
            )
        return CacheRegistration(self, normalized)

    def unregister(self, name: str) -> None:
        """注销一个短生命周期外部缓存并归还其预算预留。"""
        normalized = name.strip()
        if not normalized:
            return
        with self._lock:
            external = self._external.pop(normalized, None)
            self._world_invalidators.pop(normalized, None)
        if external is not None:
            try:
                external.on_close()
            except (OSError, RuntimeError, ValueError, TypeError):
                pass

    def register_world_invalidator(
        self,
        name: str,
        invalidate: WorldInvalidator,
    ) -> None:
        """注册按世界路径失效的回调（与已有分区名关联）。

        Args:
            name: 缓存分区名（应已 create/register）。
            invalidate: ``(normalized_world_key) -> None``。
        """
        normalized = name.strip()
        if not normalized:
            raise ValueError("世界失效器名称不能为空")
        with self._lock:
            self._ensure_open_locked()
            if normalized not in self._regions and normalized not in self._external:
                raise ValueError(f"世界失效器没有对应缓存分区: {normalized}")
            self._world_invalidators[normalized] = invalidate

    def invalidate_world(self, world_path: Path | str) -> int:
        """按世界路径通知所有已注册失效器。

        Args:
            world_path: 世界根路径。

        Returns:
            实际调用的失效器数量。
        """
        import os

        world = Path(world_path).expanduser().resolve()
        key = os.path.normcase(str(world))
        with self._lock:
            if self._closed:
                return 0
            invalidators = tuple(self._world_invalidators.items())
        called = 0
        for _name, invalidate in invalidators:
            try:
                invalidate(key)
                called += 1
            except (OSError, RuntimeError, ValueError, TypeError):
                continue
        return called

    def stats(self) -> CacheRegistryStats:
        """返回所有分区的聚合可观测快照。"""
        with self._lock:
            regions = tuple(self._regions.values())
            external = tuple(self._external.values())
            budget = self._budget_bytes
        snapshots = [region.stats() for region in regions]
        for item in external:
            try:
                snapshots.append(item.stats())
            except (OSError, RuntimeError, ValueError, TypeError):
                continue
        snapshots.sort(key=lambda item: item.name)
        return CacheRegistryStats(
            budget_bytes=budget,
            bytes_used=sum(item.bytes_used for item in snapshots),
            regions=tuple(snapshots),
        )

    def clear_all(self) -> None:
        """清理注册表内外的全部缓存内容。"""
        with self._lock:
            regions = tuple(self._regions.values())
            external = tuple(self._external.values())
        for region in regions:
            region.clear()
        for item in external:
            try:
                item.clear()
            except (OSError, RuntimeError, ValueError, TypeError):
                continue

    def close(self) -> None:
        """关闭全部内存分区并清理外部缓存；可重复调用。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            regions = tuple(self._regions.values())
            external = tuple(self._external.values())
            self._regions.clear()
            self._external.clear()
            self._world_invalidators.clear()
        for region in regions:
            region.close()
        for item in external:
            try:
                item.on_close()
            except (OSError, RuntimeError, ValueError, TypeError):
                continue

    def _remove_region(self, name: str) -> None:
        with self._lock:
            self._regions.pop(name, None)
            # 分区可能先于所有者关闭；同步移除回调，避免世界通知继续调用已关闭缓存。
            self._world_invalidators.pop(name, None)

    def _ensure_budget_locked(self, requested_bytes: int) -> None:
        allocated = sum(
            region.stats().max_bytes for region in self._regions.values()
        )
        allocated += sum(
            item.policy.max_bytes for item in self._external.values()
        )
        if allocated + requested_bytes > self._budget_bytes:
            raise ValueError(
                "缓存分区预算超过应用总上限: "
                f"{allocated + requested_bytes}>{self._budget_bytes}"
            )

    def _ensure_open_locked(self) -> None:
        if self._closed:
            raise RuntimeError("缓存注册表已经关闭")


def bytes_cache_stats(
    name: str,
    get_bytes: Callable[[], int],
    get_entries: Callable[[], int],
    max_bytes: int,
    max_entries: int,
) -> ExternalStats:
    """为旧缓存构建只读统计适配器。"""
    def stats() -> CacheStats:
        return CacheStats(
            name=name,
            entries=get_entries(),
            bytes_used=get_bytes(),
            max_entries=max_entries,
            max_bytes=max_bytes,
            hits=0,
            misses=0,
            evictions=0,
        )

    return stats


__all__ = [
    "CachePolicy",
    "CacheRegistration",
    "CacheRegion",
    "CacheRegistry",
    "CacheRegistryStats",
    "CacheStats",
    "DEFAULT_CACHE_BUDGET_BYTES",
    "bytes_cache_stats",
]
