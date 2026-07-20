"""Unit tests for core.mca.region_file (synthetic region, no anvil)."""
from __future__ import annotations

import io
import mmap
import struct
import zlib
from pathlib import Path

import nbtlib
import pytest

from core.mca import ChunkMissing, CorruptChunk, NativeRegion, RegionFile
from core.mca.format import (
    COMPRESSION_ZLIB,
    EXTERNAL_CHUNK_STREAM_FLAG,
    HEADER_SIZE,
    SECTOR_SIZE,
)
from core.mca.region_file import local_chunk_index, world_to_local
from core.mca import chunk_codec


def _build_minimal_chunk_nbt(
    x: int = 0,
    z: int = 0,
    data_version: int = 3463,
) -> bytes:
    root = nbtlib.File({
        "DataVersion": nbtlib.Int(data_version),
        "xPos": nbtlib.Int(x),
        "zPos": nbtlib.Int(z),
        "Status": nbtlib.String("full"),
        "IsLightOn": nbtlib.Byte(1),
    })
    buf = io.BytesIO()
    root.write(buf)
    return buf.getvalue()


def _build_region_with_chunk(
    local_cx: int,
    local_cz: int,
    chunk_nbt: bytes,
) -> bytes:
    compressed = zlib.compress(chunk_nbt)
    length = 1 + len(compressed)
    chunk_record = struct.pack(">I", length) + bytes([COMPRESSION_ZLIB]) + compressed

    sector_offset = 2
    data_sectors = (len(chunk_record) + SECTOR_SIZE - 1) // SECTOR_SIZE
    payload_size = data_sectors * SECTOR_SIZE
    payload = chunk_record + b"\x00" * (payload_size - len(chunk_record))

    header = bytearray(HEADER_SIZE)
    index = local_chunk_index(local_cx, local_cz)
    b_off = index * 4
    header[b_off:b_off + 3] = sector_offset.to_bytes(3, "big")
    header[b_off + 3] = data_sectors

    return bytes(header) + payload


def _build_region_with_external_chunk(local_cx: int, local_cz: int) -> bytes:
    marker = EXTERNAL_CHUNK_STREAM_FLAG | COMPRESSION_ZLIB
    chunk_record = struct.pack(">I", 1) + bytes([marker])
    payload = chunk_record + b"\x00" * (SECTOR_SIZE - len(chunk_record))
    header = bytearray(HEADER_SIZE)
    index = local_chunk_index(local_cx, local_cz)
    b_off = index * 4
    header[b_off:b_off + 3] = (2).to_bytes(3, "big")
    header[b_off + 3] = 1
    return bytes(header) + payload


class TestLocalIndex:
    def test_local_chunk_index(self) -> None:
        assert local_chunk_index(0, 0) == 0
        assert local_chunk_index(1, 0) == 1
        assert local_chunk_index(0, 1) == 32
        assert local_chunk_index(31, 31) == 1023

    def test_local_out_of_bounds(self) -> None:
        with pytest.raises(ChunkMissing):
            local_chunk_index(32, 0)

    def test_world_to_local_positive(self) -> None:
        rx, rz, lx, lz = world_to_local(33, 1)
        assert (rx, rz, lx, lz) == (1, 0, 1, 1)

    def test_world_to_local_negative(self) -> None:
        rx, rz, lx, lz = world_to_local(-1, -1)
        assert (rx, rz) == (-1, -1)
        assert (lx, lz) == (31, 31)


