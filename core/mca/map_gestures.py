"""Pure gesture decision helpers for the MCA map."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from core.mca.map_navigation import McaMapNavigator, SelectionNotification
from core.mca.viewport import ChunkCoord, MapViewLevel, RegionCoord


@dataclass(frozen=True)
class MapGestureResult:
    """手势决策结果：选择通知、相机聚焦与是否重绘。

    视图层只消费此结构，避免手势分支与 Flet 事件混在一起。
    """

    notification: Optional[SelectionNotification] = None
    focus_region: Optional[RegionCoord] = None
    focus_chunk: Optional[ChunkCoord] = None
    focus_fill: float = 0.72
    set_level: Optional[MapViewLevel] = None
    request_detail: Optional[RegionCoord] = None
    fit_to_view: bool = False
    fit_padding: float = 0.82
    rebuild: bool = False


def decide_tap(
    *,
    navigator: McaMapNavigator,
    region_sizes: Mapping[RegionCoord, int],
    view_level: MapViewLevel,
    scale: float,
    scale_block: float,
    hit_chunk: Optional[ChunkCoord],
    hit_region: Optional[RegionCoord],
) -> Optional[MapGestureResult]:
    """单击：在区块层选区块，否则选区域并建议聚焦。

    Returns:
        决策结果；未命中有效区域时为 None。
    """
    if hit_chunk is not None and view_level in {"chunk", "block"}:
        level: MapViewLevel = "block" if view_level == "block" else "chunk"
        notification = navigator.select_chunk(hit_chunk, region_sizes, level)
        focus_chunk = None
        set_level: Optional[MapViewLevel] = None
        if view_level == "block" or scale >= scale_block * 0.85:
            focus_chunk = hit_chunk
            set_level = "block"
        return MapGestureResult(
            notification=notification,
            focus_chunk=focus_chunk,
            focus_fill=0.78,
            set_level=set_level,
            rebuild=True,
        )

    if hit_region is None or hit_region not in region_sizes:
        return None

    notification = navigator.select_region(hit_region, region_sizes)
    return MapGestureResult(
        notification=notification,
        focus_region=hit_region,
        focus_fill=0.72,
        set_level="region",
    )


def decide_double_tap(
    *,
    navigator: McaMapNavigator,
    region_sizes: Mapping[RegionCoord, int],
    view_level: MapViewLevel,
    hit_chunk: Optional[ChunkCoord],
    hit_region: Optional[RegionCoord],
    selected_region: Optional[RegionCoord],
) -> Optional[MapGestureResult]:
    """双击：深入一层（区块→方块，或区域→区块）。"""
    if hit_chunk is not None and view_level in {"chunk", "block"}:
        notification = navigator.select_chunk(hit_chunk, region_sizes, "block")
        return MapGestureResult(
            notification=notification,
            focus_chunk=hit_chunk,
            focus_fill=0.85,
            set_level="block",
        )

    region = hit_region if hit_region is not None else selected_region
    if region is None or region not in region_sizes:
        return None

    notification = navigator.select_region(region, region_sizes, "chunk")
    return MapGestureResult(
        notification=notification,
        focus_region=region,
        focus_fill=0.92,
        set_level="chunk",
        request_detail=region,
    )


def decide_secondary_tap(
    *,
    navigator: McaMapNavigator,
    region_sizes: Mapping[RegionCoord, int],
    previous_level: MapViewLevel,
    selected_region: Optional[RegionCoord],
) -> MapGestureResult:
    """右键/次要点击：语义层级后退一级并调整相机。"""
    notification = navigator.step_back(region_sizes)
    if previous_level == "block":
        return MapGestureResult(
            notification=notification,
            focus_region=selected_region,
            focus_fill=0.88,
        )
    if previous_level == "chunk":
        if selected_region is not None:
            return MapGestureResult(
                notification=notification,
                focus_region=selected_region,
                focus_fill=0.55,
            )
        return MapGestureResult(
            notification=notification,
            fit_to_view=True,
            fit_padding=0.82,
        )
    return MapGestureResult(
        notification=notification,
        fit_to_view=True,
        fit_padding=0.82,
    )
