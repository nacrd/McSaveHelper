"""Qt 页面布局组件：页头、面板、容器。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.qtui.components.cards import muted_label


def page_header(
    title: str,
    subtitle: str = "",
    icon: str = "",
) -> QWidget:
    """构建页面头部（与 Flet ``PageHeader`` 布局一致）。

    Args:
        title: 页面标题。
        subtitle: 次要说明。
        icon: 可选字形图标。

    Returns:
        QWidget: 头部容器（图标块 + 标题 + 副标题 + 底部边框）。
    """
    from app.qtui.theme import get_theme_manager

    header = QWidget()
    layout = QHBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 14)
    layout.setSpacing(12)
    colors = get_theme_manager().current
    root = QWidget()
    root.setStyleSheet(
        f"QWidget {{ border: none; border-bottom: 1px solid"
        f" {colors.border_subtle}; }}"
    )
    inner = QHBoxLayout(root)
    inner.setContentsMargins(0, 0, 0, 14)
    inner.setSpacing(12)
    if icon:
        icon_box = QLabel(icon)
        icon_box.setFixedSize(40, 40)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box.setStyleSheet(
            f"background-color: {colors.bg_elevated};"
            f" border: 1px solid {colors.border_standard};"
            " border-radius: 6px; font-size: 20px;"
        )
        inner.addWidget(icon_box)
    text_col = QWidget()
    text_layout = QVBoxLayout(text_col)
    text_layout.setContentsMargins(0, 0, 0, 0)
    text_layout.setSpacing(2)
    title_widget = QLabel(title)
    title_widget.setStyleSheet(
        f"color: {colors.text_primary}; font-size: 20px; font-weight: 600;"
    )
    text_layout.addWidget(title_widget)
    if subtitle:
        sub = muted_label(subtitle)
        sub.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 13px;"
        )
        text_layout.addWidget(sub)
    inner.addWidget(text_col, 1)
    inner.addStretch(1)
    layout.addWidget(root)
    return header


def section_header(title: str, subtitle: str = "") -> QWidget:
    """构建区块头：标题 + 可选说明。"""
    header = QWidget()
    layout = QVBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    layout.addWidget(QLabel(title))
    if subtitle:
        subtitle_label = muted_label(subtitle)
        layout.addWidget(subtitle_label)
    return header


def panel(content: QWidget) -> QWidget:
    """构建可滚动内容面板。"""
    from PySide6.QtWidgets import QScrollArea

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)
    return scroll


def vbox_spacing(widget: QWidget, spacing: int = 10) -> None:
    """设置控件根布局的间距（供视图构建后统一调整）。"""
    layout = widget.layout()
    if layout is not None and isinstance(layout, QVBoxLayout):
        layout.setSpacing(spacing)


def hbox(
    widgets: list[QWidget],
    *,
    spacing: int = 10,
    stretch_last: bool = True,
) -> QWidget:
    """构建水平容器。"""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    if stretch_last:
        layout.addStretch(1)
    return container
