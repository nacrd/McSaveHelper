"""WritableRegion round-trip tests (no anvil)."""
from __future__ import annotations

from pathlib import Path

import core.nbt as nbtlib
import pytest

from core.mca import (
    RegionFile,
    WritableRegion,
    copy_chunk_record,
    delete_chunk_entries,
)
from core.mca.format import HEADER_SIZE
from core.mca.errors import McaError


def _mini_chunk(x: int = 0, z: int = 0, marker: str = "full") -> nbtlib.File:
    return nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "xPos": nbtlib.Int(x),
        "zPos": nbtlib.Int(z),
        "Status": nbtlib.String(marker),
    })


def test_writable_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "r.0.0.mca"
    wr = WritableRegion.empty(path)
    wr.set_chunk(1, 2, _mini_chunk(1, 2, "a"))
    wr.set_chunk(3, 4, _mini_chunk(3, 4, "b"))
    wr.save(path, backup=False)
    assert path.is_file()
    assert path.stat().st_size > HEADER_SIZE

    with RegionFile.open(path) as rf:
        assert rf.count_chunks() == 2
        assert rf.has_chunk(1, 2)
        assert rf.has_chunk(3, 4)
        nbt = rf.read_chunk(1, 2)
        assert str(nbt["Status"]) == "a"
        nbt2 = rf.read_chunk(3, 4)
        assert str(nbt2["Status"]) == "b"


def test_writable_delete_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "r.1.1.mca"
    wr = WritableRegion.empty(path)
    wr.set_chunk(0, 0, _mini_chunk(0, 0, "keep"))
    wr.set_chunk(5, 5, _mini_chunk(5, 5, "gone"))
    wr.save(path, backup=False)

    wr2 = WritableRegion.open(path)
    assert wr2.delete_chunk(5, 5)
    wr2.save(path, backup=True)
    assert path.with_suffix(".mca.bak").is_file()

    with RegionFile.open(path) as rf:
        assert rf.has_chunk(0, 0)
        assert not rf.has_chunk(5, 5)
        assert str(rf.read_chunk(0, 0)["Status"]) == "keep"


def test_delete_chunk_entries(tmp_path: Path) -> None:
    path = tmp_path / "r.2.2.mca"
    wr = WritableRegion.empty(path)
    wr.set_chunk(1, 1, _mini_chunk(1, 1, "x"))
    wr.set_chunk(2, 2, _mini_chunk(2, 2, "y"))
    wr.save(path, backup=False)

    n = delete_chunk_entries(path, [(1, 1)], backup=True)
    assert n == 1
    with RegionFile.open(path) as rf:
        assert not rf.has_chunk(1, 1)
        assert rf.has_chunk(2, 2)


def test_mutate_chunk_nbt_in_place(tmp_path: Path) -> None:
    path = tmp_path / "r.3.3.mca"
    wr = WritableRegion.empty(path)
    wr.set_chunk(0, 1, _mini_chunk(0, 1, "old"))
    wr.save(path, backup=False)

    wr2 = WritableRegion.open(path)
    ch = wr2.get_chunk(0, 1)
    assert ch is not None
    ch["Status"] = nbtlib.String("new")
    wr2.save(path, backup=False)

    with RegionFile.open(path) as rf:
        assert str(rf.read_chunk(0, 1)["Status"]) == "new"


def test_delete_unknown_or_already_deleted_chunk_returns_false(tmp_path: Path) -> None:
    region = WritableRegion.empty(tmp_path / "r.0.0.mca")
    assert region.delete_chunk(1, 1) is False
    region.set_chunk(2, 2, _mini_chunk())
    assert region.delete_chunk(2, 2) is True
    assert region.delete_chunk(2, 2) is False


def test_writable_region_refuses_partial_load(tmp_path: Path) -> None:
    path = tmp_path / "r.0.0.mca"
    region = WritableRegion.empty(path)
    region.set_chunk(0, 0, _mini_chunk())
    region.save(backup=False)
    raw = bytearray(path.read_bytes())
    raw[HEADER_SIZE + 4] = 4  # unsupported LZ4 compression
    path.write_bytes(raw)

    with pytest.raises(McaError, match=r"chunk \(0, 0\)"):
        WritableRegion.open(path)


def test_copy_chunk_record_preserves_source_and_updates_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "r.0.0.mca"
    destination = tmp_path / "r.1.0.mca"

    source_region = WritableRegion.empty(source)
    source_region.set_chunk(1, 2, _mini_chunk(1, 2, "copied"))
    source_region.save(backup=False)

    destination_region = WritableRegion.empty(destination)
    destination_region.set_chunk(0, 0, _mini_chunk(0, 0, "kept"))
    destination_region.save(backup=False)

    copy_chunk_record(source, (1, 2), destination, (3, 4), backup=True)

    assert destination.with_suffix(".mca.bak").is_file()
    with RegionFile.open(source) as region:
        assert str(region.read_chunk(1, 2)["Status"]) == "copied"
    with RegionFile.open(destination) as region:
        assert str(region.read_chunk(0, 0)["Status"]) == "kept"
        assert str(region.read_chunk(3, 4)["Status"]) == "copied"
