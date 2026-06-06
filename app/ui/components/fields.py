"""Minecraft-style input field components"""
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
    read_only: bool = False,
) -> ft.TextField:
    """Create a Minecraft-style text field"""
    tf = ft.TextField(
        value=value,
        label=label,
        hint_text=hint_text,
        width=width,
        on_change=on_change,
        password=password,
        read_only=read_only,
        border_color=THEME.border_standard,
        focused_border_color=THEME.mc_diamond,
        text_size=13,
        color=THEME.text_primary,
        bgcolor=THEME.bg_secondary,
        border_radius=0,
        cursor_color=THEME.mc_diamond,
        label_style=ft.TextStyle(color=THEME.text_secondary, size=12),
        hint_style=ft.TextStyle(color=THEME.text_muted, size=12),
        content_padding=ft.Padding(left=12, right=12, top=8, bottom=8),
    )
    tf.expand = expand
    return tf


def checkbox(
    label: str,
    value: bool = False,
    on_change: Optional[Callable[[ft.ControlEvent], Any]] = None,
) -> ft.Checkbox:
    """Create a Minecraft-style checkbox"""
    return ft.Checkbox(
        label=label,
        value=value,
        on_change=on_change,
        check_color=THEME.bg_primary,
        fill_color=THEME.mc_grass,
        label_style=ft.TextStyle(size=13, color=THEME.text_secondary),
    )


def label(text: str, icon: str = "") -> ft.Text:
    """Create a field label with optional icon"""
    display_text = f"{icon} {text}" if icon else text
    return ft.Text(
        display_text,
        size=12,
        weight=ft.FontWeight.BOLD,
        color=THEME.mc_gold,
        font_family="monospace",
    )
