"""Region surface sampling for top-down map tiles.

Speed strategy:
1. Cap unique chunk decodes for overview resolutions (stride).
2. Process-level LRU of compact surface samples (reuse across LOD upgrades).
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
from core.mca.errors import McaError
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

# (path_str, mtime_ns, file_size, cx, cz, external_signature) -> sampled
# local block positions and IDs.  The external signature is scoped to one
# chunk so a changed .mcc stream does not invalidate every ordinary chunk in
# the region or every lower-resolution LOD.
# Do not retain ChunkBlocks/NBT trees here: modded chunk trees can be very large.
SurfaceSamples = Dict[Tuple[int, int], Optional[str]]
ChunkCacheKey = Tuple[str, int, int, int, int, str]
_CHUNK_LRU: "OrderedDict[ChunkCacheKey, SurfaceSamples]" = OrderedDict()
_CHUNK_LRU_LOCK = threading.Lock()
_CHUNK_LRU_EPOCH = 0
# Keep the compact derived cache bounded while preserving full tile sampling
# precision. Values are only strings/coordinates, never complete NBT trees.
_CHUNK_LRU_MAX = 4096


def _coarse_edge(tile_size: int) -> int:
    """How many samples along a region edge before upscaling."""
    if tile_size <= 16:
        return 8   # 64 chunks
    if tile_size <= 32:
        return 16  # 256 chunks
    if tile_size <= 64:
        return 24  # 576 chunks
    return 32      # 1024 chunks


def _path_signature(path: Path) -> Tuple[str, int, int]:
    try:
        st = path.stat()
        mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
        return str(path.resolve()), mtime_ns, int(st.st_size)
    except OSError:
        return str(path), 0, 0


def _lru_get(key: ChunkCacheKey) -> Tuple[bool, SurfaceSamples]:
    with _CHUNK_LRU_LOCK:
        if key not in _CHUNK_LRU:
            return False, {}
        _CHUNK_LRU.move_to_end(key)
        return True, _CHUNK_LRU[key]


def _lru_epoch() -> int:
    with _CHUNK_LRU_LOCK:
        return _CHUNK_LRU_EPOCH


def _lru_merge(
    key: ChunkCacheKey,
    sampled: SurfaceSamples,
    expected_epoch: int,
) -> SurfaceSamples:
    """Atomically merge samples unless the cache was cleared meanwhile."""
    with _CHUNK_LRU_LOCK:
        if expected_epoch != _CHUNK_LRU_EPOCH:
            return dict(sampled)
        existing = _CHUNK_LRU.get(key, {})
        merged = dict(existing)
        merged.update(sampled)
        _CHUNK_LRU[key] = merged
        _CHUNK_LRU.move_to_end(key)
        while len(_CHUNK_LRU) > _CHUNK_LRU_MAX:
            _CHUNK_LRU.popitem(last=False)
        return merged


class _SurfaceView:
    """Lightweight view backed by sampled surface IDs, not an NBT tree."""

    __slots__ = ("_samples",)

    def __init__(self, samples: SurfaceSamples) -> None:
        self._samples = samples

    def surface_block_id(self, x: int, z: int) -> Optional[str]:
        return self._samples.get((x, z))


def _decode_one(
    region: RegionFile,
    cx: int,
    cz: int,
    samples: List[Tuple[int, int]],
) -> Tuple[Tuple[int, int], SurfaceSamples]:
    nbt = region.read_chunk(cx, cz)
    blocks = get_chunk_blocks(nbt)
    return (
        (cx, cz),
        {
            (local_x, local_z): blocks.surface_block_id(local_x, local_z)
            for local_x, local_z in samples
        },
    )


def _build_sample_jobs(edge: int) -> List[SampleJob]:
    """Build the original evenly spaced, cell-centered sampling grid."""
    jobs: List[SampleJob] = []
    for row in range(edge):
        for column in range(edge):
            block_x = min(511, int((column + 0.5) * 512 / edge))
            block_z = min(511, int((row + 0.5) * 512 / edge))
            chunk_x, local_x = divmod(block_x, 16)
            chunk_z, local_z = divmod(block_z, 16)
            jobs.append((column, row, chunk_x, chunk_z, local_x, local_z))
    return jobs


def _build_all_lod_samples() -> Dict[Tuple[int, int], List[Tuple[int, int]]]:
    by_chunk: Dict[Tuple[int, int], Set[Tuple[int, int]]] = {}
    for edge in (8, 16, 24, 32):
        for _, _, chunk_x, chunk_z, local_x, local_z in _build_sample_jobs(edge):
            by_chunk.setdefault((chunk_x, chunk_z), set()).add((local_x, local_z))
    return {chunk: sorted(samples) for chunk, samples in by_chunk.items()}


_ALL_LOD_SAMPLES = _build_all_lod_samples()


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
    jobs: Optional[List[SampleJob]] = None,
    *,
    file_size: int = 0,
    cancel_check: Optional[Callable[[], bool]] = None,
    decode_workers: Optional[int] = None,
    failed_chunks: Optional[Set[Tuple[int, int]]] = None,
    external_signatures: Optional[Dict[Tuple[int, int], str]] = None,
) -> Dict[Tuple[int, int], Optional[Any]]:
    views: Dict[Tuple[int, int], Optional[Any]] = {}
    jobs_by_chunk: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    if jobs is not None:
        for _, _, chunk_x, chunk_z, local_x, local_z in jobs:
            jobs_by_chunk.setdefault((chunk_x, chunk_z), []).append(
                (local_x, local_z)
            )
    misses: List[Tuple[int, int, List[Tuple[int, int]]]] = []
    external_signatures = external_signatures or {}
    cache_epoch = _lru_epoch()
    for chunk_x, chunk_z in needed:
        external_signature = external_signatures.get((chunk_x, chunk_z), "")
        hit, view = _lru_get(
            (
                path_key,
                mtime_ns,
                file_size,
                chunk_x,
                chunk_z,
                external_signature,
            )
        )
        requested = jobs_by_chunk.get((chunk_x, chunk_z), [])
        if hit and all(position in view for position in requested):
            views[(chunk_x, chunk_z)] = _SurfaceView(view)
        else:
            all_lod_positions = _ALL_LOD_SAMPLES.get(
                (chunk_x, chunk_z),
                requested,
            )
            missing_positions = [
                position for position in all_lod_positions if position not in view
            ]
            misses.append((chunk_x, chunk_z, missing_positions))

    requested_workers = (
        _DECODE_WORKERS if decode_workers is None else max(1, int(decode_workers))
    )
    workers = min(_DECODE_WORKERS, requested_workers)
    # RegionMapService already parallelizes complete tiles.  A worker there
    # requests one decoder to avoid nested pools; standalone callers retain
    # the small decoder pool for throughput.
    if (
        cancel_check is not None
        or len(misses) < 12
        or min(workers, len(misses)) <= 1
    ):
        _decode_misses_sequential(
            region,
            misses,
            path_key,
            mtime_ns,
            file_size,
            views,
            cache_epoch,
            cancel_check=cancel_check,
            failed_chunks=failed_chunks,
            external_signatures=external_signatures,
        )
    else:
        _decode_misses_parallel(
            region,
            misses,
            path_key,
            mtime_ns,
            file_size,
            views,
            cache_epoch,
            workers=workers,
            failed_chunks=failed_chunks,
            external_signatures=external_signatures,
        )
    return views


def _decode_misses_sequential(
    region: RegionFile,
    misses: List[Tuple[int, int, List[Tuple[int, int]]]],
    path_key: str,
    mtime_ns: int,
    file_size: int,
    views: Dict[Tuple[int, int], Optional[Any]],
    cache_epoch: int,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    failed_chunks: Optional[Set[Tuple[int, int]]] = None,
    external_signatures: Optional[Dict[Tuple[int, int], str]] = None,
) -> None:
    external_signatures = external_signatures or {}
    for chunk_x, chunk_z, samples in misses:
        if cancel_check is not None and cancel_check():
            return
        try:
            key, sampled = _decode_one(region, chunk_x, chunk_z, samples)
        except Exception:
            if failed_chunks is not None:
                failed_chunks.add((chunk_x, chunk_z))
            continue
        if cancel_check is not None and cancel_check():
            return
        _merge_sampled_view(
            key,
            sampled,
            path_key,
            mtime_ns,
            file_size,
            views,
            cache_epoch,
            external_signatures.get(key, ""),
        )


def _decode_misses_parallel(
    region: RegionFile,
    misses: List[Tuple[int, int, List[Tuple[int, int]]]],
    path_key: str,
    mtime_ns: int,
    file_size: int,
    views: Dict[Tuple[int, int], Optional[Any]],
    cache_epoch: int,
    *,
    workers: int,
    failed_chunks: Optional[Set[Tuple[int, int]]] = None,
    external_signatures: Optional[Dict[Tuple[int, int], str]] = None,
) -> None:
    external_signatures = external_signatures or {}
    workers = min(workers, len(misses))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_coords = {
            pool.submit(_decode_one, region, chunk_x, chunk_z, samples):
            (chunk_x, chunk_z)
            for chunk_x, chunk_z, samples in misses
        }
        for future in as_completed(future_coords):
            try:
                key, sampled = future.result()
            except Exception:
                if failed_chunks is not None:
                    failed_chunks.add(future_coords[future])
                continue
            _merge_sampled_view(
                key,
                sampled,
                path_key,
                mtime_ns,
                file_size,
                views,
                cache_epoch,
                external_signatures.get(key, ""),
            )


def _merge_sampled_view(
    key: Tuple[int, int],
    sampled: SurfaceSamples,
    path_key: str,
    mtime_ns: int,
    file_size: int,
    views: Dict[Tuple[int, int], Optional[Any]],
    cache_epoch: int,
    external_signature: str,
) -> None:
    cache_key = (
        path_key,
        mtime_ns,
        file_size,
        key[0],
        key[1],
        external_signature,
    )
    merged = _lru_merge(cache_key, sampled, cache_epoch)
    views[key] = _SurfaceView(merged)


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
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    decode_workers: Optional[int] = None,
    failed_chunks: Optional[Set[Tuple[int, int]]] = None,
) -> Optional[List[List[Optional[str]]]]:
    """Return tile_size x tile_size grid of surface block ids (or None)."""
    tile_size = max(8, min(256, int(tile_size)))
    region_path = Path(region_file)
    try:
        rf = RegionFile.open(region_path)
    except McaError:
        return None

    try:
        if cancel_check is not None and cancel_check():
            return None
        path_key, mtime_ns, file_size = _path_signature(region_path)
        edge = _coarse_edge(tile_size)
        jobs = _build_sample_jobs(edge)
        needed = _needed_chunks(rf, jobs)
        external_signatures = rf.external_chunk_signatures(
            needed,
            cancel_check=cancel_check,
        )
        chunk_views = _load_chunk_views(
            rf,
            needed,
            path_key,
            mtime_ns,
            jobs,
            file_size=file_size,
            cancel_check=cancel_check,
            decode_workers=decode_workers,
            failed_chunks=failed_chunks,
            external_signatures=external_signatures,
        )
        if cancel_check is not None and cancel_check():
            return None
        coarse = _sample_coarse_grid(edge, jobs, chunk_views)
        return _resize_nearest(coarse, tile_size)
    finally:
        rf.close()


def sample_region_surface_colors(
    region_file: PathLike,
    tile_size: int = 64,
    color_for_block: Optional[ColorFunc] = None,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    decode_workers: Optional[int] = None,
    failed_chunks: Optional[Set[Tuple[int, int]]] = None,
) -> Optional[List[List[Color]]]:
    """Return tile_size x tile_size RGB grid for a region top-down view."""
    ids = sample_region_surface_ids(
        region_file,
        tile_size=tile_size,
        cancel_check=cancel_check,
        decode_workers=decode_workers,
        failed_chunks=failed_chunks,
    )
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


def sample_region_surface_colors_with_status(
    region_file: PathLike,
    tile_size: int = 64,
    color_for_block: Optional[ColorFunc] = None,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    decode_workers: Optional[int] = None,
) -> Tuple[Optional[List[List[Color]]], bool]:
    """Return colors plus whether every sampled chunk decoded successfully."""
    failed_chunks: Set[Tuple[int, int]] = set()
    colors = sample_region_surface_colors(
        region_file,
        tile_size=tile_size,
        color_for_block=color_for_block,
        cancel_check=cancel_check,
        decode_workers=decode_workers,
        failed_chunks=failed_chunks,
    )
    return colors, colors is not None and not failed_chunks


def clear_chunk_decode_cache() -> None:
    """Drop process-level decoded chunk cache (tests / memory pressure)."""
    global _CHUNK_LRU_EPOCH
    with _CHUNK_LRU_LOCK:
        _CHUNK_LRU.clear()
        _CHUNK_LRU_EPOCH += 1


def chunk_decode_cache_size() -> int:
    """Number of entries in the process-level chunk decode LRU."""
    with _CHUNK_LRU_LOCK:
        return len(_CHUNK_LRU)
