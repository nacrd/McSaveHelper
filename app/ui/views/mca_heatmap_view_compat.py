"""
MCA 热力图兼容性视图组件

使用 Container 网格实现（兼容不支持 Canvas 的 Flet 版本），
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


class McaHeatmapViewCompat(ft.Container):
    """
    MCA 热力图兼容性视图组件
    
    使用 Container 网格实现，兼容不支持 Canvas 的 Flet 版本。
    特性：
    - Container 网格绘制
    - 颜色映射：冷色（蓝）到暖色（红）
    - 支持缩放和平移
    - 点击选中
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
        on_selection_changed: Optional[callable] = None,
        width: int = 700,
        height: int = 450,
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
        
        # 缓存当前数据用于绘制
        self._current_data: Dict[Tuple[int, int], int] = {}
        self._cell_containers: Dict[Tuple[int, int], ft.Container] = {}
        
        # 布局配置
        self.width = width
        self.height = height
        self.expand = True
        self.bgcolor = self.BACKGROUND_COLOR
        self.border_radius = 8
        
        # 内部网格容器
        self._grid_container = ft.Container()
        self._grid = ft.Column(spacing=self.CELL_GAP)
        self._grid_container.content = self._grid
        
        # 组装布局
        self.content = ft.Stack([self._grid_container])
        
        # 异步更新任务
        self._update_task: Optional[asyncio.Task] = None
    
    def _rebuild_grid(self) -> None:
        """重建网格"""
        # 获取当前数据
        self._current_data = self._heatmap_service.get_all_data()
        
        if not self._current_data:
            self._grid.controls.clear()
            self._grid.update()
            return
        
        # 计算世界坐标范围
        coords = list(self._current_data.keys())
        if not coords:
            return
            
        min_x = min(c[0] for c in coords)
        max_x = max(c[0] for c in coords)
        min_z = min(c[1] for c in coords)
        max_z = max(c[1] for c in coords)
        
        # 清空旧网格
        self._grid.controls.clear()
        self._cell_containers.clear()
        
        # 重建网格（从左上到右下）
        for z in range(min_z, max_z + 1):
            row = ft.Row(spacing=self.CELL_GAP)
            
            for x in range(min_x, max_x + 1):
                coord = (x, z)
                
                if coord in self._current_data:
                    # 有数据
                    size = self._current_data[coord]
                    color = self._get_color(size)
                    
                    cell = ft.Container(
                        width=self.CELL_SIZE,
                        height=self.CELL_SIZE,
                        bgcolor=color,
                        border_radius=3,
                        on_click=lambda e, c=coord: self._on_cell_click(c),
                    )
                else:
                    # 无数据，显示网格线
                    cell = ft.Container(
                        width=self.CELL_SIZE,
                        height=self.CELL_SIZE,
                        bgcolor="transparent",
                        border=ft.border.all(1, self.GRID_LINE_COLOR),
                        border_radius=3,
                    )
                
                self._cell_containers[coord] = cell
                row.controls.append(cell)
            
            self._grid.controls.append(row)
        
        self._grid.update()
    
    def _get_color(self, size: int) -> str:
        """
        根据文件大小获取颜色
        
        使用冷到暖的颜色渐变：
        - 小文件：蓝色 (冷)
        - 中等文件：青色/绿色
        - 大文件：黄色/橙色
        - 很大文件：红色 (暖)
        """
        # 获取统计信息
        stats = self._heatmap_service.get_statistics()
        
        if stats["min_size"] == stats["max_size"]:
            return "#64B5F6"
        
        # 归一化大小到 0-1
        min_size = max(1, stats["min_size"])
        max_size = stats["max_size"]
        
        # 使用对数缩放
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
    
    def _on_cell_click(self, coord: Tuple[int, int]) -> None:
        """单元格点击"""
        if coord in self._current_data:
            self._selected_cell = coord
            size = self._current_data[coord]
            
            # 触发回调
            if self._on_selection_changed:
                self._on_selection_changed(coord, size)
            
            # 更新视觉效果
            self._update_selection_visual()
    
    def _update_selection_visual(self) -> None:
        """更新选中视觉效果"""
        for coord, container in self._cell_containers.items():
            if coord == self._selected_cell:
                container.border = ft.border.all(2, "#FFFFFF")
            else:
                if coord in self._current_data:
                    container.border = None
                else:
                    container.border = ft.border.all(1, self.GRID_LINE_COLOR)
        
        try:
            self.update()
        except RuntimeError:
            pass
    
    async def _update_loop(self) -> None:
        """异步更新循环 - 实现渐进式动态加载"""
        while self._heatmap_service.is_scanning:
            # 重建网格
            self._rebuild_grid()
            await asyncio.sleep(0.3)  # 每 300ms 刷新一次
        
        # 扫描完成后最后重建一次
        self._rebuild_grid()
    
    def _trigger_rebuild(self) -> None:
        """触发网格重建"""
        self._rebuild_grid()
    
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
        self._rebuild_grid()
    
    def reset_view(self) -> None:
        """重置视图（缩放和平移）"""
        self._transform = ViewTransform()
        self._selected_cell = None
        self.refresh()
    
    def zoom_in(self) -> None:
        """放大（暂未实现）"""
        pass
    
    def zoom_out(self) -> None:
        """缩小（暂未实现）"""
        pass
    
    def get_selected_cell(self) -> Optional[Tuple[int, int]]:
        """获取当前选中的单元格"""
        return self._selected_cell
