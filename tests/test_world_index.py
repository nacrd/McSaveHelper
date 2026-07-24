"""共享世界只读索引与应用缓存测试。"""
from __future__ import annotations

import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from app.services.cache_registry import CacheRegistry
from app.services.world_index_service import (
    WorldIndexRegistry,
    WorldIndexRegistryClosedError,
)
from core.nbt import Compound, File, Int
from core.region_utils import DimensionRegionDirectory
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


def test_builder_preserves_new_player_and_data_path_precedence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = _world(tmp_path)
    modern_players = world / "players" / "data"
    modern_data = world / "data" / "minecraft"
    modern_players.mkdir(parents=True)
    modern_data.mkdir(parents=True)
    (modern_players / "aabb.dat").write_bytes(b"modern-player")
    (modern_data / "map_1.dat").write_bytes(b"modern-data")
    from core import world_index as world_index_module

    original_player_dirs = world_index_module.find_player_data_dirs
    original_data_dirs = world_index_module.find_data_dirs
    calls = {"players": 0, "data": 0}

    def player_dirs(path: Path):
        calls["players"] += 1
        return original_player_dirs(path)

    def data_dirs(path: Path):
        calls["data"] += 1
        return original_data_dirs(path)

    monkeypatch.setattr(world_index_module, "find_player_data_dirs", player_dirs)
    monkeypatch.setattr(world_index_module, "find_data_dirs", data_dirs)

    snapshot = WorldIndexBuilder().build(world)

    assert snapshot.player_file_map()["aabb"] == modern_players / "aabb.dat"
    assert snapshot.data_files == (modern_data / "map_1.dat",)
    assert calls == {"players": 1, "data": 1}


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


def test_builder_reuses_probe_dimension_descriptors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = _world(tmp_path)
    from core import world_index as world_index_module

    original_discover = world_index_module.discover_dimension_region_dirs
    calls = 0

    def discover_once(path: Path):
        nonlocal calls
        calls += 1
        if calls > 1:
            return []
        return original_discover(path)

    monkeypatch.setattr(
        world_index_module,
        "discover_dimension_region_dirs",
        discover_once,
    )

    snapshot = WorldIndexBuilder().build(world)

    assert calls == 1
    assert snapshot.dimensions[0].region_files == snapshot.region_files


def test_builder_excludes_region_deleted_during_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = _world(tmp_path)
    region_path = world / "region" / "r.0.0.mca"
    from core import world_index as world_index_module

    original_scan = world_index_module.scan_region_dir
    calls = 0

    def scan_then_delete(region_dir: Path) -> list[Path]:
        nonlocal calls
        calls += 1
        scanned = original_scan(region_dir)
        if region_path.exists():
            region_path.unlink()
        return scanned

    monkeypatch.setattr(world_index_module, "scan_region_dir", scan_then_delete)

    snapshot = WorldIndexBuilder().build(world)

    assert calls == 1
    assert snapshot.region_files == ()
    assert all(not dimension.region_files for dimension in snapshot.dimensions)
    assert snapshot.probe == WorldIndexBuilder().probe(world)


@pytest.mark.parametrize(
    ("relative_path", "snapshot_field"),
    [
        (Path("region/r.1.0.mca"), "region_files"),
        (Path("playerdata/bbcc.dat"), "player_files"),
        (Path("data/map_2.dat"), "data_files"),
    ],
)
def test_builder_excludes_linked_world_content(
    tmp_path: Path,
    relative_path: Path,
    snapshot_field: str,
) -> None:
    world = _world(tmp_path)
    outside = tmp_path / "outside" / relative_path.name
    outside.parent.mkdir()
    outside.write_bytes(b"external")
    linked = world / relative_path
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"当前平台不能创建测试符号链接: {exc}")

    snapshot = WorldIndexBuilder().build(world)
    indexed = getattr(snapshot, snapshot_field)
    indexed_paths = (
        tuple(path for _key, path in indexed)
        if snapshot_field == "player_files"
        else indexed
    )

    assert linked not in indexed_paths
    assert outside not in indexed_paths


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


class _InvalidateDuringBuildBuilder:
    """在首次快照生成后暂停，用于验证失效世代不会回填旧结果。"""

    def __init__(self) -> None:
        self.delegate = WorldIndexBuilder()
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def build(self, world_path: Path) -> WorldIndexSnapshot:
        self.calls += 1
        snapshot = self.delegate.build(world_path)
        if self.calls == 1:
            self.started.set()
            if not self.release.wait(2):
                raise RuntimeError("测试构建等待超时")
        return snapshot

    def probe(self, world_path: Path):
        return self.delegate.probe(world_path)


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


