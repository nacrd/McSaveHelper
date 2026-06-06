"""Minecraft 风格卡片布局组件"""
import flet as ft

from app.ui.theme import THEME


def card(
    content: ft.Control,
    padding: int = 20,
) -> ft.Container:
    inner = content
    if not isinstance(content, ft.Container):
        inner = ft.Container(content=content, padding=padding)
    return ft.Container(
        content=inner,
        bgcolor=THEME.bg_card,
        border=ft.Border(
            left=ft.BorderSide(2, THEME.border_tertiary),
            top=ft.BorderSide(2, THEME.border_tertiary),
            right=ft.BorderSide(2, THEME.bg_secondary),
            bottom=ft.BorderSide(2, THEME.bg_secondary),
        ),
        border_radius=0,
        shadow=ft.BoxShadow(
            spread_radius=0,
            blur_radius=0,
            color=THEME.shadow,
            offset=ft.Offset(4, 4),
        ),
    )


def section_title(text: str) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            [
                ft.Container(width=8, height=18, bgcolor=THEME.mc_grass),
                ft.Text(
                    text,
                    size=15,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                    font_family="monospace",
                ),
                ft.Container(height=2, bgcolor=THEME.border_standard),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(left=20, right=20, top=18, bottom=8),
    )
