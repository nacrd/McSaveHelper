"""地图视口投影：从交互状态推导重建/瓦片请求意图。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.mca.map_models import MapViewState, MapViewStateSnapshot


MapStateLike = MapViewState | MapViewStateSnapshot


@dataclass(frozen=True)
class MapViewportSnapshot:
    """一次 Flet 投影可用的只读视口快照。"""

    generation: int
    dimension_id: str
    style: str
    center_x: float
    center_z: float
    scale: float
    show_markers: bool
    show_coordinates: bool
    show_empty_regions: bool


@dataclass(frozen=True)
class MapRebuildDecision:
    """是否需要因状态变化触发画布/瓦片重建。"""

    should_rebuild: bool
    reason: str
    snapshot: MapViewportSnapshot


def snapshot_map_view_state(state: MapStateLike) -> MapViewportSnapshot:
    """提取 MapViewState 的不可变投影字段。"""
    layers = state.layers
    return MapViewportSnapshot(
        generation=int(state.generation),
        dimension_id=str(state.dimension_id),
        style=str(state.style),
        center_x=float(state.center_x),
        center_z=float(state.center_z),
        scale=float(state.scale),
        show_markers=bool(layers.show_markers),
        show_coordinates=bool(layers.show_coordinates),
        show_empty_regions=bool(layers.show_empty_regions),
    )


def decide_map_rebuild(
    previous: Optional[MapViewportSnapshot],
    current: MapStateLike,
) -> MapRebuildDecision:
    """比较前后视口快照，决定是否需要重建。

    Args:
        previous: 上一帧已投影快照；None 表示首次。
        current: 控制器当前可变状态。
    """
    snapshot = snapshot_map_view_state(current)
    if previous is None:
        return MapRebuildDecision(True, "initial", snapshot)
    if previous.generation != snapshot.generation:
        return MapRebuildDecision(True, "generation", snapshot)
    if previous.dimension_id != snapshot.dimension_id:
        return MapRebuildDecision(True, "dimension", snapshot)
    if previous.style != snapshot.style:
        return MapRebuildDecision(True, "style", snapshot)
    if (
        previous.center_x != snapshot.center_x
        or previous.center_z != snapshot.center_z
        or previous.scale != snapshot.scale
    ):
        return MapRebuildDecision(True, "camera", snapshot)
    if (
        previous.show_markers != snapshot.show_markers
        or previous.show_coordinates != snapshot.show_coordinates
        or previous.show_empty_regions != snapshot.show_empty_regions
    ):
        return MapRebuildDecision(True, "layers", snapshot)
    return MapRebuildDecision(False, "unchanged", snapshot)


__all__ = [
    "MapRebuildDecision",
    "MapViewportSnapshot",
    "decide_map_rebuild",
    "snapshot_map_view_state",
]
