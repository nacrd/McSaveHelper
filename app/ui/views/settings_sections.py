"""Collapsible section helper for the settings page."""
from __future__ import annotations

import flet as ft

from app.ui.theme import THEME, mc_border


def collapsible_section(
    title: str,
    content: ft.Control,
    expanded: bool = False,
) -> ft.Container:
    """Wrap a section body in a collapsible card."""
    arrow = ft.Icon(
        ft.Icons.KEYBOARD_ARROW_DOWN if expanded else ft.Icons.KEYBOARD_ARROW_RIGHT,
        size=18,
        color=THEME.text_secondary,
    )
    title_row = ft.Row(
        [
            ft.Container(
                content=ft.Text("▣", size=13, color=THEME.text_primary),
                width=24,
                height=24,
                alignment=ft.alignment.Alignment(0, 0),
                bgcolor=THEME.mc_grass,
                border_radius=4,
                border=mc_border(1),
            ),
            ft.Text(
                title,
                size=14,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
                font_family="monospace",
                expand=True,
            ),
            arrow,
        ],
        spacing=10,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    title_bar = ft.Container(
        content=title_row,
        padding=ft.Padding(left=16, right=16, top=12, bottom=12),
        ink=True,
        border_radius=6,
    )
    body_wrapper = ft.Container(
        content=content,
        padding=ft.Padding(left=4, right=4, top=0, bottom=4),
        animate_opacity=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        animate_size=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )
    body_wrapper.visible = expanded
    body_wrapper.opacity = 1.0 if expanded else 0.0

    def _toggle() -> None:
        is_visible = body_wrapper.visible
        body_wrapper.visible = not is_visible
        body_wrapper.opacity = 0.0 if is_visible else 1.0
        arrow.icon = (
            ft.Icons.KEYBOARD_ARROW_DOWN if not is_visible
            else ft.Icons.KEYBOARD_ARROW_RIGHT
        )
        body_wrapper.update()
        arrow.update()

    title_bar.on_click = _toggle
    card_container = ft.Container(
        content=ft.Column([title_bar, body_wrapper], spacing=0),
        bgcolor=THEME.bg_card,
        border=mc_border(),
        border_radius=8,
    )
    return ft.Container(
        content=card_container,
        padding=ft.Padding(bottom=12),
    )
