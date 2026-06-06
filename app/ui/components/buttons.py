"""Minecraft-style button components"""
from typing import Optional, Callable, Any

import flet as ft

from app.ui.theme import THEME


def _mc_button(
    text: str,
    bgcolor: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 40,
    icon: Optional[str] = None,
    text_color: str = None,
) -> ft.Container:
    """Create a Minecraft-style button with beveled borders"""
    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(icon, size=16, color=text_color or THEME.text_primary) if icon else ft.Container(width=0),
                ft.Text(
                    text,
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=text_color or THEME.text_primary,
                    font_family="monospace",
                ),
            ],
            spacing=6,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        width=width,
        height=height,
        bgcolor=bgcolor,
        border=ft.Border(
            left=ft.BorderSide(2, THEME.border_light),
            top=ft.BorderSide(2, THEME.border_light),
            right=ft.BorderSide(2, THEME.border_dark),
            bottom=ft.BorderSide(2, THEME.border_dark),
        ),
        alignment=ft.alignment.Alignment(0, 0),
        on_click=on_click,
        ink=True,
    )


def btn_primary(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 40,
    icon: Optional[str] = None,
) -> ft.Container:
    """Primary button - grass green"""
    return _mc_button(text, THEME.mc_grass, on_click, width, height, icon)


def btn_ghost(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 40,
) -> ft.Container:
    """Secondary button - stone gray"""
    return _mc_button(text, THEME.mc_stone, on_click, width, height, text_color=THEME.text_primary)


def btn_success(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 40,
) -> ft.Container:
    """Success button - emerald green"""
    return _mc_button(text, THEME.mc_emerald, on_click, width, height)


def btn_danger(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 40,
) -> ft.Container:
    """Danger button - redstone red"""
    return _mc_button(text, THEME.mc_redstone, on_click, width, height)
