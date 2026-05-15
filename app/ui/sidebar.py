"""侧边栏导航组件（Linear 风格）"""
from typing import Callable, List, Dict, Any, Optional

import flet as ft

from app.ui.theme import THEME


class Sidebar(ft.Container):
    """左侧导航栏"""

    def __init__(
        self,
        tabs: List[Dict[str, Any]],
        on_tab_select: Callable[[str], None],
        default_tab: Optional[str] = None,
    ) -> None:
        self._tabs: List[Dict[str, Any]] = tabs
        self._on_tab_select: Callable[[str], None] = on_tab_select
        self._selected_id: Optional[str] = default_tab or (tabs[0]["id"] if tabs else None)
        self._buttons: Dict[str, ft.Container] = {}

        col = ft.Column(spacing=2)
        col.expand = True

        # Logo
        col.controls.append(
            ft.Container(
                content=ft.Text(
                    "MCSaveHelper",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.accent,
                ),
                padding=ft.Padding(left=20, right=20, top=30, bottom=24),
            )
        )

        # 标签按钮
        for tab in tabs:
            btn = self._build_tab_button(tab)
            self._buttons[tab["id"]] = btn
            col.controls.append(btn)

        # 弹性空间
        col.controls.append(ft.Container())
        col.controls[-1].expand = True

        # 版本号
        col.controls.append(
            ft.Container(
                content=ft.Text(
                    "v1.0.0",
                    size=10,
                    color=THEME.text_quaternary,
                ),
                padding=ft.Padding(left=20, top=20, right=20, bottom=20),
            )
        )

        super().__init__(
            content=col,
            width=180,
            bgcolor=THEME.bg_primary,
            border=ft.Border(
                left=None, top=None,
                right=ft.BorderSide(1, "rgba(255,255,255,0.05)"),
                bottom=None,
            ),
        )

    def _build_tab_button(self, tab: Dict[str, Any]) -> ft.Container:
        selected = tab["id"] == self._selected_id
        icon = tab.get("icon", "")
        label_text = tab.get("label", tab["id"])
        text_str = f"  {icon} {label_text}" if icon else f"  {label_text}"

        text_ctrl = ft.Text(
            text_str,
            size=13,
            color=THEME.text_primary if selected else THEME.text_secondary,
            weight=ft.FontWeight.W_500 if selected else ft.FontWeight.NORMAL,
        )
        indicator = ft.Container(
            width=4, height=24,
            bgcolor=THEME.accent if selected else None,
            border_radius=2,
        )

        row = ft.Row(
            [indicator, text_ctrl],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        container = ft.Container(
            content=row,
            padding=ft.Padding(left=16, top=10, right=16, bottom=10),
            border_radius=6,
            bgcolor=THEME.bg_card if selected else None,
            ink=True,
        )
        container.on_click = lambda e, tid=tab["id"]: self._select(tid)
        return container

    def _select(self, tab_id: str) -> None:
        if tab_id == self._selected_id:
            return
        if self._selected_id and self._selected_id in self._buttons:
            self._apply_style(self._buttons[self._selected_id], False)
        self._selected_id = tab_id
        if tab_id in self._buttons:
            self._apply_style(self._buttons[tab_id], True)
        self.update()
        self._on_tab_select(tab_id)

    def _apply_style(self, container: ft.Container, selected: bool) -> None:
        row = container.content
        if isinstance(row, ft.Row) and len(row.controls) >= 2:
            tc = row.controls[1]
            ind = row.controls[0]
            tc.color = THEME.text_primary if selected else THEME.text_secondary
            tc.weight = ft.FontWeight.W_500 if selected else ft.FontWeight.NORMAL
            ind.bgcolor = THEME.accent if selected else None
        container.bgcolor = THEME.bg_card if selected else None

    @property
    def selected_id(self) -> Optional[str]:
        return self._selected_id

    def select_tab(self, tab_id: str) -> None:
        self._select(tab_id)
