"""地图标记覆盖层。

图层拥有不可共享的 marker 快照、每帧命中矩形和选中状态。它不执行持久化，
也不处理 Flet 事件，只向 ``McaMapView`` 暴露 draw/hit-test 边界。
"""
from __future__ import annotations

from typing import List, Optional

try:
    import flet.canvas as cv
except ImportError as exc:  # pragma: no cover
    raise ImportError("flet.canvas is not available in this Flet version") from exc

from app.ui.views.explorer.map import map_shapes
from core.mca.map_models import MapMarker
from core.mca.viewport import McaViewport


class MapMarkerLayer:
    """动态标记层的快照、绘制和点击命中。"""

    def __init__(self) -> None:
        self.visible = True
        self._markers: list[MapMarker] = []
        self._bounds: dict[str, tuple[float, float, float, float]] = {}
        self._selected_id: Optional[str] = None

    @property
    def selected_id(self) -> Optional[str]:
        return self._selected_id

    def toggle(self) -> bool:
        return self.set_visible(not self.visible)

    def set_visible(self, visible: bool) -> bool:
        self.visible = bool(visible)
        if not self.visible:
            self._bounds.clear()
        return self.visible

    def set_markers(self, markers: List[MapMarker]) -> None:
        self._markers = [MapMarker.from_dict(marker.to_dict()) for marker in markers]
        if self._selected_id not in {marker.id for marker in self._markers}:
            self._selected_id = None

    def snapshot(self) -> list[MapMarker]:
        return [MapMarker.from_dict(marker.to_dict()) for marker in self._markers]

    def draw(
        self,
        viewport: McaViewport,
        *,
        width: float,
        height: float,
    ) -> list[cv.Shape]:
        if not self.visible or not self._markers:
            self._bounds.clear()
            return []
        shapes, bounds = map_shapes.marker_overlay(
            self._markers,
            block_to_screen=viewport.block_to_screen,
            width=width,
            height=height,
            scale=viewport.scale,
            selected_id=self._selected_id,
        )
        self._bounds = bounds
        return shapes

    def hit_test(self, x: float, y: float) -> Optional[MapMarker]:
        if not self.visible:
            return None
        for marker in self._markers:
            rect = self._bounds.get(marker.id)
            if rect is None:
                continue
            left, top, width, height = rect
            if left <= x <= left + width and top <= y <= top + height:
                self._selected_id = marker.id
                return MapMarker.from_dict(marker.to_dict())
        return None

    def select(self, marker_id: Optional[str]) -> None:
        if marker_id is None or marker_id in {marker.id for marker in self._markers}:
            self._selected_id = marker_id


__all__ = ["MapMarkerLayer"]
