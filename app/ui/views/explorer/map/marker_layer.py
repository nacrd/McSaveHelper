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
    """动态标记层的快照、绘制与点击命中。

    图层持有不可共享的 marker 副本与选中 id；不负责持久化或 Flet 事件，
    只向 ``McaMapView`` 暴露 draw/hit-test 边界。
    """

    def __init__(self) -> None:
        """创建空标记层（默认可见）。"""
        self.visible = True
        self._markers: list[MapMarker] = []
        self._bounds: dict[str, tuple[float, float, float, float]] = {}
        self._selected_id: Optional[str] = None

    @property
    def selected_id(self) -> Optional[str]:
        """当前选中标记 id；无选中时为 None。"""
        return self._selected_id

    def toggle(self) -> bool:
        """切换可见性。

        Returns:
            切换后的 ``visible`` 值。
        """
        return self.set_visible(not self.visible)

    def set_visible(self, visible: bool) -> bool:
        """设置图层可见性；隐藏时清空命中矩形缓存。

        Args:
            visible: 是否可见。

        Returns:
            设置后的可见状态。
        """
        self.visible = bool(visible)
        if not self.visible:
            self._bounds.clear()
        return self.visible

    def set_markers(self, markers: List[MapMarker]) -> None:
        """替换标记快照（深拷贝，避免与服务层共享可变状态）。

        若当前选中 id 不在新列表中则清除选中。

        Args:
            markers: 新的标记列表。
        """
        self._markers = [MapMarker.from_dict(marker.to_dict()) for marker in markers]
        if self._selected_id not in {marker.id for marker in self._markers}:
            self._selected_id = None

    def snapshot(self) -> list[MapMarker]:
        """返回当前标记的深拷贝列表。

        Returns:
            与内部状态解耦的 ``MapMarker`` 列表。
        """
        return [MapMarker.from_dict(marker.to_dict()) for marker in self._markers]

    def draw(
        self,
        viewport: McaViewport,
        *,
        width: float,
        height: float,
    ) -> list[cv.Shape]:
        """按视口绘制可见标记并更新命中矩形。

        Args:
            viewport: 当前地图视口。
            width: 画布宽度（像素）。
            height: 画布高度（像素）。

        Returns:
            Flet canvas 形状列表；不可见或无标记时为空。
        """
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
        """命中测试：屏幕坐标落在标记矩形内则选中并返回拷贝。

        Args:
            x: 屏幕 X。
            y: 屏幕 Y。

        Returns:
            命中的标记拷贝；未命中或不可见时为 None。
        """
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
        """设置选中标记；id 不存在时忽略（None 表示清除选中）。

        Args:
            marker_id: 标记 id 或 None。
        """
        if marker_id is None or marker_id in {marker.id for marker in self._markers}:
            self._selected_id = marker_id


__all__ = ["MapMarkerLayer"]
