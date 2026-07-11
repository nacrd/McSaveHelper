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


def decompress_chunk(compression: int, payload: bytes) -> bytes:
    """Return raw NBT bytes for a chunk payload."""
    try:
        if compression == COMPRESSION_ZLIB:
            return zlib.decompress(payload)
        if compression == COMPRESSION_GZIP:
            return gzip.decompress(payload)
        if compression == COMPRESSION_NONE:
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