class TestRegionFileSynthetic:
    def test_missing_chunk(self) -> None:
        empty = b"\x00" * HEADER_SIZE
        rf = RegionFile.from_bytes(empty)
        assert rf.count_chunks() == 0
        assert not rf.has_chunk(0, 0)
        with pytest.raises(ChunkMissing):
            rf.read_chunk(0, 0)
        assert rf.read_chunk_or_none(0, 0) is None

    def test_read_chunk_fields(self) -> None:
        raw_nbt = _build_minimal_chunk_nbt(x=2, z=3, data_version=3463)
        blob = _build_region_with_chunk(2, 3, raw_nbt)
        rf = RegionFile.from_bytes(blob)

        assert rf.has_chunk(2, 3)
        assert not rf.has_chunk(0, 0)
        assert rf.count_chunks() == 1
        assert list(rf.iter_present_chunks()) == [(2, 3)]

        nbt = rf.read_chunk(2, 3)
        assert int(nbt["DataVersion"]) == 3463
        assert int(nbt["xPos"]) == 2
        assert int(nbt["zPos"]) == 3
        assert str(nbt["Status"]) == "full"

    def test_repeated_location_scans_reuse_parsed_table(self) -> None:
        blob = _build_region_with_chunk(2, 3, _build_minimal_chunk_nbt())
        rf = RegionFile.from_bytes(blob)

        assert rf.chunk_location(2, 3) != (0, 0)
        assert rf._locations is None
        first_scan = list(rf.iter_present_chunks())
        locations = rf._locations
        second_scan = list(rf.iter_present_chunks())

        assert first_scan == second_scan == [(2, 3)]
        assert locations is not None
        assert rf._locations is locations
        assert rf.chunk_location(2, 3) == locations[local_chunk_index(2, 3)]

    def test_corrupt_truncated(self) -> None:
        header = bytearray(HEADER_SIZE)
        header[0:3] = (2).to_bytes(3, "big")
        header[3] = 1
        blob = bytes(header)
        rf = RegionFile.from_bytes(blob)
        with pytest.raises(CorruptChunk):
            rf.read_chunk(0, 0)

    def test_chunk_payload_cannot_cross_allocated_sector(self) -> None:
        header = bytearray(HEADER_SIZE)
        header[0:3] = (2).to_bytes(3, "big")
        header[3] = 1
        record = (5000).to_bytes(4, "big") + bytes([COMPRESSION_ZLIB])
        blob = bytes(header) + record + b"x" * (SECTOR_SIZE * 2 - len(record))

        with pytest.raises(CorruptChunk, match="allocated sectors"):
            RegionFile.from_bytes(blob).read_chunk_raw(0, 0)

    def test_too_small_file(self) -> None:
        with pytest.raises(Exception):
            RegionFile.from_bytes(b"short")

    def test_context_manager_closes(self) -> None:
        raw_nbt = _build_minimal_chunk_nbt()
        blob = _build_region_with_chunk(0, 0, raw_nbt)
        with RegionFile.from_bytes(blob) as rf:
            assert rf.has_chunk(0, 0)
        with pytest.raises(Exception):
            rf.has_chunk(0, 0)

    def test_open_uses_read_only_mmap(self, tmp_path: Path, monkeypatch) -> None:
        path = tmp_path / "r.0.0.mca"
        path.write_bytes(_build_region_with_chunk(0, 0, _build_minimal_chunk_nbt()))

        def reject_read_bytes(self: Path) -> bytes:
            raise AssertionError(f"unexpected full-file read: {self}")

        monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)
        with RegionFile.open(path) as region:
            assert isinstance(region._data, mmap.mmap)
            assert int(region.read_chunk(0, 0)["DataVersion"]) == 3463

        assert region._data == b""

    def test_reads_standard_external_mcc_chunk(self, tmp_path: Path) -> None:
        local_cx, local_cz = 31, 3
        region_path = tmp_path / "r.-1.2.mca"
        region_path.write_bytes(
            _build_region_with_external_chunk(local_cx, local_cz)
        )
        external_path = tmp_path / "c.-1.67.mcc"
        external_path.write_bytes(
            zlib.compress(_build_minimal_chunk_nbt(x=-1, z=67))
        )

        with RegionFile.open(region_path) as region:
            assert region.external_chunk_path(local_cx, local_cz) == external_path
            chunk = region.read_chunk(local_cx, local_cz)

        assert int(chunk["xPos"]) == -1
        assert int(chunk["zPos"]) == 67

        with RegionFile.open(region_path) as region:
            assert region.has_external_chunks() is True
            first_signature = region.external_chunk_signature([(local_cx, local_cz)])
        external_path.write_bytes(
            zlib.compress(_build_minimal_chunk_nbt(x=-1, z=67) + b"changed")
        )
        with RegionFile.open(region_path) as region:
            assert region.external_chunk_signature([(local_cx, local_cz)]) != first_signature

    def test_native_region_iterates_only_present_chunks(self, tmp_path: Path) -> None:
        region_path = tmp_path / "r.-2.3.mca"
        region_path.write_bytes(
            _build_region_with_chunk(1, 4, _build_minimal_chunk_nbt(x=1, z=4))
        )

        with NativeRegion.from_file(region_path) as region:
            assert list(region.iter_present_chunks()) == [(1, 4)]
            chunks = list(region.iter_chunks())

        assert [(cx, cz) for cx, cz, _chunk in chunks] == [(1, 4)]
        assert chunks[0][2] is not None

    def test_missing_external_mcc_isolated_as_corrupt_chunk(
        self,
        tmp_path: Path,
    ) -> None:
        region_path = tmp_path / "r.0.0.mca"
        region_path.write_bytes(_build_region_with_external_chunk(1, 2))

        with RegionFile.open(region_path) as region:
            with pytest.raises(CorruptChunk, match="external chunk"):
                region.read_chunk_raw(1, 2)


def test_decompression_has_output_limit(monkeypatch) -> None:
    monkeypatch.setattr(chunk_codec, "MAX_DECOMPRESSED_CHUNK_BYTES", 1024)
    payload = zlib.compress(b"x" * 2048)

    with pytest.raises(CorruptChunk, match="解压结果"):
        chunk_codec.decompress_chunk(COMPRESSION_ZLIB, payload)
