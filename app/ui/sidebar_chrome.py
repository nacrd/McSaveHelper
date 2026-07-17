"""Sidebar header, footer and toggle chrome builders."""
from __future__ import annotations

from typing import Callable, List, cast

import flet as ft

from app.ui.icons import IconSet
from app.ui.theme import THEME, mc_border, mc_shadow_glow
from core.version import APP_VERSION

_EMPTY_BORDER_SIDE = ft.BorderSide(0, ft.Colors.TRANSPARENT)


def build_header_collapsed() -> ft.Container:
    return ft.Container(
        content=ft.Container(
            content=ft.Icon(IconSet.PICKAXE, size=22, color=THEME.mc_gold),
            width=40,
            height=40,
            alignment=ft.alignment.Alignment(0, 0),
            bgcolor=THEME.bg_secondary,
            border=mc_border(2),
            border_radius=6,
        ),
        alignment=ft.alignment.Alignment(0, 0),
        padding=ft.Padding(left=0, right=0, top=16, bottom=16),
        bgcolor=THEME.mc_dirt,
        border=ft.Border(
            left=_EMPTY_BORDER_SIDE,
            top=_EMPTY_BORDER_SIDE,
            right=_EMPTY_BORDER_SIDE,
            bottom=ft.BorderSide(3, THEME.mc_grass),
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
    return ft.Container(
        content=ft.Column(
            cast(List[ft.Control], [
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Icon(
                                IconSet.PICKAXE, size=20, color=THEME.mc_gold,
                            ),
                            width=36,
                            height=36,
                            alignment=ft.alignment.Alignment(0, 0),
                            bgcolor=THEME.bg_secondary,
                            border=mc_border(2),
                            border_radius=6,
                        ),
                        ft.Column(
                            [
                                ft.Text(
                                    "MCSaveHelper",
                                    size=15,
                                    weight=ft.FontWeight.BOLD,
                                    color=THEME.mc_gold,
                                    font_family="monospace",
                                ),
                                ft.Text(
                                    "Minecraft Save Toolkit",
                                    size=10,
                                    color=THEME.text_muted,
                                    font_family="monospace",
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(
                    height=1,
                    bgcolor=THEME.border_subtle,
                    margin=ft.Margin(top=12, bottom=12, left=0, right=0),
                ),
                ft.Container(
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
                        spacing=6,
                    ),
                    padding=8,
                    bgcolor=THEME.bg_secondary,
                    border_radius=6,
                    border=mc_border(1),
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                IconSet.FOLDER_OPEN,
                                size=16,
                                color=THEME.text_primary,
                            ),
                            ft.Text(
                                "设置当前存档",
                                size=12,
                                weight=ft.FontWeight.W_600,
                                color=THEME.text_primary,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding(left=12, right=12, top=10, bottom=10),
                    bgcolor=THEME.mc_grass,
                    border_radius=6,
                    border=mc_border(2),
                    ink=True,
                    on_click=on_set_current_save,
                    margin=ft.Margin(top=10, bottom=0, left=0, right=0),
                    shadow=mc_shadow_glow(THEME.shadow_accent, 6),
                ),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Container(
                                content=ft.Row(
                                    [
                                        ft.Icon(
                                            IconSet.CLOCK,
                                            size=12,
                                            color=THEME.text_secondary,
                                        ),
                                        ft.Text(
                                            "最近存档",
                                            size=11,
                                            weight=ft.FontWeight.W_600,
                                            color=THEME.text_primary,
                                            font_family="monospace",
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
                    padding=ft.Padding(left=0, right=0, top=12, bottom=0),
                ),
            ]),
            spacing=0,
        ),
        padding=ft.Padding(left=16, right=16, top=16, bottom=16),
        bgcolor=THEME.mc_dirt,
        border=ft.Border(
            left=_EMPTY_BORDER_SIDE,
            top=_EMPTY_BORDER_SIDE,
            right=_EMPTY_BORDER_SIDE,
            bottom=ft.BorderSide(3, THEME.mc_grass),
        ),
    )


def build_footer(collapsed: bool) -> ft.Control:
    if collapsed:
        return ft.Container(height=0)
    return ft.Container(
        content=ft.Row(
            [
                ft.Text(
                    APP_VERSION,
                    size=10,
                    color=THEME.text_secondary,
                    font_family="monospace",
                ),
                ft.Container(expand=True),
                ft.Text(
                    "▣ stone edition",
                    size=10,
                    color=THEME.text_muted,
                    font_family="monospace",
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        padding=ft.Padding(left=16, top=12, right=16, bottom=12),
        bgcolor=THEME.bg_secondary,
    )


def build_toggle_button(
    *,
    collapsed: bool,
    on_toggle: Callable[..., None],
) -> ft.Container:
    icon = IconSet.ARROW_RIGHT if collapsed else IconSet.ARROW_LEFT
    tooltip = "展开侧边栏" if collapsed else "收起侧边栏"
    return ft.Container(
        content=ft.Icon(icon, size=16, color=THEME.text_secondary),
        alignment=ft.alignment.Alignment(0, 0),
        padding=8,
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
