"""Disk topview cache index and prune."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.mca import tile_cache
from core.mca.tile_cache_index import (
    index_path,
    index_stats,
    load_index,
    prune_to_limit,
    record_file,
    rebuild_index,
)


def test_record_and_prune_by_index(tmp_path: Path) -> None:
    root = tmp_path / "tiles"
    root.mkdir()
    paths = []
    for index in range(5):
        path = root / f"{index}.png"
        path.write_bytes(b"\x89PNG" + bytes([index]) * 32)
        record_file(root, path)
        paths.append(path)
    stats = index_stats(root)
    assert stats["indexed_files"] == 5
    assert stats["indexed_bytes"] > 0
    deleted, freed = prune_to_limit(root, max_files=2)
    assert deleted >= 3
    assert freed > 0
    remaining = load_index(root)
    assert len(remaining) <= 2


def test_rebuild_index_from_disk(tmp_path: Path) -> None:
    root = tmp_path / "tiles"
    root.mkdir()
    (root / "a.png").write_bytes(b"\x89PNG" + b"a" * 40)
    (root / "b.png").write_bytes(b"\x89PNG" + b"b" * 40)
    entries = rebuild_index(root)
    assert set(entries) == {"a.png", "b.png"}


def test_clear_disk_cache_removes_index_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "tiles"
    root.mkdir()
    monkeypatch.setattr(tile_cache, "_CACHE_DIR", root)
    tile = root / "a.png"
    tile.write_bytes(b"\x89PNG" + b"a" * 40)
    record_file(root, tile)
    assert index_path(root).is_file()

    result = tile_cache.clear_disk_cache()

    assert result["deleted_files"] == 1
    assert not index_path(root).exists()
    assert index_stats(root)["indexed_files"] == 0
    assert index_stats(root)["indexed_bytes"] == 0


def test_prune_rebuilds_missing_index_before_eviction(tmp_path: Path) -> None:
    root = tmp_path / "tiles"
    root.mkdir()
    for index in range(3):
        (root / f"{index}.png").write_bytes(
            b"\x89PNG" + bytes([index]) * 32
        )

    deleted, freed = prune_to_limit(root, max_files=1)

    assert deleted >= 2
    assert freed > 0
    assert len(load_index(root)) <= 1
