"""Qt 区域活动热力地图画布（区域级，不含俯视瓦片）。"""
from __future__ import annotations

from typing import Callable, Mapping, Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from core.mca.map_models import BLOCKS_PER_REGION


RegionCoord = tuple[int, int]
RegionSelected = Callable[[Optional[RegionCoord], Optional[int]], None]
CameraChanged = Callable[[float, float, float], None]


class QtRegionMapCanvas(QWidget):
    """用区域文件大小绘制热力格子，并支持平移、缩放与选择。"""

    _MIN_SCALE = 0.01
    _MAX_SCALE = 2.0
    _DEFAULT_SCALE = 0.08

    def __init__(
        self,
        on_region_selected: RegionSelected,
        on_camera_changed: Optional[CameraChanged] = None,
    ) -> None:
        """构建画布。

        Args:
            on_region_selected: ``(coord, size_bytes)`` 选择回调；清空时为 None。
            on_camera_changed: 可选 ``(center_x, center_z, scale)`` 镜头回调。
        """
        super().__init__()
        self._on_region_selected = on_region_selected
        self._on_camera_changed = on_camera_changed
        self._regions: dict[RegionCoord, int] = {}
        self._selected: Optional[RegionCoord] = None
        self._center_x = 0.0
        self._center_z = 0.0
        self._scale = self._DEFAULT_SCALE
        self._dragging = False
        self._dragged = False
        self._last_pos = QPoint()
        self._press_pos = QPoint()
        self._max_size = 1
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(True)

    @property
    def selected_region(self) -> Optional[RegionCoord]:
        """返回当前选中区域坐标。"""
        return self._selected

    @property
    def center_block(self) -> tuple[float, float]:
        """返回当前镜头中心方块坐标。"""
        return self._center_x, self._center_z

    @property
    def scale(self) -> float:
        """返回当前像素/方块缩放。"""
        return self._scale

    def set_regions(self, regions: Mapping[RegionCoord, int]) -> None:
        """替换区域大小数据并尽量保持选择。"""
        self._regions = dict(regions)
        self._max_size = max(self._regions.values(), default=1)
        if self._selected is not None and self._selected not in self._regions:
            self._selected = None
            self._on_region_selected(None, None)
        if self._regions and self._center_x == 0.0 and self._center_z == 0.0:
            self.fit_to_regions()
        self.update()

    def clear(self) -> None:
        """清空区域数据与选择。"""
        self._regions = {}
        self._selected = None
        self._max_size = 1
        self.update()

    def set_camera(self, center_x: float, center_z: float, scale: float) -> None:
        """写入镜头状态（不触发 camera 回调）。"""
        self._center_x = float(center_x)
        self._center_z = float(center_z)
        self._scale = self._clamp_scale(scale)
        self.update()

    def fit_to_regions(self) -> None:
        """把镜头适配到当前区域包围盒。"""
        if not self._regions:
            self._center_x = 0.0
            self._center_z = 0.0
            self._scale = self._DEFAULT_SCALE
            self.update()
            return
        xs = [coord[0] for coord in self._regions]
        zs = [coord[1] for coord in self._regions]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        self._center_x = ((min_x + max_x + 1) / 2.0) * BLOCKS_PER_REGION
        self._center_z = ((min_z + max_z + 1) / 2.0) * BLOCKS_PER_REGION
        width_blocks = max(1, (max_x - min_x + 3)) * BLOCKS_PER_REGION
        height_blocks = max(1, (max_z - min_z + 3)) * BLOCKS_PER_REGION
        view_w = max(1, self.width())
        view_h = max(1, self.height())
        self._scale = self._clamp_scale(
            min(view_w / width_blocks, view_h / height_blocks)
        )
        self._emit_camera()
        self.update()

    def focus_block(
        self,
        block_x: float,
        block_z: float,
        *,
        scale: Optional[float] = None,
    ) -> None:
        """把镜头中心移到指定方块坐标。"""
        self._center_x = float(block_x)
        self._center_z = float(block_z)
        if scale is not None:
            self._scale = self._clamp_scale(scale)
        self._emit_camera()
        self.update()

    def select_region(self, coord: Optional[RegionCoord]) -> None:
        """程序化选择区域并通知回调。"""
        if coord is not None and coord not in self._regions:
            return
        self._selected = coord
        size = None if coord is None else self._regions.get(coord)
        self._on_region_selected(coord, size)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制背景、区域热力格与选中边框。"""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#101810"))
        cell = max(2.0, BLOCKS_PER_REGION * self._scale)
        if cell < 2.0:
            painter.end()
            return
        for coord, size in self._regions.items():
            rect = self._region_screen_rect(coord[0], coord[1], cell)
            if not rect.intersects(self.rect()):
                continue
            painter.fillRect(rect, self._heat_color(size))
            if cell >= 8:
                painter.setPen(QPen(QColor("#1A221C"), 1))
                painter.drawRect(rect)
        if self._selected is not None and self._selected in self._regions:
            rect = self._region_screen_rect(
                self._selected[0], self._selected[1], cell
            )
            painter.setPen(QPen(QColor("#FFD54F"), 2))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._dragged = False
            point = event.position().toPoint()
            self._last_pos = point
            self._press_pos = point
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            current = event.position().toPoint()
            delta = current - self._last_pos
            self._last_pos = current
            if delta.manhattanLength() > 0:
                self._dragged = True
            if self._scale > 0 and (delta.x() or delta.y()):
                self._center_x -= delta.x() / self._scale
                self._center_z -= delta.y() / self._scale
                self._emit_camera()
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            release = event.position().toPoint()
            moved = (release - self._press_pos).manhattanLength()
            if not self._dragged and moved < 6:
                coord = self._region_at(event.position().x(), event.position().y())
                if coord is not None:
                    self.select_region(coord)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1.0 / 1.15
        old_scale = self._scale
        new_scale = self._clamp_scale(old_scale * factor)
        if abs(new_scale - old_scale) < 1e-9:
            return
        # 以光标下的世界点为锚点缩放。
        pos = event.position()
        world_x, world_z = self._screen_to_block(pos.x(), pos.y())
        self._scale = new_scale
        after_x, after_z = self._screen_to_block(pos.x(), pos.y())
        self._center_x += world_x - after_x
        self._center_z += world_z - after_z
        self._emit_camera()
        self.update()

    def _region_screen_rect(self, region_x: int, region_z: int, cell: float):
        from PySide6.QtCore import QRect

        left, top = self._block_to_screen(
            region_x * BLOCKS_PER_REGION,
            region_z * BLOCKS_PER_REGION,
        )
        return QRect(int(left), int(top), max(1, int(cell)), max(1, int(cell)))

    def _block_to_screen(self, block_x: float, block_z: float) -> tuple[float, float]:
        x = (block_x - self._center_x) * self._scale + self.width() / 2.0
        z = (block_z - self._center_z) * self._scale + self.height() / 2.0
        return x, z

    def _screen_to_block(self, screen_x: float, screen_z: float) -> tuple[float, float]:
        block_x = self._center_x + (screen_x - self.width() / 2.0) / self._scale
        block_z = self._center_z + (screen_z - self.height() / 2.0) / self._scale
        return block_x, block_z

    def _region_at(self, screen_x: float, screen_z: float) -> Optional[RegionCoord]:
        block_x, block_z = self._screen_to_block(screen_x, screen_z)
        region_x = int(block_x // BLOCKS_PER_REGION)
        region_z = int(block_z // BLOCKS_PER_REGION)
        # 负坐标 floor 行为：Python // 已是 floor。
        coord = (region_x, region_z)
        if coord in self._regions:
            return coord
        return None

    def _heat_color(self, size: int) -> QColor:
        ratio = 0.0 if self._max_size <= 0 else min(1.0, size / self._max_size)
        # 深绿 -> 亮绿 -> 金黄，表示区域“活跃度”（文件大小）。
        if ratio < 0.5:
            t = ratio * 2.0
            r = int(20 + 40 * t)
            g = int(80 + 100 * t)
            b = int(40 + 20 * t)
        else:
            t = (ratio - 0.5) * 2.0
            r = int(60 + 180 * t)
            g = int(180 - 40 * t)
            b = int(60 - 20 * t)
        return QColor(r, g, b)

    def _emit_camera(self) -> None:
        if self._on_camera_changed is not None:
            self._on_camera_changed(self._center_x, self._center_z, self._scale)

    @staticmethod
    def _clamp_scale(scale: float) -> float:
        return max(
            QtRegionMapCanvas._MIN_SCALE,
            min(QtRegionMapCanvas._MAX_SCALE, float(scale)),
        )


__all__ = ["QtRegionMapCanvas"]
