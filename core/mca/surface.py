"""Region surface sampling for top-down map tiles.

Speed strategy:
1. Cap unique chunk decodes for overview resolutions (stride).
2. Process-level LRU of decoded ChunkBlocks (reuse across LOD upgrades).
3. Parallel zlib/NBT decode for cache misses.
4. Nearest-neighbor expand to the requested tile size.
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from core.mca.block_palette import get_chunk_blocks, is_air_name
from core.mca.errors import ChunkMissing, McaError
from core.mca.region_file import RegionFile

PathLike = Union[str, Path]
Color = Tuple[int, int, int]
ColorFunc = Callable[[str], Color]

DEFAULT_EMPTY = (45, 60, 50)
DEFAULT_WATERISH = (64, 164, 223)
DEFAULT_UNKNOWN = (100, 100, 100)

_DECODE_WORKERS = max(4, min(8, (os.cpu_count() or 4)))

# (path_str, mtime_ns, cx, cz) -> ChunkBlocks | None
_CHUNK_LRU: "OrderedDict[Tuple[str, int, int, int], Optional[Any]]" = OrderedDict()
_CHUNK_LRU_LOCK = threading.Lock()
_CHUNK_LRU_MAX = 2500


def _coarse_edge(tile_size: int) -> int:
    """How many samples along a region edge before upscaling."""
    if tile_size <= 16:
        return 8   # 64 chunks
    if tile_size <= 32:
        return 16  # 256 chunks
    if tile_size <= 64:
        return 24  # 576 chunks
    return 32      # 1024 chunks


def _path_mtime(path: Path) -> Tuple[str, int]:
    try:
        st = path.stat()
        mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
        return str(path.resolve()), mtime_ns
    except OSError:
        return str(path), 0


def _lru_get(key: Tuple[str, int, int, int]) -> Tuple[bool, Optional[Any]]:
    with _CHUNK_LRU_LOCK:
        if key not in _CHUNK_LRU:
            return False, None
        _CHUNK_LRU.move_to_end(key)
        return True, _CHUNK_LRU[key]


def _lru_put(key: Tuple[str, int, int, int], value: Optional[Any]) -> None:
    with _CHUNK_LRU_LOCK:
        _CHUNK_LRU[key] = value
        _CHUNK_LRU.move_to_end(key)
        while len(_CHUNK_LRU) > _CHUNK_LRU_MAX:
            _CHUNK_LRU.popitem(last=False)


def _decode_one(
    data: bytes, cx: int, cz: int
) -> Tuple[Tuple[int, int], Optional[Any]]:
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
    region_path = Path(region_file)
    try:
        rf = RegionFile.open(region_path)
    except McaError:
        return None

    try:
        path_key, mtime_ns = _path_mtime(region_path)
        n = _coarse_edge(tile_size)
        coarse: List[List[Optional[str]]] = [
            [None for _ in range(n)] for _ in range(n)
        ]
        jobs: List[Tuple[int, int, int, int, int, int]] = []
        for j in range(n):
            for i in range(n):
                bx = min(511, int((i + 0.5) * 512 / n))
                bz = min(511, int((j + 0.5) * 512 / n))
                cx, lx = divmod(bx, 16)
                cz, lz = divmod(bz, 16)
                jobs.append((i, j, cx, cz, lx, lz))

        needed: Set[Tuple[int, int]] = set()
        for _, _, cx, cz, _, _ in jobs:
            if rf.has_chunk(cx, cz):
                needed.add((cx, cz))

        chunk_views: Dict[Tuple[int, int], Optional[Any]] = {}
        miss: List[Tuple[int, int]] = []
        for cx, cz in needed:
            hit, view = _lru_get((path_key, mtime_ns, cx, cz))
            if hit:
                chunk_views[(cx, cz)] = view
            else:
                miss.append((cx, cz))

        if miss:
            data = rf._data  # noqa: SLF001
            workers = min(_DECODE_WORKERS, max(1, len(miss)))
            if len(miss) < 12 or workers == 1:
                for cx, cz in miss:
                    try:
                        nbt = rf.read_chunk(cx, cz)
                        view = get_chunk_blocks(nbt)
                    except Exception:
                        view = None
                    chunk_views[(cx, cz)] = view
                    _lru_put((path_key, mtime_ns, cx, cz), view)
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futs = [
                        pool.submit(_decode_one, data, cx, cz) for cx, cz in miss
                    ]
                    for fut in as_completed(futs):
                        try:
                            key, view = fut.result()
                            chunk_views[key] = view
                            _lru_put(
                                (path_key, mtime_ns, key[0], key[1]), view
                            )
                        except Exception:
                            continue

        for i, j, cx, cz, lx, lz in jobs:
            view = chunk_views.get((cx, cz))
            if view is None:
                continue
            try:
                coarse[j][i] = view.surface_block_id(lx, lz)
            except Exception:
                coarse[j][i] = None

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

    # Flatten color conversion — faster than nested append loops with branches.
    flat: List[Color] = []
    for row in ids:
        for name in row:
            if name is None:
                flat.append(DEFAULT_EMPTY)
            elif is_air_name(name):
                flat.append(DEFAULT_WATERISH)
            elif color_for_block is not None:
                try:
                    flat.append(color_for_block(name))
                except Exception:
                    flat.append(DEFAULT_UNKNOWN)
            else:
                flat.append(DEFAULT_UNKNOWN)

    # Rebuild 2D for callers that expect nested lists.
    colors: List[List[Color]] = []
    w = len(ids[0]) if ids else 0
    for r in range(len(ids)):
        base = r * w
        colors.append(flat[base : base + w])
    return colors


def clear_chunk_decode_cache() -> None:
    """Drop process-level decoded chunk cache (tests / memory pressure)."""
    with _CHUNK_LRU_LOCK:
        _CHUNK_LRU.clear()


def chunk_decode_cache_size() -> int:
    """Number of entries in the process-level chunk decode LRU."""
    with _CHUNK_LRU_LOCK:
        return len(_CHUNK_LRU)
