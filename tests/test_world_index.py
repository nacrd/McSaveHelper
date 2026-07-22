"""共享世界只读索引与应用缓存测试。"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import cast

import pytest

from app.services.cache_registry import CacheRegistry
from app.services.world_index_service import (
    WorldIndexRegistry,
    WorldIndexRegistryClosedError,
)
from core.nbt import Compound, File, Int
from core.world_index import WorldIndexBuilder, WorldIndexSnapshot


def _world(tmp_path: Path, name: str = "world") -> Path:
    world = tmp_path / name
    (world / "region").mkdir(parents=True)
    (world / "playerdata").mkdir()
    (world / "data").mkdir()
    (world / "stats").mkdir()
    File({"Data": Compound({"DataVersion": Int(1)})}).save(
        world / "level.dat"
    )
    (world / "region" / "r.0.0.mca").write_bytes(b"region")
    (world / "playerdata" / "aabb.dat").write_bytes(b"player")
    (world / "data" / "map_1.dat").write_bytes(b"data")
    (world / "stats" / "aabb.json").write_text("{}", encoding="utf-8")
    (world / "usercache.json").write_text(
        json.dumps([{"uuid": "aabb", "name": "Alex"}]),
        encoding="utf-8",
    )
    return world


def test_builder_returns_deterministic_immutable_world_snapshot(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)

    snapshot = WorldIndexBuilder().build(world)

    assert snapshot.world_path == world.resolve()
    assert snapshot.player_file_map()["aabb"].name == "aabb.dat"
    assert snapshot.usercache_map() == {"aabb": "Alex"}
    assert [path.name for path in snapshot.region_files] == ["r.0.0.mca"]
    assert snapshot.dimensions[0].id == "overworld"
    assert snapshot.dimensions[0].region_files == snapshot.region_files
    assert snapshot.probe.fingerprint


def test_builder_reuses_scanned_region_files_for_dimension_index(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = _world(tmp_path)
    calls = 0
    from core import scanner as scanner_module
    from core import world_index as world_index_module

    original = scanner_module.scan_region_dir

    def scan_once(region_dir: Path) -> list[Path]:
        nonlocal calls
        calls += 1
        return original(region_dir)

    monkeypatch.setattr(scanner_module, "scan_region_dir", scan_once)
    monkeypatch.setattr(world_index_module, "scan_region_dir", scan_once)

    snapshot = WorldIndexBuilder().build(world)

    assert calls == 1
    assert snapshot.dimensions[0].region_files == snapshot.region_files


def test_registry_reuses_snapshot_until_relevant_file_changes(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    registry = WorldIndexRegistry()

    first = registry.get(world)
    second = registry.get(world)
    (world / "stats" / "new.json").write_text("{}", encoding="utf-8")
    third = registry.get(world)

    assert second is first
    assert third is not first
    assert len(third.stats_files) == 2
    stats = registry.stats()
    assert stats.hits == 1
    assert stats.builds == 2


class _BlockingBuilder:
    def __init__(self, snapshot: WorldIndexSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def build(self, world_path: Path) -> WorldIndexSnapshot:
        del world_path
        self.calls += 1
        self.started.set()
        self.release.wait(1)
        return self.snapshot

    def probe(self, world_path: Path):
        del world_path
        return self.snapshot.probe


def test_registry_coalesces_concurrent_builds(tmp_path: Path) -> None:
    world = _world(tmp_path)
    snapshot = WorldIndexBuilder().build(world)
    builder = _BlockingBuilder(snapshot)
    registry = WorldIndexRegistry(builder=cast(WorldIndexBuilder, builder))
    results: list[WorldIndexSnapshot] = []

    first = threading.Thread(target=lambda: results.append(registry.get(world)))
    second = threading.Thread(target=lambda: results.append(registry.get(world)))
    first.start()
    assert builder.started.wait(1)
    second.start()
    builder.release.set()
    first.join(1)
    second.join(1)

    assert builder.calls == 1
    assert results == [snapshot, snapshot]


def test_registry_lru_invalidation_and_close(tmp_path: Path) -> None:
    first_world = _world(tmp_path, "first")
    second_world = _world(tmp_path, "second")
    registry = WorldIndexRegistry(max_entries=1)

    registry.get(first_world)
    registry.get(second_world)
    assert registry.stats().evictions == 1

    registry.invalidate(second_world)
    assert registry.stats().entries == 0
    registry.close()
    registry.close()
    with pytest.raises(WorldIndexRegistryClosedError):
        registry.get(first_world)


def test_builder_rejects_non_world(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="有效 Minecraft 存档"):
        WorldIndexBuilder().build(tmp_path)


def test_builder_refresh_reuses_snapshot_when_probe_stable(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    builder = WorldIndexBuilder()
    first = builder.build(world)
    second = builder.refresh(first)
    (world / "stats" / "extra.json").write_text("{}", encoding="utf-8")
    third = builder.refresh(first)

    assert second is first
    assert third is not first
    assert len(third.stats_files) == 2
    assert third.probe != first.probe


def test_registry_refresh_matches_get_consistency(tmp_path: Path) -> None:
    world = _world(tmp_path)
    registry = WorldIndexRegistry()
    first = registry.get(world)
    warm = registry.refresh(world)
    (world / "region" / "r.1.0.mca").write_bytes(b"region")
    rebuilt = registry.refresh(world)
    via_get = registry.get(world)

    assert warm is first
    assert rebuilt is not first
    assert via_get is rebuilt
    assert len(rebuilt.region_files) == 2
    assert registry.stats().builds >= 2


def test_registry_registers_with_cache_registry(tmp_path: Path) -> None:
    world = _world(tmp_path)
    registry = CacheRegistry(budget_bytes=8 * 256 * 1024)
    index_registry = WorldIndexRegistry(cache_registry=registry, max_entries=2)

    snapshot = index_registry.get(world)
    stats = registry.stats()
    names = [item.name for item in stats.regions]
    assert "world.index" in names
    assert snapshot.world_path == world.resolve()

    index_registry.close()
    names_after = [item.name for item in registry.stats().regions]
    assert "world.index" not in names_after
    registry.close()
