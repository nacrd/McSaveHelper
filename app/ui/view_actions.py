"""Public action descriptors exposed by views to the application shell."""
from dataclasses import dataclass
from typing import Callable, Literal

import flet as ft


@dataclass(frozen=True)
class ViewAction:
    label: str
    handler: Callable[[ft.ControlEvent], None]
    style: Literal["primary", "danger"] = "primary"
