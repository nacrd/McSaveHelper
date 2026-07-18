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
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

from core.mca.block_palette import get_chunk_blocks, is_air_name
from core.mca.errors import ChunkMissing, McaError
from core.mca.region_file import RegionFile

PathLike = Union[str, Path]
Color = Tuple[int, int, int]
ColorFunc = Callable[[str], Color]
SampleJob = Tuple[int, int, int, int, int, int]

DEFAULT_EMPTY = (45, 60, 50)
DEFAULT_WATERISH = (64, 164, 223)
DEFAULT_UNKNOWN = (100, 100, 100)

# RegionMapService renders multiple regions concurrently.  Keep this nested
# decoder pool deliberately small; large pools mostly contend on the GIL while
# starving the UI and unrelated workers.
_DECODE_WORKERS = min(2, max(1, (os.cpu_count() or 2) // 2))

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


def _build_sample_jobs(edge: int) -> List[SampleJob]:
    jobs: List[SampleJob] = []
    for row in range(edge):
        for column in range(edge):
            block_x = min(511, int((column + 0.5) * 512 / edge))
            block_z = min(511, int((row + 0.5) * 512 / edge))
            chunk_x, local_x = divmod(block_x, 16)
            chunk_z, local_z = divmod(block_z, 16)
            jobs.append((column, row, chunk_x, chunk_z, local_x, local_z))
    return jobs


def _needed_chunks(region: RegionFile, jobs: List[SampleJob]) -> Set[Tuple[int, int]]:
    return {
        (chunk_x, chunk_z)
        for _, _, chunk_x, chunk_z, _, _ in jobs
        if region.has_chunk(chunk_x, chunk_z)
    }


def _load_chunk_views(
    region: RegionFile,
    needed: Set[Tuple[int, int]],
    path_key: str,
    mtime_ns: int,
) -> Dict[Tuple[int, int], Optional[Any]]:
    views: Dict[Tuple[int, int], Optional[Any]] = {}
    misses: List[Tuple[int, int]] = []
    for chunk_x, chunk_z in needed:
        hit, view = _lru_get((path_key, mtime_ns, chunk_x, chunk_z))
        if hit:
            views[(chunk_x, chunk_z)] = view
        else:
            misses.append((chunk_x, chunk_z))

    if len(misses) < 12 or min(_DECODE_WORKERS, len(misses)) <= 1:
        _decode_misses_sequential(region, misses, path_key, mtime_ns, views)
    else:
        _decode_misses_parallel(region, misses, path_key, mtime_ns, views)
    return views


def _decode_misses_sequential(
    region: RegionFile,
    misses: List[Tuple[int, int]],
    path_key: str,
    mtime_ns: int,
    views: Dict[Tuple[int, int], Optional[Any]],
) -> None:
    for chunk_x, chunk_z in misses:
        try:
            nbt = region.read_chunk(chunk_x, chunk_z)
            view = get_chunk_blocks(nbt)
        except Exception:
            view = None
        views[(chunk_x, chunk_z)] = view
        _lru_put((path_key, mtime_ns, chunk_x, chunk_z), view)


def _decode_misses_parallel(
    region: RegionFile,
    misses: List[Tuple[int, int]],
    path_key: str,
    mtime_ns: int,
    views: Dict[Tuple[int, int], Optional[Any]],
) -> None:
    workers = min(_DECODE_WORKERS, len(misses))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_decode_one, region._data, chunk_x, chunk_z)
            for chunk_x, chunk_z in misses
        ]
        for future in as_completed(futures):
            try:
                key, view = future.result()
            except Exception:
                continue
            views[key] = view
            _lru_put((path_key, mtime_ns, key[0], key[1]), view)


def _sample_coarse_grid(
    edge: int,
    jobs: List[SampleJob],
    views: Dict[Tuple[int, int], Optional[Any]],
) -> List[List[Optional[str]]]:
    grid: List[List[Optional[str]]] = [
        [None for _ in range(edge)] for _ in range(edge)
    ]
    for column, row, chunk_x, chunk_z, local_x, local_z in jobs:
        view = views.get((chunk_x, chunk_z))
        if view is None:
            continue
        try:
            grid[row][column] = view.surface_block_id(local_x, local_z)
        except Exception:
            grid[row][column] = None
    return grid


def _resize_nearest(
    source: Sequence[Sequence[Optional[str]]],
    target_size: int,
) -> List[List[Optional[str]]]:
    source_size = len(source)
    if source_size == target_size:
        return [list(row) for row in source]
    target: List[List[Optional[str]]] = [
        [None for _ in range(target_size)] for _ in range(target_size)
    ]
    for target_z in range(target_size):
        source_z = min(source_size - 1, target_z * source_size // target_size)
        source_row = source[source_z]
        target_row = target[target_z]
        for target_x in range(target_size):
            source_x = min(
                source_size - 1,
                target_x * source_size // target_size,
            )
            target_row[target_x] = source_row[source_x]
    return target


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
        edge = _coarse_edge(tile_size)
        jobs = _build_sample_jobs(edge)
        needed = _needed_chunks(rf, jobs)
        chunk_views = _load_chunk_views(
            rf,
            needed,
            path_key,
            mtime_ns,
        )
        coarse = _sample_coarse_grid(edge, jobs, chunk_views)
        return _resize_nearest(coarse, tile_size)
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
