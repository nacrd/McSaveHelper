"""Flet sidebar navigation matching Linear design"""
import flet as ft
from typing import Callable, List, Dict, Any, Optional
from ui.constants import COLORS


class Sidebar(ft.Container):
    def __init__(
        self,
        tabs: List[Dict[str, Any]],
        on_tab_select: Callable[[str], None],
        default_tab: Optional[str] = None,
    ):
        self._tabs = tabs
        self._on_tab_select = on_tab_select
        self._selected_id = default_tab or (tabs[0]["id"] if tabs else None)
        self._buttons: Dict[str, ft.Container] = {}

        col = ft.Column(spacing=2, expand=True)
        col.controls.append(
            ft.Container(
                content=ft.Text("MCSaveHelper", size=18, weight=ft.FontWeight.BOLD, color=COLORS["accent"]),
                padding=ft.padding.only(left=20, right=20, top=30, bottom=24),
            )
        )
        for tab in tabs:
            btn = self._build_tab_button(tab)
            self._buttons[tab["id"]] = btn
            col.controls.append(btn)

        col.controls.append(ft.Container(expand=True))
        col.controls.append(
            ft.Container(
                content=ft.Text("v1.0.0", size=10, color=COLORS["text_quaternary"]),
                padding=ft.padding.all(20),
            )
        )

        super().__init__(
            content=col,
            width=180,
            bgcolor=COLORS["bg_primary"],
            border=ft.border.only(right=ft.BorderSide(1, "rgba(255,255,255,0.05)")),
        )

    def _build_tab_button(self, tab: Dict[str, Any]) -> ft.Container:
        selected = tab["id"] == self._selected_id
        icon = tab.get("icon", "")
        text_str = f"  {icon} {tab['label']}" if icon else f"  {tab['label']}"

        text_ctrl = ft.Text(
            text_str, size=13, color=COLORS["text_primary"] if selected else COLORS["text_secondary"],
            weight=ft.FontWeight.W_510 if selected else ft.FontWeight.NORMAL,
        )
        indicator = ft.Container(width=4, height=24, bgcolor=COLORS["accent"] if selected else None, border_radius=2)

        row = ft.Row([indicator, text_ctrl], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        container = ft.Container(
            content=row,
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
            border_radius=6,
            bgcolor=COLORS["bg_card"] if selected else None,
            ink=True,
        )
        container.on_click = lambda e: self._select(tab["id"])
        return container

    def _select(self, tab_id: str):
        if tab_id == self._selected_id:
            return
        if self._selected_id and self._selected_id in self._buttons:
            self._apply_style(self._buttons[self._selected_id], False)
        self._selected_id = tab_id
        if tab_id in self._buttons:
            self._apply_style(self._buttons[tab_id], True)
        self.update()
        self._on_tab_select(tab_id)

    def _apply_style(self, container: ft.Container, selected: bool):
        row = container.content
        if isinstance(row, ft.Row) and len(row.controls) >= 2:
            tc = row.controls[1]
            ind = row.controls[0]
            tc.color = COLORS["text_primary"] if selected else COLORS["text_secondary"]
            tc.weight = ft.FontWeight.W_510 if selected else ft.FontWeight.NORMAL
            ind.bgcolor = COLORS["accent"] if selected else None
        container.bgcolor = COLORS["bg_card"] if selected else None

    def select_tab(self, tab_id: str):
        self._select(tab_id)
