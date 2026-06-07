"""Explorer View - 存档浏览器主视图"""
import threading
import flet as ft
import nbtlib
from typing import TYPE_CHECKING, Any, Optional, List, Dict, Tuple, Union
from pathlib import Path

from app.ui.theme import THEME, mc_border
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
from app.ui.views.entity_block_search import EntityBlockSearchView
from app.ui.views.mca_heatmap_view import McaHeatmapView


class ExplorerView(ft.Column):
    """存档浏览器视图"""

    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=0)
        self.expand = True
        self.app: "Application" = app
        self.world_session: Optional[WorldSession] = None
        self.current_uuid: Optional[str] = None
        self.player_uuid_map: Dict[str, str] = {}
        self._current_player_data: Optional[Any] = None
        self._current_nbt_target: Optional[Union[str, Path]] = None
        self._current_nbt_label = "未加载 NBT"
        self._current_edit_format = "nbt"
        self._nbt_target_options: Dict[str, Path] = {}
        self._last_chunk_objects: List[Dict[str, Any]] = []
        self._staged_nbt_changes: List[Dict[str, Any]] = []
        self._compact_mode = False
        self._build()

    @property
    def _t(self):
        return self.app._t

    def _build(self) -> None:
        self.controls.clear()

        # 工具栏
        self._world_label = ft.Text(
            "未设置当前存档", size=12, color=THEME.text_muted,
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
        self._tab_search = ft.Container()
        self._tab_search.expand = True
        self._tab_nbt = ft.Container()
        self._tab_nbt.expand = True
        self._region_display_mode = "activity"
        
        self._tabs_content = [
            self._tab_world_info, 
            self._tab_player, 
            self._tab_region, 
            self._tab_stats,
            self._tab_search,
            self._tab_nbt
        ]
        self._tab_index = 0

        # 标签页按钮
        self._tab_labels_widgets: List[ft.Text] = []
        self._tab_buttons: List[ft.Container] = []
        tab_label_conts: List[ft.Control] = []
        for idx, name in enumerate(["存档信息", "玩家", "区域", "统计", "搜索", "NBT"]):
            icon = ["🌍", "🧍", "🧱", "📊", "🔍", "📜"][idx]
            lbl = ft.Text(name, size=12, weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary if idx == 0 else THEME.text_secondary,
                        font_family="monospace")
            slot = ft.Container(
                content=ft.Column([
                    ft.Text(icon, size=20, text_align=ft.TextAlign.CENTER),
                    lbl,
                ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                width=88,
                height=60,
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

        self._tab_labels_row = ft.Row(tab_label_conts, spacing=8)
        self._tab_indicator = ft.Container(height=4, bgcolor=THEME.mc_grass)
        self._tab_bar = ft.Container(
            content=ft.Column([self._tab_labels_row, self._tab_indicator], spacing=8),
            padding=ft.Padding(left=10, right=10, top=10, bottom=10),
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
            padding=ft.Padding(left=10, right=10, top=10, bottom=10),
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
        self._build_search_tab()
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
        left = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
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

        self._build_player_edit_panel(left)

        # 右侧物品栏初始状态 - 美化占位符
        right = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO)
        right.expand = True
        self._inventory = InventoryGrid()
        right.controls.append(self._inventory)

        self._player_left_panel = ft.Container(content=left, width=340)
        self._player_right_panel = ft.Container(content=right, expand=True)
        self._player_layout = ft.Row(
            [self._player_left_panel, self._player_right_panel],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self._tab_player.content = self._player_layout

    def _build_player_edit_panel(self, parent: ft.Column) -> None:
        self._player_edit_fields: Dict[str, ft.TextField] = {
            "Health": text_field(label="生命值", width=90, expand=False),
            "foodLevel": text_field(label="饥饿值", width=90, expand=False),
            "XpLevel": text_field(label="经验等级", width=90, expand=False),
            "XpTotal": text_field(label="总经验", width=90, expand=False),
            "Air": text_field(label="氧气", width=90, expand=False),
            "Pos.0": text_field(label="X", width=90, expand=False),
            "Pos.1": text_field(label="Y", width=90, expand=False),
            "Pos.2": text_field(label="Z", width=90, expand=False),
        }
        form = ft.Column([
            ft.Text("玩家数据编辑", size=16, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            ft.Row([
                self._player_edit_fields["Health"],
                self._player_edit_fields["foodLevel"],
            ], spacing=8),
            ft.Row([
                self._player_edit_fields["XpLevel"],
                self._player_edit_fields["XpTotal"],
                self._player_edit_fields["Air"],
            ], spacing=8),
            ft.Text("坐标", size=12, color=THEME.text_secondary),
            ft.Row([
                self._player_edit_fields["Pos.0"],
                self._player_edit_fields["Pos.1"],
                self._player_edit_fields["Pos.2"],
            ], spacing=8),
            ft.Row([
                btn_ghost("刷新表单", height=30, on_click=self._refresh_player_edit_form),
                btn_primary("暂存玩家修改", height=30, on_click=self._stage_player_edit_form),
            ], spacing=8),
            ft.Text("修改会进入 NBT 暂存区，仍需在 NBT 页提交确认。", size=11, color=THEME.text_muted),
        ], spacing=8)
        parent.controls.append(card(form, padding=15))

    def _get_tag_at_path(self, data: Any, path: List[Union[str, int]]) -> Any:
        node = data
        for part in path:
            node = node[part]
        return node

    @staticmethod
    def _tag_display_value(value: Any) -> str:
        if hasattr(value, "unpack"):
            value = value.unpack()
        elif hasattr(value, "value"):
            value = value.value
        return str(value)

    @staticmethod
    def _coerce_like_tag(raw: str, original: Any) -> Any:
        tag_type = type(original)
        text = raw.strip()
        if "(" in text and text.endswith(")"):
            text = text[text.find("(") + 1:-1]
        if isinstance(original, (nbtlib.Float, nbtlib.Double)):
            return tag_type(float(text))
        if isinstance(original, (nbtlib.Byte, nbtlib.Short, nbtlib.Int, nbtlib.Long)):
            return tag_type(int(float(text)))
        try:
            return tag_type(text)
        except Exception:
            return text

    def _refresh_player_edit_form(self, e: Any = None) -> None:
        try:
            if not self._current_player_data:
                return
            mapping = {
                "Health": ["Health"],
                "foodLevel": ["foodLevel"],
                "XpLevel": ["XpLevel"],
                "XpTotal": ["XpTotal"],
                "Air": ["Air"],
                "Pos.0": ["Pos", 0],
                "Pos.1": ["Pos", 1],
                "Pos.2": ["Pos", 2],
            }
            for key, path in mapping.items():
                field = self._player_edit_fields.get(key)
                if not field:
                    continue
                try:
                    value = self._get_tag_at_path(self._current_player_data, path)
                    field.value = self._tag_display_value(value)
                except Exception:
                    field.value = ""
                safe_update(field)
        except Exception as ex:
            self.app.handle_exception(ex, title="刷新玩家编辑表单失败")

    def _stage_player_edit_form(self, e: Any = None) -> None:
        try:
            if not self.current_uuid or not self._current_player_data:
                self.app.warn_dialog("提示", "请先选择玩家。")
                return
            mapping: Dict[str, List[Union[str, int]]] = {
                "Health": ["Health"],
                "foodLevel": ["foodLevel"],
                "XpLevel": ["XpLevel"],
                "XpTotal": ["XpTotal"],
                "Air": ["Air"],
                "Pos.0": ["Pos", 0],
                "Pos.1": ["Pos", 1],
                "Pos.2": ["Pos", 2],
            }
            staged = 0
            for key, path in mapping.items():
                field = self._player_edit_fields.get(key)
                if not field or field.value is None or str(field.value).strip() == "":
                    continue
                old_value = self._get_tag_at_path(self._current_player_data, path)
                new_value = self._coerce_like_tag(str(field.value), old_value)
                if self._tag_display_value(old_value) == self._tag_display_value(new_value):
                    continue
                self._staged_nbt_changes.append({
                    "target": self.current_uuid,
                    "target_label": f"玩家 NBT: {self.current_uuid}",
                    "format": "nbt",
                    "path": path,
                    "display_path": ".".join(str(part) for part in path),
                    "old_value": old_value,
                    "new_value": new_value,
                })
                staged += 1
            self._update_nbt_stage_status()
            if staged:
                self.app.info_dialog("已暂存", f"已暂存 {staged} 个玩家数据修改，可到 NBT 页查看并提交。")
                self._switch_tab(5)
            else:
                self.app.info_dialog("提示", "没有检测到需要暂存的玩家数据修改。")
        except Exception as ex:
            self.app.handle_exception(ex, title="暂存玩家数据失败")

    def _build_region_tab(self) -> None:
        """构建区域标签页 - 使用区域地图"""
        # 获取区域地图服务
        self._heatmap_service = get_heatmap_service()
        self._current_dimension = "overworld"
        self._dimension_region_dirs: Dict[str, str] = {}
        self._selected_region_coord: Optional[Tuple[int, int]] = None

        # 维度切换下拉框（设置当前存档时动态填充）
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

        # 创建区域地图视图（兼容处理）
        if McaHeatmapView is None:
            self._heatmap = None
            heatmap_view = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.WARNING, size=48, color="#FF9800"),
                    ft.Text(
                        "区域地图组件不可用",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary
                    ),
                    ft.Text(
                        "请升级 Flet 版本以启用区域地图功能",
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
                width=420,
                height=260,
            )
            heatmap_view = self._heatmap

        self._region_help_text = ft.Text(
            "1 格 = 1 个 r.x.z.mca 区域文件（512×512 方块），颜色越红/紫代表文件越大。",
            size=11,
            color=THEME.text_muted,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        self._region_display_mode_dropdown = ft.Dropdown(
            label="显示方式",
            value="activity",
            width=150,
            options=[
                ft.dropdown.Option("activity", "活动热力"),
                ft.dropdown.Option("size", "文件大小"),
                ft.dropdown.Option("generated", "生成分布"),
                ft.dropdown.Option("distance", "距原点距离"),
                ft.dropdown.Option("biome", "主要群系"),
                ft.dropdown.Option("structure", "生成结构"),
            ],
            on_select=self._change_region_display_mode,
            border_color=THEME.border_light,
            focused_border_color=THEME.accent,
            color=THEME.text_primary,
            bgcolor=THEME.bg_card,
        )

        self._region_detail_level_dropdown = ft.Dropdown(
            label="显示粒度",
            value="auto",
            width=130,
            options=[
                ft.dropdown.Option("auto", "自动"),
                ft.dropdown.Option("region", "区域"),
                ft.dropdown.Option("chunk", "区块"),
            ],
            on_select=self._change_region_detail_level,
            border_color=THEME.border_light,
            focused_border_color=THEME.accent,
            color=THEME.text_primary,
            bgcolor=THEME.bg_card,
        )

        self._heatmap_coord_btn = btn_ghost("隐藏坐标", width=112, on_click=lambda e: self._toggle_heatmap_coordinates())
        self._heatmap_empty_btn = btn_ghost("显示空格", width=112, on_click=lambda e: self._toggle_heatmap_empty_regions())

        self._region_stats_text = ft.Text(
            "等待设置当前存档...",
            size=12,
            color=THEME.text_muted
        )

        self._region_status_text = ft.Text(
            "👆 点击方块查看详情",
            size=13,
            color=THEME.text_secondary
        )

        action_row = ft.Column([
            ft.Row([
                btn_primary("🔄 刷新", width=100, on_click=lambda e: self._refresh_heatmap()),
                btn_ghost("🔍 放大", width=90, on_click=lambda e: self._heatmap_zoom_in()),
            ], spacing=8),
            ft.Row([
                btn_ghost("🔍 缩小", width=90, on_click=lambda e: self._heatmap_zoom_out()),
                btn_ghost("🏠 重置", width=90, on_click=lambda e: self._heatmap_reset_view()),
            ], spacing=8),
            ft.Row([
                btn_ghost("填入 NBT", width=112, on_click=self._fill_selected_region_for_nbt),
                btn_danger("删除区域", width=112, on_click=self._delete_selected_region),
            ], spacing=8),
        ], spacing=8)

        view_option_row = ft.Row([
            self._heatmap_coord_btn,
            self._heatmap_empty_btn,
        ], spacing=8)

        heatmap_card = card(
            ft.Container(
                content=heatmap_view,
                bgcolor=THEME.bg_secondary,
                border=mc_border(2),
                border_radius=0,
                padding=4,
                alignment=ft.alignment.Alignment(0, 0),
            ),
            padding=6
        )

        stats_card = card(
            ft.Column([
                ft.Text("📊 区域统计", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                self._region_stats_text
            ], spacing=6),
            padding=10
        )

        selection_card = card(
            ft.Column([
                ft.Text("👆 点击详情", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                self._region_status_text
            ], spacing=6),
            padding=10
        )

        self._region_legend_container = ft.Container(content=self._create_region_legend_content())
        legend = card(self._region_legend_container, padding=10)

        left_panel = ft.Container(
            content=ft.Column([
                card(ft.Row([dimension_row, self._region_display_mode_dropdown, self._region_detail_level_dropdown, self._region_help_text], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER), padding=8),
                heatmap_card,
            ], spacing=8),
            expand=True,
        )
        self._region_left_panel = left_panel

        side_panel = ft.Container(
            content=ft.Column([
                selection_card,
                stats_card,
                legend,
                card(ft.Column([
                    ft.Text("⚙️ 显示选项", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                    view_option_row,
                ], spacing=8), padding=10),
                card(ft.Column([
                    ft.Text("🛠️ 区域操作", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                    action_row,
                ], spacing=8), padding=10),
            ], spacing=8, scroll=ft.ScrollMode.AUTO),
            height=320,
            width=360,
        )
        self._region_side_panel = side_panel

        region_layout = ft.Row([
            left_panel,
            side_panel,
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START)

        self._tab_region.content = region_layout

    def set_compact_mode(self, compact: bool) -> None:
        if self._compact_mode == compact:
            return
        self._compact_mode = compact
        try:
            tab_width = 68 if compact else 88
            tab_height = 52 if compact else 60
            for idx, btn in enumerate(self._tab_buttons):
                btn.width = tab_width
                btn.height = tab_height
                btn.padding = ft.Padding(left=4, right=4, top=4, bottom=4) if compact else ft.Padding(left=6, right=6, top=6, bottom=6)
                if idx < len(self._tab_labels_widgets):
                    self._tab_labels_widgets[idx].size = 10 if compact else 12
            self._tab_labels_row.spacing = 4 if compact else 8
            self._tab_bar.padding = ft.Padding(left=6, right=6, top=6, bottom=6) if compact else ft.Padding(left=10, right=10, top=10, bottom=10)
            self._content_box.padding = ft.Padding(left=6, right=6, top=6, bottom=6) if compact else ft.Padding(left=10, right=10, top=10, bottom=10)
            if hasattr(self, '_player_left_panel'):
                self._player_left_panel.width = 300 if compact else 340
            if hasattr(self, '_region_left_panel'):
                self._region_side_panel.width = 320 if compact else 360
                self._region_side_panel.height = 280 if compact else 320
            if self._heatmap is not None and hasattr(self._heatmap, 'resize_map'):
                self._heatmap.resize_map(340 if compact else 420, 220 if compact else 260)
            safe_update(self)
        except Exception:
            pass

    def _build_stats_tab(self) -> None:
        self._stats_status = ft.Text("设置当前存档后可通过顶栏统计快捷操作分析世界数据。", size=12, color=THEME.text_muted)
        self._stats_summary = ft.Text("通过顶栏统计快捷操作分析世界数据。", size=12, color=THEME.text_muted)
        self._block_stats_col = ft.Column(spacing=4)
        self._entity_stats_col = ft.Column(spacing=4)
        self._size_stats_col = ft.Column(spacing=4)
        stats_col = ft.Column([
            card(self._stats_status, padding=12),
            card(ft.Column([ft.Text("汇总", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary), self._stats_summary], spacing=8), padding=12),
            card(ft.Column([ft.Text("方块分布 Top 10", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary), self._block_stats_col], spacing=8), padding=12),
            card(ft.Column([ft.Text("实体数量 Top 10", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary), self._entity_stats_col], spacing=8), padding=12),
            card(ft.Column([ft.Text("区域文件大小分布", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary), self._size_stats_col], spacing=8), padding=12),
        ], spacing=12, scroll=ft.ScrollMode.AUTO)
        stats_col.expand = True
        self._tab_stats.content = stats_col

    def _build_search_tab(self) -> None:
        self._entity_block_search_view = EntityBlockSearchView(self.app, compact=True)
        self._tab_search.content = self._entity_block_search_view
    
    def _create_region_legend_content(self) -> ft.Column:
        """创建区域显示图例内容"""
        title, items = self._get_region_display_legend()
        legend_rows = []
        for color, item_title, desc in items:
            legend_rows.append(ft.Row([
                ft.Container(width=18, height=18, bgcolor=color, border_radius=2),
                ft.Text(item_title, size=11, color=THEME.text_primary, width=58),
                ft.Text(desc, size=10, color=THEME.text_muted),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        return ft.Column([
            ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            *legend_rows,
        ], spacing=5)

    def _get_region_display_legend(self) -> tuple[str, list[tuple[str, str, str]]]:
        if self._region_display_mode == "size":
            return "💾 文件大小图例", [
                ("#2E7D32", "<2MB", "很小区域"),
                ("#689F38", "2MB+", "小型区域"),
                ("#C0A44A", "8MB+", "中等区域"),
                ("#D9822B", "16MB+", "中大型区域"),
                ("#C63D2F", "32MB+", "大型区域"),
                ("#8E24AA", "64MB+", "超大区域"),
            ]
        if self._region_display_mode == "generated":
            return "🧭 生成分布图例", [
                ("#FFD54F", "原点", "r.0.0.mca"),
                ("#66BB6A", "出生点", "原点附近"),
                ("#42A5F5", "近距", "常规探索"),
                ("#AB47BC", "中距", "扩展探索"),
                ("#78909C", "远距", "远距离生成"),
            ]
        if self._region_display_mode == "distance":
            return "📏 距原点距离图例", [
                ("#FFD54F", "0-512", "原点附近"),
                ("#66BB6A", "2K内", "近距离"),
                ("#29B6F6", "5K内", "中距离"),
                ("#7E57C2", "12K内", "远距离"),
                ("#455A64", "12K+", "极远距离"),
            ]
        if self._region_display_mode == "biome":
            return "🌿 主要群系图例", [
                ("#1E88E5", "水域", "海洋 / 河流"),
                ("#D6B44C", "干旱", "沙漠 / 恶地"),
                ("#B3E5FC", "寒冷", "雪地 / 冰原"),
                ("#2E7D32", "丛林", "热带密林"),
                ("#388E3C", "森林", "森林 / 针叶林"),
                ("#8E2424", "下界", "下界群系"),
            ]
        if self._region_display_mode == "structure":
            return "🏛️ 生成结构图例", [
                ("#455A64", "无", "未发现结构引用"),
                ("#FFD54F", "村庄", "village"),
                ("#8D6E63", "矿井", "mineshaft"),
                ("#7E57C2", "要塞", "stronghold"),
                ("#26A69A", "大型", "林地府邸 / 海底神殿"),
                ("#D84315", "下界", "堡垒 / 猪灵堡垒"),
            ]
        return "🔥 活动图层图例", [
            ("#2E7D32", "草地", "很少生成 / 文件小"),
            ("#689F38", "森林", "低活动"),
            ("#C0A44A", "沙地", "普通活动"),
            ("#D9822B", "岩浆", "高活动"),
            ("#C63D2F", "下界", "非常活跃"),
            ("#8E24AA", "紫晶", "极高活动 / 最大文件"),
        ]

    def _change_region_display_mode(self, e: ft.ControlEvent) -> None:
        mode = self._region_display_mode_dropdown.value or "activity"
        self._region_display_mode = mode
        if self._heatmap is not None and hasattr(self._heatmap, "set_display_mode"):
            self._heatmap.set_display_mode(mode)
        self._region_help_text.value = self._get_region_display_help(mode)
        self._region_legend_container.content = self._create_region_legend_content()
        safe_update(self._region_help_text)
        safe_update(self._region_legend_container)
        if self._selected_region_coord is not None:
            data = self._heatmap_service.get_all_data()
            size = data.get(self._selected_region_coord)
            if size is not None:
                self._on_region_selected(self._selected_region_coord, size, None)

    def _change_region_detail_level(self, e: ft.ControlEvent) -> None:
        level = self._region_detail_level_dropdown.value or "auto"
        if self._heatmap is not None and hasattr(self._heatmap, "set_detail_level"):
            self._heatmap.set_detail_level(level)

    def _get_region_display_help(self, mode: str) -> str:
        if mode == "size":
            return "按区域文件实际大小分级，适合找超大区域或异常膨胀区域。"
        if mode == "generated":
            return "按区域相对原点范围分层，适合观察世界生成和探索扩散。"
        if mode == "distance":
            return "按区域距原点远近着色，适合理解坐标范围和远距离探索。"
        if mode == "biome":
            return "读取区块 NBT 中的群系调色板，按区域内出现最多的群系类型着色。"
        if mode == "structure":
            return "读取区块 NBT 中的结构 starts/references，按区域内主要结构类型着色。"
        return "按文件大小相对平均值着色，适合快速判断玩家活动和内容密集区域。"

    def _get_region_mode_value_text(self, coord: tuple[int, int], size: int, stats: dict[str, Any]) -> str:
        mode = self._region_display_mode
        if mode == "size":
            if size >= 64 * 1024 * 1024:
                return "🟣 超大区域，建议重点检查是否有大量实体、容器或生成内容"
            if size >= 32 * 1024 * 1024:
                return "🔴 大型区域，内容较密集"
            if size >= 16 * 1024 * 1024:
                return "🟠 中大型区域"
            if size >= 8 * 1024 * 1024:
                return "🟡 中等区域"
            return "🟢 小型区域"
        if mode == "generated":
            x, z = coord
            if x == 0 and z == 0:
                return "⭐ 原点区域"
            if abs(x) <= 1 and abs(z) <= 1:
                return "🟢 出生点附近生成区域"
            if abs(x) <= 4 and abs(z) <= 4:
                return "🔵 近距离探索生成区域"
            if abs(x) <= 12 and abs(z) <= 12:
                return "🟣 中距离探索生成区域"
            return "⚙️ 远距离探索生成区域"
        if mode == "distance":
            distance = int((coord[0] * coord[0] + coord[1] * coord[1]) ** 0.5 * 512)
            return f"📏 距原点约 {distance} 方块"
        if mode == "biome":
            meta = self._heatmap_service.get_region_meta(coord)
            biome = meta.get("dominant_biome", "unknown")
            biomes = meta.get("biomes", {}) or {}
            names = ", ".join(list(biomes.keys())[:4]) if isinstance(biomes, dict) else ""
            return f"🌿 主要群系: {biome}" + (f"（含 {names}）" if names else "")
        if mode == "structure":
            meta = self._heatmap_service.get_region_meta(coord)
            count = int(meta.get("structure_count", 0) or 0)
            if count <= 0:
                return "🏛️ 未发现结构引用"
            structures = meta.get("structures", {}) or {}
            names = ", ".join(list(structures.keys())[:4]) if isinstance(structures, dict) else str(meta.get("dominant_structure", "unknown"))
            positions = meta.get("structure_positions", []) or []
            if positions:
                pos_lines = []
                for pos in positions[:3]:
                    px = pos.get("block_x")
                    py = pos.get("block_y")
                    pz = pos.get("block_z")
                    name = pos.get("name", "structure")
                    if py is None:
                        pos_lines.append(f"{name}@X{px}, Z{pz}")
                    else:
                        pos_lines.append(f"{name}@X{px}, Y{py}, Z{pz}")
                return f"🏛️ 结构引用: {count} 个（{names}）\n   📍 结构坐标: " + "；".join(pos_lines)
            return f"🏛️ 结构引用: {count} 个（{names}）"
        if stats['avg_size'] > 0:
            ratio = size / stats['avg_size']
            return "🔥 非常活跃" if ratio > 1.5 else \
                   "📗 较活跃" if ratio > 1.0 else \
                   "📙 一般" if ratio > 0.5 else "📕 不活跃"
        return "活动度未知"

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

    def _toggle_heatmap_coordinates(self) -> None:
        heatmap = self._heatmap
        if heatmap is not None and hasattr(heatmap, "toggle_coordinates"):
            enabled = heatmap.toggle_coordinates()
            self._heatmap_coord_btn.set_text("隐藏坐标" if enabled else "显示坐标")
            safe_update(self._heatmap_coord_btn)

    def _toggle_heatmap_empty_regions(self) -> None:
        heatmap = self._heatmap
        if heatmap is not None and hasattr(heatmap, "toggle_empty_regions"):
            enabled = heatmap.toggle_empty_regions()
            self._heatmap_empty_btn.set_text("隐藏空格" if enabled else "显示空格")
            safe_update(self._heatmap_empty_btn)
    
    def _on_region_selected(self, coord: Optional[Tuple[int, int]], size: Optional[int], detail: Optional[Dict[str, Any]] = None) -> None:
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
        
        value_text = self._get_region_mode_value_text(coord, size, stats)
        avg_text = f"平均 {format_size(int(stats['avg_size']))}" if stats['avg_size'] > 0 else "平均未知"
        region_x, region_z = coord
        chunk_x0 = region_x * 32
        chunk_x1 = region_x * 32 + 31
        chunk_z0 = region_z * 32
        chunk_z1 = region_z * 32 + 31
        block_x0 = region_x * 512
        block_x1 = region_x * 512 + 511
        block_z0 = region_z * 512
        block_z1 = region_z * 512 + 511
        self._region_status_text.value = (
            f"✅ 已选择区域\n"
            f"   🧭 区域坐标: ({region_x}, {region_z})\n"
            f"   📄 文件: r.{region_x}.{region_z}.mca\n"
            f"   🧩 区块范围: X {chunk_x0} ~ {chunk_x1}, Z {chunk_z0} ~ {chunk_z1}\n"
            f"   🧱 方块范围: X {block_x0} ~ {block_x1}, Z {block_z0} ~ {block_z1}\n"
            f"   💾 大小: {format_size(size)}（{avg_text}）\n"
            f"   {value_text}"
        )
        if detail and detail.get("level") == "chunk":
            self._region_status_text.value = (
                f"✅ 已选择区块\n"
                f"   🧭 区域坐标: {detail['region_coord']}\n"
                f"   🧩 区块坐标: {detail['chunk_coord']}\n"
                f"   🔲 区域内区块: {detail['chunk_local']}\n"
                f"   🧱 方块范围: {detail['block_range']}\n"
                f"   📄 所属文件: r.{region_x}.{region_z}.mca\n"
                f"   💾 区域文件大小: {format_size(size)}（{avg_text}）\n"
                f"   {value_text}"
            )
        self._region_status_text.color = THEME.accent_light
        
        safe_update(self._region_status_text)

    def _delete_selected_region(self, e: Any) -> None:
        try:
            if not self.world_session or not self._selected_region_coord:
                self.app.warn_dialog("提示", "请先在区域地图中选择一个区域。")
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

    def _fill_selected_region_for_nbt(self, e: Any = None) -> None:
        try:
            if not self.world_session or not self._selected_region_coord:
                self.app.warn_dialog("提示", "请先在区域地图中选择一个区域。")
                return
            region_dir = Path(self._dimension_region_dirs.get(self._current_dimension, ""))
            if not region_dir:
                self.app.warn_dialog("提示", "当前维度没有可用的 region 目录。")
                return
            coord = self._selected_region_coord
            region_path = region_dir / f"r.{coord[0]}.{coord[1]}.mca"
            if not region_path.exists():
                self.app.warn_dialog("提示", f"区域文件不存在: {region_path.name}")
                return
            relative_path = region_path.resolve().relative_to(self.world_session.world_path.resolve())
            self._region_file_field.value = str(relative_path).replace("\\", "/")
            self._chunk_x_field.value = "0"
            self._chunk_z_field.value = "0"
            safe_update(self._region_file_field)
            safe_update(self._chunk_x_field)
            safe_update(self._chunk_z_field)
            self._switch_tab(4)
        except Exception as ex:
            self.app.handle_exception(ex, title="填入区域文件失败")

    @staticmethod
    def _world_coords_to_region_chunk(world_x: int, world_z: int) -> Tuple[int, int, int, int]:
        chunk_x = world_x // 16
        chunk_z = world_z // 16
        region_x = chunk_x // 32
        region_z = chunk_z // 32
        local_chunk_x = chunk_x % 32
        local_chunk_z = chunk_z % 32
        return region_x, region_z, local_chunk_x, local_chunk_z

    def _fill_chunk_from_world_coords(self, e: Any = None) -> bool:
        try:
            if not self.world_session:
                self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return False
            region_dir = Path(self._dimension_region_dirs.get(self._current_dimension, ""))
            if not region_dir:
                self.app.warn_dialog("提示", "当前维度没有可用的 region 目录。")
                return False
            world_x = int(float((self._world_x_field.value or "0").strip()))
            world_z = int(float((self._world_z_field.value or "0").strip()))
            region_x, region_z, local_chunk_x, local_chunk_z = self._world_coords_to_region_chunk(world_x, world_z)
            region_path = region_dir / f"r.{region_x}.{region_z}.mca"
            relative_path = region_path.resolve().relative_to(self.world_session.world_path.resolve())
            self._region_file_field.value = str(relative_path).replace("\\", "/")
            self._chunk_x_field.value = str(local_chunk_x)
            self._chunk_z_field.value = str(local_chunk_z)
            safe_update(self._region_file_field)
            safe_update(self._chunk_x_field)
            safe_update(self._chunk_z_field)
            if not region_path.exists():
                self.app.warn_dialog("提示", f"已填入坐标，但区域文件不存在: r.{region_x}.{region_z}.mca")
                return False
            return True
        except ValueError:
            self.app.warn_dialog("提示", "世界坐标必须是数字。")
            return False
        except Exception as ex:
            self.app.handle_exception(ex, title="填入世界坐标失败")
            return False

    def _load_chunk_from_world_coords(self, e: Any = None) -> None:
        if self._fill_chunk_from_world_coords(e):
            self._load_chunk_nbt(e)

    def _build_nbt_tab(self) -> None:
        col = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
        col.expand = True
        
        # 搜索栏
        self._nbt_stage_status = ft.Text(
            "暂存区: 0 个变更", size=12, color=THEME.text_muted,
        )
        self._nbt_target_label = ft.Text(
            self._current_nbt_label, size=12, color=THEME.text_secondary,
        )
        self._nbt_stage_list = ft.Column(spacing=6)
        self._nbt_target_dropdown = ft.Dropdown(
            label="NBT 目标",
            options=[],
            width=300,
            border_color=THEME.border_standard,
            text_size=12,
            on_select=self._load_selected_nbt_target,
        )
        search_row = ft.Row([
            ft.Text("🔍 搜索:", size=14, color=THEME.text_primary),
            text_field(
                label="输入搜索内容",
                width=200,
                on_change=self._on_nbt_search
            ),
            self._nbt_target_dropdown,
            btn_ghost("加载玩家 NBT", on_click=self._load_current_player_nbt, height=34),
            btn_ghost("加载 level.dat", on_click=self._load_level_nbt, height=34),
            btn_ghost("导出 JSON", on_click=self._export_nbt_json, height=34),
            btn_primary("提交变更", on_click=self._commit_nbt_changes, height=34),
            btn_danger("丢弃暂存", on_click=self._discard_nbt_changes, height=34),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self._region_file_field = text_field(
            label="区域文件",
            hint_text="例如 region/r.0.0.mca",
            width=230,
            expand=False,
        )
        self._chunk_x_field = text_field(value="0", label="区块X", width=90, expand=False)
        self._chunk_z_field = text_field(value="0", label="区块Z", width=90, expand=False)
        region_row = ft.Row([
            ft.Text("🧱 区块 NBT:", size=14, color=THEME.text_primary),
            self._region_file_field,
            self._chunk_x_field,
            self._chunk_z_field,
            btn_ghost("加载区块", on_click=self._load_chunk_nbt, height=34),
            ft.Text("当前为只读预览，写回会在下一步接入", size=12, color=THEME.text_muted),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self._world_x_field = text_field(value="0", label="世界X", width=100, expand=False)
        self._world_z_field = text_field(value="0", label="世界Z", width=100, expand=False)
        coord_row = ft.Row([
            ft.Text("📍 坐标定位:", size=14, color=THEME.text_primary),
            self._world_x_field,
            self._world_z_field,
            btn_ghost("填入区块", on_click=self._fill_chunk_from_world_coords, height=34),
            btn_primary("定位并加载", on_click=self._load_chunk_from_world_coords, height=34),
            ft.Text("按世界 X/Z 自动计算 region 文件和区块坐标", size=12, color=THEME.text_muted),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self._chunk_object_filter_field = text_field(
            label="筛选对象",
            hint_text="输入实体/方块实体 ID 或坐标",
            width=260,
            expand=False,
            on_change=self._on_chunk_object_filter,
        )
        self._chunk_objects_list = ft.Column(spacing=6)
        
        col.controls.append(card(search_row, padding=10))
        col.controls.append(card(region_row, padding=10))
        col.controls.append(card(coord_row, padding=10))
        col.controls.append(card(ft.Column([
            ft.Row([
                ft.Text("区块对象", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                self._chunk_object_filter_field,
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self._chunk_objects_list,
        ], spacing=8), padding=10))
        col.controls.append(card(ft.Column([
            ft.Row([self._nbt_target_label, self._nbt_stage_status], spacing=16),
            self._nbt_stage_list,
        ], spacing=8), padding=10))
        col.controls.append(
            ft.Text("NBT 数据查看器", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary)
        )
        self._nbt_tree = NBTTreeView(on_stage_change=self._stage_nbt_change)
        c = ft.Container(content=self._nbt_tree)
        c.expand = True
        col.controls.append(c)
        self._tab_nbt.content = col

    def on_save_selected(self, path: str) -> None:
        self._load_world(path)
        if hasattr(self, "_entity_block_search_view"):
            self._entity_block_search_view.on_save_selected(path)

    def _start_entity_block_search(self, e: Any = None) -> None:
        if hasattr(self, "_entity_block_search_view"):
            self._switch_tab(4)
            self._entity_block_search_view._start_search(e)

    def _load_world(self, path: Any = None) -> None:
        try:
            if path is None or hasattr(path, "control"):
                path = getattr(self.app, "_current_save_path", None)
            if not path:
                self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return

            # 显示加载状态
            self._world_label.value = f"⏳ 正在加载存档..."
            self._world_label.color = THEME.mc_gold
            safe_update(self._world_label)

            # 后台线程加载 WorldSession，避免阻塞 UI
            def _load():
                try:
                    session = WorldSession(Path(path), log=self.app.log)
                    self._populate_world(session)
                except Exception as ex:
                    self._world_label.value = "❌ 加载存档失败"
                    self._world_label.color = THEME.warning
                    safe_update(self._world_label)
                    self.app.handle_exception(ex, title="设置当前存档失败")

            threading.Thread(target=_load, daemon=True).start()
        except Exception as ex:
            self.app.handle_exception(ex, title="设置当前存档失败")

    def _populate_world(self, session: WorldSession) -> None:
        """在 WorldSession 加载完成后填充 UI（可在后台线程调用）"""
        self.world_session = session
        self._world_label.value = f"当前存档: {session.world_path.name}"
        self._world_label.color = THEME.text_muted
        self._current_nbt_target = None
        self._current_nbt_label = "未加载 NBT"
        self._staged_nbt_changes.clear()
        self._update_nbt_target_options()
        self._update_nbt_stage_status()
        safe_update(self._world_label)

        # 更新存档信息面板
        world_info = session.get_world_info()
        dimensions = session.get_dimensions()
        stats = {
            "world_path": str(session.world_path),
            "player_count": len(session.get_player_uuids()),
            "region_count": len(session._region_files),
            "dimension_count": len(dimensions),
        }
        self._world_info_panel.update_info(world_info, stats=stats)

        # 获取玩家名称映射（仅使用 usercache，不加载 NBT）
        player_names = session.get_player_names()

        # 填充玩家下拉列表
        players = []
        for uuid, name in player_names.items():
            display = name or session._format_uuid_with_hyphens(uuid)
            formatted = session._format_uuid_with_hyphens(uuid)
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
            self._current_player_data = player_data
            self._player_hud.update_from_nbt(player_data)
            self._refresh_player_edit_form()
            inv = self.world_session.get_player_inventory(uuid)
            self._inventory.set_inventory(inv)
            self._equipment.set_equipment(inv)
            nbt = self.world_session.load_player_nbt(uuid)
            self._current_nbt_target = uuid
            self._current_nbt_label = f"玩家 NBT: {uuid}"
            self._nbt_target_label.value = self._current_nbt_label
            safe_update(self._nbt_target_label)
            self._nbt_tree.load_nbt(nbt)
        except Exception as e:
            self.app.handle_exception(e, title="加载玩家数据失败")

    def _refresh_heatmap(self) -> None:
        """刷新区域地图"""
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
                self.app.warn_dialog("提示", "当前区域地图组件不支持后台扫描")
        except Exception as e:
            self.app.handle_exception(e, title="刷新区域地图失败")

    def _analyze_world_stats(self, e: Any) -> None:
        try:
            if not self.world_session:
                self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
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

    def _stage_nbt_change(
        self,
        path_parts: List[Union[str, int]],
        old_value: Any,
        new_value: Any,
        display_path: str,
    ) -> None:
        try:
            if self._current_nbt_target is None:
                self.app.warn_dialog("提示", "请先加载要编辑的 NBT 数据。")
                return
            change = {
                "target": self._current_nbt_target,
                "target_label": self._current_nbt_label,
                "format": self._current_edit_format,
                "path": path_parts,
                "display_path": display_path,
                "old_value": old_value,
                "new_value": new_value,
            }
            self._staged_nbt_changes.append(change)
            self._update_nbt_stage_status()
            self.app.log(f"已暂存 NBT 修改: {display_path}", "QUEUE")
        except Exception as ex:
            self.app.handle_exception(ex, title="暂存 NBT 修改失败")

    def _update_nbt_stage_status(self) -> None:
        try:
            count = len(self._staged_nbt_changes)
            self._nbt_stage_status.value = f"暂存区: {count} 个变更"
            self._nbt_stage_status.color = THEME.warning if count else THEME.text_muted
            self._render_nbt_stage_list()
            safe_update(self._nbt_stage_status)
        except Exception:
            pass

    def _render_nbt_stage_list(self) -> None:
        try:
            self._nbt_stage_list.controls.clear()
            if not self._staged_nbt_changes:
                self._nbt_stage_list.controls.append(
                    ft.Text("暂无暂存变更", size=12, color=THEME.text_muted)
                )
            else:
                for index, change in enumerate(self._staged_nbt_changes):
                    old_text = self._format_stage_value(change["old_value"])
                    new_text = self._format_stage_value(change["new_value"])
                    self._nbt_stage_list.controls.append(ft.Container(
                        content=ft.Row([
                            ft.Text(f"#{index + 1}", size=12, color=THEME.mc_gold, width=34),
                            ft.Column([
                                ft.Text(change["display_path"], size=12, color=THEME.text_primary),
                                ft.Text(f"{change['target_label']}: {old_text} → {new_text}", size=11, color=THEME.text_muted),
                            ], spacing=2, expand=True),
                            ft.TextButton("撤销", on_click=lambda e, i=index: self._unstage_nbt_change(i)),
                        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=ft.Padding(left=6, right=6, top=4, bottom=4),
                        bgcolor=THEME.bg_card,
                    ))
            safe_update(self._nbt_stage_list)
        except Exception:
            pass

    @staticmethod
    def _format_stage_value(value: Any) -> str:
        text = str(getattr(value, "value", value))
        return text if len(text) <= 48 else text[:45] + "…"

    @classmethod
    def _format_diff_value(cls, value: Any) -> str:
        text = str(getattr(value, "value", value))
        return text if len(text) <= 160 else text[:157] + "…"

    @classmethod
    def _format_change_summary(cls, index: int, change: Dict[str, Any]) -> str:
        old_text = cls._format_diff_value(change["old_value"])
        new_text = cls._format_diff_value(change["new_value"])
        target = change.get("target_label", "未知目标")
        kind = "JSON" if change.get("format") == "json" else "NBT"
        return f"#{index + 1} [{kind}] {target}\n  {change['display_path']}\n  - {old_text}\n  + {new_text}"

    def _update_nbt_target_options(self) -> None:
        try:
            self._nbt_target_options.clear()
            if not self.world_session:
                self._nbt_target_dropdown.options = []
                safe_update(self._nbt_target_dropdown)
                return
            world_path = self.world_session.world_path
            candidates: List[Tuple[str, Path]] = []
            level_path = world_path / "level.dat"
            if level_path.exists():
                candidates.append(("世界 / level.dat", Path("level.dat")))
            data_dir = world_path / "data"
            if data_dir.exists():
                for path in sorted(data_dir.glob("*.dat")):
                    candidates.append((f"数据 / {path.name}", path.relative_to(world_path)))
            for folder_name, label in [("stats", "统计"), ("advancements", "进度")]:
                folder = world_path / folder_name
                if folder.exists():
                    for path in sorted(folder.glob("*.json")):
                        candidates.append((f"{label} / {path.name}", path.relative_to(world_path)))
            for label, relative_path in candidates:
                key = str(relative_path).replace("\\", "/")
                self._nbt_target_options[key] = relative_path
            self._nbt_target_dropdown.options = [
                ft.dropdown.Option(key, label) for label, key in [
                    (label, str(path).replace("\\", "/")) for label, path in candidates
                ]
            ]
            safe_update(self._nbt_target_dropdown)
        except Exception as ex:
            self.app.handle_exception(ex, title="刷新 NBT 目标失败")

    def _unstage_nbt_change(self, index: int) -> None:
        try:
            if index < 0 or index >= len(self._staged_nbt_changes):
                return
            self._staged_nbt_changes.pop(index)
            self._update_nbt_stage_status()
            self._reload_current_nbt_target()
        except Exception as ex:
            self.app.handle_exception(ex, title="撤销暂存变更失败")

    def _load_current_player_nbt(self, e: Any = None) -> None:
        try:
            if not self.current_uuid:
                self.app.warn_dialog("提示", "请先选择玩家。")
                return
            self._load_player_data(self.current_uuid)
        except Exception as ex:
            self.app.handle_exception(ex, title="加载玩家 NBT 失败")

    def _load_level_nbt(self, e: Any = None) -> None:
        try:
            if not self.world_session:
                self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return
            self._load_nbt_file(Path("level.dat"), "世界 NBT: level.dat")
        except Exception as ex:
            self.app.handle_exception(ex, title="加载 level.dat 失败")

    def _load_selected_nbt_target(self, e: Any) -> None:
        try:
            key = e.control.value
            if not key or key not in self._nbt_target_options:
                return
            relative_path = self._nbt_target_options[key]
            self._load_nbt_file(relative_path, f"NBT 文件: {key}")
        except Exception as ex:
            self.app.handle_exception(ex, title="加载 NBT 目标失败")

    def _load_nbt_file(self, relative_path: Path, label: str) -> None:
        if not self.world_session:
            self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
            return
        import nbtlib
        path = self.world_session.world_path / relative_path
        if not path.exists():
            self.app.warn_dialog("提示", f"文件不存在: {relative_path}")
            return
        if path.suffix.lower() != ".dat":
            self._load_json_file(relative_path, label)
            return
        self._current_nbt_target = relative_path
        self._current_nbt_label = label
        self._current_edit_format = "nbt"
        self._nbt_target_label.value = self._current_nbt_label
        self._nbt_target_dropdown.value = str(relative_path).replace("\\", "/")
        safe_update(self._nbt_target_label)
        safe_update(self._nbt_target_dropdown)
        self._nbt_tree.load_nbt(nbtlib.load(path))

    def _load_json_file(self, relative_path: Path, label: str) -> None:
        if not self.world_session:
            self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
            return
        import json
        path = self.world_session.world_path / relative_path
        if not path.exists():
            self.app.warn_dialog("提示", f"文件不存在: {relative_path}")
            return
        self._current_nbt_target = relative_path
        self._current_nbt_label = label.replace("NBT 文件", "JSON 文件")
        self._current_edit_format = "json"
        self._nbt_target_label.value = self._current_nbt_label
        self._nbt_target_dropdown.value = str(relative_path).replace("\\", "/")
        safe_update(self._nbt_target_label)
        safe_update(self._nbt_target_dropdown)
        with open(path, "r", encoding="utf-8") as f:
            self._nbt_tree.load_nbt(json.load(f))

    def _load_chunk_nbt(self, e: Any = None) -> None:
        try:
            if not self.world_session:
                self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return
            relative_text = (self._region_file_field.value or "").strip().replace("\\", "/")
            if not relative_text:
                self.app.warn_dialog("提示", "请输入区域文件路径，例如 region/r.0.0.mca。")
                return
            relative_path = Path(relative_text)
            region_path = (self.world_session.world_path / relative_path).resolve()
            world_root = self.world_session.world_path.resolve()
            try:
                region_path.relative_to(world_root)
            except ValueError:
                self.app.warn_dialog("提示", "区域文件必须位于当前存档目录内。")
                return
            if not region_path.exists() or region_path.suffix.lower() != ".mca":
                self.app.warn_dialog("提示", f"区域文件不存在或不是 .mca 文件: {relative_text}")
                return
            chunk_x = int((self._chunk_x_field.value or "0").strip())
            chunk_z = int((self._chunk_z_field.value or "0").strip())
            from anvil import Region
            region = Region.from_file(str(region_path))
            chunk = region.get_chunk(chunk_x, chunk_z)
            if chunk is None or not hasattr(chunk, "data"):
                self.app.warn_dialog("提示", "该区块不存在或无法读取。")
                return
            self._current_nbt_target = None
            self._current_nbt_label = f"区块 NBT 只读: {relative_text} [{chunk_x}, {chunk_z}]"
            self._current_edit_format = "chunk_readonly"
            self._nbt_target_label.value = self._current_nbt_label
            safe_update(self._nbt_target_label)
            self._nbt_tree.load_nbt(chunk.data, editable=False)
            self._render_chunk_objects(chunk.data)
        except ValueError:
            self.app.warn_dialog("提示", "区块坐标必须是整数。")
        except Exception as ex:
            self.app.handle_exception(ex, title="加载区块 NBT 失败")

    def _render_chunk_objects(self, chunk_data: Any) -> None:
        try:
            self._chunk_objects_list.controls.clear()
            self._last_chunk_objects = self._extract_chunk_objects(chunk_data)
            self._render_chunk_object_rows(self._last_chunk_objects)
        except Exception as ex:
            self.app.handle_exception(ex, title="渲染区块对象失败")

    def _on_chunk_object_filter(self, e: Any) -> None:
        query = (e.control.value or "").strip().lower()
        if not query:
            self._render_chunk_object_rows(self._last_chunk_objects)
            return
        filtered = [
            obj for obj in self._last_chunk_objects
            if query in obj["title"].lower() or query in obj["subtitle"].lower()
        ]
        self._render_chunk_object_rows(filtered)

    def _render_chunk_object_rows(self, objects: List[Dict[str, Any]]) -> None:
        try:
            self._chunk_objects_list.controls.clear()
            if not objects:
                self._chunk_objects_list.controls.append(
                    ft.Text("该区块未发现实体或方块实体", size=12, color=THEME.text_muted)
                )
            else:
                for obj in objects[:120]:
                    self._chunk_objects_list.controls.append(ft.Container(
                        content=ft.Row([
                            ft.Text(obj["icon"], size=16, width=28),
                            ft.Column([
                                ft.Text(obj["title"], size=12, color=THEME.text_primary),
                                ft.Text(obj["subtitle"], size=11, color=THEME.text_muted),
                            ], spacing=2, expand=True),
                            ft.TextButton("查看", on_click=lambda e, data=obj["data"], title=obj["title"]: self._show_chunk_object(data, title)),
                        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=ft.Padding(left=6, right=6, top=4, bottom=4),
                        bgcolor=THEME.bg_card,
                    ))
                if len(objects) > 120:
                    self._chunk_objects_list.controls.append(
                        ft.Text(f"已显示前 120 个对象，剩余 {len(objects) - 120} 个", size=12, color=THEME.text_muted)
                    )
            safe_update(self._chunk_objects_list)
        except Exception as ex:
            self.app.handle_exception(ex, title="渲染区块对象失败")

    def _show_chunk_object(self, data: Any, title: str) -> None:
        self._current_nbt_target = None
        self._current_nbt_label = f"区块对象只读: {title}"
        self._current_edit_format = "chunk_readonly"
        self._nbt_target_label.value = self._current_nbt_label
        safe_update(self._nbt_target_label)
        self._nbt_tree.load_nbt(data, editable=False)

    @staticmethod
    def _extract_chunk_objects(chunk_data: Any) -> List[Dict[str, Any]]:
        objects: List[Dict[str, Any]] = []

        def tag_value(value: Any) -> Any:
            return getattr(value, "value", value)

        def get_first_mapping(data: Any, keys: List[str]) -> Any:
            if not isinstance(data, dict):
                return None
            for key in keys:
                value = data.get(key)
                if value is not None:
                    return value
            level = data.get("Level")
            if isinstance(level, dict):
                for key in keys:
                    value = level.get(key)
                    if value is not None:
                        return value
            return None

        def format_pos(data: Any) -> str:
            if not isinstance(data, dict):
                return "未知位置"
            pos = data.get("Pos")
            if isinstance(pos, list) and len(pos) >= 3:
                return f"({tag_value(pos[0])}, {tag_value(pos[1])}, {tag_value(pos[2])})"
            xyz = [data.get("x"), data.get("y"), data.get("z")]
            if all(item is not None for item in xyz):
                return f"({tag_value(xyz[0])}, {tag_value(xyz[1])}, {tag_value(xyz[2])})"
            return "未知位置"

        entities = get_first_mapping(chunk_data, ["Entities", "entities"])
        if isinstance(entities, list):
            for index, entity in enumerate(entities):
                entity_id = str(tag_value(entity.get("id", "unknown"))) if isinstance(entity, dict) else "unknown"
                objects.append({
                    "icon": "🐾",
                    "title": f"实体 #{index + 1}: {entity_id}",
                    "subtitle": format_pos(entity),
                    "data": entity,
                })

        block_entities = get_first_mapping(chunk_data, ["block_entities", "BlockEntities", "TileEntities"])
        if isinstance(block_entities, list):
            for index, block_entity in enumerate(block_entities):
                block_id = str(tag_value(block_entity.get("id", "unknown"))) if isinstance(block_entity, dict) else "unknown"
                objects.append({
                    "icon": "📦",
                    "title": f"方块实体 #{index + 1}: {block_id}",
                    "subtitle": format_pos(block_entity),
                    "data": block_entity,
                })
        return objects

    def _reload_current_nbt_target(self) -> None:
        if isinstance(self._current_nbt_target, Path):
            self._load_nbt_file(self._current_nbt_target, self._current_nbt_label)
        elif isinstance(self._current_nbt_target, str):
            self._load_player_data(self._current_nbt_target)

    def _discard_nbt_changes(self, e: Any = None) -> None:
        try:
            if not self._staged_nbt_changes:
                self.app.info_dialog("提示", "暂存区没有变更。")
                return
            self._staged_nbt_changes.clear()
            self._update_nbt_stage_status()
            self._reload_current_nbt_target()
            self.app.info_dialog("已丢弃", "已丢弃暂存区中的 NBT 变更，并重新加载当前 NBT 数据。")
        except Exception as ex:
            self.app.handle_exception(ex, title="丢弃 NBT 变更失败")

    def _commit_nbt_changes(self, e: Any = None) -> None:
        try:
            if not self.world_session:
                self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return
            if not self._staged_nbt_changes:
                self.app.info_dialog("提示", "暂存区没有可提交的变更。")
                return
            self._show_commit_preview_dialog()
        except Exception as ex:
            self.app.handle_exception(ex, title="提交 NBT 变更失败")

    def _show_commit_preview_dialog(self) -> None:
        if not self.page:
            self._execute_nbt_commit()
            return
        summary_controls: List[ft.Control] = []
        for index, change in enumerate(self._staged_nbt_changes[:80]):
            summary_controls.append(ft.Container(
                content=ft.Text(
                    self._format_change_summary(index, change),
                    size=12,
                    color=THEME.text_secondary,
                    font_family="Consolas",
                ),
                padding=ft.Padding(left=8, right=8, top=6, bottom=6),
                bgcolor=THEME.bg_card,
            ))
        if len(self._staged_nbt_changes) > 80:
            summary_controls.append(ft.Text(
                f"还有 {len(self._staged_nbt_changes) - 80} 个变更未展示，提交时会一并写入。",
                size=12,
                color=THEME.warning,
            ))
        dialog = ft.AlertDialog(
            title=ft.Text("提交变更预览", color=THEME.text_primary),
            content=ft.Column([
                ft.Text(
                    f"即将提交 {len(self._staged_nbt_changes)} 个变更。提交前会自动备份当前存档。",
                    size=13,
                    color=THEME.text_primary,
                ),
                ft.Column(summary_controls, spacing=6, scroll=ft.ScrollMode.AUTO, height=360),
            ], tight=True, spacing=10),
            actions=[],
        )

        def close_dialog(e: Any = None) -> None:
            dialog.open = False
            self.page.update()

        def confirm_commit(e: Any = None) -> None:
            dialog.open = False
            self.page.update()
            self._execute_nbt_commit()

        dialog.actions = [
            ft.TextButton("确认提交", on_click=confirm_commit),
            ft.TextButton("取消", on_click=close_dialog),
        ]
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _execute_nbt_commit(self) -> None:
        try:
            if not self.world_session:
                self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return
            if not self._staged_nbt_changes:
                self.app.info_dialog("提示", "暂存区没有可提交的变更。")
                return
            for change in self._staged_nbt_changes:
                if change.get("format") == "json":
                    self.world_session.queue_modify_json(
                        change["target"],
                        change["path"],
                        change["new_value"],
                    )
                else:
                    self.world_session.queue_modify_nbt(
                        change["target"],
                        change["path"],
                        change["new_value"],
                    )
            queued = self.world_session.get_queue_size()
            success = self.world_session.commit(backup=True)
            if success:
                committed = len(self._staged_nbt_changes)
                self._staged_nbt_changes.clear()
                self._update_nbt_stage_status()
                self.world_session = WorldSession(self.world_session.world_path, log=self.app.log)
                self._reload_current_nbt_target()
                self.app.info_dialog("提交完成", f"已提交 {committed} 个 NBT/JSON 变更。提交前已创建备份。")
            else:
                self.app.error_dialog("提交失败", f"已排队 {queued} 个操作，但提交失败。请查看日志。")
        except Exception as ex:
            self.app.handle_exception(ex, title="提交 NBT 变更失败")
    
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
