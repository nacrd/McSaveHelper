"""Sidebar header, footer and toggle chrome builders."""
from __future__ import annotations

from typing import Callable, List, cast

import flet as ft

from app.ui.icons import IconSet
from app.ui.theme import THEME
from core.version import APP_VERSION

_EMPTY_BORDER_SIDE = ft.BorderSide(0, ft.Colors.TRANSPARENT)


def build_header_collapsed(
    on_set_current_save: Callable[..., None],
) -> ft.Container:
    """Collapsed header with brand and persistent save-selection command."""
    return ft.Container(
        content=ft.Column(
            [
                ft.Container(
                    content=ft.Icon(
                        IconSet.PICKAXE,
                        size=22,
                        color=THEME.accent,
                    ),
                    width=44,
                    height=44,
                    alignment=ft.alignment.Alignment(0, 0),
                ),
                ft.Container(
                    content=ft.Icon(
                        IconSet.FOLDER_OPEN,
                        size=20,
                        color=THEME.text_invert,
                    ),
                    width=44,
                    height=44,
                    alignment=ft.alignment.Alignment(0, 0),
                    bgcolor=THEME.accent,
                    border_radius=6,
                    ink=True,
                    tooltip="设置当前存档",
                    on_click=on_set_current_save,
                ),
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        alignment=ft.alignment.Alignment(0, 0),
        height=112,
        padding=ft.Padding(top=8, bottom=8, left=0, right=0),
        bgcolor=THEME.bg_secondary,
        border=ft.Border(
            left=_EMPTY_BORDER_SIDE,
            top=_EMPTY_BORDER_SIDE,
            right=_EMPTY_BORDER_SIDE,
            bottom=ft.BorderSide(1, THEME.border_subtle),
        ),
    )


def build_header_expanded(
    *,
    current_save_name: ft.Text,
    recent_arrow: ft.Text,
    recent_body: ft.Container,
    on_set_current_save: Callable[..., None],
    on_toggle_recent: Callable[..., None],
) -> ft.Container:
    """Expanded sidebar header: brand, current save, and recent list."""
    return ft.Container(
        content=ft.Column(
            cast(
                List[ft.Control],
                [
                    _build_brand_row(),
                    ft.Container(height=16),
                    _build_current_save_block(current_save_name),
                    _build_set_current_save_button(on_set_current_save),
                    _build_recent_saves_block(
                        recent_arrow,
                        recent_body,
                        on_toggle_recent,
                    ),
                ],
            ),
            spacing=0,
        ),
        padding=ft.Padding(left=16, right=16, top=17, bottom=16),
        bgcolor=THEME.bg_secondary,
        border=ft.Border(
            left=_EMPTY_BORDER_SIDE,
            top=_EMPTY_BORDER_SIDE,
            right=_EMPTY_BORDER_SIDE,
            bottom=ft.BorderSide(1, THEME.border_subtle),
        ),
    )


def _build_brand_row() -> ft.Row:
    return ft.Row(
        [
            ft.Container(
                content=ft.Icon(
                    IconSet.PICKAXE, size=20, color=THEME.text_invert,
                ),
                width=38,
                height=38,
                alignment=ft.alignment.Alignment(0, 0),
                bgcolor=THEME.accent,
                border_radius=6,
            ),
            ft.Column(
                [
                    ft.Text(
                        "MCSaveHelper",
                        size=15,
                        weight=ft.FontWeight.W_600,
                        color=THEME.text_primary,
                    ),
                    ft.Text(
                        "Minecraft Save Toolkit",
                        size=10,
                        color=THEME.text_muted,
                    ),
                ],
                spacing=2,
                expand=True,
            ),
        ],
        spacing=10,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _build_current_save_block(current_save_name: ft.Text) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(
                            IconSet.SAVE, size=14, color=THEME.mc_grass,
                        ),
                        ft.Text(
                            "当前存档",
                            size=11,
                            weight=ft.FontWeight.W_600,
                            color=THEME.text_secondary,
                            font_family="monospace",
                        ),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                current_save_name,
            ],
            spacing=5,
        ),
        padding=10,
        bgcolor=THEME.bg_primary,
        border_radius=6,
        border=ft.Border.all(1, THEME.border_subtle),
    )


def _build_set_current_save_button(
    on_set_current_save: Callable[..., None],
) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(
                    IconSet.FOLDER_OPEN,
                    size=16,
                    color=THEME.text_invert,
                ),
                ft.Text(
                    "设置当前存档",
                    size=12,
                    weight=ft.FontWeight.W_600,
                    color=THEME.text_invert,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        padding=ft.Padding(left=12, right=12, top=10, bottom=10),
        bgcolor=THEME.accent,
        border_radius=6,
        ink=True,
        on_click=on_set_current_save,
        margin=ft.Margin(top=10, bottom=0, left=0, right=0),
    )


def _build_recent_saves_block(
    recent_arrow: ft.Text,
    recent_body: ft.Container,
    on_toggle_recent: Callable[..., None],
) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                IconSet.CLOCK,
                                size=12,
                                color=THEME.text_muted,
                            ),
                            ft.Text(
                                "最近存档",
                                size=11,
                                weight=ft.FontWeight.W_600,
                                color=THEME.text_secondary,
                            ),
                            ft.Container(expand=True),
                            recent_arrow,
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ink=True,
                    border_radius=4,
                    on_click=on_toggle_recent,
                ),
                recent_body,
            ],
            spacing=8,
        ),
        padding=ft.Padding(left=0, right=0, top=14, bottom=0),
    )


def build_footer(collapsed: bool) -> ft.Control:
    """侧栏页脚版本信息；折叠态返回零高度占位。"""
    if collapsed:
        return ft.Container(height=0)
    return ft.Container(
        content=ft.Row(
            [
                ft.Text(
                    APP_VERSION,
                    size=10,
                    color=THEME.text_secondary,
                ),
                ft.Container(expand=True),
                ft.Text(
                    "▣ stone edition",
                    size=10,
                    color=THEME.text_muted,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        padding=ft.Padding(left=16, top=12, right=16, bottom=12),
        bgcolor=THEME.bg_primary,
    )


def build_toggle_button(
    *,
    collapsed: bool,
    on_toggle: Callable[..., None],
) -> ft.Container:
    """构建侧栏折叠/展开切换按钮。"""
    icon = IconSet.ARROW_RIGHT if collapsed else IconSet.ARROW_LEFT
    tooltip = "展开侧边栏" if collapsed else "收起侧边栏"
    return ft.Container(
        content=ft.Icon(icon, size=16, color=THEME.text_secondary),
        alignment=ft.alignment.Alignment(0, 0),
        width=44,
        height=44,
        padding=0,
        bgcolor=THEME.bg_secondary,
        border=ft.Border(
            left=_EMPTY_BORDER_SIDE,
            top=ft.BorderSide(1, THEME.border_subtle),
            right=_EMPTY_BORDER_SIDE,
            bottom=_EMPTY_BORDER_SIDE,
        ),
        ink=True,
        on_click=on_toggle,
        tooltip=tooltip,
    )
