"""可写 MCA 区域：内存中加载/修改区块 NBT，再原子落盘。

安全模型：
- 编辑在内存中进行
- save() 可选一次性复制 ``.mca.bak``
- 先写 ``.mca.tmp`` 再 os.replace 到目标
"""
from __future__ import annotations

import io
import os
import shutil
import struct
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple, Union

import core.nbt as nbtlib

from core.mca.chunk_codec import compress_chunk, decompress_chunk
from core.mca.errors import ChunkMissing, McaError
from core.mca.format import (
    CHUNKS_PER_SIDE,
    COMPRESSION_HEADER_SIZE,
    COMPRESSION_TYPE_MASK,
    COMPRESSION_ZLIB,
    EXTERNAL_CHUNK_STREAM_FLAG,
    HEADER_SIZE,
    LENGTH_HEADER_SIZE,
    LOCATION_TABLE_SIZE,
    SECTOR_SIZE,
)
from core.mca.region_file import ChunkRecord, RegionFile, local_chunk_index

PathLike = Union[str, Path]
ChunkKey = Tuple[int, int]


def nbt_to_bytes(nbt: Any) -> bytes:
    """将 NBT compound/File 序列化为未压缩 NBT 字节。

    Args:
        nbt: File 或可转为 File 的 compound。

    Returns:
        bytes: 未压缩 NBT 二进制。
    """
    if isinstance(nbt, nbtlib.File):
        root = nbt
    else:
        # Wrap plain Compound as File for write()
        root = nbtlib.File(dict(nbt) if hasattr(nbt, "items") else nbt)
    buf = io.BytesIO()
    root.write(buf)
    return buf.getvalue()


def bytes_to_nbt(raw: bytes) -> nbtlib.File:
    """将未压缩 NBT 字节解析为 File。

    Args:
        raw: 未压缩 NBT。

    Returns:
        File: 解析结果。
    """
    return nbtlib.File.parse(io.BytesIO(raw))


