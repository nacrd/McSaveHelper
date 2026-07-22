"""地图交互/显示标志的不可变快照（无 Flet）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MapInteractionSnapshot:
    """从 McaMapView 抽出的交互与显示层标志。"""

    show_coordinates: bool
    show_grid: bool
    show_empty_regions: bool
    display_mode: str
    detail_level: str
    use_topview: bool
    scale: float
    center_x: float
    center_z: float


def snapshot_map_interaction(
    *,
    show_coordinates: bool,
    show_grid: bool,
    show_empty_regions: bool,
    display_mode: str,
    detail_level: str,
    use_topview: bool,
    scale: float,
    center_x: float,
    center_z: float,
) -> MapInteractionSnapshot:
    """构造交互快照。"""
    return MapInteractionSnapshot(
        show_coordinates=bool(show_coordinates),
        show_grid=bool(show_grid),
        show_empty_regions=bool(show_empty_regions),
        display_mode=str(display_mode),
        detail_level=str(detail_level),
        use_topview=bool(use_topview),
        scale=float(scale),
        center_x=float(center_x),
        center_z=float(center_z),
    )


def snapshot_from_map_view(view: Any) -> MapInteractionSnapshot:
    """从地图视图对象抽取当前交互状态。"""
    viewport = getattr(view, "_viewport", None)
    scale = float(getattr(viewport, "scale", 1.0) or 1.0)
    center_x = float(getattr(viewport, "center_x", 0.0) or 0.0)
    center_z = float(getattr(viewport, "center_z", 0.0) or 0.0)
    return snapshot_map_interaction(
        show_coordinates=bool(getattr(view, "_show_coordinates", False)),
        show_grid=bool(getattr(view, "_show_grid", False)),
        show_empty_regions=bool(getattr(view, "_show_empty_regions", False)),
        display_mode=str(getattr(view, "_display_mode", "topview")),
        detail_level=str(getattr(view, "_detail_level", "region")),
        use_topview=bool(getattr(view, "_use_topview", True)),
        scale=scale,
        center_x=center_x,
        center_z=center_z,
    )


__all__ = [
    "MapInteractionSnapshot",
    "snapshot_from_map_view",
    "snapshot_map_interaction",
]
