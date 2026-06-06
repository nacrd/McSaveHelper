"""Minecraft-style sidebar navigation component with drag-and-drop support"""
import traceback
from typing import Callable, List, Dict, Any, Optional

import flet as ft

from app.ui.theme import THEME, mc_border
from core.version import APP_VERSION


class Sidebar(ft.Container):
    """Left navigation sidebar with drag-and-drop tab reordering"""

    def __init__(
        self,
        tabs: List[Dict[str, Any]],
        on_tab_select: Callable[[str], None],
        on_tabs_reorder: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        default_tab: Optional[str] = None,
    ) -> None:
        self._tabs: List[Dict[str, Any]] = list(tabs)
        self._on_tab_select: Callable[[str], None] = on_tab_select
        self._on_tabs_reorder: Optional[Callable[[List[Dict[str, Any]]], None]] = on_tabs_reorder
        self._selected_id: Optional[str] = default_tab or (tabs[0]["id"] if tabs else None)
        self._buttons: Dict[str, ft.Container] = {}
        self._tab_col: ft.Column = ft.Column(spacing=6)

        col = ft.Column(spacing=0, expand=True)

        # Header
        col.controls.append(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "⛏ MCSaveHelper",
                            size=16,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.mc_gold,
                            font_family="monospace",
                        ),
                        ft.Text(
                            "Minecraft Save Toolkit",
                            size=9,
                            color=THEME.text_muted,
                            font_family="monospace",
                        ),
                    ],
                    spacing=2,
                ),
                padding=ft.Padding(left=16, right=16, top=24, bottom=20),
                bgcolor=THEME.mc_dirt,
                border=ft.Border(
                    left=None,
                    top=None,
                    right=None,
                    bottom=ft.BorderSide(3, THEME.mc_grass),
                ),
            )
        )

        # Tab buttons
        self._tab_col.expand = True
        self._rebuild_tab_buttons()
        col.controls.append(
            ft.Container(
                content=self._tab_col,
                padding=ft.Padding(left=10, right=10, top=12, bottom=10),
                expand=True,
            )
        )

        # Footer
        col.controls.append(
            ft.Container(
                content=ft.Text(
                    f"{APP_VERSION}  ▣ stone edition",
                    size=9,
                    color=THEME.text_muted,
                    font_family="monospace",
                ),
                padding=ft.Padding(left=16, top=14, right=16, bottom=16),
                bgcolor=THEME.bg_secondary,
            )
        )

        super().__init__(
            content=col,
            width=210,
            bgcolor=THEME.bg_primary,
            border=ft.Border(
                left=None,
                top=None,
                right=ft.BorderSide(3, THEME.bg_secondary),
                bottom=None,
            ),
        )

    def _rebuild_tab_buttons(self) -> None:
        """根据 _tabs 顺序重建所有标签按钮"""
        self._tab_col.controls.clear()
        self._buttons.clear()
        for tab in self._tabs:
            btn = self._build_tab_button(tab)
            self._buttons[tab["id"]] = btn
            self._tab_col.controls.append(btn)

    def _build_tab_button(self, tab: Dict[str, Any]) -> ft.Container:
        """构建单个标签按钮"""
        selected = tab["id"] == self._selected_id
        icon = tab.get("icon", "▣")
        label_text = tab.get("label", tab["id"])

        icon_slot = ft.Container(
            content=ft.Text(
                icon,
                size=16,
                color=THEME.text_primary,
                text_align=ft.TextAlign.CENTER,
            ),
            width=36,
            height=36,
            alignment=ft.alignment.Alignment(0, 0),
            bgcolor=THEME.mc_gold if selected else THEME.bg_secondary,
            border=mc_border(2),
        )
        
        text_ctrl = ft.Text(
            label_text,
            size=12,
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
            [icon_slot, ft.Column([text_ctrl, marker], spacing=0)],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        
        container = ft.Container(
            content=row,
            padding=8,
            border_radius=0,
            bgcolor=THEME.mc_stone if selected else THEME.bg_card,
            border=mc_border(2),
            ink=True,
            on_click=lambda e, tid=tab["id"]: self._safe_select(tid),
        )
        
        return container

    def _safe_select(self, tab_id: str) -> None:
        """安全的选择回调，捕获所有异常防止 UI 冻结"""
        try:
            self._select(tab_id)
        except Exception as e:
            traceback.print_exc()
            # 至少更新选中状态
            self._selected_id = tab_id

    def _select(self, tab_id: str) -> None:
        """选择标签页"""
        if tab_id == self._selected_id:
            return
        # 更新旧按钮样式
        if self._selected_id and self._selected_id in self._buttons:
            self._apply_style(self._buttons[self._selected_id], False)
        self._selected_id = tab_id
        # 更新新按钮样式
        if tab_id in self._buttons:
            self._apply_style(self._buttons[tab_id], True)
        try:
            self.update()
        except Exception:
            pass
        # 通知外部
        self._on_tab_select(tab_id)

    def _apply_style(self, container: ft.Container, selected: bool) -> None:
        """应用选中/未选中样式"""
        row = container.content
        if isinstance(row, ft.Row) and len(row.controls) >= 2:
            icon_slot = row.controls[0]
            text_group = row.controls[1]
            if isinstance(icon_slot, ft.Container):
                icon_slot.bgcolor = THEME.mc_gold if selected else THEME.bg_secondary
            if isinstance(text_group, ft.Column) and len(text_group.controls) >= 2:
                tc = text_group.controls[0]
                marker = text_group.controls[1]
                tc.color = THEME.text_primary if selected else THEME.text_secondary
                tc.weight = ft.FontWeight.BOLD if selected else ft.FontWeight.W_500
                marker.value = "▶" if selected else ""
        container.bgcolor = THEME.mc_stone if selected else THEME.bg_card

    @property
    def selected_id(self) -> Optional[str]:
        return self._selected_id

    def select_tab(self, tab_id: str) -> None:
        self._safe_select(tab_id)

    def reorder_tabs(self, new_order: List[str]) -> None:
        """根据 ID 列表重新排序标签页"""
        tab_map = {t["id"]: t for t in self._tabs}
        new_tabs = []
        for tid in new_order:
            if tid in tab_map:
                new_tabs.append(tab_map[tid])
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
        """返回当前标签页 ID 的顺序"""
        return [t["id"] for t in self._tabs]
