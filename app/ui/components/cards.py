"""Minecraft-style card layout components"""
import flet as ft

from app.ui.theme import THEME, mc_border, mc_shadow
from flet import Icons


def card(
    content: ft.Control,
    padding: int = 20,
) -> ft.Container:
    """Create a Minecraft-style card with beveled borders and shadow

    Modernized with rounded corners and better styling.

    Args:
        content: Card content
        padding: Padding around content (default: 20)

    Returns:
        ft.Container: Card container
    """
    inner = content
    if not isinstance(content, ft.Container):
        inner = ft.Container(content=content, padding=padding)
    return ft.Container(
        content=inner,
        bgcolor=THEME.bg_card,
        border=mc_border(),
        border_radius=8,
        shadow=mc_shadow(),
        animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
    )


def section_title(text: str, icon: str = "▣") -> ft.Container:
    """Create a section title with Minecraft-style decorations

    Args:
        text: Section title text
        icon: Decorative icon (default: "▣")

    Returns:
        ft.Container: Section title container
    """
    return ft.Container(
        content=ft.Row(
            [
                ft.Container(
                    content=ft.Text(icon, size=14, color=THEME.text_primary),
                    width=26,
                    height=26,
                    alignment=ft.alignment.Alignment(0, 0),
                    bgcolor=THEME.mc_grass,
                    border=mc_border(1),
                    border_radius=4,
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


def placeholder(
    icon: ft.IconData = Icons.MAIL_OUTLINE,
    title: str = "暂无内容",
    subtitle: str = "请加载数据后查看",
    height: int = 150,
) -> ft.Container:
    """创建美化的空状态占位符

    Args:
        icon: 显示的图标
        title: 主标题
        subtitle: 副标题说明
        height: 容器高度

    Returns:
        ft.Container: 美化的占位符容器
    """
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Icon(icon, size=48, color=THEME.text_secondary),
                ft.Container(height=10),
                ft.Text(
                    title,
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_secondary,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(height=6),
                ft.Text(
                    subtitle,
                    size=13,
                    color=THEME.text_muted,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        ),
        padding=ft.Padding(left=20, right=20, top=30, bottom=30),
        bgcolor=THEME.bg_card,
        border=mc_border(1),
        border_radius=8,
        height=height,
        alignment=ft.alignment.Alignment(0, 0),
    )
