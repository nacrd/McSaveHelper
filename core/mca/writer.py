"""Writable MCA region: load, mutate chunk NBT, atomic save.

Safety model:
- Edits happen in memory
- save() optionally copies ``.mca.bak`` once
- Writes to ``.mca.tmp`` then os.replace onto the target
"""
from __future__ import annotations

import io
import os
import shutil
import struct
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple, Union

import nbtlib

from core.mca.chunk_codec import compress_chunk
from core.mca.errors import ChunkMissing, McaError
from core.mca.format import (
    CHUNKS_PER_SIDE,
    COMPRESSION_ZLIB,
    HEADER_SIZE,
    LOCATION_TABLE_SIZE,
    SECTOR_SIZE,
)
from core.mca.region_file import RegionFile, local_chunk_index

PathLike = Union[str, Path]


def nbt_to_bytes(nbt: Any) -> bytes:
    """Serialize an nbtlib compound/File to uncompressed NBT bytes."""
    if isinstance(nbt, nbtlib.File):
        root = nbt
    else:
        # Wrap plain Compound as File for write()
        root = nbtlib.File(dict(nbt) if hasattr(nbt, "items") else nbt)
    buf = io.BytesIO()
    root.write(buf)
    return buf.getvalue()


def bytes_to_nbt(raw: bytes) -> nbtlib.File:
    return nbtlib.File.parse(io.BytesIO(raw))


