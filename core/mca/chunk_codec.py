"""Chunk payload compress / decompress."""
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
    @property
    def eof(self) -> bool:
        ...

    def decompress(self, data: bytes, max_length: int = 0) -> bytes:
        ...

    def flush(self, length: int = ...) -> bytes:
        ...


def decompress_chunk(compression: int, payload: bytes) -> bytes:
    """Return raw NBT bytes for a chunk payload."""
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
    if len(payload) > MAX_COMPRESSED_CHUNK_BYTES:
        raise CorruptChunk("区块压缩载荷超过 64 MiB 限制")


def _decompress_zlib_stream(payload: bytes, stream: _DecompressionStream) -> bytes:
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
    """Compress raw NBT bytes. Returns (compression_type, payload)."""
    if compression == COMPRESSION_ZLIB:
        return COMPRESSION_ZLIB, zlib.compress(raw_nbt)
    if compression == COMPRESSION_GZIP:
        return COMPRESSION_GZIP, gzip.compress(raw_nbt)
    if compression == COMPRESSION_NONE:
        return COMPRESSION_NONE, raw_nbt
    raise UnsupportedCompression(f"Cannot compress with type {compression}")
