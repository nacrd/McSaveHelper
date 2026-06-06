"""Minecraft 风格输入字段组件工厂"""
from typing import Optional, Callable, Any

import flet as ft

from app.ui.theme import THEME


def text_field(
    value: str = "",
    label: Optional[str] = None,
    hint_text: Optional[str] = None,
    expand: bool = True,
    width: Optional[int] = None,
    on_change: Optional[Callable[[ft.ControlEvent], Any]] = None,
    password: bool = False,
) -> ft.TextField:
    tf = ft.TextField(
        value=value,
        label=label,
        hint_text=hint_text,
        width=width,
        on_change=on_change,
        password=password,
        border_color=THEME.border_tertiary,
        focused_border_color=THEME.mc_diamond,
        text_size=13,
        color=THEME.text_primary,
        bgcolor=THEME.bg_secondary,
        border_radius=0,
        cursor_color=THEME.mc_diamond,
        label_style=ft.TextStyle(color=THEME.text_secondary),
        hint_style=ft.TextStyle(color=THEME.text_muted),
    )
    tf.expand = expand
    return tf


def checkbox(
    label: str,
    value: bool = False,
    on_change: Optional[Callable[[ft.ControlEvent], Any]] = None,
) -> ft.Checkbox:
    return ft.Checkbox(
        label=label,
        value=value,
        on_change=on_change,
        check_color=THEME.bg_secondary,
        fill_color=THEME.mc_grass,
        label_style=ft.TextStyle(size=13, color=THEME.text_secondary),
    )


def label(text: str) -> ft.Text:
    return ft.Text(
        text,
        size=12,
        weight=ft.FontWeight.BOLD,
        color=THEME.mc_gold,
        font_family="monospace",
    )
