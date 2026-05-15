"""按钮组件工厂"""
from typing import Optional, Callable, Any

import flet as ft

from app.ui.theme import THEME


def btn_primary(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 38,
    icon: Optional[str] = None,
) -> ft.Button:
    return ft.Button(
        content=text,
        icon=icon,
        on_click=on_click,
        width=width,
        height=height,
        style=ft.ButtonStyle(
            color=THEME.text_primary,
            bgcolor=THEME.accent,
            shape=ft.RoundedRectangleBorder(radius=6),
        ),
    )


def btn_ghost(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 38,
) -> ft.Button:
    return ft.Button(
        content=text,
        on_click=on_click,
        width=width,
        height=height,
        style=ft.ButtonStyle(
            color=THEME.text_secondary,
            bgcolor="rgba(255,255,255,0.02)",
            side=ft.BorderSide(1, THEME.border_standard),
            shape=ft.RoundedRectangleBorder(radius=6),
        ),
    )


def btn_success(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 38,
) -> ft.Button:
    return ft.Button(
        content=text,
        on_click=on_click,
        width=width,
        height=height,
        style=ft.ButtonStyle(
            color=THEME.text_primary,
            bgcolor=THEME.success,
            shape=ft.RoundedRectangleBorder(radius=6),
        ),
    )


def btn_danger(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 38,
) -> ft.Button:
    return ft.Button(
        content=text,
        on_click=on_click,
        width=width,
        height=height,
        style=ft.ButtonStyle(
            color=THEME.text_primary,
            bgcolor=THEME.error,
            shape=ft.RoundedRectangleBorder(radius=6),
        ),
    )
