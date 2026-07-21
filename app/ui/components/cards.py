"""Card and empty-state components for application workspaces."""
import flet as ft

from app.ui.theme import THEME, mc_border
from flet import Icons

from app.ui.icons import IconSet


def card(
    content: ft.Control,
    padding: int = 20,
) -> ft.Container:
    """Create a restrained card for one cohesive content group.

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
        border=mc_border(1),
        border_radius=6,
    )


def section_title(
    text: str,
    icon: ft.IconData = IconSet.SECTION,
) -> ft.Container:
    """Create a compact section title.

    Args:
        text: Section title text
        icon: Leading vector icon.

    Returns:
        ft.Container: Section title container
    """
    return ft.Container(
        content=ft.Row(
            [
                ft.Container(
                    content=ft.Icon(
                        icon,
                        size=16,
                        color=THEME.text_invert,
                    ),
                    width=28,
                    height=28,
                    alignment=ft.alignment.Alignment(0, 0),
                    bgcolor=THEME.accent,
                    border_radius=4,
                ),
                ft.Text(
                    text,
                    size=14,
                    weight=ft.FontWeight.W_600,
                    color=THEME.text_primary,
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(left=16, right=16, top=14, bottom=10),
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
                ft.Icon(icon, size=36, color=THEME.text_muted),
                ft.Container(height=10),
                ft.Text(
                    title,
                    size=16,
                    weight=ft.FontWeight.W_600,
                    color=THEME.text_primary,
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
        border_radius=6,
        height=height,
        alignment=ft.alignment.Alignment(0, 0),
    )
