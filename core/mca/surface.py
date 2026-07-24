"""Region surface sampling for top-down map tiles.

Speed strategy:
1. Cap unique chunk decodes for overview resolutions (stride).
2. Process-level LRU of compact surface samples (reuse across LOD upgrades).
3. Optional injected parallel zlib/NBT decode for cache misses.
4. Nearest-neighbor expand to the requested tile size.
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union, cast

from core.parallel import (
    ParallelCancelledError,
    ParallelRunner,
    SerialParallelRunner,
    clamp_workers,
)
from core.mca.block_palette import (
    get_world_surface_chunk_blocks,
    is_air_name,
    is_transparent_surface_name,
)
from core.mca.errors import McaError
from core.mca.region_file import RegionFile

PathLike = Union[str, Path]
Color = Tuple[int, int, int]
ColorFunc = Callable[[str], Color]
SurfaceColorFunc = Callable[[str, Optional[str]], Color]
SampleJob = Tuple[int, int, int, int, int, int]

DEFAULT_EMPTY = (45, 60, 50)
DEFAULT_WATERISH = (64, 164, 223)
DEFAULT_UNKNOWN = (100, 100, 100)
DEFAULT_PROGRESS_BATCH_CHUNKS = 128
_OVERLAY_ALPHA_BY_NAME = {
    "lily_pad": 0.72,
    "kelp": 0.72,
    "kelp_plant": 0.72,
    "seagrass": 0.72,
    "tall_seagrass": 0.72,
    "vine": 0.48,
    "cave_vines": 0.48,
    "cave_vines_plant": 0.48,
    "twisting_vines": 0.48,
    "weeping_vines": 0.48,
    "grass": 0.42,
    "short_grass": 0.42,
    "tall_grass": 0.42,
    "fern": 0.42,
    "large_fern": 0.42,
    "moss_carpet": 0.62,
    "snow": 0.70,
}

# RegionMapService renders multiple regions concurrently.  Keep this nested
# decoder pool deliberately small; large pools mostly contend on the GIL while
# starving the UI and unrelated workers.
_DECODE_WORKERS = min(2, max(1, (os.cpu_count() or 2) // 2))

# (path_str, mtime_ns, file_size, cx, cz, external_signature) -> sampled
# local block positions and IDs.  The external signature is scoped to one
# chunk so a changed .mcc stream does not invalidate every ordinary chunk in
# the region or every lower-resolution LOD.
# Do not retain ChunkBlocks/NBT trees here: modded chunk trees can be very large.
SurfaceSample = Tuple[Optional[str], Optional[int], int]
SurfaceSampleBiome = Tuple[Optional[str], Optional[int], int, Optional[str]]
SurfaceSampleOverlay = Tuple[
    Optional[str],
    Optional[int],
    int,
    Optional[str],
    Optional[str],
    float,
]
SurfaceValue = Union[
    Optional[str],
    SurfaceSample,
    SurfaceSampleBiome,
    SurfaceSampleOverlay,
]
SurfaceProgressCallback = Callable[
    [List[List[SurfaceValue]], Set[Tuple[int, int]], int, int],
    None,
]
SurfaceColorProgressCallback = Callable[
    [List[List[Color]], Set[Tuple[int, int]], int, int],
    None,
]
ChunkViews = Dict[Tuple[int, int], Optional[Any]]
ChunkProgressCallback = Callable[
    [ChunkViews, Set[Tuple[int, int]], int, int],
    None,
]
_NormalizedSurface = Tuple[
    Optional[str],
    Optional[int],
    int,
    Optional[str],
    Optional[str],
    float,
]
SurfaceSamples = Dict[Tuple[int, int], SurfaceValue]
ChunkCacheKey = Tuple[str, int, int, int, int, str]
_CHUNK_LRU: "OrderedDict[ChunkCacheKey, SurfaceSamples]" = OrderedDict()
_CHUNK_LRU_LOCK = threading.Lock()
_CHUNK_LRU_EPOCH = 0
# Keep the compact derived cache bounded while preserving full tile sampling
# precision. Values are only strings/coordinates, never complete NBT trees.
CHUNK_DECODE_CACHE_MAX_ENTRIES = 4096
CHUNK_DECODE_CACHE_MAX_BYTES = 128 * 1024 * 1024
_CHUNK_LRU_MAX = CHUNK_DECODE_CACHE_MAX_ENTRIES
_CHUNK_LRU_MAX_BYTES = CHUNK_DECODE_CACHE_MAX_BYTES
_CHUNK_LRU_BYTES = 0
_CHUNK_LRU_HITS = 0
_CHUNK_LRU_MISSES = 0
_CHUNK_LRU_EVICTIONS = 0


def _estimate_surface_samples_bytes(samples: SurfaceSamples) -> int:
    """保守估算紧凑地表采样映射的内存占用。"""
    total = 64
    for position, value in samples.items():
        total += 80 + len(position) * 16
        if isinstance(value, str):
            total += len(value)
        elif isinstance(value, tuple):
            total += 24 * len(value)
            total += sum(len(item) for item in value if isinstance(item, str))
    return total


def _coarse_edge(tile_size: int) -> int:
    """How many samples along a region edge before upscaling."""
    if tile_size <= 16:
        # The 16px tile is a transient UI preview before the visible LOD
        # upgrade. Sampling 4x4 representative chunks keeps its cold path
        # interactive without reducing the quality of persistent LODs.
        return 4
    if tile_size <= 32:
        return 16
    # Persistent LODs from 64px retain their requested spatial resolution. A
    # 512px leaf tile samples every block, matching the native region
    # resolution used by JourneyMap and the finest Xaero world-map level.
    return min(512, int(tile_size))


def _path_signature(path: Path) -> Tuple[str, int, int]:
    try:
        st = path.stat()
        mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
        return str(path.resolve()), mtime_ns, int(st.st_size)
    except OSError:
        return str(path), 0, 0


def _lru_get(key: ChunkCacheKey) -> Tuple[bool, SurfaceSamples]:
    global _CHUNK_LRU_HITS, _CHUNK_LRU_MISSES
    with _CHUNK_LRU_LOCK:
        if key not in _CHUNK_LRU:
            _CHUNK_LRU_MISSES += 1
            return False, {}
        _CHUNK_LRU.move_to_end(key)
        _CHUNK_LRU_HITS += 1
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
    global _CHUNK_LRU_BYTES, _CHUNK_LRU_EVICTIONS
    with _CHUNK_LRU_LOCK:
        if expected_epoch != _CHUNK_LRU_EPOCH:
            return dict(sampled)
        existing = _CHUNK_LRU.get(key)
        if existing is not None:
            _CHUNK_LRU_BYTES -= _estimate_surface_samples_bytes(existing)
        merged = dict(existing) if existing is not None else {}
        merged.update(sampled)
        _CHUNK_LRU[key] = merged
        _CHUNK_LRU_BYTES += _estimate_surface_samples_bytes(merged)
        _CHUNK_LRU.move_to_end(key)
        while (
            len(_CHUNK_LRU) > _CHUNK_LRU_MAX
            or _CHUNK_LRU_BYTES > _CHUNK_LRU_MAX_BYTES
        ):
            _old_key, old_samples = _CHUNK_LRU.popitem(last=False)
            _CHUNK_LRU_BYTES -= _estimate_surface_samples_bytes(old_samples)
            _CHUNK_LRU_EVICTIONS += 1
        return merged


class _SurfaceView:
    """Lightweight view backed by sampled surface IDs, not an NBT tree."""

    __slots__ = ("_samples",)

    def __init__(self, samples: SurfaceSamples) -> None:
        self._samples = samples

    def surface_sample(self, x: int, z: int) -> SurfaceValue:
        value = self._samples.get((x, z))
        return _coerce_surface_sample(value)

    def surface_block_id(self, x: int, z: int) -> Optional[str]:
        return _surface_parts(self.surface_sample(x, z))[0]


def _decode_one(
    region: RegionFile,
    cx: int,
    cz: int,
    samples: List[Tuple[int, int]],
) -> Tuple[Tuple[int, int], SurfaceSamples]:
    nbt = region.read_chunk(cx, cz)
    blocks = get_world_surface_chunk_blocks(nbt)
    return (
        (cx, cz),
        {
            (local_x, local_z): _sample_column(blocks, local_x, local_z)
            for local_x, local_z in samples
        },
    )


def _surface_parts(value: SurfaceValue) -> _NormalizedSurface:
    """Normalize old and extended compact samples for internal consumers."""
    if not isinstance(value, tuple):
        return value, None, 0, None, None, 0.0
    name = value[0] if value else None
    try:
        height = int(value[1]) if len(value) > 1 and value[1] is not None else None
    except (TypeError, ValueError):
        height = None
    try:
        water_depth = max(0, int(value[2])) if len(value) > 2 else 0
    except (TypeError, ValueError):
        water_depth = 0
    biome = value[3] if len(value) > 3 else None
    overlay = value[4] if len(value) > 4 else None
    try:
        alpha = max(0.0, min(1.0, float(value[5]))) if len(value) > 5 else 0.0
    except (TypeError, ValueError):
        alpha = 0.0
    return name, height, water_depth, biome, overlay, alpha


def _surface_value(
    name: Optional[str],
    height: Optional[int],
    water_depth: int,
    biome: Optional[str],
    overlay: Optional[str],
    alpha: float,
    *,
    include_biome: bool,
    include_overlay: bool,
) -> SurfaceValue:
    """Pack a sample while retaining the arity of legacy test fixtures."""
    if include_overlay:
        return name, height, water_depth, biome, overlay, alpha
    if include_biome:
        return name, height, water_depth, biome
    return name, height, water_depth


def _overlay_alpha(name: Optional[str]) -> float:
    if not name:
        return 0.0
    path = name.lower().rsplit(":", 1)[-1]
    if "leaves" in path or path.endswith("_leaf"):
        return 0.52
    named = _OVERLAY_ALPHA_BY_NAME.get(path)
    if named is not None:
        return named
    if path.endswith(("_flower", "_flowers")):
        return 0.46
    if path.endswith(("_sapling", "_plant")):
        return 0.48
    if is_transparent_surface_name(name):
        return 0.44
    return 0.0


def _select_surface_strata(
    strata: Sequence[Tuple[str, int]],
) -> Tuple[Optional[str], Optional[int], Optional[str], float]:
    """Choose an opaque base and retain the first transparent overlay."""
    if not strata:
        return None, None, None, 0.0
    top_name, top_height = strata[0]
    base_name: Optional[str] = None
    base_height: Optional[int] = None
    overlay_name: Optional[str] = None
    overlay_alpha = 0.0
    for name, height in strata:
        alpha = _overlay_alpha(name)
        if alpha > 0.0 and overlay_name is None:
            overlay_name = name
            overlay_alpha = alpha
            continue
        base_name = name
        base_height = height
        break
    if base_name is None:
        # A column containing only transparent decorations should remain
        # visible instead of becoming an empty pixel.
        return top_name, top_height, None, 0.0
    return base_name, base_height, overlay_name, overlay_alpha


def _sample_column(blocks: Any, local_x: int, local_z: int) -> SurfaceValue:
    """Sample one column, preferring strata to avoid a second column walk."""
    strata_sample = _sample_column_from_strata(blocks, local_x, local_z)
    if strata_sample is not None:
        return strata_sample

    raw_sample = _read_surface_sample(blocks, local_x, local_z)
    name, height, unused_depth, biome, overlay, alpha = _surface_parts(raw_sample)
    has_overlay = isinstance(raw_sample, tuple) and len(raw_sample) >= 5
    biome, include_biome = _sample_biome(
        blocks, local_x, local_z, height, biome, raw_sample
    )
    water_depth = _water_depth(blocks, local_x, local_z, name, height, unused_depth)
    return _surface_value(
        name,
        height,
        water_depth,
        biome,
        overlay,
        alpha,
        include_biome=include_biome,
        include_overlay=has_overlay,
    )


def _sample_column_from_strata(
    blocks: Any,
    local_x: int,
    local_z: int,
) -> Optional[SurfaceValue]:
    strata_getter = getattr(blocks, "surface_strata", None)
    if not callable(strata_getter):
        return None
    try:
        strata = cast(Sequence[Tuple[str, int]], strata_getter(local_x, local_z))
    except (TypeError, ValueError):
        return None
    if not strata:
        # Empty strata (air/void) or fixtures that only implement surface_sample.
        return None

    name, height, overlay, alpha = _select_surface_strata(strata)
    # Seed as a 3-tuple sample so biome packing is only enabled when
    # biome_at works (include_biome requires len >= 4).
    seed: SurfaceSample = (name, height, 0)
    biome, include_biome = _sample_biome(
        blocks, local_x, local_z, height, None, seed
    )
    water_depth = _water_depth(blocks, local_x, local_z, name, height, 0)
    return _surface_value(
        name,
        height,
        water_depth,
        biome,
        overlay,
        alpha,
        include_biome=include_biome,
        include_overlay=overlay is not None,
    )


def _read_surface_sample(blocks: Any, local_x: int, local_z: int) -> SurfaceValue:
    sample = getattr(blocks, "surface_sample", None)
    if callable(sample):
        return cast(SurfaceValue, sample(local_x, local_z))
    return cast(SurfaceValue, blocks.surface_block_id(local_x, local_z))


def _sample_biome(
    blocks: Any, local_x: int, local_z: int, height: Optional[int], biome: Optional[str],
    raw_sample: SurfaceValue,
) -> Tuple[Optional[str], bool]:
    include_biome = isinstance(raw_sample, tuple) and len(raw_sample) >= 4
    biome_getter = getattr(blocks, "biome_at", None)
    if not callable(biome_getter) or height is None:
        return biome, include_biome
    try:
        return cast(Optional[str], biome_getter(local_x, height, local_z)), True
    except (TypeError, ValueError):
        return biome, include_biome


def _water_depth(
    blocks: Any, local_x: int, local_z: int, name: Optional[str], height: Optional[int], depth: int,
) -> int:
    if not name or "water" not in name.lower() or height is None:
        return depth
    water_depth = depth
    for candidate_depth in range(1, 9):
        below = blocks.block_id_at(local_x, height - candidate_depth, local_z)
        if not below or "water" not in below.lower():
            break
        water_depth = candidate_depth
    return water_depth


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


def _build_all_lod_samples(
    max_edge: int = 512,
) -> Dict[Tuple[int, int], List[Tuple[int, int]]]:
    by_chunk: Dict[Tuple[int, int], Set[Tuple[int, int]]] = {}
    for edge in (8, 32, 64, 128, 256, 512):
        if edge > max_edge:
            continue
        for _, _, chunk_x, chunk_z, local_x, local_z in _build_sample_jobs(edge):
            by_chunk.setdefault((chunk_x, chunk_z), set()).add((local_x, local_z))
    return {chunk: sorted(samples) for chunk, samples in by_chunk.items()}


_FOCUSED_LOD_SAMPLES = _build_all_lod_samples(256)


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
    parallel_runner: Optional[ParallelRunner] = None,
    progress_callback: Optional[ChunkProgressCallback] = None,
    progress_batch_chunks: int = DEFAULT_PROGRESS_BATCH_CHUNKS,
) -> ChunkViews:
    views: ChunkViews = {}
    jobs_by_chunk = _jobs_by_chunk(jobs)
    requested_edge = _requested_edge(jobs)
    # Preview LODs decode only displayed points. Intermediate 64/128px tiles
    # preload the normal 256px ceiling, while direct 256/512px requests avoid
    # reverse-preloading lower grids that cannot improve their output.
    preload_detail_positions = requested_edge >= 64
    external_signatures = external_signatures or {}
    cache_epoch = _lru_epoch()
    misses = _collect_chunk_cache_misses(
        needed=needed,
        path_key=path_key,
        mtime_ns=mtime_ns,
        file_size=file_size,
        external_signatures=external_signatures,
        jobs_by_chunk=jobs_by_chunk,
        preload_detail_positions=preload_detail_positions,
        requested_edge=requested_edge,
        views=views,
    )

    _decode_chunk_view_misses(
        region=region,
        misses=misses,
        path_key=path_key,
        mtime_ns=mtime_ns,
        file_size=file_size,
        views=views,
        cache_epoch=cache_epoch,
        cancel_check=cancel_check,
        decode_workers=decode_workers,
        failed_chunks=failed_chunks,
        external_signatures=external_signatures,
        parallel_runner=parallel_runner,
        progress_callback=progress_callback,
        progress_batch_chunks=progress_batch_chunks,
    )
    return views


def _decode_chunk_view_misses(
    *,
    region: RegionFile,
    misses: List[Tuple[int, int, List[Tuple[int, int]]]],
    path_key: str,
    mtime_ns: int,
    file_size: int,
    views: ChunkViews,
    cache_epoch: int,
    cancel_check: Optional[Callable[[], bool]],
    decode_workers: Optional[int],
    failed_chunks: Optional[Set[Tuple[int, int]]],
    external_signatures: Dict[Tuple[int, int], str],
    parallel_runner: Optional[ParallelRunner] = None,
    progress_callback: Optional[ChunkProgressCallback] = None,
    progress_batch_chunks: int = DEFAULT_PROGRESS_BATCH_CHUNKS,
) -> None:
    requested_workers = (
        _DECODE_WORKERS if decode_workers is None else max(1, int(decode_workers))
    )
    workers = min(_DECODE_WORKERS, requested_workers)
    _decode_misses_with_runner(
        region,
        misses,
        path_key,
        mtime_ns,
        file_size,
        views,
        cache_epoch,
        workers=workers,
        cancel_check=cancel_check,
        failed_chunks=failed_chunks,
        external_signatures=external_signatures,
        parallel_runner=parallel_runner,
        progress_callback=progress_callback,
        progress_batch_chunks=progress_batch_chunks,
    )


def _jobs_by_chunk(
    jobs: Optional[List[SampleJob]],
) -> Dict[Tuple[int, int], List[Tuple[int, int]]]:
    jobs_by_chunk: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    if jobs is None:
        return jobs_by_chunk
    for _, _, chunk_x, chunk_z, local_x, local_z in jobs:
        jobs_by_chunk.setdefault((chunk_x, chunk_z), []).append(
            (local_x, local_z)
        )
    return jobs_by_chunk


def _requested_edge(jobs: Optional[List[SampleJob]]) -> int:
    if not jobs:
        return 0
    return max(max(int(job[0]), int(job[1])) + 1 for job in jobs)


def _collect_chunk_cache_misses(
    *,
    needed: Set[Tuple[int, int]],
    path_key: str,
    mtime_ns: int,
    file_size: int,
    external_signatures: Dict[Tuple[int, int], str],
    jobs_by_chunk: Dict[Tuple[int, int], List[Tuple[int, int]]],
    preload_detail_positions: bool,
    requested_edge: int,
    views: ChunkViews,
) -> List[Tuple[int, int, List[Tuple[int, int]]]]:
    misses: List[Tuple[int, int, List[Tuple[int, int]]]] = []
    for chunk_x, chunk_z in sorted(needed):
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
            continue
        if preload_detail_positions and requested_edge < 256:
            all_lod_positions = _FOCUSED_LOD_SAMPLES.get(
                (chunk_x, chunk_z),
                requested,
            )
        else:
            all_lod_positions = requested
        missing_positions = [
            position for position in all_lod_positions if position not in view
        ]
        misses.append((chunk_x, chunk_z, missing_positions))
    return misses


def _run_chunk_decode_batch(
    runner: ParallelRunner,
    region: RegionFile,
    batch: List[Tuple[int, int, List[Tuple[int, int]]]],
    *,
    workers: int,
    cancel_check: Optional[Callable[[], bool]],
) -> Optional[
    List[Tuple[Tuple[int, int], SurfaceSamples] | BaseException]
]:
    """Decode one bounded batch through the injected parallelism port."""
    def decode(
        miss: Tuple[int, int, List[Tuple[int, int]]],
    ) -> Tuple[Tuple[int, int], SurfaceSamples]:
        chunk_x, chunk_z, samples = miss
        return _decode_one(region, chunk_x, chunk_z, samples)

    try:
        return runner.map(
            "mca.surface.decode-chunks",
            batch,
            decode,
            max_workers=workers,
            cancel_check=cancel_check,
        )
    except ParallelCancelledError:
        return None


def _decode_misses_with_runner(
    region: RegionFile,
    misses: List[Tuple[int, int, List[Tuple[int, int]]]],
    path_key: str,
    mtime_ns: int,
    file_size: int,
    views: Dict[Tuple[int, int], Optional[Any]],
    cache_epoch: int,
    *,
    workers: int,
    cancel_check: Optional[Callable[[], bool]] = None,
    failed_chunks: Optional[Set[Tuple[int, int]]] = None,
    external_signatures: Optional[Dict[Tuple[int, int], str]] = None,
    parallel_runner: Optional[ParallelRunner] = None,
    progress_callback: Optional[ChunkProgressCallback] = None,
    progress_batch_chunks: int = DEFAULT_PROGRESS_BATCH_CHUNKS,
) -> None:
    external_signatures = external_signatures or {}
    workers = clamp_workers(workers, item_count=len(misses))
    runner = parallel_runner if parallel_runner is not None else SerialParallelRunner()

    batch_size = len(misses) or 1
    if progress_callback is not None:
        batch_size = max(1, int(progress_batch_chunks))
    refined_chunks = set(views)
    processed = len(views)
    total = processed + len(misses)
    for offset in range(0, len(misses), batch_size):
        batch = misses[offset:offset + batch_size]
        outcomes = _run_chunk_decode_batch(
            runner,
            region,
            batch,
            workers=workers,
            cancel_check=cancel_check,
        )
        if outcomes is None:
            return
        if len(outcomes) != len(batch):
            raise RuntimeError(
                "MCA 解码并行端口返回数量不一致: "
                f"expected={len(batch)}, actual={len(outcomes)}"
            )
        for miss, outcome in zip(batch, outcomes):
            if isinstance(outcome, BaseException):
                if not isinstance(outcome, Exception):
                    raise outcome
                if failed_chunks is not None:
                    failed_chunks.add((miss[0], miss[1]))
                continue
            key, sampled = outcome
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
            refined_chunks.add(key)
        processed += len(batch)
        if (
            progress_callback is not None
            and processed < total
            and not (cancel_check is not None and cancel_check())
        ):
            progress_callback(views, set(refined_chunks), processed, total)


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
) -> List[List[SurfaceValue]]:
    grid: List[List[SurfaceValue]] = [
        [None for _ in range(edge)] for _ in range(edge)
    ]
    for column, row, chunk_x, chunk_z, local_x, local_z in jobs:
        view = views.get((chunk_x, chunk_z))
        if view is None:
            continue
        try:
            sample = getattr(view, "surface_sample", None)
            if callable(sample):
                grid[row][column] = cast(
                    SurfaceValue,
                    sample(local_x, local_z),
                )
            else:
                grid[row][column] = view.surface_block_id(local_x, local_z)
        except (OSError, ValueError, TypeError, RuntimeError, KeyError, AttributeError, IndexError):
            grid[row][column] = None
        except Exception:
            grid[row][column] = None
    return grid


def _resize_nearest(
    source: Sequence[Sequence[SurfaceValue]],
    target_size: int,
) -> List[List[SurfaceValue]]:
    source_size = len(source)
    if source_size == target_size:
        return [list(row) for row in source]
    target: List[List[SurfaceValue]] = [
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


def _aggregate_surface_values(values: Sequence[SurfaceValue]) -> SurfaceValue:
    samples = [_surface_parts(value) for value in values]
    named = [sample for sample in samples if sample[0] and not is_air_name(sample[0])]
    pool = named or [sample for sample in samples if sample[0]] or samples
    names: Dict[str, int] = {}
    for name, _height, _depth, _biome, _overlay, _alpha in pool:
        if name:
            names[name] = names.get(name, 0) + 1
    name = max(names, key=lambda key: names[key]) if names else None
    heights = [sample[1] for sample in pool if sample[1] is not None]
    depths = [sample[2] for sample in pool]
    height = int(round(sum(heights) / len(heights))) if heights else None
    depth = int(round(sum(depths) / len(depths))) if depths else 0
    biome_names: Dict[str, int] = {}
    for _name, _height, _depth, biome, _overlay, _alpha in pool:
        if biome:
            biome_names[biome] = biome_names.get(biome, 0) + 1
    biome = max(biome_names, key=lambda key: biome_names[key]) if biome_names else None
    overlay_names: Dict[str, int] = {}
    overlay_alphas: List[float] = []
    for _name, _height, _depth, _biome, overlay, alpha in pool:
        if overlay:
            overlay_names[overlay] = overlay_names.get(overlay, 0) + 1
            overlay_alphas.append(alpha)
    overlay = max(overlay_names, key=lambda key: overlay_names[key]) if overlay_names else None
    alpha = sum(overlay_alphas) / len(overlay_alphas) if overlay_alphas else 0.0
    include_biome = any(
        isinstance(value, tuple) and len(value) >= 4
        for value in values
    )
    include_overlay = any(
        isinstance(value, tuple) and len(value) >= 5
        for value in values
    )
    return _surface_value(
        name,
        height,
        depth,
        biome,
        overlay,
        alpha,
        include_biome=include_biome,
        include_overlay=include_overlay,
    )


def _downsample_surface_values(
    source: Sequence[Sequence[SurfaceValue]],
    target_size: int,
) -> List[List[SurfaceValue]]:
    """Reduce a 2x oversampled grid while retaining material boundaries."""
    if len(source) <= target_size:
        return [list(row) for row in source]
    factor = len(source) / max(1, target_size)
    target: List[List[SurfaceValue]] = []
    for z in range(target_size):
        row: List[SurfaceValue] = []
        z0 = int(z * factor)
        z1 = max(z0 + 1, int((z + 1) * factor))
        for x in range(target_size):
            x0 = int(x * factor)
            x1 = max(x0 + 1, int((x + 1) * factor))
            values = [
                source[yy][xx]
                for yy in range(z0, min(z1, len(source)))
                for xx in range(x0, min(x1, len(source[yy])))
            ]
            row.append(_aggregate_surface_values(values))
        target.append(row)
    return target


def _resize_surface_values(
    coarse: Sequence[Sequence[SurfaceValue]],
    sampling_edge: int,
    tile_size: int,
) -> List[List[SurfaceValue]]:
    """Resize one sampled grid using the production LOD rules."""
    if sampling_edge > tile_size:
        return _downsample_surface_values(coarse, tile_size)
    return _resize_nearest(coarse, tile_size)


def _build_surface_progress_callback(
    callback: Optional[SurfaceProgressCallback],
    *,
    sampling_edge: int,
    tile_size: int,
    jobs: List[SampleJob],
) -> Optional[ChunkProgressCallback]:
    """Adapt decoded chunk batches to target-sized surface sample grids."""
    if callback is None:
        return None

    def publish(
        views: ChunkViews,
        refined_chunks: Set[Tuple[int, int]],
        processed: int,
        total: int,
    ) -> None:
        coarse = _sample_coarse_grid(sampling_edge, jobs, views)
        callback(
            _resize_surface_values(coarse, sampling_edge, tile_size),
            refined_chunks,
            processed,
            total,
        )

    return publish


def sample_region_surface_samples(
    region_file: PathLike,
    tile_size: int = 64,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    decode_workers: Optional[int] = None,
    failed_chunks: Optional[Set[Tuple[int, int]]] = None,
    parallel_runner: Optional[ParallelRunner] = None,
    progress_callback: Optional[SurfaceProgressCallback] = None,
    progress_batch_chunks: int = DEFAULT_PROGRESS_BATCH_CHUNKS,
) -> Optional[List[List[SurfaceValue]]]:
    """Return visible block, height and water depth for each map pixel.

    The decoder is serial by default because map tile callers commonly run
    inside an application CPU task.  Callers that own a separate capacity
    budget may inject a ``ParallelRunner`` explicitly.

    Args:
        region_file: Source MCA path.
        tile_size: Requested sample edge length.
        cancel_check: Cooperative cancellation probe.
        decode_workers: Worker hint for the injected runner.
        failed_chunks: Optional sink for chunks that could not be decoded.
        parallel_runner: Explicit bounded parallelism port.
        progress_callback: Receives non-final partial sample grids and coverage.
        progress_batch_chunks: Cache misses handled between progress callbacks.

    Returns:
        Final surface sample grid, or ``None`` when cancelled or unreadable.
    """
    tile_size = max(8, min(512, int(tile_size)))
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
        sampling_edge = edge * 2 if 32 <= edge < 256 else edge
        jobs = _build_sample_jobs(sampling_edge)
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
            parallel_runner=parallel_runner,
            progress_callback=_build_surface_progress_callback(
                progress_callback,
                sampling_edge=sampling_edge,
                tile_size=tile_size,
                jobs=jobs,
            ),
            progress_batch_chunks=progress_batch_chunks,
        )
        if cancel_check is not None and cancel_check():
            return None
        coarse = _sample_coarse_grid(sampling_edge, jobs, chunk_views)
        return _resize_surface_values(coarse, sampling_edge, tile_size)
    finally:
        rf.close()


def _coerce_surface_sample(value: SurfaceValue) -> SurfaceValue:
    if not isinstance(value, tuple):
        return value, None, 0
    name, height, water_depth, biome, overlay, alpha = _surface_parts(value)
    return _surface_value(
        name,
        height,
        water_depth,
        biome,
        overlay,
        alpha,
        include_biome=len(value) >= 4,
        include_overlay=len(value) >= 5,
    )


def _relief_factor_from_neighbors(
    height: Optional[int],
    north: Optional[int],
    west: Optional[int],
    north_west: Optional[int],
    name: Optional[str],
    water_depth: int,
    spacing_scale: float,
) -> float:
    """Shade one sample when neighboring heights are already available."""
    if height is None:
        return 1.0
    north = height if north is None else north
    west = height if west is None else west
    north_west = height if north_west is None else north_west
    slope = spacing_scale * (
        (height - north) * 0.055
        + (height - west) * 0.040
        + (height - north_west) * 0.025
    )
    elevation = max(-0.06, min(0.10, (height - 64) * 0.0007))
    factor = 1.0 + slope + elevation
    if name and "water" in name.lower():
        # Deeper water is visibly darker, while shallow shore pixels retain
        # the sand/terrain contrast underneath them.
        factor *= 1.0 - min(8, max(0, water_depth)) * 0.030
    return max(0.72, min(1.28, factor))


def _height_from_row(
    heights: Optional[Sequence[Optional[int]]],
    index: int,
    fallback: int,
) -> int:
    """Read a clamped neighboring height without normalizing its full sample."""
    if not heights:
        return fallback
    index = min(max(0, index), len(heights) - 1)
    height = heights[index]
    return fallback if height is None else height


def _shade_color(color: Color, factor: float) -> Color:
    return (
        max(0, min(255, int(color[0] * factor))),
        max(0, min(255, int(color[1] * factor))),
        max(0, min(255, int(color[2] * factor))),
    )


def _blend_surface_color(bottom: Color, overlay: Color, alpha: float) -> Color:
    """Alpha-composite a transparent stratum while clamping channel values."""
    amount = max(0.0, min(1.0, float(alpha)))
    channels = tuple(
        max(
            0,
            min(
                255,
                int(round(bottom[index] * (1.0 - amount) + overlay[index] * amount)),
            ),
        )
        for index in range(3)
    )
    return cast(Color, channels)


def _resolve_surface_color(
    name: str,
    biome: Optional[str],
    color_for_block: Optional[ColorFunc],
    color_for_surface: Optional[SurfaceColorFunc],
) -> Color:
    try:
        if color_for_surface is not None:
            return color_for_surface(name, biome)
        if color_for_block is not None:
            return color_for_block(name)
    except (TypeError, ValueError, AttributeError, KeyError):
        return DEFAULT_UNKNOWN
    except Exception:
        return DEFAULT_UNKNOWN
    return DEFAULT_UNKNOWN


def sample_region_surface_colors(
    region_file: PathLike,
    tile_size: int = 64,
    color_for_block: Optional[ColorFunc] = None,
    *,
    color_for_surface: Optional[SurfaceColorFunc] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    decode_workers: Optional[int] = None,
    failed_chunks: Optional[Set[Tuple[int, int]]] = None,
    parallel_runner: Optional[ParallelRunner] = None,
    progress_callback: Optional[SurfaceColorProgressCallback] = None,
    progress_batch_chunks: int = DEFAULT_PROGRESS_BATCH_CHUNKS,
) -> Optional[List[List[Color]]]:
    """Return material colors with optional non-final progress grids.

    Args:
        region_file: Source MCA path.
        tile_size: Requested output edge length.
        color_for_block: Optional block material color resolver.
        color_for_surface: Optional biome-aware material resolver.
        cancel_check: Cooperative cancellation probe.
        decode_workers: Worker hint for the injected runner.
        failed_chunks: Optional sink for chunks that could not be decoded.
        parallel_runner: Explicit bounded parallelism port.
        progress_callback: Receives colored non-final grids and coverage.
        progress_batch_chunks: Cache misses handled between progress callbacks.

    Returns:
        Final color grid, or ``None`` when cancelled or unreadable.
    """
    samples = sample_region_surface_samples(
        region_file,
        tile_size=tile_size,
        cancel_check=cancel_check,
        decode_workers=decode_workers,
        failed_chunks=failed_chunks,
        parallel_runner=parallel_runner,
        progress_callback=_build_color_progress_callback(
            progress_callback,
            color_for_block=color_for_block,
            color_for_surface=color_for_surface,
            cancel_check=cancel_check,
        ),
        progress_batch_chunks=progress_batch_chunks,
    )
    if samples is None:
        return None
    return _colorize_surface_grid(
        samples,
        color_for_block=color_for_block,
        color_for_surface=color_for_surface,
        cancel_check=cancel_check,
    )


def _build_color_progress_callback(
    callback: Optional[SurfaceColorProgressCallback],
    *,
    color_for_block: Optional[ColorFunc],
    color_for_surface: Optional[SurfaceColorFunc],
    cancel_check: Optional[Callable[[], bool]],
) -> Optional[SurfaceProgressCallback]:
    """Adapt sample progress to biome-aware color grids."""
    if callback is None:
        return None

    def publish(
        partial: List[List[SurfaceValue]],
        refined_chunks: Set[Tuple[int, int]],
        processed: int,
        total: int,
    ) -> None:
        colors = _colorize_surface_grid(
            partial,
            color_for_block=color_for_block,
            color_for_surface=color_for_surface,
            cancel_check=cancel_check,
        )
        if colors is not None:
            callback(colors, refined_chunks, processed, total)

    return publish


def _colorize_surface_grid(
    samples: List[List[SurfaceValue]],
    *,
    color_for_block: Optional[ColorFunc],
    color_for_surface: Optional[SurfaceColorFunc],
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Optional[List[List[Color]]]:
    """Apply material and relief colors to one complete or partial grid."""
    colors: List[List[Color]] = []
    edge = _coarse_edge(len(samples))
    sample_spacing = max(1.0, 512.0 / max(1, edge))
    spacing_scale = min(1.0, 2.0 / sample_spacing)
    previous_heights: Optional[List[Optional[int]]] = None
    processed = 0
    for row in samples:
        color_row, current_heights = _colorize_surface_row(
            row,
            previous_heights=previous_heights,
            spacing_scale=spacing_scale,
            color_for_block=color_for_block,
            color_for_surface=color_for_surface,
        )
        colors.append(color_row)
        previous_heights = current_heights
        processed += len(row)
        if (
            cancel_check is not None
            and processed % 4096 == 0
            and cancel_check()
        ):
            return None
    return colors


def _colorize_surface_row(
    row: List[Any],
    *,
    previous_heights: Optional[List[Optional[int]]],
    spacing_scale: float,
    color_for_block: Optional[ColorFunc],
    color_for_surface: Optional[SurfaceColorFunc],
) -> tuple[List[Color], List[Optional[int]]]:
    color_row: List[Color] = []
    current_heights: List[Optional[int]] = []
    north_source = (
        current_heights if previous_heights is None else previous_heights
    )
    for x, value in enumerate(row):
        parts = _surface_parts(value)
        name, height, water_depth, biome, overlay, overlay_alpha = parts
        current_heights.append(height)
        if name is None:
            base = DEFAULT_EMPTY
        elif is_air_name(name):
            base = DEFAULT_WATERISH
        else:
            base = _resolve_surface_color(
                name,
                biome,
                color_for_block,
                color_for_surface,
            )
        if overlay and overlay_alpha > 0.0:
            overlay_color = _resolve_surface_color(
                overlay,
                biome,
                color_for_block,
                color_for_surface,
            )
            base = _blend_surface_color(base, overlay_color, overlay_alpha)
        factor = _relief_factor_from_neighbors(
            height,
            _height_from_row(north_source, x, height or 0),
            _height_from_row(current_heights, x - 1, height or 0),
            _height_from_row(north_source, x - 1, height or 0),
            name,
            water_depth,
            spacing_scale,
        )
        color_row.append(_shade_color(base, factor))
    return color_row, current_heights


def clear_chunk_decode_cache() -> None:
    """Drop process-level decoded chunk cache (tests / memory pressure)."""
    global _CHUNK_LRU_BYTES, _CHUNK_LRU_EPOCH
    global _CHUNK_LRU_HITS, _CHUNK_LRU_MISSES, _CHUNK_LRU_EVICTIONS
    with _CHUNK_LRU_LOCK:
        _CHUNK_LRU.clear()
        _CHUNK_LRU_BYTES = 0
        _CHUNK_LRU_EPOCH += 1
        _CHUNK_LRU_HITS = 0
        _CHUNK_LRU_MISSES = 0
        _CHUNK_LRU_EVICTIONS = 0


def invalidate_chunk_decode_cache_for_world(world_path: PathLike) -> int:
    """删除来源路径属于指定世界的区块解码缓存。

    解码缓存属于进程级，而世界事务会在同一路径发布新目录。这里只删除匹配键，
    既保留其他已打开世界的热数据，也推进世代以阻止旧世界的在途结果重新写回。

    Args:
        world_path: 已规范化或原始的世界根路径。

    Returns:
        删除的缓存条目数。
    """
    global _CHUNK_LRU_BYTES, _CHUNK_LRU_EPOCH
    root = os.path.normcase(os.path.abspath(os.fspath(world_path)))
    removed = 0
    with _CHUNK_LRU_LOCK:
        for key in tuple(_CHUNK_LRU):
            source = os.path.normcase(os.path.abspath(key[0]))
            try:
                belongs_to_world = os.path.commonpath((source, root)) == root
            except ValueError:
                belongs_to_world = False
            if not belongs_to_world:
                continue
            samples = _CHUNK_LRU.pop(key)
            _CHUNK_LRU_BYTES -= _estimate_surface_samples_bytes(samples)
            removed += 1
        # 即使没有已缓存条目，也可能有旧世界解码仍在运行；推进世代可阻止它在
        # 事务发布后重新写回。
        _CHUNK_LRU_EPOCH += 1
    return removed


def chunk_decode_cache_size() -> int:
    """Number of entries in the process-level chunk decode LRU."""
    with _CHUNK_LRU_LOCK:
        return len(_CHUNK_LRU)


def chunk_decode_cache_bytes() -> int:
    """返回紧凑地表采样 LRU 的估算字节数。"""
    with _CHUNK_LRU_LOCK:
        return _CHUNK_LRU_BYTES


def chunk_decode_cache_hits() -> int:
    """返回上次清理后的缓存命中数。"""
    with _CHUNK_LRU_LOCK:
        return _CHUNK_LRU_HITS


def chunk_decode_cache_misses() -> int:
    """返回上次清理后的缓存未命中数。"""
    with _CHUNK_LRU_LOCK:
        return _CHUNK_LRU_MISSES


def chunk_decode_cache_evictions() -> int:
    """返回上次清理后因预算触发的淘汰数。"""
    with _CHUNK_LRU_LOCK:
        return _CHUNK_LRU_EVICTIONS
