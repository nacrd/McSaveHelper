"""Player tab mixin for ExplorerView — three-column player browser."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import flet as ft

from app.presenters.player_presenter import format_export_bundle_text
from app.services.asset_import import (
    import_assets_from_sources,
    pick_asset_sources,
    preferred_mc_locale,
    configured_minecraft_dir,
    current_save_start_path,
)
from app.services.player.models import PLAYER_EDIT_SPECS, PlayerEditSpec
from app.services.player_avatar_service import PlayerAvatarService
from app.services.player_service import PlayerService
from app.ui.components.buttons import btn_ghost, btn_primary
from app.ui.components.cards import card
from app.ui.components.fields import text_field
from app.ui.icons import IconSet
from app.ui.theme import THEME
from app.ui.utils import run_on_ui
from app.ui.views.explorer.equipment_preview import EquipmentPreview
from app.ui.views.explorer.inventory_grid import InventoryGrid
from app.ui.views.explorer.mixin_context import ExplorerMixinHost
from app.ui.views.explorer.player_hud import PlayerHUDCard
from app.ui.views.explorer.utils import safe_update
from core.omni.player_manager import PlayerManager

# Fields shown in the compact form (full registry still available via service).
_FORM_FIELD_IDS = (
    "Health",
    "foodLevel",
    "foodSaturationLevel",
    "XpLevel",
    "XpTotal",
    "XpP",
    "Air",
    "Pos.0",
    "Pos.1",
    "Pos.2",
    "Dimension",
    "playerGameType",
    "SelectedItemSlot",
    "SpawnX",
    "SpawnY",
    "SpawnZ",
    "SpawnDimension",
    "SpawnForced",
    "abilities.flying",
    "abilities.mayfly",
    "abilities.instabuild",
    "abilities.invulnerable",
    "abilities.mayBuild",
)

_GAME_TYPE_LABELS = {
    0: ("player.game_type.survival", "生存"),
    1: ("player.game_type.creative", "创造"),
    2: ("player.game_type.adventure", "冒险"),
    3: ("player.game_type.spectator", "旁观"),
}

_DEFAULT_COL_WIDTHS = (280.0, 340.0, 520.0)
_MIN_COL_WIDTHS = (220.0, 260.0, 320.0)
_SPLITTER_CHROME = 28.0  # two handles + padding budget
_LIST_AVATAR_SIZE = 36


def resize_adjacent_columns(
    widths: List[float],
    mins: List[float],
    boundary: int,
    delta: float,
) -> List[float]:
    """Return new widths after moving ``delta`` px across ``boundary``.

    Pure helper so column resize math can be unit-tested without Flet.
    """
    if boundary < 0 or boundary + 1 >= len(widths):
        return list(widths)
    result = list(widths)
    left_i = boundary
    right_i = boundary + 1
    proposed_left = result[left_i] + delta
    proposed_right = result[right_i] - delta
    if proposed_left < mins[left_i]:
        spill = mins[left_i] - proposed_left
        proposed_left = mins[left_i]
        proposed_right -= spill
    if proposed_right < mins[right_i]:
        spill = mins[right_i] - proposed_right
        proposed_right = mins[right_i]
        proposed_left -= spill
    if proposed_left < mins[left_i] or proposed_right < mins[right_i]:
        return list(widths)
    result[left_i] = proposed_left
    result[right_i] = proposed_right
    return result


def normalize_column_widths(
    widths: List[float],
    mins: List[float],
    available: float,
) -> List[float]:
    """Scale widths to ``available`` while keeping each column above its min."""
    if available <= 0:
        return list(widths)
    floor = sum(mins)
    target = max(floor, available)
    current = sum(widths) or 1.0
    scale = target / current
    scaled = [max(mins[i], w * scale) for i, w in enumerate(widths)]
    diff = target - sum(scaled)
    scaled[-1] = max(mins[-1], scaled[-1] + diff)
    return scaled


class PlayerTabMixin(ExplorerMixinHost):
    """Build and handle Explorer player tab interactions."""

    def _player_service(self) -> PlayerService:
        service = getattr(self, "_player_service_instance", None)
        if service is None:
            service = PlayerService(log=self.app.log)
            self._player_service_instance = service
        return service

    def _player_avatar_service(self) -> PlayerAvatarService:
        service = getattr(self, "_player_avatar_service_instance", None)
        if service is None:
            service = PlayerAvatarService(enabled=True)
            self._player_avatar_service_instance = service
        return service

    def _build_player_tab(self) -> None:
        t = self._t
        self._player_avatar_generation = 0
        self._player_refs_cache: List[Any] = []
        self._player_list_tiles: Dict[str, ft.Container] = {}
        self._player_container_index = 0
        self._center_section_index = 0
        self._shulker_dialog: Optional[ft.AlertDialog] = None

        left = self._build_player_left_column(t)
        center = self._build_player_center_column(t)
        right = self._build_player_right_column(t)
        self._assemble_player_layout(left, center, right)

    def _build_player_left_column(self, t: Any) -> ft.Column:
        """Search field + player list (top-aligned)."""
        left = ft.Column(
            spacing=8,
            expand=True,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        left.controls.append(
            ft.Text(
                t("explorer.select_player", "选择玩家"),
                size=14,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
            )
        )
        self._player_filter = text_field(
            label=t("player.filter", "搜索玩家"),
            # ``expand`` in a Column consumes vertical space and pushes the
            # list down. The list host below is the only vertical expander.
            expand=False,
            on_change=self._on_player_filter_changed,
        )
        left.controls.append(self._player_filter)
        left.controls.append(
            btn_ghost(
                t("explorer.import_usercache", "导入 usercache"),
                height=44,
                on_click=self._import_usercache,
            )
        )
        self._player_list_column = ft.Column(
            spacing=4,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        left.controls.append(
            ft.Container(
                content=self._player_list_column,
                expand=True,
                alignment=ft.Alignment(-1, -1),
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            )
        )
        return left

    def _build_player_center_column(self, t: Any) -> ft.Column:
        """HUD, section switcher, and categorized edit forms."""
        center = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
        self._player_hud = PlayerHUDCard(t_cb=self._t)
        center.controls.append(card(self._player_hud, padding=10))
        center.controls.append(self._responsive_chips(self._player_action_chips(t)))
        center.controls.append(self._responsive_chips(self._player_section_chips(t)))

        self._build_player_edit_fields()
        self._attributes_list = ft.Column(
            spacing=2, scroll=ft.ScrollMode.AUTO, height=180
        )
        self._effects_list = ft.Column(
            spacing=2, scroll=ft.ScrollMode.AUTO, height=140
        )
        self._section_vitals = self._build_vitals_section(t)
        self._section_world = self._build_world_section(t)
        self._section_abilities = self._build_abilities_section(t)
        self._section_advanced = self._build_advanced_section(t)
        center.controls.extend(
            [
                self._section_vitals,
                self._section_world,
                self._section_abilities,
                self._section_advanced,
            ]
        )
        center.controls.append(
            self._responsive_chips(
                [
                    self._chip_button(
                        t("player.edit.refresh", "刷新表单"),
                        self._refresh_player_edit_form,
                    ),
                    self._chip_button(
                        t("player.edit.stage", "暂存修改"),
                        self._stage_player_edit_form,
                        primary=True,
                    ),
                ]
            )
        )
        self._switch_center_section(0)
        return center

    def _player_action_chips(self, t: Any) -> list[ft.Control]:
        return [
            self._chip_button(
                t("player.export_action", "导出"),
                self._export_player_summary,
            ),
            self._chip_button(
                t("player.teleport_death", "死亡点"),
                self._stage_teleport_to_death,
            ),
            self._chip_button(
                t("player.import_assets", "导入语言/贴图"),
                self._import_language_and_textures,
            ),
        ]

    def _player_section_chips(self, t: Any) -> list[ft.Control]:
        section_defs = (
            (0, "player.section.vitals", "生命/经验"),
            (1, "player.section.world", "坐标/出生"),
            (2, "player.section.abilities", "能力"),
            (3, "player.section.advanced", "属性/效果"),
        )
        section_controls = [
            self._chip_button(
                t(key, default),
                lambda e, i=index: self._switch_center_section(i),
            )
            for index, key, default in section_defs
        ]
        self._center_section_btns = section_controls
        return section_controls

    def _build_vitals_section(self, t: Any) -> ft.Control:
        return self._build_section_card(
            t("player.edit.section_vitals", "生命 / 饥饿 / 经验"),
            [
                self._field_row("Health", "foodLevel"),
                self._field_row("foodSaturationLevel", "Air"),
                self._field_row("XpLevel", "XpTotal"),
                self._field_row("XpP", "playerGameType"),
                self._field_row("SelectedItemSlot"),
            ],
        )

    def _build_world_section(self, t: Any) -> ft.Control:
        return self._build_section_card(
            t("player.edit.section_pos", "坐标与维度"),
            [
                self._field_row("Pos.0", "Pos.1"),
                self._field_row("Pos.2", "Dimension"),
                ft.Text(
                    t("player.edit.section_spawn", "出生点"),
                    size=12,
                    color=THEME.text_secondary,
                ),
                self._field_row("SpawnX", "SpawnY"),
                self._field_row("SpawnZ", "SpawnForced"),
                self._field_row("SpawnDimension"),
            ],
        )

    def _build_abilities_section(self, t: Any) -> ft.Control:
        return self._build_section_card(
            t("player.edit.section_abilities", "能力"),
            [
                self._field_row("abilities.flying", "abilities.mayfly"),
                self._field_row(
                    "abilities.instabuild", "abilities.invulnerable"
                ),
                self._field_row("abilities.mayBuild"),
            ],
        )

    def _build_advanced_section(self, t: Any) -> ft.Control:
        return self._build_section_card(
            t("player.section.advanced", "属性 / 效果"),
            [
                ft.Text(
                    t("player.attributes.title", "属性 Attributes"),
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                self._attributes_list,
                ft.Container(height=6),
                ft.Text(
                    t("player.effects.title", "状态效果"),
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                self._effects_list,
            ],
        )

    def _build_player_right_column(self, t: Any) -> ft.Column:
        """Equipment, inventory/ender tabs, and nested container preview."""
        right = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
        self._equipment = EquipmentPreview(
            self.app.item,
            self.app.texture,
            slot_size=52,
            t_cb=self._t,
        )
        right.controls.append(card(self._equipment, padding=12))
        right.controls.extend(self._build_player_inventory_panels(t))
        right.controls.append(self._build_container_preview_panel(t))
        return right

    def _build_player_inventory_panels(self, t: Any) -> list[ft.Control]:
        """Main inventory / ender chest panels with tab chips."""
        self._inventory = InventoryGrid(
            self.app.item,
            self.app.texture,
            layout="main",
            slot_size=52,
            t_cb=self._t,
            on_slot_click=self._on_inventory_slot_click,
        )
        self._ender_inventory = InventoryGrid(
            self.app.item,
            self.app.texture,
            layout="ender",
            slot_size=52,
            t_cb=self._t,
            on_slot_click=self._on_inventory_slot_click,
        )
        self._inventory_panel = ft.Container(
            content=self._inventory,
            padding=ft.Padding(0, 4, 0, 0),
            visible=True,
        )
        self._ender_panel = ft.Container(
            content=self._ender_inventory,
            padding=ft.Padding(0, 4, 0, 0),
            visible=False,
        )
        self._container_tab_inventory_btn = self._chip_button(
            t("player.tab.inventory", "主背包"),
            lambda e: self._switch_player_container_tab(0),
        )
        self._container_tab_ender_btn = self._chip_button(
            t("player.tab.ender", "末影箱"),
            lambda e: self._switch_player_container_tab(1),
        )
        return [
            self._responsive_chips(
                [
                    self._container_tab_inventory_btn,
                    self._container_tab_ender_btn,
                ]
            ),
            self._inventory_panel,
            self._ender_panel,
        ]

    def _build_container_preview_panel(self, t: Any) -> ft.Container:
        """Nested container (shulker etc.) preview for the right column."""
        self._container_preview_title = ft.Text(
            t("player.container.preview_title", "容器内容"),
            size=13,
            weight=ft.FontWeight.BOLD,
            color=THEME.text_primary,
            expand=True,
        )
        self._container_preview_close = btn_ghost(
            t("common.close", "关闭"),
            height=44,
            on_click=self._close_container_preview,
        )
        self._container_preview_grid = InventoryGrid(
            self.app.item,
            self.app.texture,
            layout="shulker",
            slot_size=48,
            t_cb=self._t,
            title="",
        )
        self._container_preview_panel = ft.Container(
            content=card(
                ft.Column(
                    [
                        ft.Row(
                            [
                                self._container_preview_title,
                                self._container_preview_close,
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        self._container_preview_grid,
                    ],
                    spacing=8,
                ),
                padding=12,
            ),
            visible=False,
        )
        return self._container_preview_panel

    def _assemble_player_layout(
        self,
        left: ft.Column,
        center: ft.Column,
        right: ft.Column,
    ) -> None:
        """Wire resizable three-column layout into the player tab host."""
        self._player_col_widths = list(_DEFAULT_COL_WIDTHS)
        self._player_col_min = list(_MIN_COL_WIDTHS)
        self._player_layout_width = 0.0
        self._player_left_panel = ft.Container(
            content=left,
            width=self._player_col_widths[0],
            expand=False,
            padding=ft.Padding(0, 0, 4, 0),
        )
        self._player_center_panel = ft.Container(
            content=center,
            width=self._player_col_widths[1],
            expand=False,
            padding=ft.Padding(4, 0, 4, 0),
        )
        self._player_right_panel = ft.Container(
            content=right,
            width=self._player_col_widths[2],
            expand=False,
            padding=ft.Padding(4, 0, 0, 0),
        )
        self._player_split_left = self._build_column_splitter(0)
        self._player_split_right = self._build_column_splitter(1)
        self._player_layout = ft.Row(
            [
                self._player_left_panel,
                self._player_split_left,
                self._player_center_panel,
                self._player_split_right,
                self._player_right_panel,
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
        )
        self._player_layout_host = ft.Container(
            content=self._player_layout,
            expand=True,
            padding=ft.Padding(4, 4, 4, 4),
            on_size_change=self._on_player_layout_size_change,
        )
        self._tab_player.content = self._player_layout_host
        self._set_player_compact_layout(
            bool(getattr(self, "_compact_mode", False))
        )

    def _set_player_compact_layout(self, compact: bool) -> None:
        """Stack player panels in narrow windows so none are clipped."""
        host = getattr(self, "_player_layout_host", None)
        if host is None:
            return
        panels = (
            self._player_left_panel,
            self._player_center_panel,
            self._player_right_panel,
        )
        self._player_split_left.visible = not compact
        self._player_split_right.visible = not compact
        if compact:
            for panel in panels:
                panel.width = None
                panel.height = 360
                panel.expand = False
            stacked_controls: list[ft.Control] = list(panels)
            host.content = ft.Column(
                stacked_controls,
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )
        else:
            for panel in panels:
                panel.height = None
            self._apply_player_column_widths()
            host.content = self._player_layout
        safe_update(host)

    def _build_column_splitter(self, boundary: int) -> ft.Control:
        """Draggable vertical handle between player columns.

        ``boundary`` 0 resizes left/center; 1 resizes center/right.
        """
        handle = ft.Container(
            width=6,
            bgcolor=THEME.border_light,
            border_radius=3,
            margin=ft.Margin(left=2, top=8, right=2, bottom=8),
            tooltip=self._t("player.resize_columns", "拖拽调节列宽"),
        )

        def on_enter(_e: Any = None) -> None:
            handle.bgcolor = THEME.accent
            safe_update(handle)

        def on_exit(_e: Any = None) -> None:
            handle.bgcolor = THEME.border_light
            safe_update(handle)

        def on_update(e: Any) -> None:
            delta = _drag_delta_x(e)
            if abs(delta) < 0.5:
                return
            self._resize_player_columns(boundary, delta)

        return ft.GestureDetector(
            content=handle,
            mouse_cursor=ft.MouseCursor.RESIZE_COLUMN,
            drag_interval=16,
            on_enter=on_enter,
            on_exit=on_exit,
            on_horizontal_drag_update=on_update,
            on_pan_update=on_update,
        )

    def _on_player_layout_size_change(self, e: Any = None) -> None:
        """Keep column widths within the available layout width."""
        width = 0.0
        if e is not None:
            width = float(getattr(e, "width", 0.0) or 0.0)
        if width <= 1:
            return
        self._player_layout_width = width
        self._normalize_player_column_widths()
        self._apply_player_column_widths()

    def _resize_player_columns(self, boundary: int, delta: float) -> None:
        """Move width between two adjacent columns."""
        widths = list(
            getattr(self, "_player_col_widths", list(_DEFAULT_COL_WIDTHS))
        )
        mins = list(getattr(self, "_player_col_min", list(_MIN_COL_WIDTHS)))
        self._player_col_widths = resize_adjacent_columns(
            widths, mins, boundary, delta
        )
        self._apply_player_column_widths()

    def _normalize_player_column_widths(self) -> None:
        """Scale columns to fill available width while respecting mins."""
        widths = list(
            getattr(self, "_player_col_widths", list(_DEFAULT_COL_WIDTHS))
        )
        mins = list(getattr(self, "_player_col_min", list(_MIN_COL_WIDTHS)))
        available = max(
            sum(mins),
            float(getattr(self, "_player_layout_width", 0.0)) - _SPLITTER_CHROME,
        )
        self._player_col_widths = normalize_column_widths(
            widths, mins, available
        )

    def _apply_player_column_widths(self) -> None:
        widths = getattr(self, "_player_col_widths", None)
        if not widths or len(widths) < 3:
            return
        panels = (
            getattr(self, "_player_left_panel", None),
            getattr(self, "_player_center_panel", None),
            getattr(self, "_player_right_panel", None),
        )
        for panel, width in zip(panels, widths):
            if panel is None:
                continue
            panel.width = float(width)
            panel.expand = False
            safe_update(panel)
        # Rebuild list tiles only when name/UUID size class changes.
        wide_now = float(widths[0]) >= 250.0
        prev = getattr(self, "_player_list_wide", None)
        if prev is None or prev != wide_now:
            self._player_list_wide = wide_now
            if getattr(self, "_player_refs_cache", None):
                self._apply_player_list()

    def _chip_button(
        self,
        text: str,
        on_click: Any,
        *,
        primary: bool = False,
    ) -> ft.Control:
        """Compact action chip that can reflow in ResponsiveRow."""
        factory = btn_primary if primary else btn_ghost
        button = factory(text, height=44, on_click=on_click)
        # Clear fixed width so ResponsiveRow can size chips without collision.
        button.width = None
        # Give text room; McButton content is centered.
        try:
            button.padding = ft.Padding(8, 0, 8, 0)
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        return ft.Container(
            content=button,
            col={"xs": 12, "sm": 6, "md": 4, "lg": 3},
        )

    def _responsive_chips(self, controls: List[ft.Control]) -> ft.ResponsiveRow:
        return ft.ResponsiveRow(
            controls=controls,
            columns=12,
            spacing=6,
            run_spacing=6,
            alignment=ft.MainAxisAlignment.START,
        )

    def _build_player_edit_fields(self) -> None:
        t = self._t
        label_defaults = {
            "Health": ("player.edit.health", "生命值"),
            "foodLevel": ("player.edit.food", "饥饿值"),
            "foodSaturationLevel": ("player.edit.saturation", "饱和度"),
            "XpLevel": ("player.edit.xp_level", "经验等级"),
            "XpTotal": ("player.edit.xp_total", "总经验"),
            "XpP": ("player.edit.xp_p", "经验进度"),
            "Air": ("player.edit.air", "氧气"),
            "Pos.0": ("player.edit.pos_x", "X"),
            "Pos.1": ("player.edit.pos_y", "Y"),
            "Pos.2": ("player.edit.pos_z", "Z"),
            "Dimension": ("player.edit.dimension", "维度"),
            "playerGameType": ("player.edit.game_type", "游戏模式"),
            "SelectedItemSlot": ("player.edit.selected_slot", "选中槽"),
            "SpawnX": ("player.edit.spawn_x", "出生 X"),
            "SpawnY": ("player.edit.spawn_y", "出生 Y"),
            "SpawnZ": ("player.edit.spawn_z", "出生 Z"),
            "SpawnDimension": ("player.edit.spawn_dimension", "出生维度"),
            "SpawnForced": ("player.edit.spawn_forced", "强制出生"),
            "abilities.flying": ("player.edit.flying", "飞行中"),
            "abilities.mayfly": ("player.edit.mayfly", "可飞行"),
            "abilities.instabuild": ("player.edit.instabuild", "瞬间建造"),
            "abilities.invulnerable": ("player.edit.invulnerable", "无敌"),
            "abilities.mayBuild": ("player.edit.may_build", "可建造"),
        }
        self._player_edit_fields = {}
        for field_id in _FORM_FIELD_IDS:
            key, default = label_defaults.get(
                field_id, (f"player.edit.{field_id}", field_id)
            )
            # expand=True + no fixed width: fields share available column space.
            self._player_edit_fields[field_id] = text_field(
                label=t(key, default),
                expand=True,
            )

    def _field_row(self, *field_ids: str) -> ft.ResponsiveRow:
        """Two-up adaptive field row; narrow widths stack to one column."""
        cells: List[ft.Control] = []
        count = max(1, len(field_ids))
        # 2 fields => 6/12 each; 1 field => full width; 3 => 4/12 each.
        span = 12 // min(count, 2) if count <= 2 else 4
        for field_id in field_ids:
            field = self._player_edit_fields[field_id]
            cells.append(
                ft.Container(
                    content=field,
                    col={"xs": 12, "sm": span, "md": span, "lg": span},
                    padding=ft.Padding(0, 0, 4, 4),
                )
            )
        return ft.ResponsiveRow(
            controls=cells,
            columns=12,
            spacing=4,
            run_spacing=4,
        )

    def _build_section_card(
        self,
        title: str,
        body: List[ft.Control],
    ) -> ft.Container:
        return card(
            ft.Column(
                [
                    ft.Text(
                        title,
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary,
                    ),
                    *body,
                ],
                spacing=6,
            ),
            padding=10,
        )

    def _switch_center_section(self, index: int) -> None:
        """Show one edit category at a time to avoid a long scroll stack."""
        self._center_section_index = index
        panels = (
            getattr(self, "_section_vitals", None),
            getattr(self, "_section_world", None),
            getattr(self, "_section_abilities", None),
            getattr(self, "_section_advanced", None),
        )
        for i, panel in enumerate(panels):
            if panel is None:
                continue
            panel.visible = i == index
            safe_update(panel)

    # ── Player list (left column) ─────────────────────────────

    def _switch_player_container_tab(self, index: int) -> None:
        self._player_container_index = index
        if hasattr(self, "_inventory_panel"):
            self._inventory_panel.visible = index == 0
            safe_update(self._inventory_panel)
        if hasattr(self, "_ender_panel"):
            self._ender_panel.visible = index == 1
            safe_update(self._ender_panel)

    def _on_player_filter_changed(self, e: Any = None) -> None:
        try:
            self._apply_player_list()
        except Exception as ex:
            self.app.handle_exception(
                ex,
                title=self._t("player.error.filter", "过滤玩家失败"),
            )

    def _refresh_player_list(self) -> None:
        if not self.world_session or not hasattr(self, "_player_list_column"):
            return
        service = self._player_service()
        self._player_refs_cache = service.list_players(self.world_session)
        self._apply_player_list()
        if self._player_refs_cache and not self.current_uuid:
            first = self._player_refs_cache[0]
            self._load_player_data(first.uuid_hyphen)

    def _apply_player_list(self) -> None:
        if not hasattr(self, "_player_list_column"):
            return
        query = ""
        if hasattr(self, "_player_filter") and self._player_filter.value:
            query = str(self._player_filter.value).strip().lower()

        tiles: List[ft.Control] = []
        self._player_list_tiles = {}
        self._player_list_avatars: Dict[str, ft.CircleAvatar] = {}
        self._player_list_avatar_gen = (
            getattr(self, "_player_list_avatar_gen", 0) + 1
        )
        for ref in getattr(self, "_player_refs_cache", []):
            haystack = (
                f"{ref.display_name} {ref.uuid_norm} {ref.uuid_hyphen}".lower()
            )
            if query and query not in haystack:
                continue
            tile = self._build_player_list_tile(ref)
            self._player_list_tiles[ref.uuid_norm] = tile
            tiles.append(tile)
            self._load_list_avatar(ref)

        if not tiles:
            tiles.append(
                ft.Text(
                    self._t("player.list_empty", "没有匹配的玩家"),
                    size=13,
                    color=THEME.text_muted,
                )
            )
        self._player_list_column.controls = tiles
        safe_update(self._player_list_column)

    def _build_player_list_tile(self, ref: Any) -> ft.Container:
        selected = False
        if self.current_uuid:
            selected = (
                PlayerManager.normalize_uuid(self.current_uuid) == ref.uuid_norm
            )
        avatar = self._create_player_list_avatar(ref)
        list_width = float(
            (getattr(self, "_player_col_widths", None) or [280.0])[0]
        )
        name_size = 15 if list_width >= 250 else 13
        uuid_size = 11 if list_width >= 250 else 10
        uuid_text = ref.uuid_hyphen or ref.uuid_norm
        has_known_name = bool(ref.name)
        player_label = (
            ref.display_name
            if has_known_name
            else self._t("explorer.unknown_player", "未知玩家")
        )
        return ft.Container(
            content=ft.Row(
                [
                    avatar,
                    ft.Column(
                        [
                            ft.Text(
                                player_label,
                                size=name_size,
                                weight=ft.FontWeight.BOLD,
                                color=THEME.text_primary,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                uuid_text,
                                size=uuid_size,
                                color=THEME.text_muted,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                font_family="monospace",
                                selectable=True,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(10, 10, 10, 10),
            border_radius=8,
            bgcolor=THEME.mc_stone if selected else THEME.bg_secondary,
            border=ft.Border.all(
                1, THEME.accent if selected else THEME.border_light
            ),
            on_click=lambda e, uuid=ref.uuid_hyphen: self._on_player_tile_click(
                uuid
            ),
            ink=True,
            # Fill the list column width; tiles stack from the top under search.
            width=None,
            expand=False,
        )

    def _create_player_list_avatar(self, ref: Any) -> ft.CircleAvatar:
        has_known_name = bool(ref.name)
        content: ft.Control
        if has_known_name:
            content = ft.Text(
                ref.name[:1].upper(),
                size=14,
                color=THEME.text_primary,
            )
        else:
            content = ft.Icon(
                IconSet.PERSON,
                size=18,
                color=THEME.text_secondary,
            )
        avatar = ft.CircleAvatar(
            content=content,
            radius=_LIST_AVATAR_SIZE // 2,
            bgcolor=THEME.bg_secondary,
        )
        if not hasattr(self, "_player_list_avatars"):
            self._player_list_avatars = {}
        self._player_list_avatars[ref.uuid_norm] = avatar
        return avatar

    def _load_list_avatar(self, ref: Any) -> None:
        """Async-load face avatar into the player list tile."""
        avatars = getattr(self, "_player_list_avatars", None)
        if not avatars:
            return
        avatar = avatars.get(ref.uuid_norm)
        if avatar is None:
            return
        service = self._player_avatar_service()
        generation = getattr(self, "_player_list_avatar_gen", 0)

        cached = service.get_cached_path(ref.uuid_norm)
        if cached is not None:
            self._set_list_avatar_image(avatar, str(cached))
            return

        def on_loaded(path: Optional[str]) -> None:
            def apply() -> None:
                if generation != getattr(self, "_player_list_avatar_gen", 0):
                    return
                current = getattr(self, "_player_list_avatars", {}).get(
                    ref.uuid_norm
                )
                if current is None or path is None:
                    return
                self._set_list_avatar_image(current, path)

            try:
                page = getattr(self.app, "page", None)
            except Exception:
                # UI best-effort: app shell may already be tearing down.
                page = None
            run_on_ui(page, apply)

        service.load_avatar_async(ref.uuid_norm, on_loaded)

    def _set_list_avatar_image(
        self,
        avatar: ft.CircleAvatar,
        path: str,
    ) -> None:
        size = _LIST_AVATAR_SIZE
        avatar.content = ft.Image(
            src=path,
            width=size,
            height=size,
            fit=ft.BoxFit.COVER,
            border_radius=size // 2,
        )
        safe_update(avatar)

    def _on_player_tile_click(self, uuid: str) -> None:
        try:
            if not self.world_session:
                return
            self._load_player_data(uuid)
            self._apply_player_list()
        except Exception as ex:
            self.app.handle_exception(
                ex,
                title=self._t("player.error.select", "选择玩家失败"),
            )

    # ── Load / apply player data ──────────────────────────────

    def _load_player_data(self, uuid: str) -> None:
        try:
            if not self.world_session:
                return
            self.current_uuid = uuid
            self._current_chunk_target = None

            service = self._player_service()
            player_data = self.world_session.load_player_data(uuid)
            self._current_player_data = player_data

            summary = service.load_summary(self.world_session, uuid)
            containers = service.load_containers(self.world_session, uuid)
            attributes = service.load_attributes(self.world_session, uuid)
            effects = service.load_effects(self.world_session, uuid)
            self._apply_player_summary_ui(summary, player_data)
            self._apply_player_containers_ui(uuid, containers)
            self._apply_attributes_ui(attributes)
            self._apply_effects_ui(effects)
            self._apply_player_nbt_target(uuid)
            self._apply_player_list()
        except Exception as exc:
            self.app.handle_exception(
                exc,
                title=self._t("player.error.load", "加载玩家数据失败"),
            )

    def _apply_player_summary_ui(
        self,
        summary: Any,
        player_data: Any,
    ) -> None:
        if hasattr(self, "_player_hud") and summary is not None:
            self._player_hud.update_from_summary(summary)
            self._load_player_avatar(summary.ref.uuid_norm, summary.ref.name)
        elif hasattr(self, "_player_hud"):
            self._player_hud.update_from_nbt(player_data)

        if hasattr(self, "_player_edit_fields"):
            self._refresh_player_edit_form()

    def _apply_player_containers_ui(
        self,
        uuid: str,
        containers: Any,
    ) -> None:
        if containers is not None:
            inv_items = list(containers.inventory) + list(containers.equipment)
            if hasattr(self, "_inventory"):
                self._inventory.set_inventory(
                    list(containers.inventory),
                    selected_slot=containers.selected_slot,
                )
            if hasattr(self, "_equipment"):
                self._equipment.set_equipment(
                    list(containers.equipment) or inv_items
                )
            if hasattr(self, "_ender_inventory"):
                self._ender_inventory.set_inventory(list(containers.ender_items))
            return

        if not self.world_session:
            return
        inv = self.world_session.get_player_inventory(uuid)
        if hasattr(self, "_inventory"):
            self._inventory.set_inventory(inv)
        if hasattr(self, "_equipment"):
            self._equipment.set_equipment(inv)
        if hasattr(self, "_ender_inventory"):
            ender = self.world_session.get_player_ender_items(uuid)
            self._ender_inventory.set_inventory(ender)

    def _apply_attributes_ui(self, attributes: Any) -> None:
        if not hasattr(self, "_attributes_list"):
            return
        rows: List[ft.Control] = []
        if not attributes:
            rows.append(
                ft.Text(
                    self._t("player.attributes.empty", "无属性数据"),
                    size=12,
                    color=THEME.text_muted,
                )
            )
        else:
            for attr in attributes:
                base = "--" if attr.base is None else f"{attr.base:g}"
                mod = (
                    f"  (+{attr.modifiers} mods)"
                    if attr.modifiers
                    else ""
                )
                rows.append(
                    ft.Text(
                        f"{attr.name}: {base}{mod}",
                        size=12,
                        color=THEME.text_secondary,
                        font_family="monospace",
                    )
                )
        self._attributes_list.controls = rows
        safe_update(self._attributes_list)

    def _apply_effects_ui(self, effects: Any) -> None:
        if not hasattr(self, "_effects_list"):
            return
        rows: List[ft.Control] = []
        if not effects:
            rows.append(
                ft.Text(
                    self._t("player.effects.empty", "无状态效果"),
                    size=12,
                    color=THEME.text_muted,
                )
            )
        else:
            for effect in effects:
                amp = effect.amplifier + 1
                duration_s = max(0, effect.duration) // 20
                rows.append(
                    ft.Text(
                        f"{effect.id} ×{amp}  ({duration_s}s)",
                        size=12,
                        color=THEME.text_secondary,
                        font_family="monospace",
                    )
                )
        self._effects_list.controls = rows
        safe_update(self._effects_list)

    def _apply_player_nbt_target(self, uuid: str) -> None:
        if not self.world_session:
            return
        nbt = self.world_session.load_player_nbt(uuid)
        self._current_nbt_target = uuid
        self._current_nbt_label = (
            f"{self._t('player.nbt_label', '玩家 NBT')}: {uuid}"
        )
        if hasattr(self, "_nbt_target_label"):
            self._nbt_target_label.value = self._current_nbt_label
            safe_update(self._nbt_target_label)
        if hasattr(self, "_nbt_tree"):
            self._nbt_tree.load_nbt(nbt)

    def _load_player_avatar(
        self,
        uuid_norm: str,
        name: Optional[str],
    ) -> None:
        if not hasattr(self, "_player_hud"):
            return
        self._player_avatar_generation = getattr(
            self, "_player_avatar_generation", 0
        ) + 1
        generation = self._player_avatar_generation
        service = self._player_avatar_service()

        cached = service.get_cached_path(uuid_norm)
        if cached is not None:
            self._player_hud.set_avatar_src(
                str(cached),
                initial=(name or uuid_norm or "?")[:1],
            )
            return

        def on_loaded(path: Optional[str]) -> None:
            def apply() -> None:
                if generation != getattr(self, "_player_avatar_generation", 0):
                    return
                if not hasattr(self, "_player_hud"):
                    return
                if path:
                    self._player_hud.set_avatar_src(
                        path,
                        initial=(name or uuid_norm or "?")[:1],
                    )

            try:
                page = getattr(self.app, "page", None)
            except Exception:
                # UI best-effort: app shell may already be tearing down.
                page = None
            run_on_ui(page, apply)

        service.load_avatar_async(uuid_norm, on_loaded)

    # ── Nested container preview (right column empty space) ──

    def _on_inventory_slot_click(
        self,
        slot: int,
        item: Optional[Dict[str, Any]],
    ) -> None:
        try:
            if not item:
                return
            item_id = str(item.get("id", "") or "")
            nested = self._player_service().open_nested_container(item)
            if nested is None:
                return
            self._show_container_preview(item_id, nested)
        except Exception as ex:
            self.app.handle_exception(
                ex,
                title=self._t("player.error.shulker", "打开潜影盒失败"),
            )

    def _show_container_preview(
        self,
        item_id: str,
        nested_items: List[Dict[str, Any]],
    ) -> None:
        """Show nested container contents in the right-column free space."""
        t = self._t
        title = item_id or t("player.inventory.shulker", "潜影盒内容")
        if hasattr(self, "_container_preview_title"):
            self._container_preview_title.value = (
                f"{t('player.container.preview_title', '容器内容')}: {title}"
            )
            safe_update(self._container_preview_title)
        if hasattr(self, "_container_preview_grid"):
            self._container_preview_grid.set_inventory(nested_items)
        if hasattr(self, "_container_preview_panel"):
            self._container_preview_panel.visible = True
            safe_update(self._container_preview_panel)

    def _close_container_preview(self, e: Any = None) -> None:
        if hasattr(self, "_container_preview_panel"):
            self._container_preview_panel.visible = False
            safe_update(self._container_preview_panel)
        if hasattr(self, "_container_preview_grid"):
            self._container_preview_grid.clear()

    # keep old name as alias for any external references
    def _show_shulker_dialog(
        self,
        item_id: str,
        nested_items: List[Dict[str, Any]],
    ) -> None:
        self._show_container_preview(item_id, nested_items)

    # ── Edit form / stage / export ────────────────────────────

    def _refresh_player_edit_form(self, e: Any = None) -> None:
        try:
            if not self._current_player_data:
                return
            values = self._player_service().form_values_from_data(
                self._current_player_data,
                specs=self._active_edit_specs(),
            )
            for field_id, field in self._player_edit_fields.items():
                field.value = values.get(field_id, "")
                safe_update(field)
        except Exception as ex:
            self.app.handle_exception(
                ex,
                title=self._t(
                    "player.error.refresh_form", "刷新玩家编辑表单失败"
                ),
            )

    def _stage_player_edit_form(self, e: Any = None) -> None:
        try:
            if not self.current_uuid or not self._current_player_data:
                self.app.warn_dialog(
                    self._t("dialogs.hint", "提示"),
                    self._t("player.need_select", "请先选择玩家。"),
                )
                return
            result = self._player_service().build_edit_changes(
                self.current_uuid,
                self._current_player_data,
                self._collect_player_field_values(),
                specs=self._active_edit_specs(),
                target_label=(
                    f"{self._t('player.nbt_label', '玩家 NBT')}: "
                    f"{self.current_uuid}"
                ),
            )
            self._apply_player_stage_result(result)
        except Exception as ex:
            self.app.handle_exception(
                ex,
                title=self._t("player.error.stage", "暂存玩家数据失败"),
            )

    def _collect_player_field_values(self) -> Dict[str, str]:
        field_values: Dict[str, str] = {}
        for field_id, field in self._player_edit_fields.items():
            if field.value is None:
                continue
            text = str(field.value).strip()
            if text == "":
                continue
            field_values[field_id] = text
        return field_values

    def _apply_player_stage_result(self, result: Any) -> None:
        if result.errors:
            self.app.warn_dialog(
                self._t("dialogs.hint", "提示"),
                self._t(
                    "player.edit.validation_errors",
                    "部分字段未暂存：{errors}",
                    errors=", ".join(result.errors),
                ),
            )
        for change in result.changes:
            self._nbt_stage_store.add(change)
        self._update_nbt_stage_status()
        if result.staged_count:
            self.app.info_dialog(
                self._t("player.edit.staged_title", "已暂存"),
                self._t(
                    "player.edit.staged_body",
                    "已暂存 {count} 个玩家数据修改，可到 NBT 页查看并提交。",
                    count=result.staged_count,
                ),
            )
            self._switch_tab(5)
            return
        if not result.errors:
            self.app.info_dialog(
                self._t("dialogs.hint", "提示"),
                self._t(
                    "player.edit.no_changes",
                    "没有检测到需要暂存的玩家数据修改。",
                ),
            )

    def _stage_teleport_to_death(self, e: Any = None) -> None:
        try:
            if not self.current_uuid or not self._current_player_data:
                self.app.warn_dialog(
                    self._t("dialogs.hint", "提示"),
                    self._t("player.need_select", "请先选择玩家。"),
                )
                return
            result = self._player_service().build_teleport_to_death_changes(
                self.current_uuid,
                self._current_player_data,
                target_label=(
                    f"{self._t('player.nbt_label', '玩家 NBT')}: "
                    f"{self.current_uuid}"
                ),
            )
            if result.errors:
                self.app.warn_dialog(
                    self._t("dialogs.hint", "提示"),
                    self._t(
                        "player.no_death_location",
                        "当前玩家没有可用的死亡位置。",
                    ),
                )
                return
            for change in result.changes:
                self._nbt_stage_store.add(change)
            self._update_nbt_stage_status()
            self.app.info_dialog(
                self._t("player.edit.staged_title", "已暂存"),
                self._t(
                    "player.teleport_death_staged",
                    "已暂存传送到死亡点的坐标修改。",
                ),
            )
            self._switch_tab(5)
        except Exception as ex:
            self.app.handle_exception(
                ex,
                title=self._t("player.error.teleport", "暂存传送失败"),
            )

    def _export_player_summary(self, e: Any = None) -> None:
        try:
            if not self.world_session or not self.current_uuid:
                self.app.warn_dialog(
                    self._t("dialogs.hint", "提示"),
                    self._t("player.need_select", "请先选择玩家。"),
                )
                return
            bundle = self._player_service().build_export(
                self.world_session,
                self.current_uuid,
                include_items=True,
            )
            if bundle is None:
                self.app.warn_dialog(
                    self._t("dialogs.hint", "提示"),
                    self._t("player.export_failed", "无法导出玩家摘要。"),
                )
                return

            path = self.app.save_file(
                title=self._t("player.export_dialog", "导出玩家摘要"),
                default_ext=".json",
                file_types=[
                    ("JSON", "*.json"),
                    ("Text", "*.txt"),
                ],
            )
            if not path:
                return
            out = Path(path)
            if out.suffix.lower() == ".txt":
                text = format_export_bundle_text(bundle, translate=self._t)
                out.write_text(text, encoding="utf-8")
            else:
                out.write_text(
                    json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            self.app.info_dialog(
                self._t("player.export_ok_title", "导出成功"),
                self._t(
                    "player.export_ok_body",
                    "已导出玩家摘要到：\n{path}",
                    path=str(out),
                ),
            )
        except Exception as ex:
            self.app.handle_exception(
                ex,
                title=self._t("player.error.export", "导出玩家摘要失败"),
            )

    def _import_usercache(self, e: Any = None) -> None:
        try:
            path = self.app.pick_file(
                title=self._t(
                    "player.import_usercache_title",
                    "选择 usercache.json",
                ),
                file_types=[("JSON (*.json)", "*.json")],
            )
            if path and self.world_session:
                imported = self.world_session.import_usercache(Path(path))
                if imported > 0:
                    self._refresh_player_list()
                    self.app.info_dialog(
                        self._t("dialogs.success", "成功"),
                        self._t(
                            "explorer.imported_cache",
                            "成功导入 {count} 个玩家名称。",
                            count=imported,
                        ),
                    )
                else:
                    self.app.info_dialog(
                        self._t("dialogs.hint", "提示"),
                        self._t(
                            "player.import_empty",
                            "未能导入任何玩家名称。",
                        ),
                    )
        except Exception as ex:
            self.app.handle_exception(
                ex,
                title=self._t(
                    "player.error.import_usercache", "导入 usercache 失败"
                ),
            )

    def _import_language_and_textures(self, e: Any = None) -> None:
        """Unified importer: language JSON/JAR and bulk jar textures."""
        try:
            title = self._t(
                "player.import_assets_title",
                "选择语言 JSON / Minecraft 或模组 JAR（可多选）",
            )
            paths = pick_asset_sources(self.app, title)
            if not paths:
                return
            locale = preferred_mc_locale(self.app)
            counts = import_assets_from_sources(
                item_service=self.app.item,
                texture_service=self.app.texture,
                paths=paths,
                locale=locale,
                configured_dir=configured_minecraft_dir(self.app),
                start_path=current_save_start_path(self.app),
                empty_jar_results_fallback=True,
            )
            self._notify_asset_import(
                lang_count=counts.lang_count,
                texture_count=counts.texture_count,
                jar_count=counts.jar_count,
                lang_sources=counts.lang_sources,
            )
        except Exception as ex:
            self.app.handle_exception(
                ex,
                title=self._t(
                    "player.error.import_assets",
                    "导入语言/贴图失败",
                ),
            )

    def _notify_asset_import(
        self,
        *,
        lang_count: int,
        texture_count: int,
        jar_count: int,
        lang_sources: int,
    ) -> None:
        if lang_count <= 0 and texture_count <= 0:
            self.app.info_dialog(
                self._t("dialogs.hint", "提示"),
                self._t(
                    "player.import_assets_empty",
                    "未导入任何语言名称或贴图。\n\n"
                    "支持：\n"
                    "- 语言 JSON（item.minecraft.xxx）\n"
                    "- 客户端/模组 JAR 内 lang 与 textures\n"
                    "- 可一次多选多个 JAR 批量导入贴图",
                ),
            )
            return
        parts = []
        if lang_count > 0:
            parts.append(
                self._t(
                    "player.import_assets_lang",
                    "语言名称 {count} 个",
                    count=lang_count,
                )
            )
        if texture_count > 0:
            parts.append(
                self._t(
                    "player.import_assets_tex",
                    "贴图 {count} 张（来自 {jars} 个 JAR）",
                    count=texture_count,
                    jars=max(1, jar_count),
                )
            )
        detail = "；".join(parts)
        self.app.info_dialog(
            self._t("dialogs.success", "成功"),
            self._t(
                "player.import_assets_ok",
                "导入完成：{detail}。\n物品栏名称与贴图将立即生效。",
                detail=detail,
            ),
        )
        if self.current_uuid:
            self._load_player_data(self.current_uuid)

    # Back-compat aliases used by older hooks/tests.
    def _import_language_file(self, e: Any = None) -> None:
        self._import_language_and_textures(e)

    def _import_language_from_minecraft(self, e: Any = None) -> None:
        try:
            locale = preferred_mc_locale(self.app)
            counts = import_assets_from_sources(
                item_service=self.app.item,
                texture_service=self.app.texture,
                paths=[],
                locale=locale,
                configured_dir=configured_minecraft_dir(self.app),
                start_path=current_save_start_path(self.app),
                empty_paths_fallback=True,
            )
            self._notify_asset_import(
                lang_count=counts.lang_count,
                texture_count=counts.texture_count,
                jar_count=counts.jar_count,
                lang_sources=counts.lang_sources,
            )
        except Exception as ex:
            self.app.handle_exception(
                ex,
                title=self._t(
                    "player.error.import_assets",
                    "导入语言/贴图失败",
                ),
            )

    def _active_edit_specs(self) -> List[PlayerEditSpec]:
        wanted = set(_FORM_FIELD_IDS)
        return [spec for spec in PLAYER_EDIT_SPECS if spec.field_id in wanted]

    def _player_edit_mapping(self) -> Dict[str, List[Any]]:
        return {
            spec.field_id: list(spec.nbt_path)
            for spec in self._active_edit_specs()
        }

    def _get_tag_at_path(self, data: Any, path: List[Any]) -> Any:
        node = data
        for part in path:
            node = node[part]
        return node


def _drag_delta_x(event: Any) -> float:
    """Extract horizontal drag delta from a Flet drag/pan event."""
    local_delta = getattr(event, "local_delta", None)
    if local_delta is not None:
        return float(getattr(local_delta, "x", 0.0) or 0.0)
    primary = getattr(event, "primary_delta", None)
    if primary is not None:
        return float(primary or 0.0)
    global_delta = getattr(event, "global_delta", None)
    if global_delta is not None:
        return float(getattr(global_delta, "x", 0.0) or 0.0)
    return 0.0


def _coord(value: Any) -> str:
    if value is None:
        return "--"
    try:
        number = float(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:.1f}"
    except (TypeError, ValueError):
        return str(value)
