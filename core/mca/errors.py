"""MCA subsystem errors."""
from __future__ import annotations


class McaError(Exception):
    """Base error for native MCA I/O."""


class ChunkMissing(McaError):
    """Chunk location is empty (never generated) or out of this region."""


class CorruptChunk(McaError):
    """Chunk payload is truncated, badly compressed, or not valid NBT."""


class UnsupportedCompression(McaError):
    """Chunk uses a compression scheme we do not decode yet."""


class UnsupportedVersion(McaError):
    """Chunk DataVersion / section layout is not handled yet."""
