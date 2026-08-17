"""Qt 区域地图画布：活动热力 + 俯视瓦片。"""
from __future__ import annotations

from collections import OrderedDict
import math
from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from core.mca.map_models import (
    BLOCKS_PER_REGION,
    MapMarker,
)


RegionCoord = tuple[int, int]
RegionSelected = Callable[[Optional[RegionCoord], Optional[int]], None]
CameraChanged = Callable[[float, float, float], None]
MarkerSelected = Callable[[Optional[MapMarker]], None]


class QtRegionMapCanvas(QWidget):
    """用区域文件大小绘制热力格子，并支持平移、缩放与选择。"""

    _TILE_CACHE_ENTRY_LIMIT: int = 1024
    _TILE_CACHE_MEMORY_LIMIT: int = 64 * 1024 * 1024
    _MIN_SCALE = 0.01
    _MAX_SCALE = 4.0
    _DEFAULT_SCALE = 0.08

    def __init__(
        self,
        on_region_selected: RegionSelected,
        on_camera_changed: Optional[CameraChanged] = None,
        on_marker_selected: Optional[MarkerSelected] = None,
    ) -> None:
        """构建画布。

        Args:
            on_region_selected: ``(coord, size_bytes)`` 选择回调；清空时为 None。
            on_camera_changed: 可选 ``(center_x, center_z, scale)`` 镜头回调。
            on_marker_selected: 可选标记选择回调。
        """
        super().__init__()
        self._on_region_selected = on_region_selected
        self._on_camera_changed = on_camera_changed
        self._on_marker_selected = on_marker_selected
        self._regions: dict[RegionCoord, int] = {}
        self._visible_cache_key: tuple[object, ...] | None = None
        self._visible_cache: tuple[RegionCoord, ...] = ()
        self._markers: tuple[MapMarker, ...] = ()
        self._selected: Optional[RegionCoord] = None
        self._selected_marker_id: Optional[str] = None
        self._center_x = 0.0
        self._center_z = 0.0
        self._scale = self._DEFAULT_SCALE
        self._dragging = False
        self._dragged = False
        self._last_pos = QPoint()
        self._press_pos = QPoint()
        self._camera_emit_pending = False
        self._camera_timer = QTimer(self)
        self._camera_timer.setSingleShot(True)
        self._camera_timer.setInterval(40)
        self._camera_timer.timeout.connect(self._flush_camera)
        self._max_size = 1
        self._display_mode = "activity"
        self._tiles: OrderedDict[RegionCoord, QPixmap] = OrderedDict()
        self._tile_revisions: dict[RegionCoord, int] = {}
        self._tile_memory_bytes = 0
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

    @property
    def is_dragging(self) -> bool:
        """当前是否正通过鼠标平移地图。"""
        return self._dragging

    @property
    def tile_scale(self) -> float:
        """映射到 Flet/瓦片协调器使用的区域相对缩放。"""
        region_px = max(1.0, BLOCKS_PER_REGION * self._scale)
        return region_px / 32.0

    def set_regions(self, regions: Mapping[RegionCoord, int]) -> None:
        """替换区域大小数据并尽量保持选择。"""
        self._regions = dict(regions)
        self._invalidate_visible_cache()
        self._max_size = max(self._regions.values(), default=1)
        if self._selected is not None and self._selected not in self._regions:
            self._selected = None
            self._on_region_selected(None, None)
        if self._regions and self._center_x == 0.0 and self._center_z == 0.0:
            self.fit_to_regions()
        self.update()

    def clear(self) -> None:
        """清空区域数据与选择。"""
        self._camera_timer.stop()
        self._camera_emit_pending = False
        self._regions = {}
        self._invalidate_visible_cache()
        self._markers = ()
        self._tiles.clear()
        self._tile_revisions.clear()
        self._tile_memory_bytes = 0
        self._selected = None
        self._selected_marker_id = None
        self._max_size = 1
        self.update()

    def set_markers(self, markers: Sequence[MapMarker]) -> None:
        """替换当前维度标记并尽量保持选择。"""
        self._markers = tuple(markers)
        ids = {marker.id for marker in self._markers}
        if self._selected_marker_id not in ids:
            self._selected_marker_id = None
        self.update()

    def select_marker(self, marker_id: Optional[str]) -> None:
        """程序化选中标记。"""
        self._selected_marker_id = marker_id
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

    def set_display_mode(self, mode: str) -> None:
        """切换 activity / topview 显示模式。"""
        if mode not in {"activity", "topview"}:
            mode = "activity"
        if mode == self._display_mode:
            return
        self._display_mode = mode
        self.update()

    @property
    def display_mode(self) -> str:
        """返回当前显示模式。"""
        return self._display_mode

    def set_tile(
        self,
        coord: RegionCoord,
        png_bytes: bytes,
        *,
        revision: int = 0,
    ) -> bool:
        """写入或替换一个区域的俯视 PNG 瓦片。

        Args:
            coord: 区域坐标。
            png_bytes: 完整 PNG 数据。
            revision: 服务端单调修订号；相同修订不会重复原生解码。

        Returns:
            成功加入缓存或命中已有修订时为 True，PNG 无效时为 False。
        """
        current_revision = self._tile_revisions.get(coord)
        if revision > 0 and current_revision == revision and coord in self._tiles:
            self._tiles.move_to_end(coord)
            return True
        pixmap = QPixmap()
        if not pixmap.loadFromData(png_bytes):
            return False
        previous = self._tiles.pop(coord, None)
        if previous is not None:
            self._tile_memory_bytes -= self._pixmap_bytes(previous)
        self._tiles[coord] = pixmap
        if revision > 0:
            self._tile_revisions[coord] = revision
        else:
            self._tile_revisions.pop(coord, None)
        self._tile_memory_bytes += self._pixmap_bytes(pixmap)
        self._trim_tile_cache()
        self.update()
        return True

    def clear_tiles(self) -> None:
        """清空俯视瓦片缓存。"""
        self._tiles.clear()
        self._tile_revisions.clear()
        self._tile_memory_bytes = 0
        self.update()

    @staticmethod
    def _pixmap_bytes(pixmap: QPixmap) -> int:
        """估算 QPixmap 的原生像素存储大小。"""
        bytes_per_pixel = max(1, (max(1, pixmap.depth()) + 7) // 8)
        return max(0, pixmap.width()) * max(0, pixmap.height()) * bytes_per_pixel

    def _trim_tile_cache(self) -> None:
        """按条目数和原生像素字节数限制画布 LRU。"""
        while (
            self._tiles
            and (
                len(self._tiles) > self._TILE_CACHE_ENTRY_LIMIT
                or self._tile_memory_bytes > self._TILE_CACHE_MEMORY_LIMIT
            )
        ):
            old_coord, old_pixmap = self._tiles.popitem(last=False)
            self._tile_memory_bytes -= self._pixmap_bytes(old_pixmap)
            self._tile_revisions.pop(old_coord, None)

    def visible_regions(self) -> list[RegionCoord]:
        """返回当前视口相交的区域坐标（按中心距离排序）。"""
        cache_key = self._visible_region_cache_key()
        if cache_key == self._visible_cache_key:
            return list(self._visible_cache)
        visible = self._compute_visible_regions()
        self._visible_cache_key = cache_key
        self._visible_cache = tuple(visible)
        return visible

    def _compute_visible_regions(self) -> list[RegionCoord]:
        """按视口边界筛选区域，避免逐帧扫描整个存档。"""
        visible: list[tuple[float, RegionCoord]] = []
        center = (
            int(self._center_x // BLOCKS_PER_REGION),
            int(self._center_z // BLOCKS_PER_REGION),
        )
        min_x, max_x, min_z, max_z = self._visible_region_bounds()
        candidate_count = (max_x - min_x + 1) * (max_z - min_z + 1)
        grid_limit = min(200_000, max(1, len(self._regions) * 2))
        use_grid = candidate_count <= grid_limit
        if use_grid:
            candidates = (
                (region_x, region_z)
                for region_x in range(min_x, max_x + 1)
                for region_z in range(min_z, max_z + 1)
            )
        else:
            candidates = (
                coord
                for coord in self._regions
                if min_x <= coord[0] <= max_x
                and min_z <= coord[1] <= max_z
            )
        for coord in candidates:
            if coord not in self._regions:
                continue
            dist = abs(coord[0] - center[0]) + abs(coord[1] - center[1])
            visible.append((float(dist), coord))
        visible.sort(key=lambda item: item[0])
        return [coord for _dist, coord in visible]

    def _visible_region_cache_key(self) -> tuple[object, ...]:
        """返回影响视口候选集合的稳定键。"""
        return (
            self.width(),
            self.height(),
            self._center_x,
            self._center_z,
            self._scale,
        )

    def _visible_region_bounds(self) -> tuple[int, int, int, int]:
        """返回可能与视口相交的区域坐标边界。"""
        scale = max(self._scale, self._MIN_SCALE)
        half_width = self.width() / (2.0 * scale)
        half_height = self.height() / (2.0 * scale)
        min_x = math.floor((self._center_x - half_width) / BLOCKS_PER_REGION)
        max_x = math.floor((self._center_x + half_width) / BLOCKS_PER_REGION)
        min_z = math.floor((self._center_z - half_height) / BLOCKS_PER_REGION)
        max_z = math.floor((self._center_z + half_height) / BLOCKS_PER_REGION)
        return int(min_x), int(max_x), int(min_z), int(max_z)

    def _invalidate_visible_cache(self) -> None:
        """使区域数据变化后的可见坐标快照失效。"""
        self._visible_cache_key = None
        self._visible_cache = ()

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制背景、热力/俯视瓦片与选中边框。"""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#101810"))
        cell = max(2.0, BLOCKS_PER_REGION * self._scale)
        if cell < 2.0:
            painter.end()
            return
        use_tiles = self._display_mode == "topview"
        for coord in self.visible_regions():
            size = self._regions[coord]
            rect = self._region_screen_rect(coord[0], coord[1])
            tile = self._tiles.get(coord) if use_tiles else None
            if tile is not None and not tile.isNull():
                painter.drawPixmap(rect, tile)
            else:
                painter.fillRect(rect, self._heat_color(size))
        if self._selected is not None and self._selected in self._regions:
            rect = self._region_screen_rect(
                self._selected[0], self._selected[1]
            )
            painter.setPen(QPen(QColor("#FFD54F"), 2))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        self._paint_markers(painter)
        painter.end()

    def _paint_markers(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for marker in self._markers:
            screen_x, screen_z = self._block_to_screen(
                float(marker.x), float(marker.z)
            )
            if not self.rect().adjusted(-12, -12, 12, 12).contains(
                int(screen_x), int(screen_z)
            ):
                continue
            color = QColor(marker.color)
            if not color.isValid():
                color = QColor("#FFD54F")
            selected = marker.id == self._selected_marker_id
            radius = 7 if selected else 5
            painter.setBrush(color)
            painter.setPen(QPen(QColor("#101810"), 2 if selected else 1))
            painter.drawEllipse(
                int(screen_x - radius),
                int(screen_z - radius),
                radius * 2,
                radius * 2,
            )

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
                self._emit_camera(immediate=False)
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._emit_camera()
            release = event.position().toPoint()
            moved = (release - self._press_pos).manhattanLength()
            if not self._dragged and moved < 6:
                marker = self._marker_at(
                    event.position().x(), event.position().y()
                )
                if marker is not None:
                    self._selected_marker_id = marker.id
                    self.update()
                    if self._on_marker_selected is not None:
                        self._on_marker_selected(marker)
                else:
                    coord = self._region_at(
                        event.position().x(), event.position().y()
                    )
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

    def _region_screen_rect(
        self,
        region_x: int,
        region_z: int,
    ) -> QRect:
        left, top = self._block_to_screen(
            region_x * BLOCKS_PER_REGION,
            region_z * BLOCKS_PER_REGION,
        )
        right, bottom = self._block_to_screen(
            (region_x + 1) * BLOCKS_PER_REGION,
            (region_z + 1) * BLOCKS_PER_REGION,
        )
        left_px = math.floor(left)
        top_px = math.floor(top)
        right_px = math.ceil(right)
        bottom_px = math.ceil(bottom)
        return QRect(
            left_px,
            top_px,
            max(1, right_px - left_px),
            max(1, bottom_px - top_px),
        )

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

    def _marker_at(
        self,
        screen_x: float,
        screen_z: float,
    ) -> Optional[MapMarker]:
        hit_radius = 10.0
        best: Optional[MapMarker] = None
        best_dist = hit_radius * hit_radius
        for marker in self._markers:
            mx, mz = self._block_to_screen(float(marker.x), float(marker.z))
            dist = (mx - screen_x) ** 2 + (mz - screen_z) ** 2
            if dist <= best_dist:
                best = marker
                best_dist = dist
        return best

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

    def _emit_camera(self, *, immediate: bool = True) -> None:
        """发送镜头状态；拖拽期间合并高频回调。"""
        if self._on_camera_changed is None:
            return
        if immediate:
            self._camera_timer.stop()
            self._camera_emit_pending = False
            self._on_camera_changed(
                self._center_x,
                self._center_z,
                self._scale,
            )
            return
        if self._camera_emit_pending:
            return
        self._camera_emit_pending = True
        self._camera_timer.start()

    def _flush_camera(self) -> None:
        """发送合并后的最新镜头状态。"""
        if not self._camera_emit_pending:
            return
        self._camera_emit_pending = False
        callback = self._on_camera_changed
        if callback is not None:
            callback(self._center_x, self._center_z, self._scale)

    @staticmethod
    def _clamp_scale(scale: float) -> float:
        return max(
            QtRegionMapCanvas._MIN_SCALE,
            min(QtRegionMapCanvas._MAX_SCALE, float(scale)),
        )


__all__ = ["QtRegionMapCanvas"]
