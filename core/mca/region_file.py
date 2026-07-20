"""Read-only Anvil region file (.mca) access.

Phase 1: open, list present chunks, load chunk NBT as nbtlib compounds.
Does not depend on anvil-parser.
"""
from __future__ import annotations

import io
import hashlib
import mmap
import re
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, Iterable, Optional, Tuple, Union

import nbtlib

from core.mca.chunk_codec import MAX_COMPRESSED_CHUNK_BYTES, decompress_chunk
from core.mca.errors import ChunkMissing, CorruptChunk, McaError
from core.mca.format import (
    CHUNKS_PER_REGION,
    CHUNKS_PER_SIDE,
    COMPRESSION_TYPE_MASK,
    COMPRESSION_HEADER_SIZE,
    EXTERNAL_CHUNK_STREAM_FLAG,
    HEADER_SIZE,
    LENGTH_HEADER_SIZE,
    LOCATION_TABLE_SIZE,
    SECTOR_SIZE,
)


PathLike = Union[str, Path]
RegionData = Union[bytes, mmap.mmap]
LocationTable = Tuple[Tuple[int, int], ...]
_REGION_NAME_RE = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.mca$")


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

    __slots__ = ("_path", "_data", "_closed", "_locations")

    def __init__(self, data: RegionData, path: Optional[Path] = None) -> None:
        if len(data) < HEADER_SIZE:
            raise McaError(
                f"Region file too small ({len(data)} bytes); need >= {HEADER_SIZE}"
            )
        self._data = data
        self._path = path
        self._closed = False
        self._locations: Optional[LocationTable] = None

    @classmethod
    def open(cls, path: PathLike) -> "RegionFile":
        """Open a region through a read-only memory map without copying it."""
        p = Path(path)
        try:
            size = p.stat().st_size
            if size < HEADER_SIZE:
                raise McaError(
                    f"Region file too small ({size} bytes); need >= {HEADER_SIZE}"
                )
            with p.open("rb") as region_file:
                data = mmap.mmap(
                    region_file.fileno(),
                    length=0,
                    access=mmap.ACCESS_READ,
                )
        except McaError:
            raise
        except (OSError, ValueError) as exc:
            raise McaError(f"Cannot read region file {p}: {exc}") from exc
        return cls(data=data, path=p)

    @classmethod
    def from_bytes(cls, data: bytes, path: Optional[Path] = None) -> "RegionFile":
        return cls(data=data, path=path)

    @classmethod
    def from_file(cls, file: BinaryIO, path: Optional[Path] = None) -> "RegionFile":
        return cls(data=file.read(), path=path)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        data = self._data
        self._data = b""
        if isinstance(data, mmap.mmap):
            data.close()

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
        locations = self._locations
        if locations is not None:
            return locations[index]
        byte_offset = index * 4
        return (
            int.from_bytes(self._data[byte_offset:byte_offset + 3], "big"),
            self._data[byte_offset + 3],
        )

    def chunk_timestamp(self, local_cx: int, local_cz: int) -> int:
        self._ensure_open()
        index = local_chunk_index(local_cx, local_cz)
        b_off = LOCATION_TABLE_SIZE + index * 4
        return int.from_bytes(self._data[b_off:b_off + 4], "big")

    def has_chunk(self, local_cx: int, local_cz: int) -> bool:
        off, sectors = self.chunk_location(local_cx, local_cz)
        return not (off == 0 and sectors == 0)

    def iter_present_chunks(self) -> Iterable[Tuple[int, int]]:
        self._ensure_open()
        for index, (off, sectors) in enumerate(self._location_table()):
            if off == 0 and sectors == 0:
                continue
            local_cx = index % CHUNKS_PER_SIDE
            local_cz = index // CHUNKS_PER_SIDE
            yield local_cx, local_cz

    def _location_table(self) -> LocationTable:
        locations = self._locations
        if locations is None:
            data = self._data
            locations = tuple(
                (
                    int.from_bytes(data[index * 4:index * 4 + 3], "big"),
                    data[index * 4 + 3],
                )
                for index in range(CHUNKS_PER_REGION)
            )
            self._locations = locations
        return locations

    def has_external_chunks(self) -> bool:
        """Return whether any present chunk uses an external ``.mcc`` stream."""
        self._ensure_open()
        for local_cx, local_cz in self.iter_present_chunks():
            off, sectors = self.chunk_location(local_cx, local_cz)
            if off == 0 or sectors == 0:
                continue
            marker_offset = off * SECTOR_SIZE + LENGTH_HEADER_SIZE
            if marker_offset >= len(self._data):
                continue
            if self._data[marker_offset] & EXTERNAL_CHUNK_STREAM_FLAG:
                return True
        return False

    def external_chunk_signature(
        self,
        chunks: Iterable[Tuple[int, int]],
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        """Return a compact signature for sampled external chunk streams."""
        signatures = self.external_chunk_signatures(
            chunks,
            cancel_check=cancel_check,
        )
        if not signatures:
            return ""
        values = [
            f"{local_cx},{local_cz},{signature}"
            for (local_cx, local_cz), signature in signatures.items()
        ]
        values.sort()
        return hashlib.sha1("|".join(values).encode("ascii")).hexdigest()

    def external_chunk_signatures(
        self,
        chunks: Iterable[Tuple[int, int]],
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[Tuple[int, int], str]:
        """Return file signatures keyed by external local chunk coordinate."""
        signatures: Dict[Tuple[int, int], str] = {}
        for local_cx, local_cz in chunks:
            if cancel_check is not None and cancel_check():
                break
            off, sectors = self.chunk_location(local_cx, local_cz)
            if off == 0 or sectors == 0:
                continue
            marker_offset = off * SECTOR_SIZE + LENGTH_HEADER_SIZE
            if marker_offset >= len(self._data):
                continue
            if not (self._data[marker_offset] & EXTERNAL_CHUNK_STREAM_FLAG):
                continue
            external = self.external_chunk_path(local_cx, local_cz)
            try:
                stat = external.stat()
                signatures[(local_cx, local_cz)] = (
                    f"{stat.st_mtime_ns},{stat.st_size}"
                )
            except OSError:
                signatures[(local_cx, local_cz)] = "missing"
        return signatures

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
            self._data[byte_off:byte_off + LENGTH_HEADER_SIZE], "big"
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

        compression_marker = self._data[comp_off]
        compression = compression_marker & COMPRESSION_TYPE_MASK
        if compression_marker & EXTERNAL_CHUNK_STREAM_FLAG:
            payload = self._read_external_chunk(local_cx, local_cz)
        else:
            payload = self._data[comp_off + COMPRESSION_HEADER_SIZE:end]
        return decompress_chunk(compression, payload)

    def _read_external_chunk(self, local_cx: int, local_cz: int) -> bytes:
        external_path = self.external_chunk_path(local_cx, local_cz)
        try:
            size = external_path.stat().st_size
            if size > MAX_COMPRESSED_CHUNK_BYTES:
                raise CorruptChunk(
                    f"External chunk {external_path.name} exceeds compressed "
                    f"limit ({size} > {MAX_COMPRESSED_CHUNK_BYTES})"
                )
            with external_path.open("rb") as external_file:
                payload = external_file.read(MAX_COMPRESSED_CHUNK_BYTES + 1)
            if len(payload) > MAX_COMPRESSED_CHUNK_BYTES:
                raise CorruptChunk(
                    f"External chunk {external_path.name} grew past compressed "
                    f"limit ({len(payload)} > {MAX_COMPRESSED_CHUNK_BYTES})"
                )
            return payload
        except CorruptChunk:
            raise
        except OSError as exc:
            raise CorruptChunk(
                f"Cannot read external chunk {external_path}: {exc}"
            ) from exc

    def external_chunk_path(self, local_cx: int, local_cz: int) -> Path:
        """Return the standard external ``.mcc`` path for one local chunk."""
        local_chunk_index(local_cx, local_cz)
        if self._path is None:
            raise CorruptChunk("External chunk requires a region file path")
        match = _REGION_NAME_RE.fullmatch(self._path.name)
        if match is None:
            raise CorruptChunk(
                f"Cannot derive external chunk coordinates from {self._path.name}"
            )
        region_x, region_z = int(match.group(1)), int(match.group(2))
        chunk_x = region_x * CHUNKS_PER_SIDE + local_cx
        chunk_z = region_z * CHUNKS_PER_SIDE + local_cz
        return self._path.parent / f"c.{chunk_x}.{chunk_z}.mcc"

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
