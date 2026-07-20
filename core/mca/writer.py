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
    """将 nbtlib compound/File 序列化为未压缩 NBT 字节。

    Args:
        nbt: nbtlib.File 或可转为 File 的 compound。

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
    """将未压缩 NBT 字节解析为 nbtlib.File。

    Args:
        raw: 未压缩 NBT。

    Returns:
        nbtlib.File: 解析结果。
    """
    return nbtlib.File.parse(io.BytesIO(raw))


class WritableRegion:
    """内存中可编辑的区域文件。

    删除以 ``_deleted`` 集合记录，直到 save 才真正省略槽位。
    """

    __slots__ = ("path", "_chunks", "_deleted", "_loaded")

    def __init__(self, path: Optional[PathLike] = None) -> None:
        """创建空或绑定路径的可写区域（未自动 load）。

        Args:
            path: 可选磁盘路径。
        """
        self.path: Optional[Path] = Path(path) if path is not None else None
        # (local_cx, local_cz) -> nbtlib.File (mutable)
        self._chunks: Dict[Tuple[int, int], nbtlib.File] = {}
        self._deleted: set[Tuple[int, int]] = set()
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
        return key in self._chunks

    def get_chunk(self, local_cx: int, local_cz: int) -> Optional[nbtlib.File]:
        """返回可变区块 NBT，缺失则为 None。

        Args:
            local_cx: 局部 X。
            local_cz: 局部 Z。

        Returns:
            Optional[nbtlib.File]: 可变 File，或 None。
        """
        self._ensure_loaded()
        key = (local_cx, local_cz)
        if key in self._deleted:
            return None
        return self._chunks.get(key)

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
        if not isinstance(nbt, nbtlib.File):
            nbt = nbtlib.File(dict(nbt) if hasattr(nbt, "items") else nbt)
        self._chunks[key] = nbt

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
        existed = key in self._chunks and key not in self._deleted
        self._chunks.pop(key, None)
        self._deleted.add(key)
        return existed

    def iter_chunks(self) -> Iterable[Tuple[int, int, nbtlib.File]]:
        """遍历未删除的 ``(cx, cz, nbt)``。"""
        self._ensure_loaded()
        for key, nbt in list(self._chunks.items()):
            if key in self._deleted:
                continue
            yield key[0], key[1], nbt

    def count_chunks(self) -> int:
        """未删除区块数量。"""
        self._ensure_loaded()
        return sum(1 for k in self._chunks if k not in self._deleted)

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
