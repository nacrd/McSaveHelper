"""MCA Heatmap component"""
import flet as ft
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.ui.theme import THEME
from app.ui.views.explorer.utils import safe_update, format_size


class MCAHeatmap(ft.Container):
    """区域文件热力图 - 简单直观的区域查看器"""

    def __init__(self, cell_size: int = 28) -> None:
        super().__init__()
        self._cell_size = cell_size
        self._selected: Set[Tuple[int, int]] = set()
        self._cells: Dict[Tuple[int, int], ft.Container] = {}
        self._region_files: Dict[Tuple[int, int], Path] = {}
        
        # 统计信息
        self._stats_text = ft.Text(
            "设置当前存档后显示统计",
            size=12,
            color=THEME.text_muted
        )
        
        # 选中信息
        self._selection_text = ft.Text(
            "👆 点击方块查看详情",
            size=13,
            color=THEME.text_secondary
        )
        
        # 颜色图例
        legend_row = ft.Row([
            ft.Text("颜色说明：", size=12, color=THEME.text_secondary),
            ft.Container(width=16, height=16, bgcolor="#64B5F6", border_radius=2),  # 浅蓝
            ft.Text("小", size=11, color=THEME.text_muted),
            ft.Container(width=16, height=16, bgcolor="#1565C0", border_radius=2),  # 深蓝
            ft.Text("大", size=11, color=THEME.text_muted),
        ], spacing=6, alignment=ft.MainAxisAlignment.START)
        
        # 内部网格
        self._grid = ft.GridView(
            runs_count=0,
            max_extent=cell_size + 2,
            spacing=2,
            child_aspect_ratio=1.0,
            expand=True
        )
        
        # 组装布局
        content = ft.Column([
            ft.Text("🗺️ 世界区域地图", size=16, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            legend_row,
            ft.Container(height=8),  # 间距
            self._grid,
        ], spacing=8)
        
        self.content = content

    def set_region_files(self, region_files: Dict[Tuple[int, int], Path]) -> None:
        self._region_files = region_files
        self._cells.clear()
        self._selected.clear()
        
        # 计算统计信息
        if not region_files:
            self._stats_text.value = "⚠️ 未找到区域文件"
            self._selection_text.value = "👆 点击方块查看详情"
            self._grid.controls.clear()
            safe_update(self)
            return
        
        # 计算文件大小统计
        sizes = []
        for path in region_files.values():
            try:
                sizes.append(path.stat().st_size)
            except Exception:
                pass
        
        total_size = sum(sizes) if sizes else 0
        avg_size = total_size // len(sizes) if sizes else 0
        max_size = max(sizes) if sizes else 0
        min_size = min(sizes) if sizes else 0

        stats_lines = [
            f"📊 区域文件总数：{len(region_files)} 个",
            f"💾 总大小：{format_size(total_size)}",
            f"📈 平均大小：{format_size(avg_size)}",
            f"🔍 最小：{format_size(min_size)} | 最大：{format_size(max_size)}"
        ]
        self._stats_text.value = "\n".join(stats_lines)
        self._selection_text.value = "👆 点击方块查看详情"
        
        # 构建网格
        self._grid.controls.clear()
        xs = [c[0] for c in region_files]
        zs = [c[1] for c in region_files]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        
        # 记录全局最大最小值用于颜色映射
        self._global_min_size = min_size
        self._global_max_size = max_size if max_size > 0 else 1
        
        for z in range(min_z, max_z + 1):
            for x in range(min_x, max_x + 1):
                cell = self._create_cell((x, z), region_files.get((x, z)))
                self._cells[(x, z)] = cell
                self._grid.controls.append(cell)
        
        safe_update(self)

    def _create_cell(self, coord: Tuple[int, int], path: Optional[Path]) -> ft.Container:
        """创建单个区域方块"""
        # 根据相对大小计算颜色
        bg = self._get_color_for_path(path)
        
        def on_click(e):
            try:
                # 切换选中状态
                if coord in self._selected:
                    self._selected.remove(coord)
                    cell.border = ft.Border(
                        left=ft.BorderSide(1, THEME.border_subtle),
                        top=ft.BorderSide(1, THEME.border_subtle),
                        right=ft.BorderSide(1, THEME.border_subtle),
                        bottom=ft.BorderSide(1, THEME.border_subtle)
                    )
                else:
                    self._selected.add(coord)
                    cell.border = ft.Border(
                        left=ft.BorderSide(2, THEME.accent),
                        top=ft.BorderSide(2, THEME.accent),
                        right=ft.BorderSide(2, THEME.accent),
                        bottom=ft.BorderSide(2, THEME.accent)
                    )
                
                # 更新选中信息显示
                self._update_selection_info(coord, path)
                safe_update(cell)
                safe_update(self)
            except Exception:
                pass
        
        cell = ft.Container(
            width=self._cell_size,
            height=self._cell_size,
            bgcolor=bg,
            border=ft.Border(
                left=ft.BorderSide(1, THEME.border_subtle),
                top=ft.BorderSide(1, THEME.border_subtle),
                right=ft.BorderSide(1, THEME.border_subtle),
                bottom=ft.BorderSide(1, THEME.border_subtle)
            ),
            border_radius=3,
            on_click=on_click,
            tooltip=f"区域 ({coord[0]}, {coord[1]})"
        )
        return cell

    def _get_color_for_path(self, path: Optional[Path]) -> str:
        """根据文件大小获取颜色"""
        if path is None:
            return THEME.bg_card
        
        try:
            size = path.stat().st_size
            # 使用对数缩放让颜色分布更均匀
            min_s = max(1, self._global_min_size)
            max_s = max(1, self._global_max_size)
            
            # 对数缩放
            log_min = math.log(max(1, min_s))
            log_max = math.log(max(1, max_s))
            log_size = math.log(max(1, size))
            
            # 归一化到 0-1
            if log_max > log_min:
                ratio = (log_size - log_min) / (log_max - log_min)
            else:
                ratio = 0.5
            ratio = max(0, min(1, ratio))
            
            # 蓝色渐变：浅蓝 -> 深蓝
            # 浅色：RGB(100, 181, 246) #64B5F6
            # 深色：RGB(21, 101, 192)  #1565C0
            r = int(100 + ratio * (21 - 100))
            g = int(181 + ratio * (101 - 181))
            b = int(246 + ratio * (192 - 246))
            
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return THEME.bg_card

    def _update_selection_info(self, coord: Tuple[int, int], path: Optional[Path]) -> None:
        """更新选中区域的信息显示"""
        if path is None:
            self._selection_text.value = f"⚠️ 区域 ({coord[0]}, {coord[1]}) 不存在"
            self._selection_text.color = THEME.warning
        else:
            try:
                size = path.stat().st_size
                # 计算相对于平均的大小
                avg_size = sum(p.stat().st_size for p in self._region_files.values() if p) / len(self._region_files)
                ratio = size / avg_size if avg_size > 0 else 1
                
                if ratio > 1.5:
                    activity = "🔥 非常活跃"
                elif ratio > 1.0:
                    activity = "📗 较活跃"
                elif ratio > 0.5:
                    activity = "📙 一般"
                else:
                    activity = "📕 不活跃"
                
                self._selection_text.value = (
                    f"✅ 已选择区域 ({coord[0]}, {coord[1]})\n"
                    f"   💾 文件大小：{format_size(size)}\n"
                    f"   {activity}（相对于平均大小 {ratio:.1f}x）"
                )
                self._selection_text.color = THEME.accent_light
            except Exception:
                self._selection_text.value = f"❓ 区域 ({coord[0]}, {coord[1]}) - 无法读取信息"
                self._selection_text.color = THEME.error

    def get_selected(self) -> List[Tuple[int, int]]:
        return list(self._selected)

    def clear_selection(self) -> None:
        for c in self._selected:
            if c in self._cells:
                self._cells[c].border = ft.Border(
                    left=ft.BorderSide(1, THEME.border_subtle),
                    top=ft.BorderSide(1, THEME.border_subtle),
                    right=ft.BorderSide(1, THEME.border_subtle),
                    bottom=ft.BorderSide(1, THEME.border_subtle)
                )
        self._selected.clear()
        self._selection_text.value = "👆 点击方块查看详情"
        self._selection_text.color = THEME.text_secondary
        safe_update(self)