"""Native MCA (Minecraft Anvil region) I/O.

Phase 1-3: read path + topview + business migration.
Phase 4: WritableRegion write-back (anvil-free).
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
from core.mca.writer import WritableRegion, delete_chunk_entries

__all__ = [
    "ChunkMissing",
    "ChunkView",
    "CorruptChunk",
    "McaError",
    "NamedBlock",
    "NativeRegion",
    "RegionFile",
    "UnsupportedCompression",
    "WritableRegion",
    "block_id_at",
    "delete_chunk_entries",
    "sample_region_surface_colors",
    "sample_region_surface_ids",
    "section_range_for_chunk",
    "surface_block_id",
    "surface_y_from_heightmap",
]
