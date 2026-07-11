"""Region surface sampling for top-down map tiles."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

from core.mca.block_palette import get_chunk_blocks, is_air_name
from core.mca.errors import ChunkMissing, McaError
from core.mca.region_file import RegionFile

PathLike = Union[str, Path]
Color = Tuple[int, int, int]
ColorFunc = Callable[[str], Color]

DEFAULT_EMPTY = (45, 60, 50)
DEFAULT_WATERISH = (64, 164, 223)
DEFAULT_UNKNOWN = (100, 100, 100)


def sample_region_surface_ids(
    region_file: PathLike,
    tile_size: int = 64,
) -> Optional[List[List[Optional[str]]]]:
    """Return tile_size x tile_size grid of surface block ids (or None)."""
    tile_size = max(8, min(256, int(tile_size)))
    step = max(1, 512 // tile_size)
    try:
        rf = RegionFile.open(region_file)
    except McaError:
        return None

    grid: List[List[Optional[str]]] = [
        [None for _ in range(tile_size)] for _ in range(tile_size)
    ]
    chunk_views: Dict[Tuple[int, int], Optional[object]] = {}

    try:
        for pz in range(tile_size):
            for px in range(tile_size):
                bx = min(511, px * step + step // 2)
                bz = min(511, pz * step + step // 2)
                cx, lx = divmod(bx, 16)
                cz, lz = divmod(bz, 16)
                key = (cx, cz)
                if key not in chunk_views:
                    try:
                        nbt = rf.read_chunk(cx, cz)
                        chunk_views[key] = get_chunk_blocks(nbt)
                    except ChunkMissing:
                        chunk_views[key] = None
                    except Exception:
                        chunk_views[key] = None
                view = chunk_views[key]
                if view is None:
                    continue
                try:
                    grid[pz][px] = view.surface_block_id(lx, lz)  # type: ignore[attr-defined]
                except Exception:
                    grid[pz][px] = None
    finally:
        rf.close()
    return grid


def sample_region_surface_colors(
    region_file: PathLike,
    tile_size: int = 64,
    color_for_block: Optional[ColorFunc] = None,
) -> Optional[List[List[Color]]]:
    """Return tile_size x tile_size RGB grid for a region top-down view."""
    ids = sample_region_surface_ids(region_file, tile_size=tile_size)
    if ids is None:
        return None
    colors: List[List[Color]] = []
    for row in ids:
        out_row: List[Color] = []
        for name in row:
            if name is None:
                out_row.append(DEFAULT_EMPTY)
            elif is_air_name(name):
                out_row.append(DEFAULT_WATERISH)
            elif color_for_block is not None:
                try:
                    out_row.append(color_for_block(name))
                except Exception:
                    out_row.append(DEFAULT_UNKNOWN)
            else:
                out_row.append(DEFAULT_UNKNOWN)
        colors.append(out_row)
    return colors
