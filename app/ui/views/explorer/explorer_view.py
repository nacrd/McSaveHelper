"""Explorer View - 存档浏览器主视图"""
import flet as ft
from typing import TYPE_CHECKING, Any, Optional, List, Dict, Tuple
from pathlib import Path

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field
from app.ui.components.cards import card

if TYPE_CHECKING:
    from app.application import Application

from core.omni.world_session import WorldSession
from app.services.heatmap_service import get_heatmap_service

from app.ui.views.explorer.utils import safe_update
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
        from app.ui.views.mca_heatmap_view_compat import McaHeatmapView
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
            "未加载存档", size=12, color=THEME.text_muted,
        )
        toolbar = ft.Container(
            content=ft.Row([
                ft.Text("📂 存档浏览器", size=24, weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary),
                self._world_label,
                ft.Container(),
                btn_primary("加载存档", on_click=self._load_world),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(bottom=16),
        )

        # 标签页容器
        self._tab_world_info = ft.Container()
        self._tab_world_info.expand = True
        self._tab_player = ft.Container()
        self._tab_player.expand = True
        self._tab_region = ft.Container()
        self._tab_region.expand = True
        self._tab_nbt = ft.Container()
        self._tab_nbt.expand = True
        
        self._tabs_content = [
            self._tab_world_info, 
            self._tab_player, 
            self._tab_region, 
            self._tab_nbt
        ]
        self._tab_index = 0

        # 标签页按钮
        self._tab_labels_widgets: List[ft.Text] = []
        tab_label_conts: List[ft.Container] = []
        for idx, name in enumerate(["存档信息", "玩家", "区域", "NBT"]):
            lbl = ft.Text(name, size=14, weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary if idx == 0 else THEME.text_secondary)
            self._tab_labels_widgets.append(lbl)
            tab_label_conts.append(ft.Container(
                content=lbl,
                padding=ft.Padding(right=24, bottom=8),
                on_click=lambda e, i=idx: self._switch_tab(i),
            ))

        tab_labels_row = ft.Row(tab_label_conts, spacing=0)
        self._tab_indicator = ft.Container(height=2, bgcolor=THEME.accent)
        self._tab_bar = ft.Column([tab_labels_row, self._tab_indicator], spacing=0)
        self._content_box = ft.Container(content=self._tabs_content[0])
        self._content_box.expand = True

        self.controls.append(toolbar)
        col_tabs = ft.Column([self._tab_bar, self._content_box], spacing=8)
        col_tabs.expand = True
        self.controls.append(col_tabs)

        self._build_world_info_tab()
        self._build_player_tab()
        self._build_region_tab()
        self._build_nbt_tab()

    def _switch_tab(self, index: int) -> None:
        try:
            self._tab_index = index
            for i, lbl in enumerate(self._tab_labels_widgets):
                lbl.color = THEME.text_primary if i == index else THEME.text_secondary
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
        left = ft.Column(spacing=10, width=300)
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

        right = ft.Column(spacing=6)
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

        # 维度切换下拉框（加载存档时动态填充）
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
            "等待加载存档...",
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
            btn_ghost("🔍 放大", width=80, on_click=lambda e: self._heatmap.zoom_in() if hasattr(self._heatmap, 'zoom_in') else None),
            btn_ghost("🔍 缩小", width=80, on_click=lambda e: self._heatmap.zoom_out() if hasattr(self._heatmap, 'zoom_out') else None),
            btn_ghost("🏠 重置", width=80, on_click=lambda e: self._heatmap.reset_view() if hasattr(self._heatmap, 'reset_view') else None),
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
        ], spacing=0)
        col.expand = True

        self._tab_region.content = col
    
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
    
    def _on_region_selected(self, coord: Optional[Tuple[int, int]], size: Optional[int]) -> None:
        """区域选中回调"""
        def format_size(s):
            kb = s / 1024
            mb = kb / 1024
            if mb >= 1:
                return f"{mb:.2f} MB"
            elif kb >= 1:
                return f"{kb:.2f} KB"
            else:
                return f"{s} B"

        stats = self._heatmap_service.get_statistics()
        if coord is None or size is None:
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

    def _build_nbt_tab(self) -> None:
        col = ft.Column(spacing=10)
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

    def _load_world(self, e: ft.ControlEvent = None) -> None:
        try:
            path = self.app.pick_directory()
            if not path:
                return
            
            self.world_session = WorldSession(Path(path), log=self.app.log)
            self._world_label.value = f"已加载: {self.world_session.world_path.name}"
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
        except Exception as e:
            self.app.handle_exception(e, title="加载存档失败")

    def _on_player_selected(self, e: ft.ControlEvent) -> None:
        try:
            if not self.world_session or not e.control.value:
                return
            self._load_player_data(e.control.value)
        except Exception as e:
            self.app.handle_exception(e, title="加载玩家数据失败")
    
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

            if hasattr(self._heatmap, 'start_scan'):
                self._heatmap.start_scan(str(region_dir))
            else:
                self.app.warn_dialog("提示", "当前热力图组件不支持后台扫描")
        except Exception as e:
            self.app.handle_exception(e, title="刷新热力图失败")

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

    def _on_dimension_changed(self, e: ft.ControlEvent) -> None:
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
        
        def format_size(s):
            kb = s / 1024
            mb = kb / 1024
            if mb >= 1:
                return f"{mb:.1f} MB"
            elif kb >= 1:
                return f"{kb:.1f} KB"
            else:
                return f"{s} B"
        
        lines = [
            f"📊 区域总数: {stats['total_regions']} 个",
            f"💾 总大小: {format_size(stats['total_size'])}",
            f"📈 平均: {format_size(stats['avg_size'])}",
            f"🔍 最小: {format_size(stats['min_size'])} | 最大: {format_size(stats['max_size'])}"
        ]
        
        self._region_stats_text.value = "\n".join(lines)
        self._region_stats_text.color = THEME.text_primary
        safe_update(self._region_stats_text)

    def _import_usercache(self, e: ft.ControlEvent = None) -> None:
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
        except Exception as e:
            self.app.handle_exception(e, title="导入 usercache 失败")

    def _import_language_file(self, e: ft.ControlEvent = None) -> None:
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
        except Exception as e:
            self.app.handle_exception(e, title="导入语言文件失败")
    
    def _on_nbt_search(self, e: ft.ControlEvent) -> None:
        try:
            self._nbt_tree.search(e.control.value or "")
        except Exception as e:
            self.app.handle_exception(e, title="搜索 NBT 失败")
    
    def _export_nbt_json(self, e: ft.ControlEvent) -> None:
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
        except Exception as e:
            self.app.handle_exception(e, title="导出 JSON 失败")