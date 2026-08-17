"""Qt 卡片与标题组件。"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.qtui.components.buttons import btn_primary
from app.qtui.icons import glyph


def card(
    content: QWidget,
    *,
    padding: int = 16,
    margins: tuple[int, int, int, int] | None = None,
) -> QFrame:
    """创建带主题边框与背景的卡片容器。

    Args:
        content: 卡片内容控件。
        padding: 内容四周内边距（像素）。
        margins: 覆盖 padding 的 (左, 上, 右, 下) 外边距。

    Returns:
        QFrame: 样式化卡片。
    """
    frame = QFrame()
    frame.setProperty("role", "card")
    layout = QVBoxLayout(frame)
    if margins is not None:
        layout.setContentsMargins(*margins)
    else:
        layout.setContentsMargins(padding, padding, padding, padding)
    layout.addWidget(content)
    layout.addStretch(1)
    return frame


def section_title(text: str) -> QLabel:
    """创建段落标题标签。"""
    label = QLabel(text)
    label.setProperty("role", "section")
    return label


def placeholder(
    icon: str = glyph("CLIPBOARD"),
    title: str = "暂无内容",
    subtitle: str = "请加载数据后查看",
    height: int = 150,
    *,
    expand: bool = False,
    surface: bool = True,
    action_text: str = "",
    on_action: Callable[[], None] | None = None,
) -> QWidget:
    """创建美化的空状态占位符（与 Flet ``placeholder`` 布局一致）。

    Args:
        icon: 图标字形。
        title: 主标题。
        subtitle: 副标题说明。
        height: 容器高度。
        expand: 是否填满父内容区并保持内容居中。
        surface: 是否绘制卡片背景和边框。
        action_text: 可选主操作文案。
        on_action: 可选主操作回调。

    Returns:
        QWidget: 居中图标 + 标题 + 副标题的占位容器。
    """
    host = QWidget()
    host.setProperty("role", "state")
    host.setProperty("surface", "raised" if surface else "flat")
    if expand:
        host.setMinimumHeight(height)
        host.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
    else:
        host.setFixedHeight(height)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(20, 30, 20, 30)
    layout.setSpacing(0)
    layout.addStretch(1)
    icon_label = QLabel(icon)
    icon_label.setProperty("role", "stateIcon")
    icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(icon_label)
    spacer_icon = QWidget()
    spacer_icon.setFixedHeight(10)
    layout.addWidget(spacer_icon)
    title_label = QLabel(title)
    title_label.setProperty("role", "stateTitle")
    title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title_label)
    spacer_title = QWidget()
    spacer_title.setFixedHeight(6)
    layout.addWidget(spacer_title)
    sub = QLabel(subtitle)
    sub.setProperty("role", "stateSubtitle")
    sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sub.setWordWrap(True)
    layout.addWidget(sub)
    if action_text and on_action is not None:
        action = btn_primary(action_text, on_click=on_action)
        action.setMinimumWidth(120)
        layout.addSpacing(12)
        layout.addWidget(action, alignment=Qt.AlignmentFlag.AlignCenter)
    layout.addStretch(1)
    return host


def loading_placeholder(
    title: str = "正在加载",
    subtitle: str = "请稍候…",
    height: int = 150,
    *,
    expand: bool = False,
    surface: bool = True,
) -> QWidget:
    """创建统一的加载状态面板。"""
    host = placeholder(
        icon=glyph("REFRESH"),
        title=title,
        subtitle=subtitle,
        height=height,
        expand=expand,
        surface=surface,
    )
    layout = host.layout()
    if not isinstance(layout, QVBoxLayout):
        return host
    progress = QProgressBar()
    progress.setRange(0, 0)
    progress.setFixedHeight(5)
    progress.setMaximumWidth(240)
    progress.setProperty("role", "stateLoading")
    insert_at = max(0, layout.count() - 1)
    layout.insertSpacing(insert_at, 10)
    layout.insertWidget(
        insert_at + 1,
        progress,
        alignment=Qt.AlignmentFlag.AlignCenter,
    )
    return host


def title_label(text: str) -> QLabel:
    """创建页面主标题标签。"""
    label = QLabel(text)
    label.setProperty("role", "title")
    return label


def muted_label(text: str) -> QLabel:
    """创建次要说明文字标签。"""
    label = QLabel(text)
    label.setProperty("role", "muted")
    label.setWordWrap(True)
    return label


def stretch() -> QWidget:
    """返回可拉伸的空白控件。"""
    widget = QWidget()
    widget.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Preferred,
    )
    return widget


def divider() -> QFrame:
    """返回主题细分割线（与 Flet ``ft.Divider`` 视觉一致）。"""
    from app.qtui.theme import get_theme_manager

    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(
        f"background-color: {get_theme_manager().current.border_subtle};"
        " border: none; margin: 0;"
    )
    return line
