"""可见区域瓦片的 LOD 与调度规划。

地图视图只应请求当前视口真正需要的瓦片。这个模块不接触 Flet 或线程，
把屏幕像素需求转换成稳定的瓦片大小，并以视口中心排序坐标，供服务层
使用有界队列异步渲染。实现借鉴 Xaero/JourneyMap 的可见性 gate + LOD
策略，但保留本项目以 MCA 区域为叶节点的坐标模型。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

RegionCoord = Tuple[int, int]

# The ordinary overview remains capped at 256.  The map surface opts into the
# 512 leaf LOD only when one region is large enough on screen to justify true
# one-block-per-pixel sampling.
DEFAULT_TILE_LADDER: tuple[int, ...] = (16, 32, 64, 128, 256)
HIGH_DETAIL_TILE_LADDER: tuple[int, ...] = (*DEFAULT_TILE_LADDER, 512)


@dataclass(frozen=True)
class MapTileRequest:
    """One immutable visible-tile request."""

    coord: RegionCoord
    tile_size: int
    priority: int


def choose_tile_size(
    screen_tile_pixels: float,
    ladder: Sequence[int] = DEFAULT_TILE_LADDER,
) -> int:
    """Choose the smallest cached tile that can cover a screen tile.

    ``screen_tile_pixels`` is the rendered width of one 512-block MCA region.
    A small one-step oversampling avoids blurry tiles while preventing a large
    world overview from decoding 256x256 images for every region.
    """
    values = tuple(sorted({max(8, int(value)) for value in ladder}))
    if not values:
        raise ValueError("瓦片 LOD 梯度不能为空")
    target = max(1.0, float(screen_tile_pixels))
    for value in values:
        if value >= target:
            return value
    return values[-1]


def prioritize_regions(
    coords: Iterable[RegionCoord],
    center: RegionCoord = (0, 0),
) -> list[RegionCoord]:
    """Return unique coordinates ordered from the viewport center outward."""
    unique = {(int(x), int(z)) for x, z in coords}
    cx, cz = int(center[0]), int(center[1])
    return sorted(
        unique,
        key=lambda coord: (
            (coord[0] - cx) ** 2 + (coord[1] - cz) ** 2,
            coord[1],
            coord[0],
        ),
    )


def plan_visible_requests(
    coords: Iterable[RegionCoord],
    *,
    screen_tile_pixels: float,
    center: RegionCoord = (0, 0),
    ladder: Sequence[int] = DEFAULT_TILE_LADDER,
) -> list[MapTileRequest]:
    """Build a stable, center-first request list for a visible region set."""
    tile_size = choose_tile_size(screen_tile_pixels, ladder)
    ordered = prioritize_regions(coords, center)
    return [
        MapTileRequest(coord=coord, tile_size=tile_size, priority=index)
        for index, coord in enumerate(ordered)
    ]
