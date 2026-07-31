"""Qt 卡片与标题组件。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget


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


def placeholder(text: str) -> QLabel:
    """创建居中占位标签。"""
    label = QLabel(text)
    label.setProperty("role", "muted")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


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
