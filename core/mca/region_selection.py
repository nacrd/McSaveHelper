"""Pure formatting helpers for region-map selection details."""
from __future__ import annotations

from typing import Any, Mapping, Tuple

RegionCoord = Tuple[int, int]


def format_region_selection(
    coord: RegionCoord,
    detail: Mapping[str, Any] | None = None,
) -> str:
    """Format the selected region/chunk/block range shown by Explorer."""
    region_x, region_z = coord
    detail = detail or {}
    level = detail.get("level")
    if level in {"chunk", "block"}:
        chunk = detail.get("chunk_coord")
        block_range = detail.get("block_range", "")
        if chunk:
            title = "区块内" if level == "block" else "区块"
            return (
                f"{title} ({chunk[0]}, {chunk[1]})\n"
                f"所属 r.{region_x}.{region_z}.mca\n"
                f"方块 {block_range}"
            )
        fallback = detail.get("block_range", "")
        return (
            f"区域 ({region_x}, {region_z}) · 区块级\n"
            f"r.{region_x}.{region_z}.mca\n"
            f"方块 {fallback}"
        )

    chunk_x0 = region_x * 32
    chunk_x1 = chunk_x0 + 31
    chunk_z0 = region_z * 32
    chunk_z1 = chunk_z0 + 31
    block_x0 = region_x * 512
    block_x1 = block_x0 + 511
    block_z0 = region_z * 512
    block_z1 = block_z0 + 511
    return (
        f"区域 ({region_x}, {region_z})\n"
        f"r.{region_x}.{region_z}.mca\n"
        f"区块 X{chunk_x0}~{chunk_x1} Z{chunk_z0}~{chunk_z1}\n"
        f"方块 X{block_x0}~{block_x1} Z{block_z0}~{block_z1}"
    )
