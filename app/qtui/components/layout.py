"""Qt 页面布局组件：页头、面板、容器。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.qtui.components.cards import title_label, muted_label


def page_header(
    title: str,
    subtitle: str = "",
    icon: str = "",
) -> QWidget:
    """构建页面头部：图标 + 标题 + 副标题。

    Args:
        title: 页面标题。
        subtitle: 次要说明。
        icon: 可选字形图标。

    Returns:
        QWidget: 头部容器。
    """
    header = QWidget()
    layout = QHBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 8)
    title_widget = title_label(f"{icon}  {title}" if icon else title)
    layout.addWidget(title_widget)
    if subtitle:
        layout.addWidget(muted_label(subtitle))
    layout.addStretch(1)
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
