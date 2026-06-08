"""Shared layout helpers for Minecraft-style application pages."""
from __future__ import annotations

from typing import Callable, Iterable, List, NamedTuple

import flet as ft

from app.ui.theme import THEME, mc_border


class TabSpec(NamedTuple):
    """Small descriptor for a segmented tab in a view."""

    label: str
    icon: str


def page_header(
    title: str,
    subtitle: ft.Control,
    icon: str = "▣",
    actions: ft.Control | None = None,
) -> ft.Container:
    """Create the shared page title bar used by full-page views."""
    return ft.Container(
        content=ft.Row(
            [
                ft.Row(
                    [
                        ft.Text(icon, size=26, color=THEME.mc_gold, font_family="monospace"),
                        ft.Column(
                            [
                                ft.Text(
                                    title,
                                    size=22,
                                    weight=ft.FontWeight.BOLD,
                                    color=THEME.text_primary,
                                    font_family="monospace",
                                ),
                                subtitle,
                            ],
                            spacing=0,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                actions or ft.Container(),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        padding=ft.Padding(left=16, right=16, top=14, bottom=14),
        bgcolor=THEME.mc_dirt,
        border=mc_border(2),
    )


def panel(content: ft.Control, padding: int = 10, bgcolor: str | None = None) -> ft.Container:
    """Create a bordered layout panel for grouping page sections."""
    return ft.Container(
        content=content,
        padding=padding,
        bgcolor=bgcolor or THEME.bg_secondary,
        border=mc_border(2),
    )


def segmented_tab_bar(
    tabs: Iterable[TabSpec],
    selected_index: int,
    on_select: Callable[[int], None],
) -> tuple[ft.Container, ft.Row, List[ft.Container], List[ft.Text]]:
    """Build a compact Minecraft-style segmented tab bar.

    Returns the bar plus internals that existing responsive code can adjust.
    """
    labels: List[ft.Text] = []
    buttons: List[ft.Container] = []
    controls: List[ft.Control] = []

    for idx, tab in enumerate(tabs):
        selected = idx == selected_index
        label = ft.Text(
            tab.label,
            size=12,
            weight=ft.FontWeight.BOLD,
            color=THEME.text_primary if selected else THEME.text_secondary,
            font_family="monospace",
        )
        button = ft.Container(
            content=ft.Column(
                [
                    ft.Text(tab.icon, size=20, text_align=ft.TextAlign.CENTER),
                    label,
                ],
                spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=88,
            height=60,
            alignment=ft.Alignment(0, 0),
            padding=ft.Padding(left=6, right=6, top=6, bottom=6),
            bgcolor=THEME.mc_stone if selected else THEME.bg_secondary,
            border=mc_border(3),
            on_click=lambda e, i=idx: on_select(i),
        )
        labels.append(label)
        buttons.append(button)
        controls.append(button)

    row = ft.Row(controls, spacing=8)
    indicator = ft.Container(height=4, bgcolor=THEME.mc_grass)
    bar = panel(ft.Column([row, indicator], spacing=8), padding=10, bgcolor=THEME.mc_coal)
    return bar, row, buttons, labels
