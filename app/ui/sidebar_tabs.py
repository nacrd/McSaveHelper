"""Sidebar tab button construction and style helpers."""
from __future__ import annotations

from typing import Any, Callable, Dict

import flet as ft

from app.ui.icons import IconSet
from app.ui.theme import THEME


def resolve_tab_icon(tab: Dict[str, Any]) -> ft.IconData:
    """解析侧栏 tab 定义中的图标；非法值回退到网格图标。

    Args:
        tab: 含 ``icon`` 字段的 tab 定义。

    Returns:
        Flet ``IconData``。
    """
    icon_name = tab.get("icon", IconSet.GRID)
    if not isinstance(icon_name, ft.IconData):
        return IconSet.GRID
    return icon_name


def build_tab_button(
    tab: Dict[str, Any],
    *,
    selected: bool,
    collapsed: bool,
    on_select: Callable[[str], None],
    on_hover: Callable[[ft.Event[ft.Container], str], None],
    on_hover_collapsed: Callable[[ft.Event[ft.Container], str], None],
) -> ft.Container:
    """按折叠态构建侧栏页签按钮。

    Args:
        tab: 含 ``id`` / ``label`` / ``icon`` 的定义。
        selected: 是否当前选中。
        collapsed: 侧栏是否图标折叠模式。
        on_select: 点击回调 ``(view_id)``。
        on_hover / on_hover_collapsed: 悬停样式回调。
    """
    icon_name = resolve_tab_icon(tab)
    label_text = tab.get("label", tab["id"])
    if collapsed:
        return build_tab_collapsed(
            tab,
            selected=selected,
            icon_name=icon_name,
            label_text=label_text,
            on_select=on_select,
            on_hover_collapsed=on_hover_collapsed,
        )
    return build_tab_expanded(
        tab,
        selected=selected,
        icon_name=icon_name,
        label_text=label_text,
        on_select=on_select,
        on_hover=on_hover,
    )


def build_tab_collapsed(
    tab: Dict[str, Any],
    *,
    selected: bool,
    icon_name: ft.IconData,
    label_text: str,
    on_select: Callable[[str], None],
    on_hover_collapsed: Callable[[ft.Event[ft.Container], str], None],
) -> ft.Container:
    """折叠侧栏：仅图标 + tooltip 的页签按钮。

    Args:
        tab: tab 定义。
        selected: 是否选中。
        icon_name: 图标。
        label_text: tooltip 文案。
        on_select: 点击选中回调。
        on_hover_collapsed: 悬停回调。

    Returns:
        44x44 图标按钮容器。
    """
    icon_ctrl = ft.Icon(
        icon_name,
        size=20,
        color=THEME.accent if selected else THEME.text_secondary,
    )
    container = ft.Container(
        content=icon_ctrl,
        width=44,
        height=44,
        alignment=ft.alignment.Alignment(0, 0),
        bgcolor=THEME.bg_elevated if selected else ft.Colors.TRANSPARENT,
        border=ft.Border.all(
            1,
            THEME.accent_dim if selected else ft.Colors.TRANSPARENT,
        ),
        border_radius=6,
        ink=True,
        on_click=lambda e, tid=tab["id"]: on_select(tid),
        on_hover=lambda e, tid=tab["id"]: on_hover_collapsed(e, tid),
        tooltip=label_text,
        animate=ft.Animation(140, ft.AnimationCurve.EASE_OUT),
    )
    return container


