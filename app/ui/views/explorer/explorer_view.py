"""Explorer View - 存档浏览器主视图"""
import threading
import flet as ft
from typing import TYPE_CHECKING, Any, Optional, List, Dict, Tuple
from pathlib import Path

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost, btn_danger
from app.ui.components.fields import text_field
from app.ui.components.cards import card, placeholder

if TYPE_CHECKING:
    from app.application import Application

from core.omni.world_session import WorldSession
from app.services.heatmap_service import get_heatmap_service

from app.ui.views.explorer.utils import safe_update, format_size
from app.ui.views.explorer.world_info_panel import WorldInfoPanel
from app.ui.views.explorer.player_hud import PlayerHUDCard
from app.ui.views.explorer.equipment_preview import EquipmentPreview
from app.ui.views.explorer.inventory_grid import InventoryGrid
from app.ui.views.explorer.nbt_tree import NBTTreeView

# 尝试导入 Canvas 版本
try:
    from app.ui.views.mca_heatmap_view import McaHeatmapView
    CANVAS_AVAILABLE = True
except (ImportError, AttributeError):
    # Canvas 不可用，使用兼容性版本
    CANVAS_AVAILABLE = False
    try:
        from app.ui.views.mca_heatmap_view_compat import McaHeatmapViewCompat as McaHeatmapView
    except ImportError:
        McaHeatmapView = None