class WritableRegion:
    """In-memory editable region file."""

    __slots__ = ("path", "_chunks", "_deleted", "_loaded")

    def __init__(self, path: Optional[PathLike] = None) -> None:
        self.path: Optional[Path] = Path(path) if path is not None else None
        # (local_cx, local_cz) -> nbtlib.File (mutable)
        self._chunks: Dict[Tuple[int, int], nbtlib.File] = {}
        self._deleted: set[Tuple[int, int]] = set()
        self._loaded = False

    # ------------------------------------------------------------------ factory
    @classmethod
    def open(cls, path: PathLike) -> "WritableRegion":
        wr = cls(path)
        wr.load()
        return wr

    @classmethod
    def empty(cls, path: Optional[PathLike] = None) -> "WritableRegion":
        wr = cls(path)
        wr._loaded = True
        return wr

    def load(self) -> None:
        if self.path is None:
            raise McaError("WritableRegion has no path to load")
        if not self.path.is_file():
            # Treat missing file as empty region (will create on save).
            self._chunks.clear()
            self._deleted.clear()
            self._loaded = True
            return

        self._chunks.clear()
        self._deleted.clear()
        with RegionFile.open(self.path) as rf:
            for cx, cz in rf.iter_present_chunks():
                try:
                    nbt = rf.read_chunk(cx, cz)
                    # Ensure File type for write-back
                    if not isinstance(nbt, nbtlib.File):
                        nbt = nbtlib.File(dict(nbt))
                    self._chunks[(cx, cz)] = nbt
                except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
                    raise McaError(
                        f"Cannot safely load chunk ({cx}, {cz}) from {self.path}: {exc}"
                    ) from exc
                except Exception as exc:
                    raise McaError(
                        f"Cannot safely load chunk ({cx}, {cz}) from {self.path}: {exc}"
                    ) from exc
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            if self.path is not None and self.path.is_file():
                self.load()
            else:
                self._loaded = True

    # ------------------------------------------------------------------ query
    def has_chunk(self, local_cx: int, local_cz: int) -> bool:
        self._ensure_loaded()
        key = (local_cx, local_cz)
        if key in self._deleted:
            return False
        return key in self._chunks

    def get_chunk(self, local_cx: int, local_cz: int) -> Optional[nbtlib.File]:
        """Return mutable chunk NBT, or None if missing."""
        self._ensure_loaded()
        key = (local_cx, local_cz)
        if key in self._deleted:
            return None
        return self._chunks.get(key)

    def set_chunk(self, local_cx: int, local_cz: int, nbt: Any) -> None:
        self._ensure_loaded()
        if not (0 <= local_cx < CHUNKS_PER_SIDE and 0 <= local_cz < CHUNKS_PER_SIDE):
            raise ChunkMissing(f"Local chunk ({local_cx}, {local_cz}) out of bounds")
        key = (local_cx, local_cz)
        self._deleted.discard(key)
        if not isinstance(nbt, nbtlib.File):
            nbt = nbtlib.File(dict(nbt) if hasattr(nbt, "items") else nbt)
        self._chunks[key] = nbt

    def delete_chunk(self, local_cx: int, local_cz: int) -> bool:
        self._ensure_loaded()
        key = (local_cx, local_cz)
        existed = key in self._chunks and key not in self._deleted
        self._chunks.pop(key, None)
        self._deleted.add(key)
        return existed

    def iter_chunks(self) -> Iterable[Tuple[int, int, nbtlib.File]]:
        self._ensure_loaded()
        for key, nbt in list(self._chunks.items()):
            if key in self._deleted:
                continue
            yield key[0], key[1], nbt

    def count_chunks(self) -> int:
        self._ensure_loaded()
        return sum(1 for k in self._chunks if k not in self._deleted)

    # ------------------------------------------------------------------ save
    def save(
        self,
        path: Optional[PathLike] = None,
        *,
        backup: bool = True,
    ) -> None:
        """Write region to disk atomically.

        Parameters
        ----------
        path:
            Destination; defaults to the path used at open().
        backup:
            If True and the destination already exists, copy to ``.mca.bak``
            once (does not overwrite an existing bak).
        """
        self._ensure_loaded()
        dest = Path(path) if path is not None else self.path
        if dest is None:
            raise McaError("No destination path for WritableRegion.save()")
        dest.parent.mkdir(parents=True, exist_ok=True)
        _create_backup(dest, backup)
        _replace_file_atomically(dest, self._serialize(), "Failed to write region")
        self.path = dest
        self._deleted.clear()

    def _serialize(self) -> bytes:
        """Build a complete MCA byte blob from in-memory chunks."""
        # location table + timestamps
        locations = bytearray(LOCATION_TABLE_SIZE)
        timestamps = bytearray(LOCATION_TABLE_SIZE)
        now = int(time.time()) & 0xFFFFFFFF

        # Data starts after 2-sector header
        body = bytearray()
        next_sector = 2  # header occupies sectors 0 and 1

        # Deterministic order
        keys = sorted(k for k in self._chunks.keys() if k not in self._deleted)
        for cx, cz in keys:
            nbt = self._chunks[(cx, cz)]
            try:
                raw = nbt_to_bytes(nbt)
                compression, payload = compress_chunk(raw, COMPRESSION_ZLIB)
            except (OSError, ValueError, TypeError, RuntimeError) as exc:
                raise McaError(
                    f"Failed to encode chunk ({cx}, {cz}): {exc}"
                ) from exc
            except Exception as exc:
                raise McaError(
                    f"Failed to encode chunk ({cx}, {cz}): {exc}"
                ) from exc

            length = 1 + len(payload)  # includes compression byte
            record = struct.pack(">I", length) + bytes([compression]) + payload
            sectors = (len(record) + SECTOR_SIZE - 1) // SECTOR_SIZE
            if sectors <= 0 or sectors > 255:
                raise McaError(
                    f"Chunk ({cx}, {cz}) needs {sectors} sectors (max 255)"
                )
            pad = sectors * SECTOR_SIZE - len(record)
            body.extend(record)
            if pad:
                body.extend(b"\x00" * pad)

            index = local_chunk_index(cx, cz)
            b_off = index * 4
            locations[b_off:b_off + 3] = int(next_sector).to_bytes(3, "big")
            locations[b_off + 3] = sectors
            timestamps[b_off:b_off + 4] = struct.pack(">I", now)
            next_sector += sectors

        return bytes(locations) + bytes(timestamps) + bytes(body)


def _create_backup(destination: Path, backup: bool) -> None:
    if not backup or not destination.is_file():
        return
    backup_path = destination.with_suffix(destination.suffix + ".bak")
    if backup_path.exists():
        return
    try:
        shutil.copy2(destination, backup_path)
    except OSError as exc:
        raise McaError(f"Backup failed for {destination}: {exc}") from exc


def _replace_file_atomically(destination: Path, data: bytes, error_prefix: str) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, destination)
    except OSError as exc:
        _remove_temporary_file(temporary)
        raise McaError(f"{error_prefix} {destination}: {exc}") from exc


def _remove_temporary_file(temporary: Path) -> None:
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass


