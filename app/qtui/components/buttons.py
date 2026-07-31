"""Qt 按钮组件：primary / ghost / success / danger 视觉变体。"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtWidgets import QPushButton


class QtButton(QPushButton):
    """带主题角色的按钮。"""

    def __init__(
        self,
        text: str = "",
        *,
        role: str = "default",
        width: Optional[int] = None,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        """构建按钮。

        Args:
            text: 按钮文案。
            role: ``default`` / ``primary`` / ``ghost`` / ``danger``。
            width: 可选固定宽度（像素）。
            on_click: 点击回调（无参数）。
        """
        super().__init__(text)
        if role != "default":
            self.setProperty("role", role)
        if width is not None:
            self.setFixedWidth(width)
        if on_click is not None:
            self.clicked.connect(lambda _checked: on_click())


def btn_primary(
    text: str,
    *,
    width: Optional[int] = None,
    on_click: Optional[Callable[[], None]] = None,
) -> QtButton:
    """创建主操作按钮。"""
    return QtButton(text, role="primary", width=width, on_click=on_click)


def btn_ghost(
    text: str,
    *,
    width: Optional[int] = None,
    on_click: Optional[Callable[[], None]] = None,
) -> QtButton:
    """创建次操作按钮。"""
    return QtButton(text, role="ghost", width=width, on_click=on_click)


def btn_success(
    text: str,
    *,
    width: Optional[int] = None,
    on_click: Optional[Callable[[], None]] = None,
) -> QtButton:
    """创建成功语义按钮（沿用主色调）。"""
    return QtButton(text, role="primary", width=width, on_click=on_click)


def btn_danger(
    text: str,
    *,
    width: Optional[int] = None,
    on_click: Optional[Callable[[], None]] = None,
) -> QtButton:
    """创建危险操作按钮。"""
    return QtButton(text, role="danger", width=width, on_click=on_click)
