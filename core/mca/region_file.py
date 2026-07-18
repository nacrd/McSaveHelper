"""Read-only Anvil region file (.mca) access.

Phase 1: open, list present chunks, load chunk NBT as nbtlib compounds.
Does not depend on anvil-parser.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Optional, Tuple, Union

import nbtlib

from core.mca.chunk_codec import decompress_chunk
from core.mca.errors import ChunkMissing, CorruptChunk, McaError
from core.mca.format import (
    CHUNKS_PER_REGION,
    CHUNKS_PER_SIDE,
    COMPRESSION_HEADER_SIZE,
    HEADER_SIZE,
    LENGTH_HEADER_SIZE,
    LOCATION_TABLE_SIZE,
    SECTOR_SIZE,
)


PathLike = Union[str, Path]


def local_chunk_index(local_cx: int, local_cz: int) -> int:
    """Map local chunk coords (0..31) to location-table index."""
    if not (0 <= local_cx < CHUNKS_PER_SIDE and 0 <= local_cz < CHUNKS_PER_SIDE):
        raise ChunkMissing(
            f"Local chunk ({local_cx}, {local_cz}) out of region bounds"
        )
    return local_cx + local_cz * CHUNKS_PER_SIDE


def world_to_local(chunk_x: int, chunk_z: int) -> Tuple[int, int, int, int]:
    """Return (region_x, region_z, local_cx, local_cz) for world chunk coords."""
    region_x, local_cx = divmod(chunk_x, CHUNKS_PER_SIDE)
    region_z, local_cz = divmod(chunk_z, CHUNKS_PER_SIDE)
    return region_x, region_z, local_cx, local_cz


class RegionFile:
    """Read-only view of one ``r.X.Z.mca`` file."""

    __slots__ = ("_path", "_data", "_closed")

    def __init__(self, data: bytes, path: Optional[Path] = None) -> None:
        if len(data) < HEADER_SIZE:
            raise McaError(
                f"Region file too small ({len(data)} bytes); need >= {HEADER_SIZE}"
            )
        self._data = data
        self._path = path
        self._closed = False

    @classmethod
    def open(cls, path: PathLike) -> "RegionFile":
        """Read entire file into memory (Phase 1). mmap can come later."""
        p = Path(path)
        try:
            data = p.read_bytes()
        except OSError as exc:
            raise McaError(f"Cannot read region file {p}: {exc}") from exc
        return cls(data=data, path=p)

    @classmethod
    def from_bytes(cls, data: bytes, path: Optional[Path] = None) -> "RegionFile":
        return cls(data=data, path=path)

    @classmethod
    def from_file(cls, file: BinaryIO, path: Optional[Path] = None) -> "RegionFile":
        return cls(data=file.read(), path=path)

    def close(self) -> None:
        self._closed = True
        self._data = b""

    def __enter__(self) -> "RegionFile":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise McaError("RegionFile is closed")

    @property
    def path(self) -> Optional[Path]:
        return self._path

    @property
    def size(self) -> int:
        self._ensure_open()
        return len(self._data)

    def chunk_location(self, local_cx: int, local_cz: int) -> Tuple[int, int]:
        """Return (sector_offset, sector_count). (0, 0) means missing."""
        self._ensure_open()
        index = local_chunk_index(local_cx, local_cz)
        b_off = index * 4
        off = int.from_bytes(self._data[b_off : b_off + 3], "big")
        sectors = self._data[b_off + 3]
        return off, sectors

    def chunk_timestamp(self, local_cx: int, local_cz: int) -> int:
        self._ensure_open()
        index = local_chunk_index(local_cx, local_cz)
        b_off = LOCATION_TABLE_SIZE + index * 4
        return int.from_bytes(self._data[b_off : b_off + 4], "big")

    def has_chunk(self, local_cx: int, local_cz: int) -> bool:
        off, sectors = self.chunk_location(local_cx, local_cz)
        return not (off == 0 and sectors == 0)

    def iter_present_chunks(self) -> Iterable[Tuple[int, int]]:
        self._ensure_open()
        for index in range(CHUNKS_PER_REGION):
            b_off = index * 4
            off = int.from_bytes(self._data[b_off : b_off + 3], "big")
            sectors = self._data[b_off + 3]
            if off == 0 and sectors == 0:
                continue
            local_cx = index % CHUNKS_PER_SIDE
            local_cz = index // CHUNKS_PER_SIDE
            yield local_cx, local_cz

    def count_chunks(self) -> int:
        return sum(1 for _ in self.iter_present_chunks())

    def read_chunk_raw(self, local_cx: int, local_cz: int) -> bytes:
        """Decompress and return raw NBT bytes for a local chunk."""
        self._ensure_open()
        off, sectors = self.chunk_location(local_cx, local_cz)
        if off == 0 and sectors == 0:
            raise ChunkMissing(f"Chunk ({local_cx}, {local_cz}) not present")
        if off == 0 or sectors == 0:
            raise CorruptChunk(
                f"Chunk ({local_cx}, {local_cz}) has invalid location "
                f"(offset={off}, sectors={sectors})"
            )

        byte_off = off * SECTOR_SIZE
        allocated_end = byte_off + sectors * SECTOR_SIZE
        if allocated_end > len(self._data):
            raise CorruptChunk(
                f"Chunk ({local_cx}, {local_cz}) allocation exceeds file "
                f"(need {allocated_end}, have {len(self._data)})"
            )
        if byte_off + LENGTH_HEADER_SIZE > len(self._data):
            raise CorruptChunk(
                f"Chunk ({local_cx}, {local_cz}) offset past EOF "
                f"(offset={byte_off}, file={len(self._data)})"
            )

        length = int.from_bytes(
            self._data[byte_off : byte_off + LENGTH_HEADER_SIZE], "big"
        )
        if length < COMPRESSION_HEADER_SIZE:
            raise CorruptChunk(
                f"Chunk ({local_cx}, {local_cz}) invalid length {length}"
            )

        comp_off = byte_off + LENGTH_HEADER_SIZE
        end = comp_off + length
        if end > allocated_end:
            raise CorruptChunk(
                f"Chunk ({local_cx}, {local_cz}) payload exceeds allocated sectors "
                f"(need {end}, allocated through {allocated_end})"
            )
        if end > len(self._data):
            raise CorruptChunk(
                f"Chunk ({local_cx}, {local_cz}) payload truncated "
                f"(need {end}, have {len(self._data)})"
            )

        compression = self._data[comp_off]
        payload = self._data[comp_off + COMPRESSION_HEADER_SIZE : end]
        return decompress_chunk(compression, payload)

    def read_chunk(self, local_cx: int, local_cz: int) -> nbtlib.Compound:
        """Load chunk NBT as an nbtlib compound root."""
        raw = self.read_chunk_raw(local_cx, local_cz)
        try:
            # nbtlib 2.x: File.parse(fileobj) for in-memory bytes
            nbt_file = nbtlib.File.parse(io.BytesIO(raw))
        except Exception as exc:
            raise CorruptChunk(
                f"Chunk ({local_cx}, {local_cz}) NBT parse failed: {exc}"
            ) from exc
        return nbt_file

    def read_chunk_or_none(
        self, local_cx: int, local_cz: int
    ) -> Optional[nbtlib.Compound]:
        try:
            return self.read_chunk(local_cx, local_cz)
        except ChunkMissing:
            return None
