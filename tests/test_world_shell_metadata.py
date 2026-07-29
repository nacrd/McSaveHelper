"""Progressive world shell metadata."""
from __future__ import annotations

from pathlib import Path

from app.services.world_index_service import WorldIndexRegistry
from app.services.world_repository import WorldRepository
from core.world_index import WorldIndexBuilder, WorldShellMetadata


def _world(tmp_path: Path) -> Path:
    world = tmp_path / "DemoWorld"
    (world / "region").mkdir(parents=True)
    (world / "level.dat").write_bytes(b"level")
    (world / "region" / "r.0.0.mca").write_bytes(b"\x00" * 64)
    (world / "region" / "r.1.0.mca").write_bytes(b"\x00" * 64)
    (world / "DIM-1" / "region").mkdir(parents=True)
    return world


def test_shell_metadata_is_lightweight(tmp_path: Path) -> None:
    world = _world(tmp_path)
    meta = WorldIndexBuilder().shell_metadata(world)
    assert isinstance(meta, WorldShellMetadata)
    assert meta.display_name == "DemoWorld"
    assert meta.has_level_dat is True
    assert meta.overworld_region_count == 2
    assert meta.dimension_hint_count >= 1


def test_repository_get_shell_metadata(tmp_path: Path) -> None:
    world = _world(tmp_path)
    repo = WorldRepository(WorldIndexRegistry())
    try:
        meta = repo.get_shell_metadata(world)
        assert meta.world_path == world.resolve() or meta.world_path == world
        assert meta.overworld_region_count == 2
    finally:
        repo.close()
