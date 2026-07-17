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
from core.mca.editor import ChunkInfo, RegionEditor, RegionInfo
from core.mca.heightmaps import surface_y_from_heightmap
from core.mca.region_file import RegionFile
from core.mca.surface import sample_region_surface_colors, sample_region_surface_ids
from core.mca.topview_renderer import (
    DEFAULT_TILE_SIZE,
    DETAIL_TILE_SIZE,
    HIRES_TILE_SIZE,
    PREVIEW_TILE_SIZE,
    render_region_topview,
    render_region_topview_base64,
)
from core.mca.viewport import (
    McaMapSelection,
    McaViewport,
    ViewportTarget,
    view_level_from_scale,
)
from core.mca.writer import (
    WritableRegion,
    copy_chunk_record,
    delete_chunk_entries,
    write_chunk_record,
)

__all__ = [
    "ChunkMissing",
    "ChunkInfo",
    "ChunkView",
    "CorruptChunk",
    "DEFAULT_TILE_SIZE",
    "DETAIL_TILE_SIZE",
    "HIRES_TILE_SIZE",
    "McaError",
    "McaMapSelection",
    "McaViewport",
    "NamedBlock",
    "NativeRegion",
    "RegionFile",
    "RegionEditor",
    "RegionInfo",
    "PREVIEW_TILE_SIZE",
    "UnsupportedCompression",
    "ViewportTarget",
    "WritableRegion",
    "block_id_at",
    "copy_chunk_record",
    "delete_chunk_entries",
    "sample_region_surface_colors",
    "sample_region_surface_ids",
    "render_region_topview",
    "render_region_topview_base64",
    "section_range_for_chunk",
    "surface_block_id",
    "surface_y_from_heightmap",
    "view_level_from_scale",
    "write_chunk_record",
]
