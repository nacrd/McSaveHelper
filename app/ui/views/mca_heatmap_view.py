"""
MCA 区域地图 Canvas 视图组件

使用 Flet Canvas 绘制极简几何风格的区域地图，
支持缩放、平移和渐进式动态加载。

参考: https://flet.dev/docs/controls/canvas/
"""
import asyncio
import math
import threading
from typing import Any, Callable, Dict, List, Tuple, Optional

import flet as ft

# 尝试导入 canvas 模块，如果失败则抛出 ImportError 以便兼容性处理
try:
    import flet.canvas as cv
except ImportError:
    raise ImportError("flet.canvas is not available in this Flet version")

from app.services.heatmap_service import get_heatmap_service, HeatmapService
from app.ui.utils import format_size


HeatmapSelectionCallback = Callable[[
    Optional[Tuple[int, int]], Optional[int], Optional[Dict[str, Any]]], None]


class McaHeatmapView(ft.Container):
    """
    MCA 区域地图 Canvas 视图组件

    特性：
    - 使用 cv.Canvas 绘制
    - 颜色映射：冷色（蓝）到暖色（红）
    - 支持滚轮缩放和拖拽平移
    - 渐进式动态加载动画
    """

    # 默认颜色主题
    BACKGROUND_COLOR = "#162016"
    GRID_LINE_COLOR = "#3B4A34"
    EMPTY_REGION_COLOR = "#263426"
    ORIGIN_COLOR = "#7CB34288"

    # 单元格配置
    CELL_SIZE = 32
    CELL_GAP = 2

    def __init__(
        self,
        heatmap_service: Optional[HeatmapService] = None,
        on_selection_changed: Optional[HeatmapSelectionCallback] = None,
        width: int = 700,
        height: int = 450,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)

        # 依赖注入区域扫描服务
        self._heatmap_service = heatmap_service or get_heatmap_service()
        self._on_selection_changed = on_selection_changed

        # 视图变换状态
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._scale = 1.0
        self._show_coordinates = True
        self._show_empty_regions = False
        self._display_mode = "activity"
        self._detail_level = "auto"

        # 选中状态
        self._selected_cell: Optional[Tuple[int, int]] = None
        self._selected_chunk: Optional[Tuple[int, int, int, int]] = None

        # 缓存当前数据用于绘制
        self._current_data: Dict[Tuple[int, int], int] = {}
        self._cell_bounds: Dict[Tuple[int, int],
                                Tuple[float, float, float, float]] = {}
        self._chunk_bounds: Dict[Tuple[int, int, int,
                                       int], Tuple[float, float, float, float]] = {}

        # 布局配置
        self.width = width
        self.height = height
        self.bgcolor = self.BACKGROUND_COLOR
        self.border_radius = 0

        # 创建 Canvas
        self._canvas = cv.Canvas(
            width=width,
            height=height,
            shapes=self._build_shapes(),
        )

        # 创建手势检测器
        self._gesture_detector = ft.GestureDetector(
            on_pan_start=self._on_pan_start,
            on_pan_update=self._on_pan_update,
            on_tap=self._on_tap,
            on_scroll=self._on_scroll,
        )

        # 组装布局
        self.content = ft.Stack([
            self._canvas,
            self._gesture_detector,
        ])

        self._gesture_detector.width = width
        self._gesture_detector.height = height

        # 异步更新任务
        self._update_task: Optional[asyncio.Task[Any]] = None

        # 标记是否需要首次绘制
        self._needs_initial_draw = True

    def _build_shapes(self) -> List[cv.Shape]:
        """构建初始形状列表"""
        return [
            cv.Rect(
                0, 0, self.width or 800, self.height or 600,
                paint=ft.Paint(color=self.BACKGROUND_COLOR)
            )
        ]

    def _on_pan_start(self, e: ft.DragStartEvent) -> None:
        """拖拽开始"""
        self._last_x = e.local_position.x
        self._last_y = e.local_position.y

    def _on_pan_update(self, e: ft.DragUpdateEvent) -> None:
        """拖拽更新"""
        dx = e.local_position.x - self._last_x
        dy = e.local_position.y - self._last_y

        self._offset_x += dx
        self._offset_y += dy
        self._last_x = e.local_position.x
        self._last_y = e.local_position.y

        self._rebuild_canvas()

    def _on_tap(self, e: ft.TapEvent) -> None:
        """点击选择"""
        tap_x = e.local_position.x
        tap_y = e.local_position.y

        if self._effective_detail_level() == "chunk":
            for key, bounds in self._chunk_bounds.items():
                bx, by, bw, bh = bounds
                if bx <= tap_x <= bx + bw and by <= tap_y <= by + bh:
                    rx, rz, lx, lz = key
                    coord = (rx, rz)
                    if coord in self._current_data:
                        self._selected_cell = coord
                        self._selected_chunk = key
                        size = self._current_data[coord]
                        if self._on_selection_changed:
                            self._on_selection_changed(
                                coord, size, self._chunk_detail(key))
                        self._rebuild_canvas()
                    return

        # 检查点击的单元格
        for coord, bounds in self._cell_bounds.items():
            bx, by, bw, bh = bounds
            if bx <= tap_x <= bx + bw and by <= tap_y <= by + bh:
                if coord in self._current_data:
                    self._selected_cell = coord
                    size = self._current_data[coord]
                    self._selected_chunk = None

                    # 触发回调
                    if self._on_selection_changed:
                        self._on_selection_changed(
                            coord, size, {"level": "region"})

                    self._rebuild_canvas()
                break

    def _on_scroll(self, e: ft.ScrollEvent) -> None:
        """滚轮缩放"""
        scroll_delta = getattr(e, "scroll_delta", None)
        delta_y = getattr(
            scroll_delta,
            "y",
            0) if scroll_delta is not None else getattr(
            e,
            "delta_y",
            0)
        if not delta_y:
            return

        zoom_factor = 1.1 if delta_y < 0 else 0.9
        new_scale = max(0.1, min(10.0, self._scale * zoom_factor))

        if new_scale != self._scale:
            pointer_x = getattr(
                getattr(
                    e,
                    "local_position",
                    None),
                "x",
                (self.width or 800) /
                2)
            pointer_y = getattr(
                getattr(
                    e,
                    "local_position",
                    None),
                "y",
                (self.height or 600) /
                2)
            world_x = (pointer_x - self._offset_x) / self._scale
            world_y = (pointer_y - self._offset_y) / self._scale
            self._scale = new_scale
            self._offset_x = pointer_x - world_x * self._scale
            self._offset_y = pointer_y - world_y * self._scale
            self._rebuild_canvas()

    def _rebuild_canvas(self) -> None:
        """重建 Canvas"""
        # 获取当前数据
        self._current_data = self._heatmap_service.get_all_data()

        # 预先计算一次统计信息，避免每个单元格重复计算（O(n²) → O(n)）
        stats = self._heatmap_service.get_statistics()
        self._cached_stats = stats

        # 构建形状列表
        shapes: List[cv.Shape] = []

        # 绘制背景
        shapes.append(cv.Rect(
            0, 0, self.width or 800, self.height or 600,
            paint=ft.Paint(color=self.BACKGROUND_COLOR)
        ))

        if not self._current_data:
            # 没有数据时显示友好提示
            shapes.append(cv.Text(
                x=(self.width or 800) / 2 - 90,
                y=(self.height or 600) / 2 - 30,
                value="🗺️",
                style=ft.TextStyle(size=48, color="#888888")
            ))
            shapes.append(cv.Text(
                x=(self.width or 800) / 2 - 95,
                y=(self.height or 600) / 2 + 30,
                value="设置当前存档后显示区域地图",
                style=ft.TextStyle(size=16, color="#CCCCCC")
            ))
            shapes.extend(self._build_info_overlay())
            self._canvas.shapes = shapes
            try:
                self._canvas.update()
            except RuntimeError:
                pass
            return

        # 计算世界坐标范围
        coords = list(self._current_data.keys())
        min_x = min(c[0] for c in coords)
        max_x = max(c[0] for c in coords)
        min_z = min(c[1] for c in coords)
        max_z = max(c[1] for c in coords)

        # 扩展范围
        padding = 0
        min_x -= padding
        max_x += padding
        min_z -= padding
        max_z += padding

        # 计算世界坐标范围的实际像素尺寸
        world_width = (max_x - min_x + 1) * (self.CELL_SIZE + self.CELL_GAP)
        world_height = (max_z - min_z + 1) * (self.CELL_SIZE + self.CELL_GAP)

        # 初始自动缩放和居中
        if self._scale == 1.0 and self._offset_x == 0 and self._offset_y == 0:
            scale_x = (self.width or 800) / world_width * 0.78
            scale_y = (self.height or 600) / world_height * 0.78
            self._scale = max(0.35, min(scale_x, scale_y, 3.0))

            # 居中偏移
            self._offset_x = (
                (self.width or 800) - world_width * self._scale) / 2
            self._offset_y = (
                (self.height or 600) - world_height * self._scale) / 2

        # 清空单元格边界缓存
        self._cell_bounds.clear()
        self._chunk_bounds.clear()

        # 绘制网格
        origin_x = 0 * (self.CELL_SIZE + self.CELL_GAP) * \
            self._scale + self._offset_x
        origin_y = 0 * (self.CELL_SIZE + self.CELL_GAP) * \
            self._scale + self._offset_y
        shapes.extend(self._build_origin_marker(origin_x, origin_y))

        for z in range(min_z, max_z + 1):
            for x in range(min_x, max_x + 1):
                # 世界坐标
                world_x = x * (self.CELL_SIZE + self.CELL_GAP)
                world_z = z * (self.CELL_SIZE + self.CELL_GAP)

                # 应用变换
                screen_x = world_x * self._scale + self._offset_x
                screen_y = world_z * self._scale + self._offset_y
                cell_size = self.CELL_SIZE * self._scale

                # 缓存单元格边界
                coord = (x, z)
                self._cell_bounds[coord] = (
                    screen_x, screen_y, cell_size, cell_size)

                if coord in self._current_data:
                    size = self._current_data[coord]
                    color = self._get_color(size, coord)
                    shapes.extend(
                        self._build_region_cell(
                            screen_x,
                            screen_y,
                            cell_size,
                            color,
                            coord,
                            size))
                    if self._effective_detail_level() == "chunk":
                        shapes.extend(
                            self._build_chunk_grid(
                                screen_x,
                                screen_y,
                                cell_size,
                                color,
                                coord,
                                size))
                elif self._show_empty_regions:
                    shapes.append(cv.Rect(
                        screen_x, screen_y, cell_size, cell_size,
                        paint=ft.Paint(
                            color=self.EMPTY_REGION_COLOR,
                            style=ft.PaintingStyle.STROKE,
                            stroke_width=0.5
                        )
                    ))
                    if self._show_coordinates and self._scale >= 0.75:
                        shapes.extend(
                            self._build_coordinate_label(
                                screen_x,
                                screen_y,
                                cell_size,
                                coord,
                                muted=True))

        # 添加信息覆盖层
        shapes.extend(self._build_info_overlay())

        # 更新 Canvas
        self._canvas.shapes = shapes

        try:
            self._canvas.update()
        except RuntimeError:
            pass

        # 标记已完成首次绘制
        self._needs_initial_draw = False

    def _build_info_overlay(self) -> List[cv.Shape]:
        """构建信息覆盖层"""
        shapes: List[cv.Shape] = []
        width = self.width or 800
        height = self.height or 600

        zoom_text = f"{
            self._get_mode_title()} · {
            self._effective_detail_name()} · 缩放 {
            self._scale:.1f}x"
        shapes.append(
            cv.Rect(
                10,
                10,
                214,
                26,
                paint=ft.Paint(
                    color="#00000099")))
        shapes.append(cv.Text(
            x=15, y=15,
            value=zoom_text,
            style=ft.TextStyle(size=12, color="#D7CCC8")
        ))

        shapes.append(
            cv.Rect(
                10,
                42,
                214,
                24,
                paint=ft.Paint(
                    color="#00000066")))
        shapes.append(cv.Text(
            x=15, y=47,
            value="拖拽平移 · 滚轮缩放 · 点击区域",
            style=ft.TextStyle(size=11, color="#A5D6A7")
        ))

        # 扫描进度
        if self._heatmap_service.is_scanning:
            progress = self._heatmap_service.scan_progress
            progress_text = f"扫描中: {int(progress * 100)}%"
            shapes.append(
                cv.Rect(
                    10,
                    height - 34,
                    120,
                    24,
                    paint=ft.Paint(
                        color="#00000088")))
            shapes.append(cv.Text(
                x=15, y=height - 29,
                value=progress_text,
                style=ft.TextStyle(size=12, color="#64B5F6")
            ))

        # 选中信息
        if self._selected_cell:
            coord = self._selected_cell
            size = self._current_data.get(coord, 0)
            size_str = format_size(size)

            if self._selected_chunk:
                detail = self._chunk_detail(self._selected_chunk)
                info_text = f"区块 {
                    detail['chunk_coord']} · {
                    detail['block_range']} · {size_str}"
            else:
                block_range = self._format_block_range(coord, compact=True)
                info_text = f"r.{
                    coord[0]}.{
                    coord[1]}.mca · {block_range} · {size_str} · {
                    self._get_region_value_label(
                        coord,
                        size)}"
            text_width = len(info_text) * 7 + 20

            shapes.append(cv.Rect(
                width - text_width - 10, 10, text_width, 24,
                paint=ft.Paint(color="#00000088")
            ))
            shapes.append(cv.Text(
                x=width - text_width - 5, y=15,
                value=info_text,
                style=ft.TextStyle(size=12, color="#64B5F6")
            ))

        return shapes

    def _build_region_cell(self,
                           x: float,
                           y: float,
                           size: float,
                           color: str,
                           coord: Tuple[int,
                                        int],
                           file_size: int) -> List[cv.Shape]:
        shapes: List[cv.Shape] = []
        selected = coord == self._selected_cell
        shapes.append(cv.Rect(x, y, size, size, paint=ft.Paint(color=color)))
        if size >= 10:
            shapes.append(cv.Rect(x, y, size, max(1, size * 0.18),
                          paint=ft.Paint(color="#FFFFFF20")))
            shapes.append(cv.Rect(x, y + size * 0.78, size, max(1,
                          size * 0.22), paint=ft.Paint(color="#00000024")))
        shapes.append(cv.Rect(
            x, y, size, size,
            paint=ft.Paint(
                color="#FFD54F" if selected else "#00000055",
                style=ft.PaintingStyle.STROKE,
                stroke_width=3 if selected else 1,
            ),
        ))
        if self._show_coordinates and size >= 18:
            shapes.extend(
                self._build_coordinate_label(
                    x, y, size, coord, muted=False))
        if size >= 30:
            level = self._get_activity_icon(file_size)
            shapes.append(cv.Text(
                x=x + 5,
                y=y + size - 17,
                value=level,
                style=ft.TextStyle(size=12, color="#F5F5DC"),
            ))
        return shapes

    def _build_chunk_grid(self,
                          x: float,
                          y: float,
                          size: float,
                          color: str,
                          coord: Tuple[int,
                                       int],
                          file_size: int) -> List[cv.Shape]:
        shapes: List[cv.Shape] = []
        chunk_size = size / 32
        if chunk_size < 2:
            return shapes
        rx, rz = coord
        line_color = "#00000066" if chunk_size >= 4 else "#00000040"
        for i in range(1, 32):
            pos = i * chunk_size
            shapes.append(
                cv.Line(
                    x + pos,
                    y,
                    x + pos,
                    y + size,
                    paint=ft.Paint(
                        color=line_color,
                        stroke_width=0.5)))
            shapes.append(
                cv.Line(
                    x,
                    y + pos,
                    x + size,
                    y + pos,
                    paint=ft.Paint(
                        color=line_color,
                        stroke_width=0.5)))
        for local_z in range(32):
            for local_x in range(32):
                bx = x + local_x * chunk_size
                by = y + local_z * chunk_size
                self._chunk_bounds[(rx, rz, local_x, local_z)] = (
                    bx, by, chunk_size, chunk_size)
        if self._selected_chunk and self._selected_chunk[:2] == coord:
            _, _, lx, lz = self._selected_chunk
            sx = x + lx * chunk_size
            sy = y + lz * chunk_size
            shapes.append(
                cv.Rect(
                    sx, sy, chunk_size, chunk_size, paint=ft.Paint(
                        color="#FFD54F", style=ft.PaintingStyle.STROKE, stroke_width=max(
                            1, min(
                                3, chunk_size / 2))), ))
        if chunk_size >= 7:
            shapes.append(cv.Text(
                x=x + 4,
                y=y + size - 16,
                value="32×32 区块",
                style=ft.TextStyle(size=10, color="#F5F5DC"),
            ))
        return shapes

    def _build_coordinate_label(self,
                                x: float,
                                y: float,
                                size: float,
                                coord: Tuple[int,
                                             int],
                                muted: bool) -> List[cv.Shape]:
        color = "#A5D6A7" if not muted else "#5E6D58"
        block_x0, block_x1, block_z0, block_z1 = self._block_range(coord)
        label_size = 8 if size < 42 else 9
        if size >= 52:
            return [
                cv.Text(
                    x=x + 4,
                    y=y + 5,
                    value=f"X {block_x0}~{block_x1}",
                    style=ft.TextStyle(
                        size=label_size,
                        color=color)),
                cv.Text(
                    x=x + 4,
                    y=y + 17,
                    value=f"Z {block_z0}~{block_z1}",
                    style=ft.TextStyle(
                        size=label_size,
                        color=color)),
            ]
        return [
            cv.Text(
                x=x + 4,
                y=y + 5,
                value=self._format_block_range(coord, compact=True),
                style=ft.TextStyle(size=label_size, color=color),
            )
        ]

    def _block_range(
            self, coord: Tuple[int, int]) -> Tuple[int, int, int, int]:
        x, z = coord
        return x * 512, x * 512 + 511, z * 512, z * 512 + 511

    def _format_block_range(
            self, coord: Tuple[int, int], compact: bool = False) -> str:
        x0, x1, z0, z1 = self._block_range(coord)
        if compact:
            return f"X{x0}~{x1} Z{z0}~{z1}"
        return f"X {x0} ~ {x1}, Z {z0} ~ {z1}"

    def _effective_detail_level(self) -> str:
        if self._detail_level == "auto":
            return "chunk" if self._scale >= 3.6 else "region"
        return self._detail_level

    def _effective_detail_name(self) -> str:
        return "区块级" if self._effective_detail_level() == "chunk" else "区域级"

    def _chunk_detail(self, key: Tuple[int, int, int, int]) -> Dict[str, Any]:
        rx, rz, lx, lz = key
        chunk_x = rx * 32 + lx
        chunk_z = rz * 32 + lz
        block_x0 = chunk_x * 16
        block_x1 = block_x0 + 15
        block_z0 = chunk_z * 16
        block_z1 = block_z0 + 15
        return {
            "level": "chunk",
            "region_coord": (rx, rz),
            "chunk_local": (lx, lz),
            "chunk_coord": (chunk_x, chunk_z),
            "chunk_range": f"X {chunk_x}, Z {chunk_z}",
            "block_range": f"X {block_x0} ~ {block_x1}, Z {block_z0} ~ {block_z1}",
        }

    def _build_origin_marker(self, x: float, y: float) -> List[cv.Shape]:
        width = self.width or 800
        height = self.height or 600
        return [
            cv.Rect(x, 0, 2, height, paint=ft.Paint(color=self.ORIGIN_COLOR)),
            cv.Rect(0, y, width, 2, paint=ft.Paint(color=self.ORIGIN_COLOR)),
        ]

    def _get_color(self, size: int, coord: Tuple[int, int]) -> str:
        if self._display_mode == "biome":
            return self._get_biome_color(coord)
        if self._display_mode == "structure":
            return self._get_structure_color(coord)
        return self._get_activity_color(size)

    def _get_activity_color(self, size: int) -> str:
        stats = getattr(
            self,
            '_cached_stats',
            None) or self._heatmap_service.get_statistics()

        if stats["min_size"] == stats["max_size"]:
            return "#64B5F6"

        min_size = max(1, stats["min_size"])
        max_size = stats["max_size"]

        # 对数缩放
        try:
            log_min = math.log(min_size)
            log_max = math.log(max_size)
            log_size = math.log(max(1, size))

            if log_max > log_min:
                ratio = (log_size - log_min) / (log_max - log_min)
            else:
                ratio = 0.5
        except (ValueError, TypeError):
            ratio = 0.5

        ratio = max(0.0, min(1.0, ratio))

        if ratio < 0.18:
            return "#2E7D32"
        if ratio < 0.36:
            return "#689F38"
        if ratio < 0.56:
            return "#C0A44A"
        if ratio < 0.76:
            return "#D9822B"
        if ratio < 0.92:
            return "#C63D2F"
        return "#8E24AA"

    def _get_biome_color(self, coord: Tuple[int, int]) -> str:
        biome = str(self._heatmap_service.get_region_meta(
            coord).get("dominant_biome", "unknown")).lower()
        if "ocean" in biome or "river" in biome:
            return "#1E88E5"
        if "desert" in biome or "badlands" in biome:
            return "#D6B44C"
        if "snow" in biome or "frozen" in biome or "ice" in biome:
            return "#B3E5FC"
        if "jungle" in biome:
            return "#2E7D32"
        if "forest" in biome or "taiga" in biome:
            return "#388E3C"
        if "swamp" in biome or "mangrove" in biome:
            return "#607D3B"
        if "nether" in biome or "basalt" in biome or "crimson" in biome or "warped" in biome:
            return "#8E2424"
        if "end" in biome:
            return "#C5B56D"
        if biome == "unknown":
            return "#455A64"
        return "#7CB342"

    def _get_structure_color(self, coord: Tuple[int, int]) -> str:
        meta = self._heatmap_service.get_region_meta(coord)
        count = int(meta.get("structure_count", 0) or 0)
        name = str(meta.get("dominant_structure", "none")).lower()
        if count <= 0 or name == "none":
            return "#455A64"
        if "village" in name:
            return "#FFD54F"
        if "mineshaft" in name:
            return "#8D6E63"
        if "stronghold" in name:
            return "#7E57C2"
        if "mansion" in name or "monument" in name:
            return "#26A69A"
        if "fortress" in name or "bastion" in name:
            return "#D84315"
        return "#FFB300" if count < 3 else "#FF7043"

    def _get_mode_title(self) -> str:
        return {
            "activity": "活动热力",
            "biome": "主要群系",
            "structure": "生成结构",
        }.get(self._display_mode, "区域视图")

    def _get_region_value_label(
            self, coord: Tuple[int, int], size: int) -> str:
        if self._display_mode == "biome":
            return self._get_biome_label(coord)
        if self._display_mode == "structure":
            return self._get_structure_label(coord)
        return self._get_activity_name(size)

    def _get_biome_label(self, coord: Tuple[int, int]) -> str:
        biome = self._heatmap_service.get_region_meta(
            coord).get("dominant_biome", "unknown")
        return f"主要群系 {biome}"

    def _get_structure_label(self, coord: Tuple[int, int]) -> str:
        meta = self._heatmap_service.get_region_meta(coord)
        count = int(meta.get("structure_count", 0) or 0)
        if count <= 0:
            return "未发现结构"
        return f"{meta.get('dominant_structure', 'unknown')} 等 {count} 个结构引用"

    def _get_activity_name(self, size: int) -> str:
        stats = getattr(
            self,
            '_cached_stats',
            None) or self._heatmap_service.get_statistics()
        avg = stats.get("avg_size", 0) or 0
        if avg <= 0:
            return "未知活动度"
        ratio = size / avg
        if ratio >= 2.0:
            return "极高活动"
        if ratio >= 1.4:
            return "高活动"
        if ratio >= 0.8:
            return "普通活动"
        if ratio >= 0.35:
            return "低活动"
        return "很少生成"

    def _get_activity_icon(self, size: int) -> str:
        name = self._get_activity_name(size)
        if name == "极高活动":
            return "◆◆"
        if name == "高活动":
            return "◆"
        if name == "普通活动":
            return "■"
        if name == "低活动":
            return "▪"
        return "·"

    def _hsl_to_hex(self, h: float, s: float, l: float) -> str:
        """HSL 颜色转十六进制"""
        h = h / 360
        s = s / 100
        l = l / 100

        if s == 0:
            r = g = b = l
        else:
            def hue2rgb(p: float, q: float, t: float) -> float:
                if t < 0:
                    t += 1
                if t > 1:
                    t -= 1
                if t < 1 / 6:
                    return p + (q - p) * 6 * t
                if t < 1 / 2:
                    return q
                if t < 2 / 3:
                    return p + (q - p) * (2 / 3 - t) * 6
                return p

            q = l * (1 + s) if l < 0.5 else l + s - l * s
            p = 2 * l - q
            r = hue2rgb(p, q, h + 1 / 3)
            g = hue2rgb(p, q, h)
            b = hue2rgb(p, q, h - 1 / 3)

        return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

    async def _monitor_scan_completion(self) -> None:
        """监控扫描结束并刷新宿主视图状态"""
        while self._heatmap_service.is_scanning:
            await asyncio.sleep(0.2)
        self._rebuild_canvas()
        if self._on_selection_changed:
            self._on_selection_changed(None, None, None)

    async def _update_loop(self) -> None:
        """异步更新循环 - 实现渐进式动态加载"""
        while self._heatmap_service.is_scanning:
            self._rebuild_canvas()
            await asyncio.sleep(0.2)
        self._rebuild_canvas()
        if self._on_selection_changed:
            self._on_selection_changed(None, None, None)

    def did_mount(self) -> None:
        """组件挂载时启动更新循环"""
        super().did_mount()

        # 进行首次绘制
        if self._needs_initial_draw:
            self._rebuild_canvas()

        # 如果正在扫描，启动更新循环
        if self._heatmap_service.is_scanning:
            self._start_update_loop()

    def did_unmount(self) -> None:
        """组件卸载时停止更新循环"""
        super_did_unmount = getattr(super(), "did_unmount", None)
        if super_did_unmount:
            super_did_unmount()
        self._stop_update_loop()

    def _schedule_task(self, coro: Any) -> Optional[asyncio.Task[Any]]:
        """安全地调度异步任务"""
        try:
            return asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            # 没有运行中的事件循环时，在后台线程中启动新的事件循环
            def _run_in_thread() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(coro)
                finally:
                    loop.close()
            threading.Thread(target=_run_in_thread, daemon=True).start()
            return None

    def _start_update_loop(self) -> None:
        """启动异步更新循环"""
        if self._update_task is None or self._update_task.done():
            self._update_task = self._schedule_task(self._update_loop())

    def _stop_update_loop(self) -> None:
        """停止异步更新循环"""
        if self._update_task and not self._update_task.done():
            self._update_task.cancel()
            # 不调用 run_until_complete，让任务在下一个 await 自然取消

    def start_scan(self, region_dir: str) -> None:
        """启动区域地图扫描"""
        self._schedule_task(
            self._heatmap_service.start_silent_scan(region_dir))
        self._start_update_loop()

    def refresh(self) -> None:
        """手动刷新区域地图"""
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._rebuild_canvas()

    def reset_view(self) -> None:
        """重置视图"""
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._selected_cell = None
        self._selected_chunk = None
        self._rebuild_canvas()

    def resize_map(self, width: int, height: int) -> None:
        if self.width == width and self.height == height:
            return
        self.width = width
        self.height = height
        self._canvas.width = width
        self._canvas.height = height
        self._gesture_detector.width = width
        self._gesture_detector.height = height
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._rebuild_canvas()

    def toggle_coordinates(self) -> bool:
        self._show_coordinates = not self._show_coordinates
        self._rebuild_canvas()
        return self._show_coordinates

    def toggle_empty_regions(self) -> bool:
        self._show_empty_regions = not self._show_empty_regions
        self._rebuild_canvas()
        return self._show_empty_regions

    def set_display_mode(self, mode: str) -> None:
        if mode not in {"activity", "biome", "structure"}:
            return
        self._display_mode = mode
        self._rebuild_canvas()

    def get_display_mode(self) -> str:
        return self._display_mode

    def set_detail_level(self, level: str) -> None:
        if level not in {"auto", "region", "chunk"}:
            return
        self._detail_level = level
        self._selected_chunk = None
        self._rebuild_canvas()

    def get_detail_level(self) -> str:
        return self._detail_level

    def zoom_in(self) -> None:
        """放大"""
        self._scale *= 1.2
        self._scale = min(10.0, self._scale)
        self._rebuild_canvas()

    def zoom_out(self) -> None:
        """缩小"""
        self._scale *= 0.8
        self._scale = max(0.1, self._scale)
        self._rebuild_canvas()

    def get_selected_cell(self) -> Optional[Tuple[int, int]]:
        """获取当前选中的单元格"""
        return self._selected_cell
