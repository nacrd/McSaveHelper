"""Native MCA (Minecraft Anvil region) I/O.

Phase 1-3: read path + topview + business migration.
Phase 4: WritableRegion write-back (anvil-free).
"""
from __future__ import annotations

from core.mca.block_palette import (
    block_id_at,
    get_world_surface_chunk_blocks,
    is_transparent_surface_name,
    surface_block_id,
)
from core.mca.biome_palette import (
    BiomeSection,
    ChunkBiomes,
    decode_biome_section,
)
from core.mca.chunk_view import ChunkView, NamedBlock, NativeRegion, section_range_for_chunk
from core.mca.errors import (
    ChunkMissing,
    CorruptChunk,
    McaError,
    UnsupportedCompression,
)
from core.mca.editor import ChunkInfo, RegionEditor, RegionInfo
from core.mca.heightmaps import (
    WORLD_SURFACE_HEIGHTMAP_NAMES,
    surface_y_from_heightmap,
)
from core.mca.map_coordinates import (
    BlockBounds,
    chunk_block_bounds,
    format_chunk_block_range,
    format_region_block_range,
    format_region_coordinate_label,
    region_block_bounds,
)
from core.mca.map_navigation import (
    LevelChange,
    McaMapNavigator,
    SelectionNotification,
)
from core.mca.map_models import (
    BLOCKS_PER_CHUNK,
    BLOCKS_PER_REGION,
    CHUNKS_PER_REGION,
    MapDimension,
    MapExportSpec,
    MapLayerState,
    MapLayerStateSnapshot,
    MapMarker,
    MapSelection,
    MapTileKey,
    MapViewState,
    MapViewStateSnapshot,
)
from core.mca.map_tiles import (
    DEFAULT_TILE_LADDER,
    HIGH_DETAIL_TILE_LADDER,
    MapTileRequest,
    choose_tile_size,
    plan_visible_requests,
    prioritize_regions,
)
from core.mca.region_file import RegionFile
from core.mca.region_selection import format_region_selection
from core.mca.surface import (
    chunk_decode_cache_bytes,
    chunk_decode_cache_evictions,
    chunk_decode_cache_hits,
    chunk_decode_cache_misses,
    chunk_decode_cache_size,
    clear_chunk_decode_cache,
    invalidate_chunk_decode_cache_for_world,
    sample_region_surface_colors,
    sample_region_surface_samples,
)
from core.mca.topview_renderer import (
    DEFAULT_TILE_SIZE,
    DETAIL_TILE_SIZE,
    HIRES_TILE_SIZE,
    LEAF_TILE_SIZE,
    PREVIEW_TILE_SIZE,
    TopviewProgressFrame,
    ULTRA_TILE_SIZE,
    render_region_topview,
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
    "BlockBounds",
    "BLOCKS_PER_CHUNK",
    "BLOCKS_PER_REGION",
    "CHUNKS_PER_REGION",
    "DEFAULT_TILE_SIZE",
    "DEFAULT_TILE_LADDER",
    "DETAIL_TILE_SIZE",
    "HIGH_DETAIL_TILE_LADDER",
    "HIRES_TILE_SIZE",
    "McaError",
    "McaMapSelection",
    "McaMapNavigator",
    "MapTileRequest",
    "McaViewport",
    "MapDimension",
    "MapExportSpec",
    "MapLayerState",
    "MapLayerStateSnapshot",
    "MapMarker",
    "MapSelection",
    "MapTileKey",
    "MapViewState",
    "MapViewStateSnapshot",
    "NamedBlock",
    "NativeRegion",
    "RegionFile",
    "RegionEditor",
    "RegionInfo",
    "LevelChange",
    "LEAF_TILE_SIZE",
    "PREVIEW_TILE_SIZE",
    "TopviewProgressFrame",
    "UnsupportedCompression",
    "ULTRA_TILE_SIZE",
    "SelectionNotification",
    "ViewportTarget",
    "WritableRegion",
    "block_id_at",
    "BiomeSection",
    "ChunkBiomes",
    "decode_biome_section",
    "get_world_surface_chunk_blocks",
    "copy_chunk_record",
    "chunk_block_bounds",
    "choose_tile_size",
    "delete_chunk_entries",
    "format_chunk_block_range",
    "format_region_block_range",
    "format_region_coordinate_label",
    "format_region_selection",
    "sample_region_surface_colors",
    "sample_region_surface_samples",
    "clear_chunk_decode_cache",
    "invalidate_chunk_decode_cache_for_world",
    "chunk_decode_cache_bytes",
    "chunk_decode_cache_evictions",
    "chunk_decode_cache_hits",
    "chunk_decode_cache_misses",
    "chunk_decode_cache_size",
    "render_region_topview",
    "plan_visible_requests",
    "prioritize_regions",
    "region_block_bounds",
    "section_range_for_chunk",
    "surface_block_id",
    "is_transparent_surface_name",
    "WORLD_SURFACE_HEIGHTMAP_NAMES",
    "surface_y_from_heightmap",
    "view_level_from_scale",
    "write_chunk_record",
]
