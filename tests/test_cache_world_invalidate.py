"""CacheRegistry world-path invalidate and avatar namespace registration."""
from __future__ import annotations

from pathlib import Path

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
