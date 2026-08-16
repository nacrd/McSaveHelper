"""WritableRegion round-trip tests (no anvil)."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import core.nbt as nbtlib
import pytest

import core.mca.writer as writer_module
from core.mca import (
    RegionFile,
    WritableRegion,
    copy_chunk_record,
    delete_chunk_entries,
)
from core.mca.errors import McaError
from core.mca.format import (
    COMPRESSION_ZLIB,
    EXTERNAL_CHUNK_STREAM_FLAG,
    HEADER_SIZE,
    SECTOR_SIZE,
)
from core.types import UUIDMapping
from core.worker import process_region_file


def _mini_chunk(x: int = 0, z: int = 0, marker: str = "full") -> nbtlib.File:
    return nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "xPos": nbtlib.Int(x),
        "zPos": nbtlib.Int(z),
        "Status": nbtlib.String(marker),
    })


def _uuid_mapping(old_uuid: str, new_uuid: str) -> UUIDMapping:
    return ([], [], old_uuid, new_uuid, (0, 0), (0, 0))


def _make_chunk_external(path: Path, local_cx: int, local_cz: int) -> Path:
    with RegionFile.open(path) as region:
        sector, sectors = region.chunk_location(local_cx, local_cz)
        external_path = region.external_chunk_path(local_cx, local_cz)
        chunk = region.read_chunk(local_cx, local_cz)
    assert sectors >= 1

    raw = writer_module.nbt_to_bytes(chunk)
    external_path.write_bytes(zlib.compress(raw))
    marker = EXTERNAL_CHUNK_STREAM_FLAG | COMPRESSION_ZLIB
    record = struct.pack(">I", 1) + bytes([marker])
    padded_record = record + b"\x00" * (sectors * SECTOR_SIZE - len(record))
    region_bytes = bytearray(path.read_bytes())
    record_offset = sector * SECTOR_SIZE
    region_bytes[
        record_offset:record_offset + sectors * SECTOR_SIZE
    ] = padded_record
    path.write_bytes(region_bytes)
    return external_path


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


def test_sparse_save_reencodes_only_dirty_chunk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "r.0.0.mca"
    initial = WritableRegion.empty(path)
    initial.set_chunk(0, 0, _mini_chunk(marker="change"))
    initial.set_chunk(1, 0, _mini_chunk(marker="keep"))
    initial.save(backup=False)
    with RegionFile.open(path) as source:
        clean_before = source.read_chunk_record(1, 0)

    compression_calls = 0
    original_compress = writer_module.compress_chunk

    def track_compression(raw: bytes, compression: int) -> tuple[int, bytes]:
        nonlocal compression_calls
        compression_calls += 1
        return original_compress(raw, compression)

    monkeypatch.setattr(writer_module, "compress_chunk", track_compression)
    region = WritableRegion.open_for_patch(path)
    for local_cx, local_cz, chunk in region.iter_chunks():
        if (local_cx, local_cz) == (0, 0):
            chunk["Status"] = nbtlib.String("changed")
            region.mark_chunk_dirty(local_cx, local_cz)
        else:
            region.discard_chunk_changes(local_cx, local_cz)
    region.save(backup=False)

    assert compression_calls == 1
    with RegionFile.open(path) as saved:
        assert str(saved.read_chunk(0, 0)["Status"]) == "changed"
        assert saved.read_chunk_record(1, 0) == clean_before


def test_sparse_save_preserves_clean_external_chunk(tmp_path: Path) -> None:
    path = tmp_path / "r.0.0.mca"
    initial = WritableRegion.empty(path)
    initial.set_chunk(0, 0, _mini_chunk(marker="change"))
    initial.set_chunk(1, 0, _mini_chunk(x=1, marker="external"))
    initial.save(backup=False)
    external_path = _make_chunk_external(path, 1, 0)
    external_before = external_path.read_bytes()

    region = WritableRegion.open_for_patch(path)
    for local_cx, local_cz, chunk in region.iter_chunks():
        if (local_cx, local_cz) == (0, 0):
            chunk["Status"] = nbtlib.String("changed")
            region.mark_chunk_dirty(local_cx, local_cz)
        else:
            region.discard_chunk_changes(local_cx, local_cz)
    region.save(backup=False)

    assert external_path.read_bytes() == external_before
    with RegionFile.open(path) as saved:
        external_record = saved.read_chunk_record(1, 0)
        assert external_record.data[4] & EXTERNAL_CHUNK_STREAM_FLAG
        assert str(saved.read_chunk(1, 0)["Status"]) == "external"


def test_region_worker_does_not_write_when_uuid_is_absent(tmp_path: Path) -> None:
    path = tmp_path / "r.0.0.mca"
    initial = WritableRegion.empty(path)
    chunk = _mini_chunk()
    chunk["Owner"] = nbtlib.String("unrelated")
    initial.set_chunk(0, 0, chunk)
    initial.save(backup=False)
    before = path.read_bytes()

    result = process_region_file(
        path,
        [_uuid_mapping("old-uuid", "new-uuid")],
    )

    assert result == (str(path), 0, None)
    assert path.read_bytes() == before
    assert not path.with_suffix(".mca.bak").exists()


def test_region_worker_preserves_clean_record_and_patches_match(
    tmp_path: Path,
) -> None:
    path = tmp_path / "r.0.0.mca"
    initial = WritableRegion.empty(path)
    changed = _mini_chunk(marker="change")
    changed["Owner"] = nbtlib.String("old-uuid")
    clean = _mini_chunk(x=1, marker="keep")
    clean["Owner"] = nbtlib.String("unrelated")
    initial.set_chunk(0, 0, changed)
    initial.set_chunk(1, 0, clean)
    initial.save(backup=False)
    with RegionFile.open(path) as source:
        clean_before = source.read_chunk_record(1, 0)

    result = process_region_file(
        path,
        [_uuid_mapping("old-uuid", "new-uuid")],
    )

    assert result == (str(path), 1, None)
    assert path.with_suffix(".mca.bak").is_file()
    with RegionFile.open(path) as saved:
        assert str(saved.read_chunk(0, 0)["Owner"]) == "new-uuid"
        assert saved.read_chunk_record(1, 0) == clean_before


def test_region_worker_keeps_original_file_when_patch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "r.0.0.mca"
    initial = WritableRegion.empty(path)
    initial.set_chunk(0, 0, _mini_chunk())
    initial.save(backup=False)
    before = path.read_bytes()

    def fail_patch(_tag: object, _mappings: list[UUIDMapping]) -> None:
        raise ValueError("patch failed")

    monkeypatch.setattr("core.worker.patch_nbt", fail_patch)
    result = process_region_file(path, [])

    assert result == (str(path), -1, "patch failed")
    assert path.read_bytes() == before
    assert not path.with_suffix(".mca.bak").exists()
