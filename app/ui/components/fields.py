"""Minecraft-style input field components"""
from typing import Optional, Callable, Any, List, Union

import flet as ft

from app.ui.theme import THEME


def text_field(
    value: str = "",
    label: Optional[str] = None,
    hint_text: Optional[str] = None,
    expand: bool = True,
    width: Optional[int] = None,
    on_change: Optional[Callable[..., Any]] = None,
    password: bool = False,
    read_only: bool = False,
) -> ft.TextField:
    """Create a Minecraft-style text field

    Modernized with rounded corners and better styling.

    Args:
        value: Initial value
        label: Field label
        hint_text: Placeholder text
        expand: Whether to expand horizontally
        width: Fixed width (overrides expand)
        on_change: Change handler
        password: Password field mode
        read_only: Read-only mode

    Returns:
        ft.TextField: Configured text field
    """
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
        border_radius=6,
        cursor_color=THEME.mc_diamond,
        label_style=ft.TextStyle(color=THEME.text_secondary, size=12),
        hint_style=ft.TextStyle(color=THEME.text_muted, size=12),
        content_padding=ft.Padding(left=14, right=14, top=10, bottom=10),
    )
    tf.expand = expand
    return tf


def current_save_field(
    label: str = "当前存档",
    hint_text: str = "请通过侧边栏「设置当前存档」设置存档目录",
    value: str = "",
) -> ft.TextField:
    """Create a read-only field for displaying current save path

    Args:
        label: Field label
        hint_text: Placeholder text
        value: Initial value

    Returns:
        ft.TextField: Read-only text field
    """
    return text_field(
        value=value,
        label=label,
        hint_text=hint_text,
        read_only=True,
    )


def checkbox(
    label: str,
    value: bool = False,
    on_change: Optional[Callable[..., Any]] = None,
) -> ft.Checkbox:
    """Create a Minecraft-style checkbox

    Args:
        label: Checkbox label
        value: Initial value
        on_change: Change handler

    Returns:
        ft.Checkbox: Configured checkbox
    """
    return ft.Checkbox(
        label=label,
        value=value,
        on_change=on_change,
        check_color=THEME.bg_primary,
        fill_color=THEME.mc_grass,
        label_style=ft.TextStyle(size=13, color=THEME.text_secondary),
    )


def label(text: str, icon: str = "") -> ft.Text:
    """Create a field label with optional icon

    Args:
        text: Label text
        icon: Optional icon prefix

    Returns:
        ft.Text: Styled label
    """
    display_text = f"{icon} {text}" if icon else text
    return ft.Text(
        display_text,
        size=12,
        weight=ft.FontWeight.BOLD,
        color=THEME.mc_gold,
        font_family="monospace",
    )


def dropdown(
    options: Union[List[str], List[ft.dropdown.Option]],
    value: Optional[str] = None,
    label: Optional[str] = None,
    hint_text: Optional[str] = None,
    on_change: Optional[Callable[..., Any]] = None,
    expand: bool = True,
    width: Optional[int] = None,
    text_size: int = 13,
    border_radius: int = 6,
) -> ft.Dropdown:
    """Create a Minecraft-styled dropdown with consistent theme colors.

    Args:
        options: List of strings or ft.dropdown.Option objects
        value: Currently selected value
        label: Dropdown label
        hint_text: Placeholder text when nothing selected
        on_change: Change handler
        expand: Whether to expand horizontally
        width: Fixed width (overrides expand)
        text_size: Text size in pixels
        border_radius: Border radius in pixels

    Returns:
        ft.Dropdown: Themed dropdown control
    """
    # Normalize string options to ft.dropdown.Option
    normalized: List[ft.dropdown.Option] = []
    for opt in options:
        if isinstance(opt, str):
            normalized.append(ft.dropdown.Option(opt))
        else:
            normalized.append(opt)

    dd = ft.Dropdown(
        options=normalized,
        value=value,
        label=label,
        hint_text=hint_text,
        on_select=on_change,
        bgcolor=THEME.bg_secondary,
        border_color=THEME.border_standard,
        focused_border_color=THEME.mc_diamond,
        color=THEME.text_primary,
        text_size=text_size,
        border_radius=border_radius,
        label_style=ft.TextStyle(color=THEME.text_secondary, size=12),
        hint_style=ft.TextStyle(color=THEME.text_muted, size=12),
        content_padding=ft.Padding(left=14, right=14, top=10, bottom=10),
    )
    dd.expand = expand
    if width is not None:
        dd.width = width
    return dd
