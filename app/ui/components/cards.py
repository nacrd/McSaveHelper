"""Minecraft-style card layout components"""
import flet as ft

from app.ui.theme import THEME, mc_border, mc_shadow


def card(
    content: ft.Control,
    padding: int = 20,
) -> ft.Container:
    """Create a Minecraft-style card with beveled borders and shadow"""
    inner = content
    if not isinstance(content, ft.Container):
        inner = ft.Container(content=content, padding=padding)
    return ft.Container(
        content=inner,
        bgcolor=THEME.bg_card,
        border=mc_border(),
        border_radius=0,
        shadow=mc_shadow(),
    )


def section_title(text: str, icon: str = "▣") -> ft.Container:
    """Create a section title with Minecraft-style decorations"""
    return ft.Container(
        content=ft.Row(
            [
                ft.Container(
                    content=ft.Text(icon, size=14, color=THEME.text_primary),
                    width=24,
                    height=24,
                    alignment=ft.alignment.Alignment(0, 0),
                    bgcolor=THEME.mc_grass,
                    border=mc_border(1),
                ),
                ft.Text(
                    text,
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                    font_family="monospace",
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(left=20, right=20, top=16, bottom=12),
    )
