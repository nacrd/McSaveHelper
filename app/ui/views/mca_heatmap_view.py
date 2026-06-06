"""
MCA 热力图 Canvas 视图组件

使用 Flet Canvas 绘制极简几何风格的热力图，
支持缩放、平移和渐进式动态加载。

参考: https://flet.dev/docs/controls/canvas/
"""
import asyncio
import math
import threading
from typing import Any, Callable, Dict, List, Tuple, Optional

import flet as ft
import flet.canvas as cv

from app.services.heatmap_service import get_heatmap_service, HeatmapService


HeatmapSelectionCallback = Callable[[Optional[Tuple[int, int]], Optional[int]], None]


class McaHeatmapView(ft.Container):
    """
    MCA 热力图 Canvas 视图组件
    
    特性：
    - 使用 cv.Canvas 绘制
    - 颜色映射：冷色（蓝）到暖色（红）
    - 支持滚轮缩放和拖拽平移
    - 渐进式动态加载动画
    """
    
    # 默认颜色主题
    BACKGROUND_COLOR = "#1E1E1E"
    GRID_LINE_COLOR = "#333333"
    
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
        
        # 依赖注入热力图服务
        self._heatmap_service = heatmap_service or get_heatmap_service()
        self._on_selection_changed = on_selection_changed
        
        # 视图变换状态
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._scale = 1.0
        
        # 选中状态
        self._selected_cell: Optional[Tuple[int, int]] = None
        
        # 缓存当前数据用于绘制
        self._current_data: Dict[Tuple[int, int], int] = {}
        self._cell_bounds: Dict[Tuple[int, int], Tuple[float, float, float, float]] = {}
        
        # 布局配置
        self.width = width
        self.height = height
        self.expand = True
        self.bgcolor = self.BACKGROUND_COLOR
        self.border_radius = 8
        
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
        
        # 填充整个容器
        self._gesture_detector.expand = True
        
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
        
        # 检查点击的单元格
        for coord, bounds in self._cell_bounds.items():
            bx, by, bw, bh = bounds
            if bx <= tap_x <= bx + bw and by <= tap_y <= by + bh:
                if coord in self._current_data:
                    self._selected_cell = coord
                    size = self._current_data[coord]
                    
                    # 触发回调
                    if self._on_selection_changed:
                        self._on_selection_changed(coord, size)
                    
                    self._rebuild_canvas()
                break
    
    def _on_scroll(self, e: ft.ScrollEvent) -> None:
        """滚轮缩放"""
        scroll_delta = getattr(e, "scroll_delta", None)
        delta_y = getattr(scroll_delta, "y", 0) if scroll_delta is not None else getattr(e, "delta_y", 0)
        if not delta_y:
            return

        zoom_factor = 1.1 if delta_y < 0 else 0.9
        new_scale = max(0.1, min(10.0, self._scale * zoom_factor))

        if new_scale != self._scale:
            self._scale = new_scale
            self._rebuild_canvas()
    
    def _rebuild_canvas(self) -> None:
        """重建 Canvas"""
        # 获取当前数据
        self._current_data = self._heatmap_service.get_all_data()
        
        # 构建形状列表
        shapes: List[cv.Shape] = []
        
        # 绘制背景
        shapes.append(cv.Rect(
            0, 0, self.width or 800, self.height or 600,
            paint=ft.Paint(color=self.BACKGROUND_COLOR)
        ))
        
        if not self._current_data:
            # 没有数据时显示提示
            shapes.append(cv.Line(
                (self.width or 800) / 2 - 100, (self.height or 600) / 2,
                (self.width or 800) / 2 + 100, (self.height or 600) / 2,
                paint=ft.Paint(color="#555555", stroke_width=1)
            ))
            shapes.append(cv.Text(
                x=(self.width or 800) / 2 - 80,
                y=(self.height or 600) / 2 + 20,
                value="加载存档后显示热力图",
                style=ft.TextStyle(size=14, color="#888888")
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
        padding = 1
        min_x -= padding
        max_x += padding
        min_z -= padding
        max_z += padding
        
        # 计算世界坐标范围的实际像素尺寸
        world_width = (max_x - min_x + 1) * (self.CELL_SIZE + self.CELL_GAP)
        world_height = (max_z - min_z + 1) * (self.CELL_SIZE + self.CELL_GAP)
        
        # 初始自动缩放和居中
        if self._scale == 1.0 and self._offset_x == 0 and self._offset_y == 0:
            scale_x = (self.width or 800) / world_width * 0.85
            scale_y = (self.height or 600) / world_height * 0.85
            self._scale = min(scale_x, scale_y, 1.0)
            
            # 居中偏移
            self._offset_x = ((self.width or 800) - world_width * self._scale) / 2
            self._offset_y = ((self.height or 600) - world_height * self._scale) / 2
        
        # 清空单元格边界缓存
        self._cell_bounds.clear()
        
        # 绘制网格
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
                self._cell_bounds[coord] = (screen_x, screen_y, cell_size, cell_size)
                
                if coord in self._current_data:
                    # 有数据，使用颜色映射
                    size = self._current_data[coord]
                    color = self._get_color(size)
                    
                    # 绘制填充
                    shapes.append(cv.Rect(
                        screen_x, screen_y, cell_size, cell_size,
                        paint=ft.Paint(color=color)
                    ))
                    
                    # 绘制边框
                    border_color = "#FFFFFF44" if coord == self._selected_cell else "#FFFFFF11"
                    shapes.append(cv.Rect(
                        screen_x, screen_y, cell_size, cell_size,
                        paint=ft.Paint(
                            color=border_color,
                            style=ft.PaintingStyle.STROKE,
                            stroke_width=1 if coord != self._selected_cell else 2
                        )
                    ))
                else:
                    # 无数据，绘制网格线
                    shapes.append(cv.Rect(
                        screen_x, screen_y, cell_size, cell_size,
                        paint=ft.Paint(
                            color=self.GRID_LINE_COLOR,
                            style=ft.PaintingStyle.STROKE,
                            stroke_width=0.5
                        )
                    ))
        
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
        
        # 缩放级别
        zoom_text = f"缩放: {self._scale:.1f}x"
        shapes.append(cv.Rect(10, 10, 100, 24, paint=ft.Paint(color="#00000088")))
        shapes.append(cv.Text(
            x=15, y=15,
            value=zoom_text,
            style=ft.TextStyle(size=12, color="#FFFFFF88")
        ))
        
        # 扫描进度
        if self._heatmap_service.is_scanning:
            progress = self._heatmap_service.scan_progress
            progress_text = f"扫描中: {int(progress * 100)}%"
            shapes.append(cv.Rect(10, height - 34, 120, 24, paint=ft.Paint(color="#00000088")))
            shapes.append(cv.Text(
                x=15, y=height - 29,
                value=progress_text,
                style=ft.TextStyle(size=12, color="#64B5F6")
            ))
        
        # 选中信息
        if self._selected_cell:
            coord = self._selected_cell
            size = self._current_data.get(coord, 0)
            size_str = self._format_size(size)
            
            info_text = f"区域 ({coord[0]}, {coord[1]}): {size_str}"
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
    
    def _get_color(self, size: int) -> str:
        """根据文件大小获取颜色"""
        stats = self._heatmap_service.get_statistics()
        
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
        
        # 颜色渐变：蓝 -> 青 -> 绿 -> 黄 -> 橙 -> 红
        if ratio < 0.2:
            hue = 240 - ratio * 200
            return self._hsl_to_hex(hue, 70, 60)
        elif ratio < 0.4:
            hue = 180 - (ratio - 0.2) * 200
            return self._hsl_to_hex(hue, 70, 50)
        elif ratio < 0.6:
            hue = 120 - (ratio - 0.4) * 300
            return self._hsl_to_hex(hue, 80, 55)
        elif ratio < 0.8:
            hue = 45 - (ratio - 0.6) * 100
            return self._hsl_to_hex(hue, 85, 55)
        else:
            hue = 20 - (ratio - 0.8) * 60
            return self._hsl_to_hex(hue, 80, 50)
    
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
            r = hue2rgb(p, q, h + 1/3)
            g = hue2rgb(p, q, h)
            b = hue2rgb(p, q, h - 1/3)
        
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    
    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        elif size >= 1024:
            return f"{size / 1024:.2f} KB"
        else:
            return f"{size} B"
    
    async def _monitor_scan_completion(self) -> None:
        """监控扫描结束并刷新宿主视图状态"""
        while self._heatmap_service.is_scanning:
            await asyncio.sleep(0.2)
        self._rebuild_canvas()
        if self._on_selection_changed:
            self._on_selection_changed(None, None)

    async def _update_loop(self) -> None:
        """异步更新循环 - 实现渐进式动态加载"""
        while self._heatmap_service.is_scanning:
            self._rebuild_canvas()
            await asyncio.sleep(0.2)
        self._rebuild_canvas()
    
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
        try:
            return asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()
            return None
    
    def _start_update_loop(self) -> None:
        """启动异步更新循环"""
        if self._update_task is None or self._update_task.done():
            self._update_task = self._schedule_task(self._update_loop())
    
    def _stop_update_loop(self) -> None:
        """停止异步更新循环"""
        if self._update_task and not self._update_task.done():
            self._update_task.cancel()
            try:
                asyncio.get_event_loop().run_until_complete(self._update_task)
            except (asyncio.CancelledError, RuntimeError):
                pass
    
    def start_scan(self, region_dir: str) -> None:
        """启动热力图扫描"""
        self._schedule_task(self._heatmap_service.start_silent_scan(region_dir))
        self._start_update_loop()
    
    def refresh(self) -> None:
        """手动刷新热力图"""
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
        self._rebuild_canvas()
    
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
