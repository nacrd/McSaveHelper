"""Public action descriptors exposed by views to the application shell."""
from dataclasses import dataclass
from typing import Callable, Literal

import flet as ft


@dataclass(frozen=True)
class ViewAction:
    """视图暴露给顶栏的命令描述符。

    Attributes:
        label: 按钮文案。
        handler: 点击回调。
        style: ``primary`` 或 ``danger`` 视觉样式。
    """

    label: str
    handler: Callable[[ft.ControlEvent], None]
    style: Literal["primary", "danger"] = "primary"
