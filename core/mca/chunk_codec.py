"""Chunk payload compress / decompress."""
from __future__ import annotations

import gzip
import zlib
from typing import Tuple

from core.mca.errors import CorruptChunk, UnsupportedCompression
from core.mca.format import (
    COMPRESSION_GZIP,
    COMPRESSION_LZ4,
    COMPRESSION_NONE,
    COMPRESSION_ZLIB,
)

MAX_COMPRESSED_CHUNK_BYTES = 64 * 1024 * 1024
MAX_DECOMPRESSED_CHUNK_BYTES = 256 * 1024 * 1024


def decompress_chunk(compression: int, payload: bytes) -> bytes:
    """Return raw NBT bytes for a chunk payload."""
    try:
        if len(payload) > MAX_COMPRESSED_CHUNK_BYTES:
            raise CorruptChunk("区块压缩载荷超过 64 MiB 限制")
        if compression == COMPRESSION_ZLIB:
            stream = zlib.decompressobj()
            result = stream.decompress(payload, MAX_DECOMPRESSED_CHUNK_BYTES + 1)
            if len(result) > MAX_DECOMPRESSED_CHUNK_BYTES:
                raise CorruptChunk("区块解压结果超过 256 MiB 限制")
            result += stream.flush(MAX_DECOMPRESSED_CHUNK_BYTES + 1 - len(result))
            if len(result) > MAX_DECOMPRESSED_CHUNK_BYTES or not stream.eof:
                raise CorruptChunk("区块解压结果超过 256 MiB 限制")
            return result
        if compression == COMPRESSION_GZIP:
            stream = zlib.decompressobj(16 + zlib.MAX_WBITS)
            result = stream.decompress(payload, MAX_DECOMPRESSED_CHUNK_BYTES + 1)
            if len(result) > MAX_DECOMPRESSED_CHUNK_BYTES:
                raise CorruptChunk("区块解压结果超过 256 MiB 限制")
            result += stream.flush(MAX_DECOMPRESSED_CHUNK_BYTES + 1 - len(result))
            if len(result) > MAX_DECOMPRESSED_CHUNK_BYTES or not stream.eof:
                raise CorruptChunk("区块解压结果超过 256 MiB 限制")
            return result
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
    except Exception as exc:
        raise CorruptChunk(f"Failed to decompress chunk: {exc}") from exc


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
