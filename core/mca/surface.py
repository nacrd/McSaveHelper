"""Region surface sampling for top-down map tiles.

Speed strategy:
1. Cap unique chunk decodes for overview resolutions (stride).
2. Parallel zlib/NBT decode of those chunks.
3. Nearest-neighbor expand to the requested tile size.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Union

from core.mca.block_palette import get_chunk_blocks, is_air_name
from core.mca.errors import ChunkMissing, McaError
from core.mca.region_file import RegionFile

PathLike = Union[str, Path]
Color = Tuple[int, int, int]
ColorFunc = Callable[[str], Color]

DEFAULT_EMPTY = (45, 60, 50)
DEFAULT_WATERISH = (64, 164, 223)
DEFAULT_UNKNOWN = (100, 100, 100)

_DECODE_WORKERS = 6


def _coarse_edge(tile_size: int) -> int:
    """How many samples along a region edge before upscaling.

    Full region has 32 chunks; decoding all 1024 is the topview bottleneck.
    Overview tiles intentionally subsample chunks then upscale.
    """
    if tile_size <= 16:
        return 8   # 64 chunks
    if tile_size <= 32:
        return 16  # 256 chunks
    if tile_size <= 64:
        return 24  # 576 chunks
    return 32      # 1024 chunks (hi-res)


def _decode_one(
    data: bytes, cx: int, cz: int
) -> Tuple[Tuple[int, int], Optional[object]]:
    try:
        rf = RegionFile.from_bytes(data)
        nbt = rf.read_chunk(cx, cz)
        return (cx, cz), get_chunk_blocks(nbt)
    except ChunkMissing:
        return (cx, cz), None
    except Exception:
        return (cx, cz), None


def sample_region_surface_ids(
    region_file: PathLike,
    tile_size: int = 64,
) -> Optional[List[List[Optional[str]]]]:
    """Return tile_size x tile_size grid of surface block ids (or None)."""
    tile_size = max(8, min(256, int(tile_size)))
    try:
        rf = RegionFile.open(region_file)
    except McaError:
        return None

    try:
        n = _coarse_edge(tile_size)
        # One sample near center of each coarse cell (chunk-aligned when n=32).
        coarse: List[List[Optional[str]]] = [
            [None for _ in range(n)] for _ in range(n)
        ]
        # Map coarse (i,j) -> chunk + local column
        jobs: List[Tuple[int, int, int, int, int, int]] = []
        # (i, j, cx, cz, lx, lz)
        for j in range(n):
            for i in range(n):
                # world block in [0,512)
                bx = min(511, int((i + 0.5) * 512 / n))
                bz = min(511, int((j + 0.5) * 512 / n))
                cx, lx = divmod(bx, 16)
                cz, lz = divmod(bz, 16)
                jobs.append((i, j, cx, cz, lx, lz))

        needed: Set[Tuple[int, int]] = set()
        for _, _, cx, cz, _, _ in jobs:
            if rf.has_chunk(cx, cz):
                needed.add((cx, cz))

        data = rf._data  # noqa: SLF001 — shared read-only buffer for workers
        chunk_views: Dict[Tuple[int, int], Optional[object]] = {}

        if needed:
            workers = min(_DECODE_WORKERS, max(1, len(needed)))
            if len(needed) < 12 or workers == 1:
                for cx, cz in needed:
                    try:
                        nbt = rf.read_chunk(cx, cz)
                        chunk_views[(cx, cz)] = get_chunk_blocks(nbt)
                    except Exception:
                        chunk_views[(cx, cz)] = None
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futs = [
                        pool.submit(_decode_one, data, cx, cz) for cx, cz in needed
                    ]
                    for fut in as_completed(futs):
                        try:
                            key, view = fut.result()
                            chunk_views[key] = view
                        except Exception:
                            continue

        for i, j, cx, cz, lx, lz in jobs:
            view = chunk_views.get((cx, cz))
            if view is None:
                continue
            try:
                coarse[j][i] = view.surface_block_id(lx, lz)  # type: ignore[attr-defined]
            except Exception:
                coarse[j][i] = None

        # Nearest-neighbor expand coarse -> tile_size
        if n == tile_size:
            return coarse

        grid: List[List[Optional[str]]] = [
            [None for _ in range(tile_size)] for _ in range(tile_size)
        ]
        for pz in range(tile_size):
            j = min(n - 1, pz * n // tile_size)
            row_c = coarse[j]
            row_g = grid[pz]
            for px in range(tile_size):
                i = min(n - 1, px * n // tile_size)
                row_g[px] = row_c[i]
        return grid
    finally:
        rf.close()


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