class WritableRegion:
    """内存中可编辑的区域文件。

    删除以 ``_deleted`` 集合记录，直到 save 才真正省略槽位。
    """

    __slots__ = (
        "path",
        "_chunks",
        "_deleted",
        "_dirty",
        "_loaded",
        "_source_records",
    )

    def __init__(self, path: Optional[PathLike] = None) -> None:
        """创建空或绑定路径的可写区域（未自动 load）。

        Args:
            path: 可选磁盘路径。
        """
        self.path: Optional[Path] = Path(path) if path is not None else None
        # (local_cx, local_cz) -> File (mutable)
        self._chunks: Dict[ChunkKey, nbtlib.File] = {}
        self._source_records: Dict[ChunkKey, ChunkRecord] = {}
        self._deleted: set[ChunkKey] = set()
        self._dirty: set[ChunkKey] = set()
        self._loaded = False

    # ------------------------------------------------------------------ factory
    @classmethod
    def open(cls, path: PathLike) -> "WritableRegion":
        """打开路径并立即 load 全部可读区块。

        Args:
            path: .mca 路径。

        Returns:
            WritableRegion: 已加载实例。
        """
        wr = cls(path)
        wr.load()
        return wr

    @classmethod
    def open_for_patch(cls, path: PathLike) -> "WritableRegion":
        """Open a region while deferring NBT decoding until iteration.

        This mode is intended for sparse patch operations. Call
        :meth:`discard_chunk_changes` after inspecting an unchanged chunk so
        its parsed tree can be released and its original compressed record is
        copied during save.

        Args:
            path: Source ``.mca`` path.

        Returns:
            WritableRegion: Lazily decoded writable region.
        """
        region = cls(path)
        region._load(parse_chunks=False)
        return region

    @classmethod
    def empty(cls, path: Optional[PathLike] = None) -> "WritableRegion":
        """创建空区域（不读盘），可选绑定保存路径。

        Args:
            path: 可选默认保存路径。

        Returns:
            WritableRegion: 已标记 loaded 的空实例。
        """
        wr = cls(path)
        wr._loaded = True
        return wr

    def load(self) -> None:
        """从 path 加载全部存在区块；缺失文件视为空区域。

        Raises:
            McaError: 无 path，或某区块无法安全加载。
        """
        self._load(parse_chunks=True)

    def _load(self, *, parse_chunks: bool) -> None:
        if self.path is None:
            raise McaError("WritableRegion has no path to load")
        self._chunks.clear()
        self._source_records.clear()
        self._deleted.clear()
        self._dirty.clear()
        if not self.path.is_file():
            self._loaded = True
            return

        with RegionFile.open(self.path) as rf:
            for cx, cz in rf.iter_present_chunks():
                try:
                    key = (cx, cz)
                    self._source_records[key] = rf.read_chunk_record(cx, cz)
                    if parse_chunks:
                        self._chunks[key] = _as_nbt_file(rf.read_chunk(cx, cz))
                except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
                    raise McaError(
                        f"Cannot safely load chunk ({cx}, {cz}) from {self.path}: {exc}"
                    ) from exc
                except Exception as exc:
                    raise McaError(
                        f"Cannot safely load chunk ({cx}, {cz}) from {self.path}: {exc}"
                    ) from exc
        if parse_chunks:
            self._dirty.update(self._chunks)
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            if self.path is not None and self.path.is_file():
                self.load()
            else:
                self._loaded = True

    # ------------------------------------------------------------------ query
    def has_chunk(self, local_cx: int, local_cz: int) -> bool:
        """是否存在未删除的区块。

        Args:
            local_cx: 局部 X。
            local_cz: 局部 Z。

        Returns:
            bool: 在内存表中且未标记删除。
        """
        self._ensure_loaded()
        key = (local_cx, local_cz)
        if key in self._deleted:
            return False
        return key in self._chunks or key in self._source_records

    def get_chunk(self, local_cx: int, local_cz: int) -> Optional[nbtlib.File]:
        """返回可变区块 NBT，缺失则为 None。

        Args:
            local_cx: 局部 X。
            local_cz: 局部 Z。

        Returns:
            Optional[File]: 可变 File，或 None。
        """
        self._ensure_loaded()
        key = (local_cx, local_cz)
        if key in self._deleted:
            return None
        chunk = self._chunks.get(key)
        if chunk is None:
            source_record = self._source_records.get(key)
            if source_record is None:
                return None
            chunk = self._decode_source_chunk(key, source_record)
            self._chunks[key] = chunk
        self._dirty.add(key)
        return chunk

    def _decode_source_chunk(
        self,
        key: ChunkKey,
        source_record: ChunkRecord,
    ) -> nbtlib.File:
        marker = source_record.data[LENGTH_HEADER_SIZE]
        try:
            if marker & EXTERNAL_CHUNK_STREAM_FLAG:
                if self.path is None:
                    raise McaError("External chunk has no source region path")
                with RegionFile.open(self.path) as region:
                    return _as_nbt_file(region.read_chunk(*key))
            compression = marker & COMPRESSION_TYPE_MASK
            payload = source_record.data[
                LENGTH_HEADER_SIZE + COMPRESSION_HEADER_SIZE:
            ]
            return bytes_to_nbt(decompress_chunk(compression, payload))
        except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
            raise McaError(
                f"Cannot safely load chunk {key} from {self.path}: {exc}"
            ) from exc
        except Exception as exc:
            raise McaError(
                f"Cannot safely load chunk {key} from {self.path}: {exc}"
            ) from exc

    def set_chunk(self, local_cx: int, local_cz: int, nbt: Any) -> None:
        """写入/覆盖局部区块，并取消删除标记。

        Args:
            local_cx: 局部 X（0–31）。
            local_cz: 局部 Z（0–31）。
            nbt: compound 或 File。

        Raises:
            ChunkMissing: 坐标越界。
        """
        self._ensure_loaded()
        if not (0 <= local_cx < CHUNKS_PER_SIDE and 0 <= local_cz < CHUNKS_PER_SIDE):
            raise ChunkMissing(f"Local chunk ({local_cx}, {local_cz}) out of bounds")
        key = (local_cx, local_cz)
        self._deleted.discard(key)
        self._chunks[key] = _as_nbt_file(nbt)
        self._dirty.add(key)

    def mark_chunk_dirty(self, local_cx: int, local_cz: int) -> None:
        """Retain a decoded chunk for re-encoding during save.

        Args:
            local_cx: Region-local X coordinate.
            local_cz: Region-local Z coordinate.

        Raises:
            ChunkMissing: The chunk has not been decoded or does not exist.
        """
        key = (local_cx, local_cz)
        if key not in self._chunks or key in self._deleted:
            raise ChunkMissing(f"Chunk ({local_cx}, {local_cz}) is not loaded")
        self._dirty.add(key)

    def discard_chunk_changes(self, local_cx: int, local_cz: int) -> None:
        """Release a decoded tree and restore its original compressed record.

        Args:
            local_cx: Region-local X coordinate.
            local_cz: Region-local Z coordinate.
        """
        key = (local_cx, local_cz)
        self._chunks.pop(key, None)
        self._dirty.discard(key)
        self._deleted.discard(key)

    def delete_chunk(self, local_cx: int, local_cz: int) -> bool:
        """标记删除局部区块（save 前不落盘）。

        Args:
            local_cx: 局部 X。
            local_cz: 局部 Z。

        Returns:
            bool: 删除前是否曾存在有效数据。
        """
        self._ensure_loaded()
        key = (local_cx, local_cz)
        existed = (
            key not in self._deleted
            and (key in self._chunks or key in self._source_records)
        )
        self._chunks.pop(key, None)
        self._dirty.discard(key)
        self._deleted.add(key)
        return existed

    def iter_chunks(self) -> Iterable[Tuple[int, int, nbtlib.File]]:
        """遍历未删除的 ``(cx, cz, nbt)``。"""
        self._ensure_loaded()
        keys = sorted(set(self._source_records) | set(self._chunks))
        for local_cx, local_cz in keys:
            chunk = self.get_chunk(local_cx, local_cz)
            if chunk is not None:
                yield local_cx, local_cz, chunk

    def count_chunks(self) -> int:
        """未删除区块数量。"""
        self._ensure_loaded()
        keys = set(self._source_records) | set(self._chunks)
        return sum(1 for key in keys if key not in self._deleted)

    # ------------------------------------------------------------------ save
    def save(
        self,
        path: Optional[PathLike] = None,
        *,
        backup: bool = True,
    ) -> None:
        """原子写回磁盘。

        Args:
            path: 目标路径；默认 open 时的 path。
            backup: 目标已存在时一次性复制 ``.mca.bak``（不覆盖已有 bak）。

        Raises:
            McaError: 无目标路径或写入失败。
        """
        self._ensure_loaded()
        dest = Path(path) if path is not None else self.path
        if dest is None:
            raise McaError("No destination path for WritableRegion.save()")
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._materialize_external_chunks_for_new_path(dest)
        _create_backup(dest, backup)
        _replace_file_atomically(dest, self._serialize(), "Failed to write region")
        self.path = dest
        self._load(parse_chunks=False)

    def _materialize_external_chunks_for_new_path(self, dest: Path) -> None:
        if self.path is None or dest.absolute() == self.path.absolute():
            return
        for key, source_record in self._source_records.items():
            marker = source_record.data[LENGTH_HEADER_SIZE]
            if marker & EXTERNAL_CHUNK_STREAM_FLAG and key not in self._deleted:
                self.get_chunk(*key)

    def _serialize(self) -> bytes:
        """Build a complete MCA byte blob from in-memory chunks."""
        # location table + timestamps
        locations = bytearray(LOCATION_TABLE_SIZE)
        timestamps = bytearray(LOCATION_TABLE_SIZE)
        now = int(time.time()) & 0xFFFFFFFF

        # Data starts after 2-sector header
        body = bytearray()
        next_sector = 2  # header occupies sectors 0 and 1

        keys = sorted(
            key
            for key in set(self._source_records) | set(self._chunks)
            if key not in self._deleted
        )
        for cx, cz in keys:
            key = (cx, cz)
            source_record = self._source_records.get(key)
            if key in self._dirty or source_record is None:
                record = self._encode_chunk(key)
                timestamp = now
            else:
                record = source_record.data
                timestamp = source_record.timestamp
            used_length = _validated_record_length(record)
            sectors = (used_length + SECTOR_SIZE - 1) // SECTOR_SIZE
            if sectors <= 0 or sectors > 255:
                raise McaError(
                    f"Chunk ({cx}, {cz}) needs {sectors} sectors (max 255)"
                )
            pad = sectors * SECTOR_SIZE - used_length
            body.extend(record[:used_length])
            if pad:
                body.extend(b"\x00" * pad)

            index = local_chunk_index(cx, cz)
            b_off = index * 4
            locations[b_off:b_off + 3] = int(next_sector).to_bytes(3, "big")
            locations[b_off + 3] = sectors
            timestamps[b_off:b_off + 4] = struct.pack(">I", timestamp)
            next_sector += sectors

        return bytes(locations) + bytes(timestamps) + bytes(body)

    def _encode_chunk(self, key: ChunkKey) -> bytes:
        try:
            raw = nbt_to_bytes(self._chunks[key])
            compression, payload = compress_chunk(raw, COMPRESSION_ZLIB)
        except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
            raise McaError(f"Failed to encode chunk {key}: {exc}") from exc
        except Exception as exc:
            raise McaError(f"Failed to encode chunk {key}: {exc}") from exc
        length = COMPRESSION_HEADER_SIZE + len(payload)
        return struct.pack(">I", length) + bytes([compression]) + payload


def _as_nbt_file(value: Any) -> nbtlib.File:
    if isinstance(value, nbtlib.File):
        return value
    return nbtlib.File(dict(value) if hasattr(value, "items") else value)


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
    """清除位置表项以标记区块为空（不重写整文件体）。

    批量「重置区块」且无需完整 rewrite 时优先使用。

    Args:
        region_path: 区域文件路径。
        coords: 局部 ``(cx, cz)``。
        backup: 是否备份。

    Returns:
        int: 实际清零的表项数。
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
    """将完整压缩区块记录以原子替换方式写入目标区域。

    Args:
        destination_path: 目标 .mca。
        destination_coords: 局部 ``(cx, cz)``。
        record: 含 length+compression+payload 的扇区记录。
        backup: 是否备份。

    Raises:
        McaError: 记录非法或写入失败。
    """
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
    """在区域文件间原子复制一条压缩区块记录（不重解析 NBT）。

    Args:
        source_path: 源 .mca。
        source_coords: 源局部坐标。
        destination_path: 目标 .mca。
        destination_coords: 目标局部坐标。
        backup: 是否备份目标。

    Raises:
        ChunkMissing: 源槽为空。
        McaError: 记录越界或写入失败。
    """
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
