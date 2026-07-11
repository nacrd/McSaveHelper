"""Native MCA (Minecraft Anvil region) I/O.

Phase 1: read-only region + chunk NBT (nbtlib).
Phase 2: heightmaps, block id sampling, surface sampling for topview.
Phase 3: anvil-compatible ChunkView/NativeRegion for read-path migration.
"""
from __future__ import annotations

from core.mca.block_palette import block_id_at, surface_block_id
from core.mca.chunk_view import ChunkView, NamedBlock, NativeRegion, section_range_for_chunk
from core.mca.errors import (
    ChunkMissing,
    CorruptChunk,
    McaError,
    UnsupportedCompression,
)
from core.mca.heightmaps import surface_y_from_heightmap
from core.mca.region_file import RegionFile
from core.mca.surface import sample_region_surface_colors, sample_region_surface_ids

__all__ = [
    "ChunkMissing",
    "ChunkView",
    "CorruptChunk",
    "McaError",
    "NamedBlock",
    "NativeRegion",
    "RegionFile",
    "UnsupportedCompression",
    "block_id_at",
    "sample_region_surface_colors",
    "sample_region_surface_ids",
    "section_range_for_chunk",
    "surface_block_id",
    "surface_y_from_heightmap",
]
