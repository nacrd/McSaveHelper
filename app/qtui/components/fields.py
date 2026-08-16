"""Qt 表单字段组件：文本、下拉、复选。"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QLineEdit, QWidget


def text_field(
    value: str = "",
    *,
    hint_text: str = "",
    width: Optional[int] = None,
    read_only: bool = False,
    on_changed: Optional[Callable[[str], None]] = None,
) -> QLineEdit:
    """创建文本输入框。

    Args:
        value: 初始值。
        hint_text: 空值时显示的提示。
        width: 可选固定宽度。
        read_only: 是否只读。
        on_changed: 文本变化回调。
    """
    field = QLineEdit()
    field.setText(value)
    if hint_text:
        field.setPlaceholderText(hint_text)
    if width is not None:
        field.setFixedWidth(width)
    field.setReadOnly(read_only)
    if on_changed is not None:
        field.textChanged.connect(on_changed)
    return field


def checkbox(
    text: str,
    value: bool = False,
    *,
    on_changed: Optional[Callable[[bool], None]] = None,
) -> QCheckBox:
    """创建复选框。"""
    box = QCheckBox(text)
    box.setChecked(value)
    if on_changed is not None:
        box.toggled.connect(on_changed)
    return box


def dropdown(
    options: Sequence[str],
    value: str = "",
    *,
    width: Optional[int] = None,
    on_changed: Optional[Callable[[str], None]] = None,
) -> QComboBox:
    """创建下拉框。

    Args:
        options: 选项文本序列。
        value: 初始选中值。
        width: 可选固定宽度。
        on_changed: 选择变化回调。
    """
    combo = QComboBox()
    combo.addItems(list(options))
    if value:
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)
    if width is not None:
        combo.setFixedWidth(width)
    if on_changed is not None:
        combo.currentTextChanged.connect(on_changed)
    return combo


def form_row(field: QWidget, description: str = "") -> tuple[QWidget, QLabel]:
    """构造字段与说明文字的对（供表单网格使用）。"""
    hint = QLabel(description)
    hint.setProperty("role", "muted")
    hint.setWordWrap(True)
    return field, hint
