"""输入字段组件工厂"""
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
        border_color=THEME.border_standard,
        focused_border_color=THEME.accent,
        text_size=13,
        color=THEME.text_primary,
        bgcolor="rgba(255,255,255,0.02)",
        border_radius=6,
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
        check_color=THEME.accent,
        label_style=ft.TextStyle(size=13, color=THEME.text_secondary),
    )


def label(text: str) -> ft.Text:
    """辅助标签组件"""
    return ft.Text(
        text,
        size=12,
        weight=ft.FontWeight.BOLD,
        color=THEME.text_secondary,
    )