def build_tab_expanded(
    tab: Dict[str, Any],
    *,
    selected: bool,
    icon_name: ft.IconData,
    label_text: str,
    on_select: Callable[[str], None],
    on_hover: Callable[[ft.Event[ft.Container], str], None],
) -> ft.Container:
    """展开侧栏：图标槽 + 标签 + 选中标记。

    Args:
        tab: tab 定义。
        selected: 是否选中。
        icon_name: 图标。
        label_text: 显示文案。
        on_select: 点击选中回调。
        on_hover: 悬停回调。

    Returns:
        带文字的 tab 容器。
    """
    icon_slot = ft.Container(
        content=ft.Icon(
            icon_name,
            size=18,
            color=THEME.accent if selected else THEME.text_muted,
        ),
        width=28,
        height=28,
        alignment=ft.alignment.Alignment(0, 0),
        bgcolor=ft.Colors.TRANSPARENT,
    )
    text_ctrl = ft.Text(
        label_text,
        size=13,
        color=THEME.text_primary if selected else THEME.text_secondary,
        weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500,
    )
    marker = ft.Text(
        "•" if selected else "",
        size=14,
        color=THEME.accent,
    )
    row = ft.Row(
        [icon_slot, text_ctrl, ft.Container(expand=True), marker],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    container = ft.Container(
        content=row,
        height=44,
        padding=ft.Padding(left=10, right=10, top=6, bottom=6),
        border_radius=6,
        bgcolor=THEME.bg_elevated if selected else ft.Colors.TRANSPARENT,
        border=ft.Border.all(
            1,
            THEME.border_standard if selected else ft.Colors.TRANSPARENT,
        ),
        ink=True,
        on_click=lambda e, tid=tab["id"]: on_select(tid),
        on_hover=lambda e, tid=tab["id"]: on_hover(e, tid),
        animate=ft.Animation(140, ft.AnimationCurve.EASE_OUT),
    )
    return container


def apply_style_collapsed(container: ft.Container, selected: bool) -> None:
    """就地更新折叠按钮的选中样式（避免整表重建）。

    Args:
        container: ``build_tab_collapsed`` 产出的容器。
        selected: 是否选中。
    """
    if container.content and isinstance(container.content, ft.Icon):
        container.content.color = (
            THEME.accent if selected else THEME.text_secondary
        )
    container.bgcolor = THEME.bg_elevated if selected else ft.Colors.TRANSPARENT
    container.border = ft.Border.all(
        1,
        THEME.accent_dim if selected else ft.Colors.TRANSPARENT,
    )


def apply_style_expanded(container: ft.Container, selected: bool) -> None:
    """就地更新展开按钮的选中样式与标记符。

    Args:
        container: ``build_tab_expanded`` 产出的容器。
        selected: 是否选中。
    """
    row = container.content
    if isinstance(row, ft.Row) and len(row.controls) >= 4:
        icon_slot = row.controls[0]
        text_ctrl = row.controls[1]
        marker = row.controls[3]
        if isinstance(icon_slot, ft.Container):
            if icon_slot.content and isinstance(icon_slot.content, ft.Icon):
                icon_slot.content.color = (
                    THEME.accent if selected else THEME.text_muted
                )
        if isinstance(text_ctrl, ft.Text):
            text_ctrl.color = (
                THEME.text_primary if selected else THEME.text_secondary
            )
            text_ctrl.weight = (
                ft.FontWeight.W_600 if selected else ft.FontWeight.W_500
            )
        if isinstance(marker, ft.Text):
            marker.value = "•" if selected else ""
    container.bgcolor = THEME.bg_elevated if selected else ft.Colors.TRANSPARENT
    container.border = ft.Border.all(
        1,
        THEME.border_standard if selected else ft.Colors.TRANSPARENT,
    )


def handle_hover_expanded(
    container: ft.Container,
    *,
    selected: bool,
    hovering: bool,
) -> None:
    """展开按钮悬停高亮；已选中时忽略。

    Args:
        container: tab 容器。
        selected: 是否选中。
        hovering: 指针是否悬停。
    """
    if selected:
        return
    if hovering:
        container.bgcolor = THEME.bg_card_hover
        return
    container.bgcolor = ft.Colors.TRANSPARENT


def handle_hover_collapsed(
    container: ft.Container,
    *,
    selected: bool,
    hovering: bool,
) -> None:
    """折叠按钮悬停高亮；已选中时忽略。

    Args:
        container: tab 容器。
        selected: 是否选中。
        hovering: 指针是否悬停。
    """
    if selected:
        return
    if hovering:
        container.bgcolor = THEME.bg_card_hover
        return
    container.bgcolor = ft.Colors.TRANSPARENT