class ExplorerView(ft.Column):
    """存档浏览器视图"""

    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=0)
        self.expand = True
        self.app: "Application" = app
        self.world_session: Optional[WorldSession] = None
        self.current_uuid: Optional[str] = None
        self.player_uuid_map: Dict[str, str] = {}
        self._build()

    @property
    def _t(self):
        return self.app._t

    def _build(self) -> None:
        self.controls.clear()

        # 工具栏
        self._world_label = ft.Text(
            "未导入存档", size=12, color=THEME.text_muted,
        )
        toolbar = ft.Container(
            content=ft.Row([
                ft.Row([
                    ft.Text("🧭", size=26, color=THEME.mc_gold, font_family="monospace"),
                    ft.Column([
                        ft.Text("存档浏览器", size=22, weight=ft.FontWeight.BOLD,
                                color=THEME.text_primary, font_family="monospace"),
                        self._world_label,
                    ], spacing=0),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Container(),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(left=16, right=16, top=14, bottom=14),
            bgcolor=THEME.mc_dirt,
            border=ft.Border(
                left=ft.BorderSide(2, THEME.border_tertiary),
                top=ft.BorderSide(2, THEME.border_tertiary),
                right=ft.BorderSide(2, THEME.bg_secondary),
                bottom=ft.BorderSide(2, THEME.bg_secondary),
            ),
        )

        # 标签页容器
        self._tab_world_info = ft.Container()
        self._tab_world_info.expand = True
        self._tab_player = ft.Container()
        self._tab_player.expand = True
        self._tab_region = ft.Container()
        self._tab_region.expand = True
        self._tab_stats = ft.Container()
        self._tab_stats.expand = True
        self._tab_nbt = ft.Container()
        self._tab_nbt.expand = True
        
        self._tabs_content = [
            self._tab_world_info, 
            self._tab_player, 
            self._tab_region, 
            self._tab_stats,
            self._tab_nbt
        ]
        self._tab_index = 0

        # 标签页按钮
        self._tab_labels_widgets: List[ft.Text] = []
        self._tab_buttons: List[ft.Container] = []
        tab_label_conts: List[ft.Control] = []
        for idx, name in enumerate(["存档信息", "玩家", "区域", "统计", "NBT"]):
            icon = ["🌍", "🧍", "🧱", "📊", "📜"][idx]
            lbl = ft.Text(name, size=12, weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary if idx == 0 else THEME.text_secondary,
                        font_family="monospace")
            slot = ft.Container(
                content=ft.Column([
                    ft.Text(icon, size=20, text_align=ft.TextAlign.CENTER),
                    lbl,
                ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                width=92,
                height=64,
                alignment=ft.Alignment(0, 0),
                padding=ft.Padding(left=6, right=6, top=6, bottom=6),
                bgcolor=THEME.mc_stone if idx == 0 else THEME.bg_secondary,
                border=ft.Border(
                    left=ft.BorderSide(3, THEME.border_tertiary),
                    top=ft.BorderSide(3, THEME.border_tertiary),
                    right=ft.BorderSide(3, THEME.bg_secondary),
                    bottom=ft.BorderSide(3, THEME.bg_secondary),
                ),
                on_click=lambda e, i=idx: self._switch_tab(i),
            )
            self._tab_labels_widgets.append(lbl)
            self._tab_buttons.append(slot)
            tab_label_conts.append(slot)

        tab_labels_row = ft.Row(tab_label_conts, spacing=10)
        self._tab_indicator = ft.Container(height=4, bgcolor=THEME.mc_grass)
        self._tab_bar = ft.Container(
            content=ft.Column([tab_labels_row, self._tab_indicator], spacing=10),
            padding=ft.Padding(left=12, right=12, top=12, bottom=12),
            bgcolor=THEME.mc_coal,
            border=ft.Border(
                left=ft.BorderSide(2, THEME.border_tertiary),
                top=ft.BorderSide(2, THEME.border_tertiary),
                right=ft.BorderSide(2, THEME.bg_secondary),
                bottom=ft.BorderSide(2, THEME.bg_secondary),
            ),
        )
        self._content_box = ft.Container(
            content=self._tabs_content[0],
            padding=ft.Padding(left=12, right=12, top=12, bottom=12),
            bgcolor=THEME.bg_secondary,
            border=ft.Border(
                left=ft.BorderSide(2, THEME.border_tertiary),
                top=ft.BorderSide(2, THEME.border_tertiary),
                right=ft.BorderSide(2, THEME.bg_secondary),
                bottom=ft.BorderSide(2, THEME.bg_secondary),
            ),
        )
        self._content_box.expand = True

        self.controls.append(toolbar)
        col_tabs = ft.Column([self._tab_bar, self._content_box], spacing=8)
        col_tabs.expand = True
        self.controls.append(col_tabs)

        self._build_world_info_tab()
        self._build_player_tab()
        self._build_region_tab()
        self._build_stats_tab()
        self._build_nbt_tab()

    def _switch_tab(self, index: int) -> None:
        try:
            self._tab_index = index
            for i, lbl in enumerate(self._tab_labels_widgets):
                selected = i == index
                lbl.color = THEME.text_primary if selected else THEME.text_secondary
                if i < len(self._tab_buttons):
                    self._tab_buttons[i].bgcolor = THEME.mc_stone if selected else THEME.bg_secondary
            self._content_box.content = self._tabs_content[index]
            safe_update(self._content_box)
            safe_update(self._tab_bar)
        except Exception as e:
            self.app.handle_exception(e)

    def _build_world_info_tab(self) -> None:
        """构建存档信息标签页"""
        self._world_info_panel = WorldInfoPanel(self._t)
        self._tab_world_info.content = self._world_info_panel

    def _build_player_tab(self) -> None:
        left = ft.Column(spacing=10, width=300, scroll=ft.ScrollMode.AUTO)
        left.controls.append(
            ft.Text("选择玩家", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary)
        )
        self._player_dropdown = ft.Dropdown(
            options=[], on_select=self._on_player_selected,
            border_color=THEME.border_standard, text_size=13,
        )
        left.controls.append(self._player_dropdown)

        # 按钮行
        btn_row = ft.Row([
            btn_ghost("导入 usercache", height=30, on_click=self._import_usercache),
            btn_ghost("导入语言文件", height=30, on_click=self._import_language_file),
        ], spacing=8)
        left.controls.append(btn_row)

        self._player_hud = PlayerHUDCard()
        self._hud_card = card(self._player_hud, padding=15)
        left.controls.append(self._hud_card)

        self._equipment = EquipmentPreview()
        self._equip_card = card(self._equipment, padding=15)
        left.controls.append(self._equip_card)

        # 右侧物品栏初始状态 - 美化占位符
        right = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO)
        right.expand = True
        self._inventory = InventoryGrid()
        right.controls.append(self._inventory)

        self._tab_player.content = ft.Row([left, ft.Container(width=20), right], expand=True)

    def _build_region_tab(self) -> None:
        """构建区域标签页 - 使用热力图"""
        # 获取热力图服务
        self._heatmap_service = get_heatmap_service()
        self._current_dimension = "overworld"
        self._dimension_region_dirs: Dict[str, str] = {}
        self._selected_region_coord: Optional[Tuple[int, int]] = None

        # 维度切换下拉框（导入存档时动态填充）
        self._dimension_dropdown = ft.Dropdown(
            options=[],
            on_select=self._on_dimension_changed,
            border_color=THEME.border_standard,
            text_size=13,
            width=180,
        )

        dimension_row = ft.Row([
            ft.Text("维度：", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._dimension_dropdown,
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        # 创建热力图视图（兼容处理）
        if McaHeatmapView is None:
            self._heatmap = None
            heatmap_view = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.WARNING, size=48, color="#FF9800"),
                    ft.Text(
                        "热力图组件不可用",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary
                    ),
                    ft.Text(
                        "请升级 Flet 版本以启用热力图功能",
                        size=13,
                        color=THEME.text_muted
                    ),
                ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=50,
                bgcolor=THEME.bg_card,
                border_radius=8,
            )
        else:
            self._heatmap = McaHeatmapView(
                heatmap_service=self._heatmap_service,
                on_selection_changed=self._on_region_selected,
                width=700,
                height=450,
            )
            heatmap_view = self._heatmap

        help_text = ft.Text(
            "💡 提示：每个方块代表一个 32×32 区块的区域，颜色从蓝到红表示活动程度",
            size=12,
            color=THEME.text_muted,
            italic=True
        )

        self._region_stats_text = ft.Text(
            "等待导入存档...",
            size=12,
            color=THEME.text_muted
        )

        self._region_status_text = ft.Text(
            "👆 点击方块查看详情",
            size=13,
            color=THEME.text_secondary
        )

        action_row = ft.Row([
            btn_primary("🔄 刷新", width=100, on_click=lambda e: self._refresh_heatmap()),
            btn_ghost("🔍 放大", width=80, on_click=lambda e: self._heatmap_zoom_in()),
            btn_ghost("🔍 缩小", width=80, on_click=lambda e: self._heatmap_zoom_out()),
            btn_ghost("🏠 重置", width=80, on_click=lambda e: self._heatmap_reset_view()),
            btn_danger("删除选中区域", width=130, on_click=self._delete_selected_region),
        ], spacing=8)

        heatmap_card = card(
            ft.Container(
                content=heatmap_view,
                bgcolor=THEME.BACKGROUND_COLOR if hasattr(THEME, 'BACKGROUND_COLOR') else "#1E1E1E",
                border_radius=8,
            ),
            padding=0
        )

        stats_card = card(
            ft.Column([
                ft.Text("📊 区域统计", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                self._region_stats_text
            ], spacing=6),
            padding=12
        )

        selection_card = card(
            ft.Column([
                ft.Text("👆 点击详情", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                self._region_status_text
            ], spacing=6),
            padding=12
        )

        legend = self._create_heatmap_legend()

        col = ft.Column([
            dimension_row,
            ft.Container(height=8),
            help_text,
            heatmap_card,
            ft.Container(height=8),
            selection_card,
            ft.Container(height=8),
            stats_card,
            ft.Container(height=8),
            legend,
            ft.Container(height=8),
            action_row,
        ], spacing=0, scroll=ft.ScrollMode.AUTO)
        col.expand = True

        self._tab_region.content = col

    def _build_stats_tab(self) -> None:
        self._stats_status = ft.Text("导入存档后可分析统计。", size=12, color=THEME.text_muted)
        self._stats_summary = ft.Text("点击「开始统计」按钮分析世界数据。", size=12, color=THEME.text_muted)
        self._block_stats_col = ft.Column(spacing=4)
        self._entity_stats_col = ft.Column(spacing=4)
        self._size_stats_col = ft.Column(spacing=4)
        stats_col = ft.Column([
            card(ft.Row([
                btn_primary("开始统计", width=110, on_click=self._analyze_world_stats),
                self._stats_status,
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER), padding=12),
            card(ft.Column([ft.Text("汇总", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary), self._stats_summary], spacing=8), padding=12),
            card(ft.Column([ft.Text("方块分布 Top 10", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary), self._block_stats_col], spacing=8), padding=12),
            card(ft.Column([ft.Text("实体数量 Top 10", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary), self._entity_stats_col], spacing=8), padding=12),
            card(ft.Column([ft.Text("区域文件大小分布", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary), self._size_stats_col], spacing=8), padding=12),
        ], spacing=12, scroll=ft.ScrollMode.AUTO)
        stats_col.expand = True
        self._tab_stats.content = stats_col
    
    def _create_heatmap_legend(self) -> ft.Container:
        """创建颜色图例"""
        legend_items = ft.Row([
            ft.Container(
                content=ft.Text("冷", size=11, color=THEME.text_muted),
                padding=5,
            ),
            *[
                ft.Container(
                    width=25,
                    height=18,
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

    def _heatmap_zoom_in(self) -> None:
        heatmap = self._heatmap
        if heatmap is not None and hasattr(heatmap, "zoom_in"):
            heatmap.zoom_in()

    def _heatmap_zoom_out(self) -> None:
        heatmap = self._heatmap
        if heatmap is not None and hasattr(heatmap, "zoom_out"):
            heatmap.zoom_out()

    def _heatmap_reset_view(self) -> None:
        heatmap = self._heatmap
        if heatmap is not None and hasattr(heatmap, "reset_view"):
            heatmap.reset_view()
    
    def _on_region_selected(self, coord: Optional[Tuple[int, int]], size: Optional[int]) -> None:
        """区域选中回调"""
        stats = self._heatmap_service.get_statistics()
        if coord is None or size is None:
            self._selected_region_coord = None
            lines = [
                f"📊 区域总数: {stats['total_regions']} 个",
                f"💾 总大小: {format_size(stats['total_size'])}",
                f"📈 平均: {format_size(stats['avg_size'])}",
                f"🔍 最小: {format_size(stats['min_size'])} | 最大: {format_size(stats['max_size'])}"
            ]
            self._region_stats_text.value = "\n".join(lines)
            self._region_stats_text.color = THEME.text_primary
            self._region_status_text.value = "✅ 扫描完成，点击方块查看详情"
            self._region_status_text.color = THEME.text_secondary
            safe_update(self._region_stats_text)
            safe_update(self._region_status_text)
            return
        self._selected_region_coord = coord
        
        if stats['avg_size'] > 0:
            ratio = size / stats['avg_size']
            activity = "🔥 非常活跃" if ratio > 1.5 else \
                      "📗 较活跃" if ratio > 1.0 else \
                      "📙 一般" if ratio > 0.5 else "📕 不活跃"
            
            self._region_status_text.value = (
                f"✅ 已选择区域 ({coord[0]}, {coord[1]})\n"
                f"   💾 大小: {format_size(size)}\n"
                f"   {activity}（平均 {format_size(int(stats['avg_size']))}）"
            )
            self._region_status_text.color = THEME.accent_light
        else:
            self._region_status_text.value = f"✅ 已选择区域 ({coord[0]}, {coord[1]}): {format_size(size)}"
            self._region_status_text.color = THEME.text_primary
        
        safe_update(self._region_status_text)

    def _delete_selected_region(self, e: Any) -> None:
        try:
            if not self.world_session or not self._selected_region_coord:
                self.app.warn_dialog("提示", "请先在热力图中选择一个区域。")
                return
            region_dir = Path(self._dimension_region_dirs.get(self._current_dimension, ""))
            coord = self._selected_region_coord
            region_path = region_dir / f"r.{coord[0]}.{coord[1]}.mca"
            if not region_path.exists():
                self.app.warn_dialog("提示", f"区域文件不存在: {region_path.name}")
                return
            from app.services.region_editor_service import get_region_editor_service
            service = get_region_editor_service(log=self.app.log)
            if service.reset_region(region_path, backup=True):
                self.app.info_dialog("成功", f"已删除区域 {coord}，游戏下次进入会重新生成。备份文件保留为 .bak。")
                self._selected_region_coord = None
                self._refresh_heatmap()
            else:
                self.app.warn_dialog("失败", "区域删除失败，请查看日志。")
        except Exception as ex:
            self.app.handle_exception(ex, title="删除区域失败")

    def _build_nbt_tab(self) -> None:
        col = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
        col.expand = True
        
        # 搜索栏
        search_row = ft.Row([
            ft.Text("🔍 搜索:", size=14, color=THEME.text_primary),
            text_field(
                label="输入搜索内容",
                width=300,
                on_change=self._on_nbt_search
            ),
            btn_ghost("导出 JSON", on_click=self._export_nbt_json)
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        
        col.controls.append(card(search_row, padding=10))
        col.controls.append(
            ft.Text("NBT 数据查看器", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary)
        )
        self._nbt_tree = NBTTreeView()
        c = ft.Container(content=self._nbt_tree)
        c.expand = True
        col.controls.append(c)
        self._tab_nbt.content = col

    def _load_world(self, path: Any = None) -> None:
        try:
            if path is None or hasattr(path, "control"):
                path = getattr(self.app, "_current_save_path", None)
            if not path:
                self.app.warn_dialog("提示", "请先通过侧边栏导入存档。")
                return
            
            self.world_session = WorldSession(Path(path), log=self.app.log)
            self._world_label.value = f"当前存档: {self.world_session.world_path.name}"
            safe_update(self._world_label)

            # 更新存档信息面板
            world_info = self.world_session.get_world_info()
            stats = {
                "player_count": len(self.world_session.get_player_uuids()),
                "region_count": len(self.world_session._region_files),
            }
            self._world_info_panel.update_info(world_info, stats=stats)

            # 获取完整的玩家名称映射
            player_names = self.world_session.get_player_names()

            # 填充玩家下拉列表
            players = []
            for uuid, name in player_names.items():
                display = name or uuid
                formatted = self.world_session._format_uuid_with_hyphens(uuid)
                players.append((formatted, display))
            self._player_dropdown.options = [
                ft.dropdown.Option(v[0], v[1]) for v in players
            ]
            safe_update(self._player_dropdown)
            
            # 自动选择第一个玩家并加载其数据
            if players:
                first_player_uuid = players[0][0]
                self._player_dropdown.value = first_player_uuid
                safe_update(self._player_dropdown)
                self._load_player_data(first_player_uuid)

            # 扫描并填充维度列表
            self._update_dimension_list()

            self._refresh_heatmap()
        except Exception as ex:
            self.app.handle_exception(ex, title="导入存档失败")

    def _on_player_selected(self, e: Any) -> None:
        try:
            if not self.world_session or not e.control.value:
                return
            self._load_player_data(e.control.value)
        except Exception as ex:
            self.app.handle_exception(ex, title="加载玩家数据失败")
    
    def _load_player_data(self, uuid: str) -> None:
        """加载指定 UUID 的玩家数据"""
        try:
            if not self.world_session:
                return
            self.current_uuid = uuid
            player_data = self.world_session.load_player_data(uuid)
            self._player_hud.update_from_nbt(player_data)
            inv = self.world_session.get_player_inventory(uuid)
            self._inventory.set_inventory(inv)
            self._equipment.set_equipment(inv)
            nbt = self.world_session.load_player_nbt(uuid)
            self._nbt_tree.load_nbt(nbt)
        except Exception as e:
            self.app.handle_exception(e, title="加载玩家数据失败")

    def _refresh_heatmap(self) -> None:
        """刷新热力图"""
        try:
            if not self.world_session:
                return
            self._selected_region_coord = None

            region_dir_str = self._dimension_region_dirs.get(self._current_dimension)
            if not region_dir_str:
                self._region_stats_text.value = "⚠️ 未找到当前维度的 region 目录"
                self._region_stats_text.color = THEME.warning
                safe_update(self._region_stats_text)
                return

            region_dir = Path(region_dir_str)
            if not region_dir.exists():
                self._region_stats_text.value = "⚠️ region 目录不存在"
                self._region_stats_text.color = THEME.warning
                safe_update(self._region_stats_text)
                return

            self._heatmap_service.clear_data()
            self._region_stats_text.value = "🔄 正在扫描..."
            self._region_stats_text.color = THEME.accent
            safe_update(self._region_stats_text)

            heatmap = self._heatmap
            if heatmap is not None and hasattr(heatmap, 'start_scan'):
                heatmap.start_scan(str(region_dir))
            else:
                self.app.warn_dialog("提示", "当前热力图组件不支持后台扫描")
        except Exception as e:
            self.app.handle_exception(e, title="刷新热力图失败")

    def _analyze_world_stats(self, e: Any) -> None:
        try:
            if not self.world_session:
                self.app.warn_dialog("提示", "请先通过侧边栏导入存档。")
                return
            from app.services.world_stats_service import get_world_stats_service
            service = get_world_stats_service(log=self.app.log)
            self._stats_status.value = "正在分析，较大存档可能需要较长时间..."
            safe_update(self._stats_status)
            
            def _run():
                try:
                    stats = service.analyze_world(self.world_session.world_path)
                    def _update_ui():
                        try:
                            loaded_ratio = (stats.loaded_chunks / (stats.loaded_chunks + stats.empty_chunks) * 100) if (stats.loaded_chunks + stats.empty_chunks) else 0
                            total_size = sum(stats.region_sizes.values())
                            self._stats_summary.value = (
                                f"区域: {stats.total_regions}\n"
                                f"已加载区块: {stats.loaded_chunks}，空/未加载槽位: {stats.empty_chunks}，加载比例: {loaded_ratio:.1f}%\n"
                                f"区域文件总大小: {format_size(total_size)}\n"
                                f"方块调色板条目: {stats.total_blocks}，实体/方块实体: {stats.total_entities}"
                            )
                            self._fill_rank(self._block_stats_col, stats.block_stats.top_blocks[:10] if stats.block_stats else [])
                            self._fill_rank(self._entity_stats_col, stats.entity_stats.top_entities[:10] if stats.entity_stats else [])
                            self._fill_rank(self._size_stats_col, list(service.get_region_size_distribution(stats).items()))
                            self._stats_status.value = "统计完成。"
                            safe_update(self._tab_stats)
                        except Exception as ex:
                            self.app.handle_exception(ex, title="统计存档失败")
                    self.app.page.run_task(_update_ui)
                except Exception as ex:
                    self.app.page.run_task(lambda: self.app.handle_exception(ex, title="统计存档失败"))
            
            threading.Thread(target=_run, daemon=True).start()
        except Exception as ex:
            self.app.handle_exception(ex, title="统计存档失败")

    def _fill_rank(self, col: ft.Column, items: List[Tuple[str, int]]) -> None:
        col.controls.clear()
        if not items:
            col.controls.append(ft.Text("暂无数据", size=12, color=THEME.text_muted))
            return
        max_value = max(value for _, value in items) or 1
        for name, value in items:
            col.controls.append(ft.Row([
                ft.Text(str(name), size=11, color=THEME.text_secondary, width=240),
                ft.ProgressBar(value=value / max_value, width=180, color=THEME.mc_grass, bgcolor=THEME.bg_secondary),
                ft.Text(str(value), size=11, color=THEME.text_muted),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))

    def _update_dimension_list(self) -> None:
        """扫描存档并更新维度下拉列表"""
        try:
            if not self.world_session:
                return

            dimensions = self.world_session.get_dimensions()
            self._dimension_region_dirs.clear()

            options = []
            for dim in dimensions:
                dim_id = dim["id"]
                dim_name = dim["name"]
                region_dir = dim["region_dir"]
                self._dimension_region_dirs[dim_id] = region_dir
                options.append(ft.dropdown.Option(dim_id, dim_name))

            self._dimension_dropdown.options = options

            if options:
                if self._current_dimension not in self._dimension_region_dirs:
                    self._current_dimension = options[0].key
                self._dimension_dropdown.value = self._current_dimension
            else:
                self._current_dimension = ""

            safe_update(self._dimension_dropdown)
        except Exception as e:
            self.app.handle_exception(e, title="扫描维度失败")

    def _on_dimension_changed(self, e: Any) -> None:
        """维度切换回调"""
        try:
            new_dim = e.control.value
            if new_dim == self._current_dimension:
                return
            self._current_dimension = new_dim
            self._refresh_heatmap()
        except Exception as ex:
            self.app.handle_exception(ex, title="切换维度失败")
    
    def _update_region_stats(self) -> None:
        """更新区域统计信息"""
        stats = self._heatmap_service.get_statistics()

        lines = [
            f"📊 区域总数: {stats['total_regions']} 个",
            f"💾 总大小: {format_size(stats['total_size'])}",
            f"📈 平均: {format_size(stats['avg_size'])}",
            f"🔍 最小: {format_size(stats['min_size'])} | 最大: {format_size(stats['max_size'])}"
        ]
        
        self._region_stats_text.value = "\n".join(lines)
        self._region_stats_text.color = THEME.text_primary
        safe_update(self._region_stats_text)

    def _import_usercache(self, e: Any = None) -> None:
        try:
            path = self.app.pick_file(
                title="选择 usercache.json",
                file_types=[("JSON 文件 (*.json)", "*.json")],
            )
            if path and self.world_session:
                imported = self.world_session.import_usercache(Path(path))
                if imported > 0:
                    player_names = self.world_session.get_player_names()
                    players = []
                    for uuid, name in player_names.items():
                        display = name or uuid
                        formatted = self.world_session._format_uuid_with_hyphens(uuid)
                        players.append((formatted, display))
                    self._player_dropdown.options = [
                        ft.dropdown.Option(v[0], v[1]) for v in players
                    ]
                    safe_update(self._player_dropdown)
                    self.app.info_dialog("成功", f"成功导入 {imported} 个玩家名称。")
                else:
                    self.app.info_dialog("提示", "未能导入任何玩家名称。")
        except Exception as ex:
            self.app.handle_exception(ex, title="导入 usercache 失败")

    def _import_language_file(self, e: Any = None) -> None:
        """导入 Minecraft 语言文件（支持模组）"""
        try:
            path = self.app.pick_file(
                title="选择语言文件 (zh_cn.json 等)",
                file_types=[("JSON 文件 (*.json)", "*.json")],
            )
            if path:
                from app.services.item_service import get_item_service
                item_service = get_item_service()
                count = item_service.load_language_file(Path(path))
                if count > 0:
                    self.app.info_dialog("成功", f"成功导入 {count} 个物品/附魔名称。\n物品栏和装备预览将使用新名称。")
                    # 刷新当前显示
                    if self.current_uuid:
                        self._load_player_data(self.current_uuid)
                else:
                    self.app.info_dialog("提示", "未能从文件中解析出有效的物品名称。\n\n支持的格式：\n- Minecraft 语言文件 (item.minecraft.xxx)\n- 直接 ID 映射 (minecraft:xxx)")
        except Exception as ex:
            self.app.handle_exception(ex, title="导入语言文件失败")
    
    def _on_nbt_search(self, e: Any) -> None:
        try:
            self._nbt_tree.search(e.control.value or "")
        except Exception as ex:
            self.app.handle_exception(ex, title="搜索 NBT 失败")
    
    def _export_nbt_json(self, e: Any) -> None:
        try:
            if not self._nbt_tree._root_data:
                self.app.warn_dialog("提示", "没有可导出的 NBT 数据")
                return
            
            path = self.app.save_file(
                title="保存 JSON 文件",
                default_ext=".json",
                file_types=[("JSON 文件 (*.json)", "*.json")]
            )
            if path:
                success = self._nbt_tree.export_json(path)
                if success:
                    self.app.info_dialog("成功", f"已导出到: {path}")
                else:
                    self.app.error_dialog("失败", "导出 JSON 失败")
        except Exception as ex:
            self.app.handle_exception(ex, title="导出 JSON 失败")
