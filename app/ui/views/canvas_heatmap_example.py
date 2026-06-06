"""
MCA 热力图集成示例

展示如何在 ExplorerView 中集成新的 Canvas 热力图组件。
"""
import flet as ft
from pathlib import Path
from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from app.application import Application

from app.services.heatmap_service import get_heatmap_service
from app.ui.views.mca_heatmap_view import McaHeatmapView
from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.cards import card


class CanvasHeatmapTab(ft.Column):
    """
    Canvas 风格热力图标签页
    
    展示如何使用新的 McaHeatmapView 组件
    """
    
    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=12)
        self.app = app
        self.world_session = None
        
        # 获取热力图服务
        self._heatmap_service = get_heatmap_service()
        
        # 状态显示
        self._status_text = ft.Text(
            "💡 加载存档后自动开始扫描区域文件...",
            size=13,
            color=THEME.text_secondary
        )
        
        # 统计信息
        self._stats_text = ft.Text(
            "等待加载存档...",
            size=12,
            color=THEME.text_muted
        )
        
        # 创建 Canvas 热力图视图
        self._heatmap_view = McaHeatmapView(
            heatmap_service=self._heatmap_service,
            on_selection_changed=self._on_region_selected,
            width=700,
            height=450,
        )
        
        self._build()
    
    def _build(self) -> None:
        """构建 UI"""
        # 标题和提示
        header = ft.Column([
            ft.Text(
                "🗺️ 世界区域地图 (Canvas)",
                size=18,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary
            ),
            ft.Text(
                "颜色从蓝到红表示活动程度（冷到暖）",
                size=12,
                color=THEME.text_muted
            ),
        ], spacing=4)
        
        # 操作按钮
        action_row = ft.Row([
            btn_primary(
                "🔄 重新扫描",
                on_click=self._rescan,
                width=120
            ),
            btn_ghost(
                "🔍 放大",
                on_click=lambda e: self._heatmap_view.zoom_in(),
                width=80
            ),
            btn_ghost(
                "🔍 缩小",
                on_click=lambda e: self._heatmap_view.zoom_out(),
                width=80
            ),
            btn_ghost(
                "🏠 重置视图",
                on_click=lambda e: self._heatmap_view.reset_view(),
                width=90
            ),
        ], spacing=8)
        
        # 热力图容器
        heatmap_card = card(
            ft.Container(
                content=self._heatmap_view,
                bgcolor=THEME.BACKGROUND_COLOR if hasattr(THEME, 'BACKGROUND_COLOR') else "#1E1E1E",
                border_radius=8,
            ),
            padding=0
        )
        
        # 状态卡片
        status_card = card(
            ft.Column([
                ft.Text("📊 扫描状态", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                self._status_text,
                self._stats_text,
            ], spacing=6),
            padding=12
        )
        
        # 颜色图例
        legend = self._create_legend()
        
        # 添加到布局
        self.controls.extend([
            header,
            action_row,
            heatmap_card,
            legend,
            status_card,
        ])
    
    def _create_legend(self) -> ft.Container:
        """创建颜色图例"""
        legend_items = ft.Row([
            ft.Container(
                content=ft.Text("冷", size=11, color=THEME.text_muted),
                padding=5,
            ),
            *[
                ft.Container(
                    width=30,
                    height=20,
                    bgcolor=color,
                    border_radius=3,
                )
                for color in ["#64B5F6", "#4DB6AC", "#CDDC39", "#FFA726", "#FF5722"]
            ],
            ft.Container(
                content=ft.Text("暖", size=11, color=THEME.text_muted),
                padding=5,
            ),
        ], spacing=2)
        
        return card(
            ft.Row([
                ft.Text("颜色图例：", size=12, color=THEME.text_secondary),
                legend_items,
                ft.Text("(小文件 → 大文件)", size=11, color=THEME.text_muted),
            ], spacing=10),
            padding=10
        )
    
    def _on_region_selected(self, coord: Tuple[int, int], size: int) -> None:
        """区域选中回调"""
        def format_size(size):
            kb = size / 1024
            mb = kb / 1024
            if mb >= 1:
                return f"{mb:.2f} MB"
            elif kb >= 1:
                return f"{kb:.2f} KB"
            else:
                return f"{size} B"
        
        self._status_text.value = f"✅ 已选择区域 ({coord[0]}, {coord[1]})"
        self._status_text.color = THEME.accent_light
        
        # 显示统计
        stats = self._heatmap_service.get_statistics()
        if stats["total_regions"] > 0:
            avg = stats["avg_size"]
            ratio = size / avg if avg > 0 else 1
            
            activity = "🔥 非常活跃" if ratio > 1.5 else \
                      "📗 较活跃" if ratio > 1.0 else \
                      "📙 一般" if ratio > 0.5 else "📕 不活跃"
            
            self._stats_text.value = f"💾 大小: {format_size(size)} | {activity} (平均 {format_size(avg)})"
        
        self._safe_update()
    
    def load_world(self, world_path: Path) -> None:
        """加载存档并启动扫描"""
        try:
            self.world_session = world_path
            region_dir = world_path / "region"
            
            if not region_dir.exists():
                self._status_text.value = "⚠️ 未找到 region 目录"
                self._status_text.color = THEME.warning
                self._safe_update()
                return
            
            # 更新状态
            self._status_text.value = "🔄 正在扫描区域文件..."
            self._status_text.color = THEME.accent
            self._safe_update()
            
            # 启动后台扫描
            self._heatmap_service.clear_data()
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                self._heatmap_service.start_silent_scan(str(region_dir))
            )
            
            # 更新统计
            self._update_stats()
            
        except Exception as e:
            self._status_text.value = f"❌ 扫描失败: {str(e)}"
            self._status_text.color = THEME.error
            self._safe_update()
    
    def _rescan(self, e: ft.ControlEvent = None) -> None:
        """重新扫描"""
        if self.world_session:
            self.load_world(self.world_session)
    
    def _update_stats(self) -> None:
        """更新统计信息"""
        stats = self._heatmap_service.get_statistics()
        
        def format_size(size):
            kb = size / 1024
            mb = kb / 1024
            if mb >= 1:
                return f"{mb:.1f} MB"
            elif kb >= 1:
                return f"{kb:.1f} KB"
            else:
                return f"{size} B"
        
        lines = [
            f"📊 区域总数: {stats['total_regions']} 个",
            f"💾 总大小: {format_size(stats['total_size'])}",
            f"📈 平均: {format_size(stats['avg_size'])}",
            f"🔍 最小: {format_size(stats['min_size'])} | 最大: {format_size(stats['max_size'])}"
        ]
        
        self._stats_text.value = "\n".join(lines)
        self._stats_text.color = THEME.text_primary
        
        self._status_text.value = "✅ 扫描完成"
        self._status_text.color = THEME.success if hasattr(THEME, 'success') else THEME.accent
        
        self._safe_update()
    
    def _safe_update(self) -> None:
        """安全更新"""
        try:
            self.update()
        except RuntimeError:
            pass
