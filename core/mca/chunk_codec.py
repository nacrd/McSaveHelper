"""区块载荷压缩 / 解压（MCA chunk payload）。"""
from __future__ import annotations

import gzip
import zlib
from typing import Protocol, Tuple, cast

from core.mca.errors import CorruptChunk, UnsupportedCompression
from core.mca.format import (
    COMPRESSION_GZIP,
    COMPRESSION_LZ4,
    COMPRESSION_NONE,
    COMPRESSION_ZLIB,
)

MAX_COMPRESSED_CHUNK_BYTES = 64 * 1024 * 1024
MAX_DECOMPRESSED_CHUNK_BYTES = 256 * 1024 * 1024


class _DecompressionStream(Protocol):
    """zlib 风格解压流接口（仅内部使用）。"""

    @property
    def eof(self) -> bool:
        """流是否已读到结尾。"""
        ...

    def decompress(self, data: bytes, max_length: int = 0) -> bytes:
        """解压一段输入；可限制输出上限。"""
        ...

    def flush(self, length: int = ...) -> bytes:
        """冲刷剩余缓冲；可限制输出长度。"""
        ...


def decompress_chunk(compression: int, payload: bytes) -> bytes:
    """解压区块载荷，返回原始 NBT 字节。

    压缩与解压后大小均受 64/256 MiB 上限约束，防止损坏数据撑爆内存。

    Args:
        compression: 压缩类型常量（zlib/gzip/none/lz4）。
        payload: 压缩后的区块字节。

    Returns:
        解压后的原始 NBT 字节。

    Raises:
        CorruptChunk: 载荷过大、解压失败或超限。
        UnsupportedCompression: LZ4 或未知类型。
    """
    try:
        _validate_compressed_size(payload)
        if compression == COMPRESSION_ZLIB:
            stream = cast(_DecompressionStream, zlib.decompressobj())
            return _decompress_zlib_stream(payload, stream)
        if compression == COMPRESSION_GZIP:
            stream = cast(
                _DecompressionStream,
                zlib.decompressobj(16 + zlib.MAX_WBITS),
            )
            return _decompress_zlib_stream(
                payload,
                stream,
            )
        if compression == COMPRESSION_NONE:
            if len(payload) > MAX_DECOMPRESSED_CHUNK_BYTES:
                raise CorruptChunk("区块载荷超过 256 MiB 限制")
            return payload
        if compression == COMPRESSION_LZ4:
            raise UnsupportedCompression(
                "LZ4 chunk compression is not supported yet (Phase 1)"
            )
        raise UnsupportedCompression(f"Unknown compression type: {compression}")
    except UnsupportedCompression:
        raise
    except (OSError, ValueError, TypeError, RuntimeError, zlib.error) as exc:
        raise CorruptChunk(f"Failed to decompress chunk: {exc}") from exc
    except Exception as exc:
        raise CorruptChunk(f"Failed to decompress chunk: {exc}") from exc


def _validate_compressed_size(payload: bytes) -> None:
    """校验压缩载荷不超过 64 MiB。"""
    if len(payload) > MAX_COMPRESSED_CHUNK_BYTES:
        raise CorruptChunk("区块压缩载荷超过 64 MiB 限制")


def _decompress_zlib_stream(payload: bytes, stream: _DecompressionStream) -> bytes:
    """用流式 API 解压并强制 256 MiB 上限。"""
    result = stream.decompress(payload, MAX_DECOMPRESSED_CHUNK_BYTES + 1)
    if len(result) > MAX_DECOMPRESSED_CHUNK_BYTES:
        raise CorruptChunk("区块解压结果超过 256 MiB 限制")
    result += stream.flush(MAX_DECOMPRESSED_CHUNK_BYTES + 1 - len(result))
    if len(result) > MAX_DECOMPRESSED_CHUNK_BYTES or not stream.eof:
        raise CorruptChunk("区块解压结果超过 256 MiB 限制")
    return result


def compress_chunk(
    raw_nbt: bytes, compression: int = COMPRESSION_ZLIB
) -> Tuple[int, bytes]:
    """压缩原始 NBT 字节。

    Args:
        raw_nbt: 未压缩 NBT 载荷。
        compression: 目标压缩类型，默认 zlib。

    Returns:
        ``(compression_type, payload)`` 元组。

    Raises:
        UnsupportedCompression: 不支持的压缩类型。
    """
    if compression == COMPRESSION_ZLIB:
        return COMPRESSION_ZLIB, zlib.compress(raw_nbt)
    if compression == COMPRESSION_GZIP:
        return COMPRESSION_GZIP, gzip.compress(raw_nbt)
    if compression == COMPRESSION_NONE:
        return COMPRESSION_NONE, raw_nbt
    raise UnsupportedCompression(f"Cannot compress with type {compression}")
