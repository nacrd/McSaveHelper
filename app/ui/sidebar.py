"""Minecraft-style sidebar navigation component — collapsible edition

Supports two states:
  - Expanded (220px): branding + current save + tabs (icon+text) + recent saves + version
  - Collapsed (60px):  brand icon + tabs (icon only, tooltip text) + expand button
"""
import traceback
from typing import Callable, List, Dict, Any, Optional

import flet as ft

from app.ui.utils import safe_update

from app.ui.theme import THEME, mc_border
from app.ui.sidebar_tabs import (
    apply_style_collapsed,
    apply_style_expanded,
    build_tab_button,
    handle_hover_collapsed,
    handle_hover_expanded,
)
from app.ui.sidebar_chrome import (
    build_footer,
    build_header_collapsed,
    build_header_expanded,
    build_toggle_button,
)
from app.ui.icons import IconSet


_EMPTY_BORDER_SIDE = ft.BorderSide(0, ft.Colors.TRANSPARENT)


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
        """构建应用侧边栏。"""
        self._init_state(
            tabs=tabs,
            on_tab_select=on_tab_select,
            on_tabs_reorder=on_tabs_reorder,
            on_import_save=on_import_save,
            on_set_current_save=on_set_current_save,
            on_recent_save_select=on_recent_save_select,
            recent_saves=recent_saves,
            default_tab=default_tab,
            width=width,
            collapsed=collapsed,
        )
        self._rebuild_all()
        super().__init__(
            content=self._build_root_column(collapsed),
            width=self.COLLAPSED_WIDTH if collapsed else self._sidebar_width,
            bgcolor=THEME.bg_primary,
            border=ft.Border(
                left=_EMPTY_BORDER_SIDE,
                top=_EMPTY_BORDER_SIDE,
                right=ft.BorderSide(3, THEME.bg_secondary),
                bottom=_EMPTY_BORDER_SIDE,
            ),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )

    def _init_state(
        self,
        *,
        tabs: List[Dict[str, Any]],
        on_tab_select: Callable[[str], None],
        on_tabs_reorder: Optional[Callable[[List[Dict[str, Any]]], None]],
        on_import_save: Optional[Callable[[], None]],
        on_set_current_save: Optional[Callable[[], None]],
        on_recent_save_select: Optional[Callable[[str], None]],
        recent_saves: Optional[List[Dict[str, Any]]],
        default_tab: Optional[str],
        width: int,
        collapsed: bool,
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
        self._recent_expanded: bool = False
        self._recent_arrow: ft.Text = ft.Text(
            "▶", size=10, color=THEME.text_secondary, font_family="monospace",
        )
        self._recent_body: ft.Container = ft.Container(
            content=self._recent_save_col,
            visible=self._recent_expanded,
        )
        self._current_save_name = ft.Text(
            "未设置当前存档",
            size=12,
            color=THEME.text_muted,
            font_family="monospace",
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._header_container = ft.Container(expand=False)
        self._footer_container = ft.Container(expand=False)
        self._toggle_btn = ft.Container(expand=False)

    def _build_root_column(self, collapsed: bool) -> ft.Column:
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
        return col

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
            self._header_container.content = build_header_collapsed()
        else:
            self._header_container.content = build_header_expanded(
                current_save_name=self._current_save_name,
                recent_arrow=self._recent_arrow,
                recent_body=self._recent_body,
                on_set_current_save=self._handle_set_current_save,
                on_toggle_recent=self._toggle_recent,
            )
        self._header_container.padding = 0

    def _rebuild_footer(self) -> None:
        """Build the footer section."""
        self._footer_container.content = build_footer(self._collapsed)
        self._footer_container.padding = 0

    def _rebuild_toggle_btn(self) -> None:
        """Build the expand/collapse toggle button."""
        self._toggle_btn.content = build_toggle_button(
            collapsed=self._collapsed,
            on_toggle=lambda e: self._handle_toggle(),
        )

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
        """Build a single tab button for the current collapsed state."""
        return build_tab_button(
            tab,
            selected=tab["id"] == self._selected_id,
            collapsed=self._collapsed,
            on_select=self._safe_select,
            on_hover=self._handle_hover,
            on_hover_collapsed=self._handle_hover_collapsed,
        )

    def _handle_hover(self, e: ft.Event[ft.Container], tab_id: str) -> None:
        """Hover handler for expanded tab buttons."""
        if tab_id not in self._buttons:
            return
        container = self._buttons[tab_id]
        try:
            handle_hover_expanded(
                container,
                selected=tab_id == self._selected_id,
                hovering=e.data == "true",
            )
        except Exception:
            # UI best-effort: style helpers may fail after dispose.
            pass
        safe_update(container)

    def _handle_hover_collapsed(
        self,
        e: ft.Event[ft.Container],
        tab_id: str,
    ) -> None:
        """Hover handler for collapsed tab buttons."""
        if tab_id not in self._buttons:
            return
        container = self._buttons[tab_id]
        try:
            handle_hover_collapsed(
                container,
                selected=tab_id == self._selected_id,
                hovering=e.data == "true",
            )
        except Exception:
            # UI best-effort: style helpers may fail after dispose.
            pass
        safe_update(container)

    def _safe_select(self, tab_id: str) -> None:
        """Safe tab selection with exception guard."""
        try:
            self._select(tab_id)
        except Exception:
            # Keep selection state even if a view switch callback fails.
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
        safe_update(self)
        self._on_tab_select(tab_id)

    def _apply_style(self, container: ft.Container, selected: bool) -> None:
        """Apply selected/unselected visual style to a tab button."""
        if self._collapsed:
            apply_style_collapsed(container, selected)
        else:
            apply_style_expanded(container, selected)

    # ════════════════════════════════════════════
    #  Toggle collapse/expand
    # ════════════════════════════════════════════

    def _handle_toggle(self) -> None:
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
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self)

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

    # ════════════════════════════════════════════
    #  Recent saves expand/collapse
    # ════════════════════════════════════════════

    def _toggle_recent(self) -> None:
        """Toggle the recent saves section expanded/collapsed."""
        self._recent_expanded = not self._recent_expanded
        self._recent_body.visible = self._recent_expanded
        self._recent_arrow.value = "▼" if self._recent_expanded else "▶"
        safe_update(self._recent_body)
        safe_update(self._recent_arrow)

    def _expand_recent(self) -> None:
        """Expand the recent saves section if currently collapsed."""
        if self._recent_expanded:
            return
        self._recent_expanded = True
        self._recent_body.visible = True
        self._recent_arrow.value = "▼"
        safe_update(self._recent_body)
        safe_update(self._recent_arrow)

    def _safe_select_recent_save(self, save_id: str) -> None:
        """Safe callback for recent save click."""
        if not save_id:
            return
        self._expand_recent()
        try:
            if self._on_recent_save_select:
                self._on_recent_save_select(save_id)
        except Exception:
            # Caller callback failures should not break the sidebar.
            traceback.print_exc()

    # ════════════════════════════════════════════
    #  Event handlers
    # ════════════════════════════════════════════

    def _handle_set_current_save(self) -> None:
        """Handle 'set current save' button click."""
        try:
            if self._on_set_current_save:
                self._on_set_current_save()
            elif self._on_import_save:
                self._on_import_save()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    def _handle_import_save(self) -> None:
        """Backward-compat alias for set current save."""
        self._handle_set_current_save()

    # ════════════════════════════════════════════
    #  Public API
    # ════════════════════════════════════════════

    def set_recent_saves(self, saves: Optional[List[Dict[str, Any]]]) -> None:
        """Update the recent saves list."""
        self._recent_saves = list(saves or [])
        self._rebuild_recent_saves()
        safe_update(self._recent_save_col)

    def set_current_save_name(
        self, name: Optional[str], path: Optional[str] = None,
    ) -> None:
        """Update current save display name."""
        try:
            if name:
                self._current_save_name.value = name
                self._current_save_name.color = THEME.mc_gold
                self._current_save_name.tooltip = path or name
                self._expand_recent()
            else:
                self._current_save_name.value = "未设置当前存档"
                self._current_save_name.color = THEME.text_muted
                self._current_save_name.tooltip = None
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self._current_save_name)

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
        safe_update(self._tab_col)
        if self._on_tabs_reorder:
            try:
                self._on_tabs_reorder(self._tabs)
            except Exception:
                # Reorder callback failures should not corrupt local order.
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
            # UI best-effort: control may already be unmounted.
            pass

    @property
    def sidebar_width(self) -> int:
        """Current sidebar width setting."""
        return self._sidebar_width
