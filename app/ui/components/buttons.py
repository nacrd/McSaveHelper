"""Minecraft 风格按钮组件工厂"""
from typing import Optional, Callable, Any

import flet as ft

from app.ui.theme import THEME

MC_BORDER_WIDTH = 2
MC_INNER_PADDING = 4


def btn_primary(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 40,
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
            bgcolor=THEME.mc_grass,
            shape=ft.RoundedRectangleBorder(radius=0),
            side=ft.BorderSide(MC_BORDER_WIDTH, "#3A6B1E"),
            padding=ft.Padding(left=16, right=16, top=MC_INNER_PADDING, bottom=MC_INNER_PADDING),
        ),
    )


def btn_ghost(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 40,
) -> ft.Button:
    return ft.Button(
        content=text,
        on_click=on_click,
        width=width,
        height=height,
        style=ft.ButtonStyle(
            color=THEME.text_secondary,
            bgcolor=THEME.mc_stone,
            side=ft.BorderSide(MC_BORDER_WIDTH, "#5A5A5A"),
            shape=ft.RoundedRectangleBorder(radius=0),
            padding=ft.Padding(left=16, right=16, top=MC_INNER_PADDING, bottom=MC_INNER_PADDING),
        ),
    )


def btn_success(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 40,
) -> ft.Button:
    return ft.Button(
        content=text,
        on_click=on_click,
        width=width,
        height=height,
        style=ft.ButtonStyle(
            color=THEME.text_primary,
            bgcolor=THEME.mc_emerald,
            side=ft.BorderSide(MC_BORDER_WIDTH, "#0E8B3E"),
            shape=ft.RoundedRectangleBorder(radius=0),
            padding=ft.Padding(left=16, right=16, top=MC_INNER_PADDING, bottom=MC_INNER_PADDING),
        ),
    )


def btn_danger(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 40,
) -> ft.Button:
    return ft.Button(
        content=text,
        on_click=on_click,
        width=width,
        height=height,
        style=ft.ButtonStyle(
            color=THEME.text_primary,
            bgcolor=THEME.mc_redstone,
            side=ft.BorderSide(MC_BORDER_WIDTH, "#AA0000"),
            shape=ft.RoundedRectangleBorder(radius=0),
            padding=ft.Padding(left=16, right=16, top=MC_INNER_PADDING, bottom=MC_INNER_PADDING),
        ),
    )
