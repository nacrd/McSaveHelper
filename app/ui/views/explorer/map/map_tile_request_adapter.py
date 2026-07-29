"""地图瓦片请求适配：视口 → 有序区域请求（无 Flet）。

将 ``core.mca.map_tiles`` 规划结果整理为服务可消费的坐标序列，
对应设计中 mca_map_view 的「瓦片请求适配」层。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

from core.mca.map_tiles import prioritize_regions


RegionCoord = Tuple[int, int]


@dataclass(frozen=True)
class TileRequestBatch:
    """一次视口刷新的瓦片请求批次。"""

    coords: tuple[RegionCoord, ...]
    preferred_tile_size: int


def adapt_viewport_tile_requests(
    visible_coords: Sequence[RegionCoord],
    *,
    center: RegionCoord,
    preferred_tile_size: int,
    limit: int = 64,
) -> TileRequestBatch:
    """对可见区域坐标做优先级排序并截断。

    Args:
        visible_coords: 当前视口覆盖的区域坐标。
        center: 视口中心区域坐标。
        preferred_tile_size: 期望瓦片边长。
        limit: 单次提交上限。
    """
    ordered = prioritize_regions(list(visible_coords), center=center)
    capped = tuple(ordered[: max(1, int(limit))])
    return TileRequestBatch(
        coords=capped,
        preferred_tile_size=max(1, int(preferred_tile_size)),
    )


def iter_request_coords(batch: TileRequestBatch) -> Iterable[RegionCoord]:
    """迭代批次坐标。"""
    return batch.coords


__all__ = [
    "RegionCoord",
    "TileRequestBatch",
    "adapt_viewport_tile_requests",
    "iter_request_coords",
]