def delete_chunk_entries(
    region_path: PathLike,
    coords: Iterable[Tuple[int, int]],
    *,
    backup: bool = True,
) -> int:
    """Clear location-table entries for coords (marks chunks empty).

    Prefer this for bulk 'reset chunk' when full rewrite is unnecessary.
    Returns number of entries cleared.
    """
    path = Path(region_path)
    if not path.is_file():
        return 0
    _create_backup(path, backup)

    cleared = 0
    with open(path, "r+b") as f:
        data = f.read(HEADER_SIZE)
        if len(data) < HEADER_SIZE:
            return 0
        loc = bytearray(data[:LOCATION_TABLE_SIZE])
        ts = bytearray(data[LOCATION_TABLE_SIZE:HEADER_SIZE])
        for cx, cz in coords:
            if not (0 <= cx < 32 and 0 <= cz < 32):
                continue
            index = local_chunk_index(cx, cz)
            b = index * 4
            if loc[b:b + 4] != b"\x00\x00\x00\x00":
                loc[b:b + 4] = b"\x00\x00\x00\x00"
                ts[b:b + 4] = b"\x00\x00\x00\x00"
                cleared += 1
        f.seek(0)
        f.write(loc)
        f.write(ts)
    return cleared


def write_chunk_record(
    destination_path: PathLike,
    destination_coords: Tuple[int, int],
    record: bytes,
    *,
    backup: bool = True,
) -> None:
    """Write a complete compressed chunk record using atomic replacement."""
    destination = Path(destination_path)
    destination_cx, destination_cz = destination_coords
    destination_index = local_chunk_index(destination_cx, destination_cz)
    used_length = _validated_record_length(record)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = _load_region_for_chunk_write(destination, backup)
    destination_sector, copied_sectors = _append_chunk_record(data, record, used_length)
    _update_chunk_header(data, destination_index, destination_sector, copied_sectors)
    _replace_file_atomically(destination, bytes(data), "Failed to write chunk into")


def _validated_record_length(record: bytes) -> int:
    if len(record) < 5:
        raise McaError("Chunk record is missing its length or compression header")
    payload_length = int.from_bytes(record[:4], "big")
    used_length = 4 + payload_length
    if payload_length < 1 or used_length > len(record):
        raise McaError(f"Invalid chunk record length: {payload_length}")
    return used_length


def _load_region_for_chunk_write(destination: Path, backup: bool) -> bytearray:
    if not destination.exists():
        return bytearray(HEADER_SIZE)
    data = bytearray(destination.read_bytes())
    if len(data) < HEADER_SIZE:
        raise McaError(f"Region file too small: {destination}")
    _create_backup(destination, backup)
    return data


def _append_chunk_record(
    data: bytearray,
    record: bytes,
    used_length: int,
) -> Tuple[int, int]:
    remainder = len(data) % SECTOR_SIZE
    if remainder:
        data.extend(b"\x00" * (SECTOR_SIZE - remainder))
    destination_sector = len(data) // SECTOR_SIZE
    copied_sectors = (used_length + SECTOR_SIZE - 1) // SECTOR_SIZE
    if copied_sectors > 255:
        raise McaError(f"Chunk record needs {copied_sectors} sectors (max 255)")
    data.extend(record[:used_length])
    data.extend(b"\x00" * (copied_sectors * SECTOR_SIZE - used_length))
    return destination_sector, copied_sectors


def _update_chunk_header(
    data: bytearray,
    destination_index: int,
    destination_sector: int,
    copied_sectors: int,
) -> None:
    header_offset = destination_index * 4
    data[header_offset:header_offset + 3] = destination_sector.to_bytes(3, "big")
    data[header_offset + 3] = copied_sectors
    timestamp_offset = LOCATION_TABLE_SIZE + header_offset
    data[timestamp_offset:timestamp_offset + 4] = struct.pack(
        ">I", int(time.time()) & 0xFFFFFFFF
    )


def copy_chunk_record(
    source_path: PathLike,
    source_coords: Tuple[int, int],
    destination_path: PathLike,
    destination_coords: Tuple[int, int],
    *,
    backup: bool = True,
) -> None:
    """Copy one compressed chunk record between region files atomically."""
    source = Path(source_path)
    source_cx, source_cz = source_coords
    local_chunk_index(source_cx, source_cz)

    with RegionFile.open(source) as region:
        source_sector, source_sector_count = region.chunk_location(
            source_cx, source_cz
        )
    if source_sector == 0 or source_sector_count == 0:
        raise ChunkMissing(
            f"Chunk ({source_cx}, {source_cz}) not present in {source}"
        )

    source_bytes = source.read_bytes()
    record_start = source_sector * SECTOR_SIZE
    record_end = record_start + source_sector_count * SECTOR_SIZE
    if record_end > len(source_bytes):
        raise McaError(
            f"Chunk ({source_cx}, {source_cz}) record exceeds {source}"
        )
    write_chunk_record(
        destination_path,
        destination_coords,
        source_bytes[record_start:record_end],
        backup=backup,
    )
