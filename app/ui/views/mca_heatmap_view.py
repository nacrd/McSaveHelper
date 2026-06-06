"""
MCA 热力图 Canvas 视图组件

使用 Flet Canvas 绘制极简几何风格的热力图，
支持缩放、平移和渐进式动态加载。
"""
import asyncio
import math
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass

import flet as ft

from app.services.heatmap_service import get_heatmap_service, HeatmapService


@dataclass
class ViewTransform:
    """视图变换状态"""
    offset_x: float = 0.0
    offset_y: float = 0.0
    scale: float = 1.0
    
    def apply(self, x: float, y: float) -> Tuple[float, float]:
        """将世界坐标转换为屏幕坐标"""
        return (
            x * self.scale + self.offset_x,
            y * self.scale + self.offset_y
        )
    
    def inverse(self, screen_x: float, screen_y: float) -> Tuple[float, float]:
        """将屏幕坐标转换为世界坐标"""
        return (
            (screen_x - self.offset_x) / self.scale,
            (screen_y - self.offset_y) / self.scale
        )


class McaHeatmapView(ft.Container):
    """
    MCA 热力图 Canvas 视图组件
    
    特性：
    - 使用 ft.canvas.Canvas 绘制
    - 颜色映射：冷色（蓝）到暖色（红）
    - 支持滚轮缩放和拖拽平移
    - 渐进式动态加载动画
    """
    
    # 默认颜色主题
    BACKGROUND_COLOR = "#1E1E1E"
    GRID_LINE_COLOR = "#333333"
    EMPTY_REGION_COLOR = "#2A2A2A"
    
    # 单元格配置
    CELL_SIZE = 32  # 基础单元格大小（世界坐标单位）
    CELL_GAP = 2    # 单元格间隙
    
    def __init__(
        self,
        heatmap_service: Optional[HeatmapService] = None,
        on_selection_changed: Optional[callable] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        
        # 依赖注入热力图服务
        self._heatmap_service = heatmap_service or get_heatmap_service()
        self._on_selection_changed = on_selection_changed
        
        # 视图变换状态
        self._transform = ViewTransform()
        
        # 选中状态
        self._selected_cell: Optional[Tuple[int, int]] = None
        self._hovered_cell: Optional[Tuple[int, int]] = None
        
        # Canvas 引用
        self._canvas: Optional[ft.canvas.Canvas] = None
        self._canvas_paints: List[ft.canvas.Paint] = []
        
        # 异步更新任务
        self._update_task: Optional[asyncio.Task] = None
        
        # 缓存当前数据用于绘制
        self._current_data: Dict[Tuple[int, int], int] = {}
        self._cell_bounds: Dict[Tuple[int, int], ft.Rect] = {}
        
        # 布局配置
        self.expand = True
        self.bgcolor = self.BACKGROUND_COLOR
        self.border_radius = 8
        
        # 构建 UI
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建 UI 组件"""
        # 创建 Canvas
        self._canvas = ft.canvas.Canvas(
            on_paint=self._on_canvas_paint,
        )
        
        # 创建手势检测器（支持缩放和平移）
        self._gesture_detector = ft.GestureDetector(
            on_scale_start=self._on_scale_start,
            on_scale_update=self._on_scale_update,
            on_scale_end=self._on_scale_end,
            on_hover=self._on_hover,
            on_tap=self._on_tap,
        )
        
        # 组装布局
        self.content = ft.Stack([
            self._canvas,
            self._gesture_detector,
        ])
        
        # 填充整个容器
        self._gesture_detector.expand = True
    
    def _on_canvas_paint(self, e: ft.canvas.CanvasPaintEvent) -> None:
        """Canvas 绘制回调"""
        canvas = e.canvas
        
        # 获取画布尺寸
        width = self.width if self.width else 800
        height = self.height if self.height else 600
        
        # 绘制背景
        canvas.draw_rect(
            ft.Rect(0, 0, width, height),
            ft.canvas.Paint(color=self.BACKGROUND_COLOR)
        )
        
        # 获取当前数据
        self._current_data = self._heatmap_service.get_all_data()
        
        if not self._current_data:
            # 没有数据时显示提示
            canvas.draw_line(
                width / 2 - 100, height / 2,
                width / 2 + 100, height / 2,
                ft.canvas.Paint(color="#555555", stroke_width=1)
            )
            return
        
        # 计算世界坐标范围
        coords = list(self._current_data.keys())
        min_x = min(c[0] for c in coords)
        max_x = max(c[0] for c in coords)
        min_z = min(c[1] for c in coords)
        max_z = max(c[1] for c in coords)
        
        # 扩展范围以确保所有区域可见
        padding = 1
        min_x -= padding
        max_x += padding
        min_z -= padding
        max_z += padding
        
        # 计算缩放以适应画布
        world_width = (max_x - min_x + 1) * (self.CELL_SIZE + self.CELL_GAP)
        world_height = (max_z - min_z + 1) * (self.CELL_SIZE + self.CELL_GAP)
        
        if self._transform.scale == 1.0:
            # 初始自动缩放
            scale_x = width / world_width * 0.9
            scale_y = height / world_height * 0.9
            self._transform.scale = min(scale_x, scale_y, 1.0)
            
            # 居中偏移
            self._transform.offset_x = width / 2 - (world_width * self._transform.scale) / 2
            self._transform.offset_y = height / 2 - (world_height * self._transform.scale) / 2
        
        # 清空单元格边界缓存
        self._cell_bounds.clear()
        
        # 绘制网格
        for z in range(min_z, max_z + 1):
            for x in range(min_x, max_x + 1):
                # 世界坐标
                world_x = x * (self.CELL_SIZE + self.CELL_GAP)
                world_z = z * (self.CELL_SIZE + self.CELL_GAP)
                
                # 屏幕坐标
                screen_x, screen_y = self._transform.apply(world_x, world_z)
                cell_size = self.CELL_SIZE * self._transform.scale
                
                # 屏幕坐标的矩形
                rect = ft.Rect(screen_x, screen_y, cell_size, cell_size)
                
                # 检查坐标是否存在
                coord = (x, z)
                if coord in self._current_data:
                    # 有数据，使用颜色映射
                    size = self._current_data[coord]
                    color = self._get_color(size)
                    
                    # 绘制填充
                    canvas.draw_rect(
                        rect,
                        ft.canvas.Paint(color=color)
                    )
                    
                    # 绘制边框
                    border_color = "#FFFFFF22" if coord == self._selected_cell else "#FFFFFF11"
                    canvas.draw_rect(
                        rect,
                        ft.canvas.Paint(color=border_color, style=ft.canvas.PaintStyle.STROKE, stroke_width=1)
                    )
                else:
                    # 无数据，绘制网格线
                    canvas.draw_rect(
                        rect,
                        ft.canvas.Paint(color=self.GRID_LINE_COLOR, style=ft.canvas.PaintStyle.STROKE, stroke_width=0.5)
                    )
                
                # 缓存单元格边界
                self._cell_bounds[coord] = rect
        
        # 绘制缩放和平移提示
        self._draw_info_overlay(canvas, width, height)
    
    def _get_color(self, size: int) -> str:
        """
        根据文件大小获取颜色
        
        使用冷到暖的颜色渐变：
        - 小文件：蓝色 (冷)
        - 中等文件：青色/绿色
        - 大文件：黄色/橙色
        - 很大文件：红色 (暖)
        
        Args:
            size: 文件大小（字节）
            
        Returns:
            十六进制颜色字符串
        """
        # 获取统计信息
        stats = self._heatmap_service.get_statistics()
        
        if stats["min_size"] == stats["max_size"]:
            # 所有文件大小相同
            return "#64B5F6"  # 中蓝色
        
        # 归一化大小到 0-1
        min_size = max(1, stats["min_size"])
        max_size = stats["max_size"]
        
        # 使用对数缩放（文件大小差异可能很大）
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
        # 使用 HSL 色彩空间，色相从 240° (蓝) 到 0° (红)
        if ratio < 0.2:
            # 蓝色到青色
            hue = 240 - ratio * 200  # 240 -> 200
            return self._hsl_to_hex(hue, 70, 60)
        elif ratio < 0.4:
            # 青色到绿色
            hue = 180 - (ratio - 0.2) * 200  # 180 -> 160
            return self._hsl_to_hex(hue, 70, 50)
        elif ratio < 0.6:
            # 绿色到黄色
            hue = 120 - (ratio - 0.4) * 300  # 120 -> 60
            return self._hsl_to_hex(hue, 80, 55)
        elif ratio < 0.8:
            # 黄色到橙色
            hue = 45 - (ratio - 0.6) * 100  # 45 -> 25
            return self._hsl_to_hex(hue, 85, 55)
        else:
            # 橙色到红色
            hue = 20 - (ratio - 0.8) * 60  # 20 -> 0
            return self._hsl_to_hex(hue, 80, 50)
    
    def _hsl_to_hex(self, h: float, s: float, l: float) -> str:
        """HSL 颜色转十六进制"""
        h = h / 360
        s = s / 100
        l = l / 100
        
        if s == 0:
            r = g = b = l
        else:
            def hue2rgb(p, q, t):
                if t < 0: t += 1
                if t > 1: t -= 1
                if t < 1/6: return p + (q - p) * 6 * t
                if t < 1/2: return q
                if t < 2/3: return p + (q - p) * (2/3 - t) * 6
                return p
            
            q = l * (1 + s) if l < 0.5 else l + s - l * s
            p = 2 * l - q
            r = hue2rgb(p, q, h + 1/3)
            g = hue2rgb(p, q, h)
            b = hue2rgb(p, q, h - 1/3)
        
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    
    def _draw_info_overlay(self, canvas, width: float, height: float) -> None:
        """绘制信息叠加层"""
        # 绘制缩放级别
        zoom_text = f"缩放: {self._transform.scale:.1f}x"
        canvas.draw_rect(
            ft.Rect(10, 10, 100, 24),
            ft.canvas.Paint(color="#00000088")
        )
        canvas.draw_text(
            zoom_text,
            ft.TextSpan(
                15, 25,
                ft.TextStyle(size=12, color="#FFFFFF88", font_family="monospace")
            )
        )
        
        # 绘制扫描进度
        if self._heatmap_service.is_scanning:
            progress = self._heatmap_service.scan_progress
            progress_text = f"扫描中: {int(progress * 100)}%"
            canvas.draw_rect(
                ft.Rect(10, height - 34, 120, 24),
                ft.canvas.Paint(color="#00000088")
            )
            canvas.draw_text(
                progress_text,
                ft.TextSpan(
                    15, height - 20,
                    ft.TextStyle(size=12, color="#64B5F6", font_family="monospace")
                )
            )
        
        # 绘制选中信息
        if self._selected_cell:
            coord = self._selected_cell
            size = self._current_data.get(coord, 0)
            size_str = self._format_size(size)
            
            info_text = f"区域 ({coord[0]}, {coord[1]}): {size_str}"
            text_width = len(info_text) * 7 + 20
            
            canvas.draw_rect(
                ft.Rect(width - text_width - 10, 10, text_width, 24),
                ft.canvas.Paint(color="#00000088")
            )
            canvas.draw_text(
                info_text,
                ft.TextSpan(
                    width - text_width, 25,
                    ft.TextStyle(size=12, color="#64B5F6", font_family="monospace")
                )
            )
    
    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        elif size >= 1024:
            return f"{size / 1024:.2f} KB"
        else:
            return f"{size} B"
    
    def _on_scale_start(self, e: ft.GestureEvent) -> None:
        """缩放开始"""
        self._last_focal_point = (e.focal_x, e.focal_y)
        self._last_scale = self._transform.scale
    
    def _on_scale_update(self, e: ft.GestureEvent) -> None:
        """缩放更新（支持滚轮和手势）"""
        if hasattr(e, 'scale') and e.scale != 1.0:
            # 手势缩放
            new_scale = self._last_scale * e.scale
            new_scale = max(0.1, min(10.0, new_scale))
            
            # 以焦点为中心缩放
            if self._last_focal_point:
                dx = e.focal_x - self._last_focal_point[0]
                dy = e.focal_y - self._last_focal_point[1]
                
                self._transform.offset_x += dx
                self._transform.offset_y += dy
            
            self._transform.scale = new_scale
            self._request_canvas_update()
    
    def _on_scale_end(self, e: ft.GestureEvent) -> None:
        """缩放结束"""
        pass
    
    def _on_hover(self, e: ft.GestureEvent) -> None:
        """鼠标悬停"""
        # 计算悬停的单元格
        screen_x, screen_y = e.x, e.y
        
        for coord, rect in self._cell_bounds.items():
            if (rect.x <= screen_x <= rect.x + rect.width and
                rect.y <= screen_y <= rect.y + rect.height):
                if self._hovered_cell != coord:
                    self._hovered_cell = coord
                    self._request_canvas_update()
                return
        
        if self._hovered_cell is not None:
            self._hovered_cell = None
            self._request_canvas_update()
    
    def _on_tap(self, e: ft.TapEvent) -> None:
        """点击选择"""
        screen_x, screen_y = e.x, e.y
        
        for coord, rect in self._cell_bounds.items():
            if (rect.x <= screen_x <= rect.x + rect.width and
                rect.y <= screen_y <= rect.y + rect.height):
                if coord in self._current_data:
                    self._selected_cell = coord
                    self._request_canvas_update()
                    
                    # 触发回调
                    if self._on_selection_changed:
                        size = self._current_data[coord]
                        self._on_selection_changed(coord, size)
                return
    
    def _request_canvas_update(self) -> None:
        """请求 Canvas 重绘"""
        if self._canvas:
            self._canvas.update()
    
    async def _update_loop(self) -> None:
        """异步更新循环 - 实现渐进式动态加载"""
        while self._heatmap_service.is_scanning:
            # 读取当前已有的部分数据进行重绘
            self._request_canvas_update()
            await asyncio.sleep(0.2)  # 每 200ms 刷新一次
        
        # 扫描完成后最后重绘一次
        self._request_canvas_update()
    
    def _trigger_canvas_rebuild(self) -> None:
        """触发 Canvas 重建"""
        # 重置缩放以适应新数据
        self._transform.scale = 1.0
        self._request_canvas_update()
    
    def did_mount(self) -> None:
        """组件挂载时启动更新循环"""
        super().did_mount()
        
        # 如果正在扫描，启动更新循环
        if self._heatmap_service.is_scanning:
            self._start_update_loop()
    
    def did_unmount(self) -> None:
        """组件卸载时停止更新循环"""
        super().did_unmount()
        self._stop_update_loop()
    
    def _start_update_loop(self) -> None:
        """启动异步更新循环"""
        if self._update_task is None or self._update_task.done():
            self._update_task = asyncio.create_task(self._update_loop())
    
    def _stop_update_loop(self) -> None:
        """停止异步更新循环"""
        if self._update_task and not self._update_task.done():
            self._update_task.cancel()
            try:
                # 等待任务取消
                import asyncio
                asyncio.get_event_loop().run_until_complete(self._update_task)
            except (asyncio.CancelledError, RuntimeError):
                pass
    
    def start_scan(self, region_dir: str) -> None:
        """
        启动热力图扫描
        
        Args:
            region_dir: region 目录路径
        """
        # 启动后台扫描
        asyncio.create_task(
            self._heatmap_service.start_silent_scan(region_dir)
        )
        
        # 启动更新循环
        self._start_update_loop()
    
    def refresh(self) -> None:
        """手动刷新热力图"""
        self._trigger_canvas_rebuild()
    
    def reset_view(self) -> None:
        """重置视图（缩放和平移）"""
        self._transform = ViewTransform()
        self._selected_cell = None
        self._request_canvas_update()
    
    def get_selected_cell(self) -> Optional[Tuple[int, int]]:
        """获取当前选中的单元格"""
        return self._selected_cell
    
    def set_zoom(self, scale: float) -> None:
        """设置缩放级别"""
        self._transform.scale = max(0.1, min(10.0, scale))
        self._request_canvas_update()
    
    def zoom_in(self) -> None:
        """放大"""
        self.set_zoom(self._transform.scale * 1.2)
    
    def zoom_out(self) -> None:
        """缩小"""
        self.set_zoom(self._transform.scale / 1.2)
