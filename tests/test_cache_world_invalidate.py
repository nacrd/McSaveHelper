"""CacheRegistry world-path invalidate and avatar namespace registration."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.cache_registry import CacheRegistry
from app.services.execution_runtime import ExecutionRuntime
from app.services.player_avatar_service import PlayerAvatarService
from app.services.world_index_service import WorldIndexRegistry
from core.world_index import WorldIndexBuilder


def _mini_world(tmp_path: Path) -> Path:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"level")
    (world / "region").mkdir()
    return world


def test_invalidate_world_drops_index_entries(tmp_path: Path) -> None:
    world = _mini_world(tmp_path)
    cache = CacheRegistry(budget_bytes=8 * 1024 * 1024)
    indexes = WorldIndexRegistry(
        builder=WorldIndexBuilder(),
        cache_registry=cache,
        max_entries=4,
        max_bytes=8 * 1024 * 1024,
    )
    try:
        first = indexes.get(world)
        names = {item.name for item in cache.stats().regions}
        assert "world.index" in names
        assert cache.invalidate_world(world) >= 1
        second = indexes.get(world)
        # After invalidate, a rebuild occurs (new or equal snapshot).
        assert second.world_path == first.world_path
        stats = indexes.stats()
        assert stats.builds >= 2
    finally:
        indexes.close()
        cache.close()


def test_world_index_registration_failure_releases_reserved_budget(
    monkeypatch,
) -> None:
    cache = CacheRegistry(budget_bytes=2 * 1024 * 1024)

    def reject_invalidator(_name, _callback) -> None:
        raise ValueError("invalidator unavailable")

    monkeypatch.setattr(cache, "register_world_invalidator", reject_invalidator)
    with pytest.raises(ValueError, match="invalidator unavailable"):
        WorldIndexRegistry(
            cache_registry=cache,
            max_entries=1,
            max_bytes=1024 * 1024,
        )

    assert cache.stats().regions == ()
    cache.close()


def test_player_avatar_registers_shared_namespace(tmp_path: Path) -> None:
    runtime = ExecutionRuntime()
    cache = CacheRegistry(budget_bytes=16 * 1024 * 1024)
    try:
        service = PlayerAvatarService(
            runtime,
            cache_dir=tmp_path / "avatars",
            enabled=False,
            cache_registry=cache,
        )
        names = {item.name for item in cache.stats().regions}
        assert "player.avatar" in names
        service.close()
        names_after = {item.name for item in cache.stats().regions}
        assert "player.avatar" not in names_after
    finally:
        runtime.shutdown(wait=False)
        cache.close()


def test_player_avatar_reports_bounded_lru_statistics(tmp_path: Path) -> None:
    runtime = ExecutionRuntime()
    cache = CacheRegistry(budget_bytes=2 * 1024 * 1024)
    avatar_dir = tmp_path / "avatars"
    service = PlayerAvatarService(
        runtime,
        cache_dir=avatar_dir,
        enabled=False,
        cache_registry=cache,
    )
    try:
        uuids = [f"{index:032x}" for index in range(129)]
        for uuid in uuids:
            path = avatar_dir / f"{uuid}.png"
            path.write_bytes(b"png")
            assert service.get_cached_path(uuid) == path
        assert service.get_cached_path(uuids[-1]) is not None

        stats = service._avatar_cache_stats()
        assert stats.entries == 128
        assert stats.max_bytes == 128 * 1024
        assert stats.hits == 1
        assert stats.misses == 129
        assert stats.evictions == 1
    finally:
        service.close()
        runtime.shutdown(wait=False)
        cache.close()


def test_player_avatar_discards_worker_result_after_close(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = ExecutionRuntime()
    cache = CacheRegistry(budget_bytes=2 * 1024 * 1024)
    service = PlayerAvatarService(
        runtime,
        cache_dir=tmp_path / "avatars",
        enabled=True,
        cache_registry=cache,
    )
    uuid = "11111111222233334444555555555555"
    callbacks: list[object] = []

    def close_during_fetch(_uuid: str) -> Path:
        service.close()
        return tmp_path / "fetched.png"

    monkeypatch.setattr(service, "_fetch_and_cache", close_during_fetch)
    service._inflight[uuid] = [callbacks.append]
    try:
        service._fetch_worker(uuid)
        assert callbacks == []
        assert service._memory == {}
        assert cache.stats().regions == ()
    finally:
        service.close()
        runtime.shutdown(wait=False)
        cache.close()