def test_registry_discards_inflight_snapshot_after_invalidate(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    builder = _InvalidateDuringBuildBuilder()
    registry = WorldIndexRegistry(builder=cast(WorldIndexBuilder, builder))
    results: list[WorldIndexSnapshot] = []
    errors: list[Exception] = []

    def load() -> None:
        try:
            results.append(registry.get(world))
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=load)
    thread.start()
    assert builder.started.wait(2)
    (world / "stats" / "after-invalidate.json").write_text(
        "{}",
        encoding="utf-8",
    )
    registry.invalidate(world)
    builder.release.set()
    thread.join(3)

    try:
        assert not thread.is_alive()
        assert errors == []
        assert len(results) == 1
        assert len(results[0].stats_files) == 2
        assert builder.calls == 2
        assert registry.stats().inflight == 0
    finally:
        registry.close()


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


def test_builder_refreshes_only_the_changed_index_category(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = _world(tmp_path)
    builder = WorldIndexBuilder()
    first = builder.build(world)
    from core.omni.world_scanner import WorldScanner

    def reject_full_scan(_scanner):
        raise AssertionError("增量刷新不应调用 scan_all")

    monkeypatch.setattr(WorldScanner, "scan_all", reject_full_scan)
    (world / "stats" / "extra.json").write_text("{}", encoding="utf-8")

    refreshed = builder.refresh(first)

    assert len(refreshed.stats_files) == 2
    assert refreshed.player_files is first.player_files
    assert refreshed.region_files is first.region_files
    assert refreshed.data_files is first.data_files


def test_builder_refresh_derives_changed_paths_from_observed_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = _world(tmp_path)
    builder = WorldIndexBuilder()
    first = builder.build(world)
    added_player = world / "playerdata" / "bbcc.dat"
    added_player.write_bytes(b"player-2")
    current_probe = builder.probe(world)
    from core.omni.world_scanner import WorldScanner

    scanner_calls = 0

    def transient_empty_scan(_scanner):
        nonlocal scanner_calls
        scanner_calls += 1
        return {}

    monkeypatch.setattr(
        WorldScanner,
        "scan_player_files",
        transient_empty_scan,
    )

    refreshed = builder.refresh(first, current_probe=current_probe)

    assert scanner_calls == 0
    assert refreshed.probe == current_probe
    assert refreshed.player_file_map() == {
        "aabb": world / "playerdata" / "aabb.dat",
        "bbcc": added_player,
    }


def test_builder_refreshes_dimensions_when_probe_metadata_changes(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    builder = WorldIndexBuilder()
    first = builder.build(world)
    extra_dimension = DimensionRegionDirectory(
        id="example:empty",
        name="example:empty",
        region_dir=world / "dimensions" / "example" / "empty" / "region",
    )
    changed_probe = replace(
        first.probe,
        dimensions=first.probe.dimensions + (extra_dimension,),
    )

    refreshed = builder.refresh(first, current_probe=changed_probe)

    assert refreshed.probe is changed_probe
    assert refreshed.dimensions[-1].id == "example:empty"


def test_registry_retries_transient_usercache_read_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = _world(tmp_path)
    registry = WorldIndexRegistry()
    first = registry.get(world)
    usercache_path = world / "usercache.json"
    usercache_path.write_text(
        json.dumps([{"uuid": "aabb", "name": "Steve"}]),
        encoding="utf-8",
    )
    from core.omni import world_scanner

    original_load = world_scanner.load_usercache_candidate

    def fail_read(_path: Path, _player_ids: set[str]):
        raise OSError("temporarily unavailable")

    monkeypatch.setattr(
        world_scanner,
        "load_usercache_candidate",
        fail_read,
    )
    with pytest.raises(OSError, match="读取 usercache 失败"):
        registry.get(world)

    monkeypatch.setattr(
        world_scanner,
        "load_usercache_candidate",
        original_load,
    )
    refreshed = registry.get(world)

    assert refreshed is not first
    assert refreshed.usercache_map() == {"aabb": "Steve"}
    registry.close()


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
    registry = CacheRegistry(
        budget_bytes=2 * WorldIndexRegistry.ENTRY_BUDGET_BYTES,
    )
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


def test_registry_does_not_retain_snapshot_over_byte_budget(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    registry = WorldIndexRegistry(max_entries=2, max_bytes=1)

    first = registry.get(world)
    second = registry.get(world)

    assert second == first
    assert registry.stats().entries == 0
    assert registry.stats().builds == 2
    assert registry.stats().evictions == 2
    registry.close()
