"""Disk topview cache index and prune."""
from __future__ import annotations

from pathlib import Path

from core.mca.tile_cache_index import (
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
