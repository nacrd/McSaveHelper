"""Minecraft 风格侧边栏导航组件，支持拖拽排序"""
import traceback
from typing import Callable, List, Dict, Any, Optional

import flet as ft

from app.ui.theme import THEME
from core.version import APP_VERSION


class Sidebar(ft.Container):
    """左侧导航栏，支持拖拽排序标签页"""

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
        self._tab_col: ft.Column = ft.Column(spacing=8)

        col = ft.Column(spacing=4)
        col.expand = True

        col.controls.append(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "⛏ MCSaveHelper",
                            size=17,
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
                    spacing=4,
                ),
                padding=ft.Padding(left=18, right=18, top=28, bottom=22),
                bgcolor=THEME.mc_dirt,
                border=ft.Border(
                    left=None,
                    top=None,
                    right=None,
                    bottom=ft.BorderSide(3, THEME.mc_grass),
                ),
            )
        )

        self._tab_col.expand = True
        self._rebuild_tab_buttons()
        col.controls.append(
            ft.Container(
                content=self._tab_col,
                padding=ft.Padding(left=10, right=10, top=14, bottom=10),
            )
        )

        col.controls.append(ft.Container())
        col.controls[-1].expand = True

        col.controls.append(
            ft.Container(
                content=ft.Text(
                    f"{APP_VERSION}  ▣ stone edition",
                    size=10,
                    color=THEME.text_muted,
                    font_family="monospace",
                ),
                padding=ft.Padding(left=18, top=16, right=18, bottom=18),
                bgcolor=THEME.bg_secondary,
            )
        )

        super().__init__(
            content=col,
            width=210,
            bgcolor=THEME.bg_primary,
            border=ft.Border(
                left=None, top=None,
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
        selected = tab["id"] == self._selected_id
        icon = tab.get("icon", "")
        label_text = tab.get("label", tab["id"])

        icon_slot = ft.Container(
            content=ft.Text(
                icon or "▣",
                size=18,
                color=THEME.text_primary,
                text_align=ft.TextAlign.CENTER,
            ),
            width=42,
            height=42,
            alignment=ft.Alignment(0, 0),
            bgcolor=THEME.mc_gold if selected else THEME.bg_secondary,
            border=ft.Border(
                left=ft.BorderSide(2, THEME.border_tertiary),
                top=ft.BorderSide(2, THEME.border_tertiary),
                right=ft.BorderSide(2, THEME.bg_secondary),
                bottom=ft.BorderSide(2, THEME.bg_secondary),
            ),
        )
        text_ctrl = ft.Text(
            label_text,
            size=13,
            color=THEME.text_primary if selected else THEME.text_secondary,
            weight=ft.FontWeight.BOLD if selected else ft.FontWeight.W_500,
            font_family="monospace",
        )
        marker = ft.Text(
            "▶" if selected else " ",
            size=12,
            color=THEME.mc_grass,
            font_family="monospace",
        )

        row = ft.Row(
            [icon_slot, ft.Column([text_ctrl, marker], spacing=0)],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        container = ft.Container(
            content=row,
            padding=ft.Padding(left=8, top=8, right=8, bottom=8),
            border_radius=0,
            bgcolor=THEME.mc_stone if selected else THEME.bg_card,
            border=ft.Border(
                left=ft.BorderSide(2, THEME.border_tertiary),
                top=ft.BorderSide(2, THEME.border_tertiary),
                right=ft.BorderSide(2, THEME.bg_secondary),
                bottom=ft.BorderSide(2, THEME.bg_secondary),
            ),
            ink=True,
        )
        container.on_click = lambda e, tid=tab["id"]: self._safe_select(tid)
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
                marker.value = "▶" if selected else " "
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
