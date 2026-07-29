"""按 MCA 位置表分析地图中真实存在的区块边界。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from core.mca.errors import McaError
from core.mca.map_models import BLOCKS_PER_CHUNK, CHUNKS_PER_REGION
from core.mca.region_file import RegionFile
from core.region_utils import parse_region_coords


class MapContentScanCancelled(Exception):
    """地图已加载区块扫描被调用方取消。"""


@dataclass(frozen=True)
class LoadedMapContent:
    """真实存在区块的边界及其区域文件。"""

    region_files: Tuple[Path, ...]
    block_bounds: Tuple[int, int, int, int]
    chunk_count: int
    skipped_files: int


def analyze_region_bounds(region_files: List[Path]) -> Dict[str, int]:
    """Return the inclusive region coordinate bounds for valid MCA paths."""
    coords = [
        parsed
        for region_file in region_files
        if (parsed := parse_region_coords(region_file)) is not None
    ]
    if not coords:
        raise ValueError("未找到有效的区域文件坐标")
    return {
        "min_x": min(coord[0] for coord in coords),
        "max_x": max(coord[0] for coord in coords),
        "min_z": min(coord[1] for coord in coords),
        "max_z": max(coord[1] for coord in coords),
    }


def analyze_loaded_map_content(
    region_files: List[Path],
    cancel_check: Optional[Callable[[], bool]] = None,
) -> LoadedMapContent:
    """Inspect MCA location tables and bound only chunks that actually exist.

    Args:
        region_files: Candidate MCA files.
        cancel_check: Optional cooperative cancellation probe.

    Returns:
        Loaded region files, inclusive block bounds, and scan statistics.

    Raises:
        MapContentScanCancelled: The caller requested cancellation.
        ValueError: No populated MCA chunk could be found.
    """
    chunk_bounds: Optional[Tuple[int, int, int, int]] = None
    populated_files: List[Path] = []
    chunk_count = 0
    skipped_files = 0

    for region_file in region_files:
        if cancel_check is not None and cancel_check():
            raise MapContentScanCancelled("地图导出已取消")
        coords = parse_region_coords(region_file)
        if coords is None:
            skipped_files += 1
            continue
        try:
            with RegionFile.open(region_file) as region:
                present_chunks = tuple(region.iter_present_chunks())
        except McaError:
            skipped_files += 1
            continue
        if not present_chunks:
            continue
        populated_files.append(region_file)
        region_x, region_z = coords
        for local_x, local_z in present_chunks:
            chunk_x = region_x * CHUNKS_PER_REGION + local_x
            chunk_z = region_z * CHUNKS_PER_REGION + local_z
            chunk_bounds = _expand_bounds(chunk_bounds, chunk_x, chunk_z)
            chunk_count += 1

    if chunk_bounds is None:
        raise ValueError("所有 MCA 文件均不包含已加载区块")
    min_chunk_x, min_chunk_z, max_chunk_x, max_chunk_z = chunk_bounds
    return LoadedMapContent(
        region_files=tuple(populated_files),
        block_bounds=(
            min_chunk_x * BLOCKS_PER_CHUNK,
            min_chunk_z * BLOCKS_PER_CHUNK,
            (max_chunk_x + 1) * BLOCKS_PER_CHUNK - 1,
            (max_chunk_z + 1) * BLOCKS_PER_CHUNK - 1,
        ),
        chunk_count=chunk_count,
        skipped_files=skipped_files,
    )


def _expand_bounds(
    bounds: Optional[Tuple[int, int, int, int]],
    chunk_x: int,
    chunk_z: int,
) -> Tuple[int, int, int, int]:
    if bounds is None:
        return chunk_x, chunk_z, chunk_x, chunk_z
    min_x, min_z, max_x, max_z = bounds
    return (
        min(min_x, chunk_x),
        min(min_z, chunk_z),
        max(max_x, chunk_x),
        max(max_z, chunk_z),
    )
