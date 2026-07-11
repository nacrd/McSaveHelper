"""Native MCA (Minecraft Anvil region) I/O.

Phase 1 scope: read-only region open + chunk NBT load via nbtlib.
Later phases add heightmaps, block sampling, topview, and write-back.
"""
from __future__ import annotations

from core.mca.errors import (
    ChunkMissing,
    CorruptChunk,
    McaError,
    UnsupportedCompression,
)
from core.mca.region_file import RegionFile

__all__ = [
    "ChunkMissing",
    "CorruptChunk",
    "McaError",
    "RegionFile",
    "UnsupportedCompression",
]
