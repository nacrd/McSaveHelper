"""Minecraft-style sidebar navigation component — collapsible edition

Supports two states:
  - Expanded (220px): branding + current save + tabs (icon+text) + recent saves + version
  - Collapsed (60px):  brand icon + tabs (icon only, tooltip text) + expand button
"""
import traceback
from typing import Callable, List, Dict, Any, Optional

import flet as ft

from app.ui.theme import THEME, mc_border, mc_shadow_glow
from app.ui.icons import IconSet
from core.version import APP_VERSION


class Sidebar(ft.Container):
    """Left navigation sidebar with collapsible support.

    Args:
        tabs: List of dicts with keys ``id``, ``label``, ``icon``.
        on_tab_select: Called with the new tab id when a tab is clicked.
        on_tabs_reorder: Called when the user changes tab order.
        on_import_save: Called when the "import save" action is triggered.
        on_set_current_save: Called when the "set current save" button is clicked.
        on_recent_save_select: Called with the save id/path when a recent save is clicked.
        recent_saves: Initial list of recent save dicts.
        default_tab: Tab id to select on creation.
        width: Initial sidebar width in pixels (default 220).
        collapsed: Whether to start in collapsed state (default False).
    """

    COLLAPSED_WIDTH = 60
    EXPANDED_WIDTH = 220

    def __init__(
        self,
        tabs: List[Dict[str, Any]],
        on_tab_select: Callable[[str], None],
        on_tabs_reorder: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        on_import_save: Optional[Callable[[], None]] = None,
        on_set_current_save: Optional[Callable[[], None]] = None,
        on_recent_save_select: Optional[Callable[[str], None]] = None,
        recent_saves: Optional[List[Dict[str, Any]]] = None,
        default_tab: Optional[str] = None,
        width: int = 220,
        collapsed: bool = False,
    ) -> None:
        self._tabs: List[Dict[str, Any]] = list(tabs)
        self._on_tab_select: Callable[[str], None] = on_tab_select
        self._on_tabs_reorder = on_tabs_reorder
        self._on_import_save = on_import_save
        self._on_set_current_save = on_set_current_save
        self._on_recent_save_select = on_recent_save_select
        self._recent_saves: List[Dict[str, Any]] = list(recent_saves or [])
        self._selected_id: Optional[str] = default_tab or (
            tabs[0]["id"] if tabs else None
        )
        self._buttons: Dict[str, ft.Container] = {}
        self._collapsed = collapsed
        self._sidebar_width = self.COLLAPSED_WIDTH if collapsed else width
        self._tab_col: ft.ListView = ft.ListView(
            spacing=6 if collapsed else 8,
            padding=0,
            expand=True,
            auto_scroll=False,
        )
        self._recent_save_col: ft.Column = ft.Column(spacing=6)

        # ─── Mutable sub-components ───
        self._current_save_name = ft.Text(
            "未设置当前存档",
            size=12,
            color=THEME.text_muted,
            font_family="monospace",
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        # Header section (rebuilt on toggle)
        self._header_container = ft.Container(expand=False)
        # Footer section (rebuilt on toggle)
        self._footer_container = ft.Container(expand=False)
        # Toggle button (rebuilt on toggle)
        self._toggle_btn = ft.Container(expand=False)

        self._rebuild_all()

        col = ft.Column(spacing=0, expand=True)
        col.controls.append(self._header_container)
        col.controls.append(
            ft.Container(
                content=self._tab_col,
                padding=ft.Padding(
                    left=6 if collapsed else 12,
                    right=6 if collapsed else 12,
                    top=10,
                    bottom=8,
                ),
                expand=True,
            )
        )
        col.controls.append(self._toggle_btn)
        col.controls.append(self._footer_container)

        effective_width = self.COLLAPSED_WIDTH if collapsed else self._sidebar_width
        super().__init__(
            content=col,
            width=effective_width,
            bgcolor=THEME.bg_primary,
            border=ft.Border(
                left=None,
                top=None,
                right=ft.BorderSide(3, THEME.bg_secondary),
                bottom=None,
            ),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )

    # ════════════════════════════════════════════
    #  Rebuild helpers
    # ════════════════════════════════════════════

    def _rebuild_all(self) -> None:
        """Rebuild header, tabs, toggle button, and footer."""
        self._rebuild_header()
        self._rebuild_tab_buttons()
        self._rebuild_toggle_btn()
        self._rebuild_footer()
        self._rebuild_recent_saves()

    def _rebuild_header(self) -> None:
        """Build the header section (branding + current save + recent saves)."""
        if self._collapsed:
            self._header_container.content = self._build_header_collapsed()
        else:
            self._header_container.content = self._build_header_expanded()
        self._header_container.padding = 0

    def _build_header_collapsed(self) -> ft.Container:
        """Collapsed header: just the brand icon."""
        return ft.Container(
            content=ft.Container(
                content=ft.Icon(IconSet.PICKAXE, size=22, color=THEME.mc_gold),
                width=40,
                height=40,
                alignment=ft.alignment.Alignment(0, 0),
                bgcolor=THEME.bg_secondary,
                border=mc_border(2),
                border_radius=6,
            ),
            alignment=ft.alignment.Alignment(0, 0),
            padding=ft.Padding(left=0, right=0, top=16, bottom=16),
            bgcolor=THEME.mc_dirt,
            border=ft.Border(
                left=None, top=None, right=None,
                bottom=ft.BorderSide(3, THEME.mc_grass),
            ),
        )

    def _build_header_expanded(self) -> ft.Container:
        """Expanded header: branding + current save + import button + recent saves."""
        return ft.Container(
            content=ft.Column(
                [
                    # ─── Branding ───
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(
                                    IconSet.PICKAXE, size=20, color=THEME.mc_gold,
                                ),
                                width=36, height=36,
                                alignment=ft.alignment.Alignment(0, 0),
                                bgcolor=THEME.bg_secondary,
                                border=mc_border(2),
                                border_radius=6,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        "MCSaveHelper",
                                        size=15,
                                        weight=ft.FontWeight.BOLD,
                                        color=THEME.mc_gold,
                                        font_family="monospace",
                                    ),
                                    ft.Text(
                                        "Minecraft Save Toolkit",
                                        size=10,
                                        color=THEME.text_muted,
                                        font_family="monospace",
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    # ─── Divider ───
                    ft.Container(
                        height=1,
                        bgcolor=THEME.border_subtle,
                        margin=ft.Margin(top=12, bottom=12, left=0, right=0),
                    ),
                    # ─── Current Save ───
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(
                                            IconSet.SAVE, size=14, color=THEME.mc_grass,
                                        ),
                                        ft.Text(
                                            "当前存档",
                                            size=11,
                                            weight=ft.FontWeight.W_600,
                                            color=THEME.text_secondary,
                                            font_family="monospace",
                                        ),
                                    ],
                                    spacing=6,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                self._current_save_name,
                            ],
                            spacing=6,
                        ),
                        padding=8,
                        bgcolor=THEME.bg_secondary,
                        border_radius=6,
                        border=mc_border(1),
                    ),
                    # ─── Set Current Save Button ───
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(
                                    IconSet.FOLDER_OPEN, size=16, color=THEME.text_primary,
                                ),
                                ft.Text(
                                    "设置当前存档",
                                    size=12,
                                    weight=ft.FontWeight.W_600,
                                    color=THEME.text_primary,
                                ),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding(left=12, right=12, top=10, bottom=10),
                        bgcolor=THEME.mc_grass,
                        border_radius=6,
                        border=mc_border(2),
                        ink=True,
                        on_click=self._handle_set_current_save,
                        margin=ft.Margin(top=10, bottom=0, left=0, right=0),
                        shadow=mc_shadow_glow(THEME.shadow_accent, 6),
                    ),
                    # ─── Recent Saves ───
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(
                                            IconSet.CLOCK, size=12, color=THEME.text_secondary,
                                        ),
                                        ft.Text(
                                            "最近存档",
                                            size=11,
                                            weight=ft.FontWeight.W_600,
                                            color=THEME.text_primary,
                                            font_family="monospace",
                                        ),
                                    ],
                                    spacing=6,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                self._recent_save_col,
                            ],
                            spacing=8,
                        ),
                        padding=ft.Padding(left=0, right=0, top=12, bottom=0),
                    ),
                ],
                spacing=0,
            ),
            padding=ft.Padding(left=16, right=16, top=16, bottom=16),
            bgcolor=THEME.mc_dirt,
            border=ft.Border(
                left=None, top=None, right=None,
                bottom=ft.BorderSide(3, THEME.mc_grass),
            ),
        )

    def _rebuild_footer(self) -> None:
        """Build the footer section."""
        if self._collapsed:
            self._footer_container.content = ft.Container(height=0)
            self._footer_container.padding = 0
        else:
            self._footer_container.content = ft.Container(
                content=ft.Row(
                    [
                        ft.Text(
                            APP_VERSION,
                            size=10, color=THEME.text_secondary,
                            font_family="monospace",
                        ),
                        ft.Container(expand=True),
                        ft.Text(
                            "▣ stone edition",
                            size=10, color=THEME.text_muted,
                            font_family="monospace",
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=ft.Padding(left=16, top=12, right=16, bottom=12),
                bgcolor=THEME.bg_secondary,
            )
            self._footer_container.padding = 0

    def _rebuild_toggle_btn(self) -> None:
        """Build the expand/collapse toggle button."""
        if self._collapsed:
            icon = IconSet.ARROW_RIGHT  # ▶ expand
            tooltip = "展开侧边栏"
        else:
            icon = IconSet.ARROW_LEFT   # ◀ collapse
            tooltip = "收起侧边栏"

        self._toggle_btn.content = ft.Container(
            content=ft.Icon(icon, size=16, color=THEME.text_secondary),
            alignment=ft.alignment.Alignment(0, 0),
            padding=8,
            bgcolor=THEME.bg_secondary,
            border=ft.Border(
                left=None, top=ft.BorderSide(1, THEME.border_subtle),
                right=None, bottom=None,
            ),
            ink=True,
            on_click=self._handle_toggle,
            tooltip=tooltip,
        )
        self._toggle_btn.padding = 0

    # ════════════════════════════════════════════
    #  Tab buttons
    # ════════════════════════════════════════════

    def _rebuild_tab_buttons(self) -> None:
        """Rebuild all tab buttons according to current collapsed state."""
        self._tab_col.controls.clear()
        self._buttons.clear()
        for tab in self._tabs:
            btn = self._build_tab_button(tab)
            self._buttons[tab["id"]] = btn
            self._tab_col.controls.append(btn)

    def _build_tab_button(self, tab: Dict[str, Any]) -> ft.Container:
        """Build a single tab button.

        In collapsed mode: icon only with tooltip.
        In expanded mode: icon + text label + selection indicator.
        """
        selected = tab["id"] == self._selected_id
        icon_name = tab.get("icon", IconSet.GRID)
        label_text = tab.get("label", tab["id"])

        if self._collapsed:
            return self._build_tab_collapsed(tab, selected, icon_name, label_text)
        return self._build_tab_expanded(tab, selected, icon_name, label_text)

    def _build_tab_collapsed(
        self, tab: Dict[str, Any], selected: bool,
        icon_name: str, label_text: str,
    ) -> ft.Container:
        """Collapsed tab: centered icon with tooltip."""
        icon_ctrl = ft.Icon(
            icon_name,
            size=20,
            color=THEME.mc_obsidian if selected else THEME.text_secondary,
        )
        container = ft.Container(
            content=icon_ctrl,
            width=40,
            height=40,
            alignment=ft.alignment.Alignment(0, 0),
            bgcolor=THEME.mc_gold if selected else THEME.bg_card,
            border=mc_border(2),
            border_radius=6,
            ink=True,
            on_click=lambda e, tid=tab["id"]: self._safe_select(tid),
            on_hover=lambda e, tid=tab["id"]: self._handle_hover_collapsed(e, tid),
            tooltip=label_text,
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )
        if selected:
            container.shadow = mc_shadow_glow(THEME.shadow_glow, 4)
        return container

    def _build_tab_expanded(
        self, tab: Dict[str, Any], selected: bool,
        icon_name: str, label_text: str,
    ) -> ft.Container:
        """Expanded tab: icon + text label + selection arrow."""
        icon_slot = ft.Container(
            content=ft.Icon(
                icon_name, size=18,
                color=THEME.mc_obsidian if selected else THEME.text_secondary,
            ),
            width=34, height=34,
            alignment=ft.alignment.Alignment(0, 0),
            bgcolor=THEME.mc_gold if selected else THEME.bg_secondary,
            border=mc_border(2),
            border_radius=4,
        )
        text_ctrl = ft.Text(
            label_text,
            size=13,
            color=THEME.text_primary if selected else THEME.text_secondary,
            weight=ft.FontWeight.BOLD if selected else ft.FontWeight.W_500,
            font_family="monospace",
        )
        marker = ft.Text(
            "▶" if selected else "",
            size=10,
            color=THEME.mc_grass,
        )
        row = ft.Row(
            [icon_slot, ft.Column([text_ctrl, marker], spacing=0, expand=True)],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        container = ft.Container(
            content=row,
            padding=10,
            border_radius=6,
            bgcolor=THEME.mc_stone if selected else THEME.bg_card,
            border=mc_border(2),
            ink=True,
            on_click=lambda e, tid=tab["id"]: self._safe_select(tid),
            on_hover=lambda e, tid=tab["id"]: self._handle_hover(e, tid),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )
        if selected:
            container.shadow = mc_shadow_glow(THEME.shadow_glow, 4)
        return container

    # ════════════════════════════════════════════
    #  Hover handlers
    # ════════════════════════════════════════════

    def _handle_hover(self, e: ft.ControlEvent, tab_id: str) -> None:
        """Hover handler for expanded tab buttons."""
        try:
            if tab_id not in self._buttons:
                return
            container = self._buttons[tab_id]
            is_selected = tab_id == self._selected_id
            if e.data == "true":
                if not is_selected:
                    container.bgcolor = THEME.bg_card_hover
                    container.shadow = mc_shadow_glow(THEME.shadow_glow, 6)
                    row = container.content
                    if isinstance(row, ft.Row) and len(row.controls) >= 1:
                        icon_slot = row.controls[0]
                        if isinstance(icon_slot, ft.Container):
                            icon_slot.bgcolor = THEME.mc_iron
            else:
                if not is_selected:
                    container.bgcolor = THEME.bg_card
                    container.shadow = None
                    row = container.content
                    if isinstance(row, ft.Row) and len(row.controls) >= 1:
                        icon_slot = row.controls[0]
                        if isinstance(icon_slot, ft.Container):
                            icon_slot.bgcolor = THEME.bg_secondary
            container.update()
        except Exception:
            pass

    def _handle_hover_collapsed(self, e: ft.ControlEvent, tab_id: str) -> None:
        """Hover handler for collapsed tab buttons."""
        try:
            if tab_id not in self._buttons:
                return
            container = self._buttons[tab_id]
            is_selected = tab_id == self._selected_id
            if e.data == "true":
                if not is_selected:
                    container.bgcolor = THEME.mc_iron
                    container.shadow = mc_shadow_glow(THEME.shadow_glow, 4)
            else:
                if not is_selected:
                    container.bgcolor = THEME.bg_card
                    container.shadow = None
            container.update()
        except Exception:
            pass

    # ════════════════════════════════════════════
    #  Selection
    # ════════════════════════════════════════════

    def _safe_select(self, tab_id: str) -> None:
        """Safe tab selection with exception guard."""
        try:
            self._select(tab_id)
        except Exception:
            traceback.print_exc()
            self._selected_id = tab_id

    def _select(self, tab_id: str) -> None:
        """Select a tab, update styles, and notify."""
        if tab_id == self._selected_id:
            return
        if self._selected_id and self._selected_id in self._buttons:
            self._apply_style(self._buttons[self._selected_id], False)
        self._selected_id = tab_id
        if tab_id in self._buttons:
            self._apply_style(self._buttons[tab_id], True)
        try:
            self.update()
        except Exception:
            pass
        self._on_tab_select(tab_id)

    def _apply_style(self, container: ft.Container, selected: bool) -> None:
        """Apply selected/unselected visual style to a tab button."""
        if self._collapsed:
            self._apply_style_collapsed(container, selected)
        else:
            self._apply_style_expanded(container, selected)

    def _apply_style_collapsed(self, container: ft.Container, selected: bool) -> None:
        """Style collapsed tab button."""
        if container.content and isinstance(container.content, ft.Icon):
            container.content.color = (
                THEME.mc_obsidian if selected else THEME.text_secondary
            )
        container.bgcolor = THEME.mc_gold if selected else THEME.bg_card
        container.shadow = mc_shadow_glow(THEME.shadow_glow, 4) if selected else None

    def _apply_style_expanded(self, container: ft.Container, selected: bool) -> None:
        """Style expanded tab button."""
        row = container.content
        if isinstance(row, ft.Row) and len(row.controls) >= 2:
            icon_slot = row.controls[0]
            text_group = row.controls[1]
            if isinstance(icon_slot, ft.Container):
                icon_slot.bgcolor = THEME.mc_gold if selected else THEME.bg_secondary
                if icon_slot.content and isinstance(icon_slot.content, ft.Icon):
                    icon_slot.content.color = (
                        THEME.mc_obsidian if selected else THEME.text_secondary
                    )
            if isinstance(text_group, ft.Column) and len(text_group.controls) >= 2:
                tc = text_group.controls[0]
                marker = text_group.controls[1]
                tc.color = THEME.text_primary if selected else THEME.text_secondary
                tc.weight = ft.FontWeight.BOLD if selected else ft.FontWeight.W_500
                marker.value = "▶" if selected else ""
        container.bgcolor = THEME.mc_stone if selected else THEME.bg_card
        container.shadow = mc_shadow_glow(THEME.shadow_glow, 4) if selected else None

    # ════════════════════════════════════════════
    #  Toggle collapse/expand
    # ════════════════════════════════════════════

    def _handle_toggle(self, e: ft.ControlEvent = None) -> None:
        """Toggle between collapsed and expanded states."""
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        """Switch between collapsed and expanded sidebar states.

        Args:
            collapsed: True to collapse, False to expand.
        """
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        # Update width
        self.width = self.COLLAPSED_WIDTH if collapsed else self._sidebar_width
        # Rebuild all sections
        self._rebuild_all()
        # Update tab col padding
        self._tab_col.spacing = 6 if collapsed else 8
        # Update parent padding on the tab container
        try:
            tab_parent = self._tab_col.parent
            if tab_parent and isinstance(tab_parent, ft.Container):
                tab_parent.padding = ft.Padding(
                    left=6 if collapsed else 12,
                    right=6 if collapsed else 12,
                    top=10, bottom=8,
                )
        except Exception:
            pass
        try:
            self.update()
        except Exception:
            pass

    @property
    def is_collapsed(self) -> bool:
        """Whether the sidebar is currently collapsed."""
        return self._collapsed

    # ════════════════════════════════════════════
    #  Recent saves
    # ════════════════════════════════════════════

    def _rebuild_recent_saves(self) -> None:
        """Rebuild the recent saves list."""
        self._recent_save_col.controls.clear()
        if not self._recent_saves:
            self._recent_save_col.controls.append(
                ft.Text(
                    "暂无最近存档",
                    size=11,
                    color=THEME.text_muted,
                    font_family="monospace",
                )
            )
            return
        for save in self._recent_saves[:5]:
            self._recent_save_col.controls.append(
                self._build_recent_save_item(save)
            )

    def _build_recent_save_item(self, save: Dict[str, Any]) -> ft.Container:
        """Build a single recent save item."""
        save_id = str(save.get("id") or save.get("path") or save.get("name") or "")
        save_name = str(save.get("name") or save.get("label") or save_id or "未命名存档")
        save_path = str(save.get("path") or save_id)

        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(IconSet.FOLDER, size=14, color=THEME.mc_grass),
                    ft.Text(
                        save_name,
                        size=11,
                        color=THEME.text_secondary,
                        font_family="monospace",
                        no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        expand=True,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=10, right=10, top=8, bottom=8),
            border_radius=5,
            bgcolor=THEME.bg_secondary,
            border=mc_border(1),
            ink=True,
            tooltip=save_path,
            on_click=lambda e, sid=save_id: self._safe_select_recent_save(sid),
            animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
        )

    def _safe_select_recent_save(self, save_id: str) -> None:
        """Safe callback for recent save click."""
        if not save_id:
            return
        try:
            if self._on_recent_save_select:
                self._on_recent_save_select(save_id)
        except Exception:
            traceback.print_exc()

    # ════════════════════════════════════════════
    #  Event handlers
    # ════════════════════════════════════════════

    def _handle_set_current_save(self, e: ft.ControlEvent) -> None:
        """Handle 'set current save' button click."""
        try:
            if self._on_set_current_save:
                self._on_set_current_save()
            elif self._on_import_save:
                self._on_import_save()
        except Exception:
            pass

    def _handle_import_save(self, e: ft.ControlEvent) -> None:
        """Backward-compat alias for set current save."""
        self._handle_set_current_save(e)

    # ════════════════════════════════════════════
    #  Public API
    # ════════════════════════════════════════════

    def set_recent_saves(self, saves: Optional[List[Dict[str, Any]]]) -> None:
        """Update the recent saves list."""
        self._recent_saves = list(saves or [])
        self._rebuild_recent_saves()
        try:
            self._recent_save_col.update()
        except Exception:
            pass

    def set_current_save_name(
        self, name: Optional[str], path: Optional[str] = None,
    ) -> None:
        """Update current save display name."""
        try:
            if name:
                self._current_save_name.value = name
                self._current_save_name.color = THEME.mc_gold
                self._current_save_name.tooltip = path or name
            else:
                self._current_save_name.value = "未设置当前存档"
                self._current_save_name.color = THEME.text_muted
                self._current_save_name.tooltip = None
            self._current_save_name.update()
        except Exception:
            pass

    @property
    def selected_id(self) -> Optional[str]:
        """Currently selected tab ID."""
        return self._selected_id

    def select_tab(self, tab_id: str) -> None:
        """Programmatically select a tab."""
        self._safe_select(tab_id)

    def reorder_tabs(self, new_order: List[str]) -> None:
        """Reorder tabs by ID list."""
        tab_map = {t["id"]: t for t in self._tabs}
        new_tabs = [tab_map[tid] for tid in new_order if tid in tab_map]
        for t in self._tabs:
            if t["id"] not in new_order:
                new_tabs.append(t)
        self._tabs = new_tabs
        self._rebuild_tab_buttons()
        try:
            self._tab_col.update()
        except Exception:
            pass
        if self._on_tabs_reorder:
            try:
                self._on_tabs_reorder(self._tabs)
            except Exception:
                traceback.print_exc()

    def get_tab_order(self) -> List[str]:
        """Return current tab ID order."""
        return [t["id"] for t in self._tabs]

    def set_width(self, width: int) -> None:
        """Dynamically set sidebar width (only effective when expanded).

        Args:
            width: New width in pixels.
        """
        try:
            self._sidebar_width = max(180, min(320, width))
            if not self._collapsed:
                self.width = self._sidebar_width
                self.update()
        except Exception:
            pass

    @property
    def sidebar_width(self) -> int:
        """Current sidebar width setting."""
        return self._sidebar_width
