"""Qt 视图动作描述符（替代 Flet 版 ViewAction）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal


@dataclass(frozen=True)
class QtViewAction:
    """视图暴露给窗口顶栏的命令描述符。

    Attributes:
        label: 按钮文案。
        handler: 无参点击回调。
        style: ``primary`` 或 ``danger`` 视觉样式。
    """

    label: str
    handler: Callable[[], None]
    style: Literal["primary", "danger"] = "primary"
