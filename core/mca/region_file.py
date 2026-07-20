"""只读 Anvil 区域文件（.mca）访问。

阶段 1：打开、枚举已存在区块、将区块 NBT 解析为 nbtlib compound。
不依赖 anvil-parser；支持 mmap 与外置 ``.mcc`` 流。
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
    """将局部 chunk 坐标 (0..31) 映射到位置表索引。

    Args:
        local_cx: 局部 X。
        local_cz: 局部 Z。

    Returns:
        int: 位置表槽位索引。

    Raises:
        ChunkMissing: 坐标越界。
    """
    if not (0 <= local_cx < CHUNKS_PER_SIDE and 0 <= local_cz < CHUNKS_PER_SIDE):
        raise ChunkMissing(
            f"Local chunk ({local_cx}, {local_cz}) out of region bounds"
        )
    return local_cx + local_cz * CHUNKS_PER_SIDE


def world_to_local(chunk_x: int, chunk_z: int) -> Tuple[int, int, int, int]:
    """世界 chunk 坐标 → ``(region_x, region_z, local_cx, local_cz)``。

    Args:
        chunk_x: 世界 chunk X。
        chunk_z: 世界 chunk Z。

    Returns:
        Tuple[int, int, int, int]: 区域与局部坐标。
    """
    region_x, local_cx = divmod(chunk_x, CHUNKS_PER_SIDE)
    region_z, local_cz = divmod(chunk_z, CHUNKS_PER_SIDE)
    return region_x, region_z, local_cx, local_cz


class RegionFile:
    """单个 ``r.X.Z.mca`` 的只读视图。"""

    __slots__ = ("_path", "_data", "_closed", "_locations")

    def __init__(self, data: RegionData, path: Optional[Path] = None) -> None:
        """用已加载的区域字节/mmap 构造只读视图。

        Args:
            data: 至少含 8KiB 头的区域数据。
            path: 可选磁盘路径（外部 .mcc 与错误信息用）。

        Raises:
            McaError: 数据短于 Anvil 头长度。
        """
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
        """以只读 mmap 打开区域文件（不整文件拷贝到堆）。

        Args:
            path: ``.mca`` 路径。

        Returns:
            RegionFile: 打开的只读实例。

        Raises:
            McaError: 文件过小或无法读取。
        """
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
        """从内存字节构造只读区域视图。

        Args:
            data: 完整 .mca 内容。
            path: 可选逻辑路径（用于 .mcc 解析与诊断）。

        Returns:
            RegionFile: 基于字节缓冲的实例。
        """
        return cls(data=data, path=path)

    @classmethod
    def from_file(cls, file: BinaryIO, path: Optional[Path] = None) -> "RegionFile":
        """从已打开的二进制流读入全部内容。

        Args:
            file: 可读二进制流。
            path: 可选逻辑路径。

        Returns:
            RegionFile: 基于读入字节的实例。
        """
        return cls(data=file.read(), path=path)

    def close(self) -> None:
        """释放 mmap/缓冲；可重复调用。"""
        if self._closed:
            return
        self._closed = True
        data = self._data
        self._data = b""
        if isinstance(data, mmap.mmap):
            data.close()

    def __enter__(self) -> "RegionFile":
        """进入上下文管理器，返回 self。"""
        return self

    def __exit__(self, *args: Any) -> None:
        """退出上下文时关闭文件。"""
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise McaError("RegionFile is closed")

    @property
    def path(self) -> Optional[Path]:
        """关联的磁盘路径（若从路径/标注打开）。"""
        return self._path

    @property
    def size(self) -> int:
        """当前区域数据字节长度。

        Raises:
            McaError: 文件已关闭。
        """
        self._ensure_open()
        return len(self._data)

    def chunk_location(self, local_cx: int, local_cz: int) -> Tuple[int, int]:
        """返回 ``(sector_offset, sector_count)``；(0, 0) 表示缺失。

        Args:
            local_cx: 局部 chunk X。
            local_cz: 局部 chunk Z。

        Returns:
            Tuple[int, int]: 扇区偏移与扇区数。
        """
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
        """读取位置表旁时间戳（Unix 秒，大端 u32）。

        Args:
            local_cx: 局部 chunk X（0–31）。
            local_cz: 局部 chunk Z（0–31）。

        Returns:
            int: 时间戳；缺失槽通常为 0。
        """
        self._ensure_open()
        index = local_chunk_index(local_cx, local_cz)
        b_off = LOCATION_TABLE_SIZE + index * 4
        return int.from_bytes(self._data[b_off:b_off + 4], "big")

    def has_chunk(self, local_cx: int, local_cz: int) -> bool:
        """位置表槽是否非空（不验证载荷完整性）。

        Args:
            local_cx: 局部 chunk X。
            local_cz: 局部 chunk Z。

        Returns:
            bool: 槽占用则 True。
        """
        off, sectors = self.chunk_location(local_cx, local_cz)
        return not (off == 0 and sectors == 0)

    def iter_present_chunks(self) -> Iterable[Tuple[int, int]]:
        """遍历位置表中非空槽的局部坐标。

        稀疏区域应优先用此接口，避免对 1024 槽逐个试探与异常。

        Yields:
            Tuple[int, int]: ``(local_cx, local_cz)``。
        """
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
        """是否存在使用外置 ``.mcc`` 流的已占用槽。

        Returns:
            bool: 任一已存在区块带外部流标志则为 True。
        """
        self._ensure_open()
        data = self._data
        for off, sectors in self._location_table():
            if off == 0 or sectors == 0:
                continue
            marker_offset = off * SECTOR_SIZE + LENGTH_HEADER_SIZE
            if marker_offset < len(data) and (
                data[marker_offset] & EXTERNAL_CHUNK_STREAM_FLAG
            ):
                return True
        return False

    def external_chunk_signature(
        self,
        chunks: Iterable[Tuple[int, int]],
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        """对采样的外置流签名做紧凑哈希，供缓存失效。

        Args:
            chunks: 要采样的局部坐标。
            cancel_check: 可选取消回调，返回 True 时中止。

        Returns:
            str: SHA1 十六进制；无外置流时为空串。
        """
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
        """按局部坐标返回外置 ``.mcc`` 文件签名（mtime_ns,size）。

        Args:
            chunks: 候选局部坐标。
            cancel_check: 可选取消回调。

        Returns:
            Dict[Tuple[int, int], str]: 仅外置槽的签名；缺失文件为 ``missing``。
        """
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
        """统计位置表中非空槽数量。"""
        return sum(1 for _ in self.iter_present_chunks())

    def read_chunk_raw(self, local_cx: int, local_cz: int) -> bytes:
        """解压并返回局部区块的原始 NBT 字节。

        Args:
            local_cx: 局部 chunk X。
            local_cz: 局部 chunk Z。

        Returns:
            bytes: 未压缩 NBT。

        Raises:
            ChunkMissing: 位置表槽为空。
            CorruptChunk: 位置/长度/外置流非法。
        """
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
        """推导局部区块对应的标准外置 ``.mcc`` 路径。

        依赖区域 path 文件名 ``r.X.Z.mca`` 与同目录布局。

        Args:
            local_cx: 局部 X。
            local_cz: 局部 Z。

        Returns:
            Path: ``c.<world_cx>.<world_cz>.mcc``。

        Raises:
            CorruptChunk: 无 path 或文件名无法解析区域坐标。
        """
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
        """加载区块 NBT 为 nbtlib compound 根。

        Args:
            local_cx: 局部 chunk X。
            local_cz: 局部 chunk Z。

        Returns:
            nbtlib.Compound: 解析后的根（通常为 File）。

        Raises:
            ChunkMissing / CorruptChunk: 缺失或 NBT 解析失败。
        """
        raw = self.read_chunk_raw(local_cx, local_cz)
        try:
            # nbtlib 2.x: File.parse(fileobj) for in-memory bytes
            nbt_file = nbtlib.File.parse(io.BytesIO(raw))
        except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
            raise CorruptChunk(
                f"Chunk ({local_cx}, {local_cz}) NBT parse failed: {exc}"
            ) from exc
        except Exception as exc:
            raise CorruptChunk(
                f"Chunk ({local_cx}, {local_cz}) NBT parse failed: {exc}"
            ) from exc
        return nbt_file

    def read_chunk_or_none(
        self, local_cx: int, local_cz: int
    ) -> Optional[nbtlib.Compound]:
        """读取区块 NBT；仅缺失时返回 None。

        与 ``read_chunk`` 不同，不吞掉损坏等其他错误，便于上层区分。

        Args:
            local_cx: 局部 chunk X。
            local_cz: 局部 chunk Z。

        Returns:
            Optional[nbtlib.Compound]: 存在时的根 compound。
        """
        try:
            return self.read_chunk(local_cx, local_cz)
        except ChunkMissing:
            return None
