"""卡片布局组件"""
import flet as ft

from app.ui.theme import THEME


def card(
    content: ft.Control,
    padding: int = 20,
) -> ft.Container:
    """创建深色主题卡片容器"""
    inner = content
    if not isinstance(content, ft.Container):
        inner = ft.Container(content=content, padding=padding)
    return ft.Container(
        content=inner,
        bgcolor=THEME.bg_card,
        border=ft.Border(
            left=ft.BorderSide(1, THEME.border_standard),
            top=ft.BorderSide(1, THEME.border_standard),
            right=ft.BorderSide(1, THEME.border_standard),
            bottom=ft.BorderSide(1, THEME.border_standard),
        ),
        border_radius=8,
    )


def section_title(text: str) -> ft.Container:
    """创建区块标题"""
    return ft.Container(
        content=ft.Row(
            [
                ft.Text(
                    text,
                    size=15,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                ft.Container(height=1, bgcolor=THEME.border_subtle),
            ],
            spacing=15,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(left=20, right=20, top=18, bottom=8),
    )
