"""应用缓存预算与 LRU 注册表测试。"""
from __future__ import annotations

import pytest

from app.services.cache_registry import CachePolicy, CacheRegistry, CacheStats


def test_region_tracks_hits_misses_and_lru_eviction() -> None:
    registry = CacheRegistry(budget_bytes=10)
    region = registry.create_region("tiles", CachePolicy(2, 6))

    region.put("a", b"aa", 2)
    region.put("b", b"bb", 2)
    assert region.get("a") == b"aa"
    assert region.get("missing") is None
    evicted = region.put("c", b"cccc", 4)

    assert evicted == ("b",)
    assert region.get("a") == b"aa"
    assert region.get("c") == b"cccc"
    stats = region.stats()
    assert stats.entries == 2
    assert stats.bytes_used == 6
    assert stats.hits == 3
    assert stats.misses == 1
    assert stats.evictions == 1


def test_registry_rejects_total_budget_overallocation() -> None:
    registry = CacheRegistry(budget_bytes=8)
    registry.create_region("first", CachePolicy(2, 5))

    with pytest.raises(ValueError, match="超过应用总上限"):
        registry.create_region("second", CachePolicy(2, 4))


def test_registry_aggregates_external_cache_and_clears_all() -> None:
    registry = CacheRegistry(budget_bytes=16)
    region = registry.create_region("avatars", CachePolicy(2, 8))
    region.put("avatar", "x", 3)
    cleared: list[bool] = []
    registry.register_external(
        "mca.surface",
        CachePolicy(2, 8),
        lambda: region.stats(),
        lambda: cleared.append(True),
    )

    snapshot = registry.stats()
    assert snapshot.bytes_used == 6
    assert [item.name for item in snapshot.regions] == [
        "avatars",
        "avatars",
    ]

    registry.clear_all()
    assert region.stats().entries == 0
    assert cleared == [True]


def test_external_registration_reserves_budget_until_closed() -> None:
    registry = CacheRegistry(budget_bytes=10)
    registration = registry.register_external(
        "map.surface",
        CachePolicy(2, 8),
        lambda: CacheStats("map.surface", 0, 0, 2, 8, 0, 0, 0),
        lambda: None,
    )

    with pytest.raises(ValueError, match="超过应用总上限"):
        registry.create_region("textures", CachePolicy(1, 3))

    registration.close()
    region = registry.create_region("textures", CachePolicy(1, 3))

    assert region.stats().max_bytes == 3


def test_external_registration_uses_distinct_clear_and_close_callbacks() -> None:
    registry = CacheRegistry(budget_bytes=10)
    calls: list[str] = []
    registration = registry.register_external(
        "shared",
        CachePolicy(1, 1),
        lambda: CacheStats("shared", 0, 0, 1, 1, 0, 0, 0),
        lambda: calls.append("clear"),
        on_close=lambda: calls.append("close"),
    )

    registry.clear_all()
    registration.close()

    assert calls == ["clear", "close"]


def test_close_rejects_new_region_and_closes_existing_region() -> None:
    registry = CacheRegistry()
    region = registry.create_region("textures", CachePolicy(2, 10))

    registry.close()

    with pytest.raises(RuntimeError, match="已经关闭"):
        registry.create_region("late", CachePolicy(1, 1))
    with pytest.raises(RuntimeError, match="已关闭"):
        region.put("x", "x", 1)


def test_close_removes_world_invalidators() -> None:
    registry = CacheRegistry()
    calls: list[str] = []
    registry.register_external(
        "world.index",
        CachePolicy(1, 1),
        lambda: CacheStats("world.index", 0, 0, 1, 1, 0, 0, 0),
        lambda: None,
    )
    registry.register_world_invalidator(
        "world.index",
        calls.append,
    )

    registry.close()

    assert registry.invalidate_world("/tmp/world") == 0
    assert calls == []


def test_region_close_removes_its_world_invalidator() -> None:
    registry = CacheRegistry()
    calls: list[str] = []
    region = registry.create_region("world.tiles", CachePolicy(1, 1))
    registry.register_world_invalidator("world.tiles", calls.append)

    region.close()

    assert registry.invalidate_world("/tmp/world") == 0
    assert calls == []


def test_world_invalidator_requires_registered_cache() -> None:
    registry = CacheRegistry()

    with pytest.raises(ValueError, match="没有对应缓存分区"):
        registry.register_world_invalidator("missing", lambda _world: None)
