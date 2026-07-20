"""Reusable drag positioning and persistence for floating controls."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import flet as ft

PositionCallback = Callable[[float, float], None]


@dataclass(frozen=True)
class FloatingBounds:
    """浮动控件相对视口的尺寸约束。

    Attributes:
        viewport_width: 视口宽。
        viewport_height: 视口高。
        control_width: 控件宽。
        control_height: 控件高。
    """

    viewport_width: float
    viewport_height: float
    control_width: float
    control_height: float


def clamp_position(
    horizontal: float,
    vertical: float,
    bounds: FloatingBounds,
) -> Tuple[float, float]:
    """将 top-left 或 bottom-right 偏移钳到视口内，避免控件拖出屏幕。

    Args:
        horizontal: 水平偏移。
        vertical: 垂直偏移。
        bounds: 视口与控件尺寸。

    Returns:
        钳位后的 ``(horizontal, vertical)``。
    """
    return (
        max(0.0, min(bounds.viewport_width - bounds.control_width, horizontal)),
        max(0.0, min(bounds.viewport_height - bounds.control_height, vertical)),
    )


class DragTracker:
    """跟踪指针增量，不依赖具体 Flet 事件类型。"""

    def __init__(self) -> None:
        """创建未激活的拖动跟踪器。"""
        self.active = False
        self._last_x = 0.0
        self._last_y = 0.0

    def start(self, x: float, y: float) -> None:
        """开始拖动，记录起点。

        Args:
            x: 指针 X。
            y: 指针 Y。
        """
        self.active = True
        self._last_x = x
        self._last_y = y

    def update(self, x: float, y: float) -> Optional[Tuple[float, float]]:
        """更新指针位置并返回相对上次的 ``(dx, dy)``。

        Args:
            x: 当前指针 X。
            y: 当前指针 Y。

        Returns:
            位移增量；未激活时为 None。
        """
        if not self.active:
            return None
        delta = (x - self._last_x, y - self._last_y)
        self._last_x = x
        self._last_y = y
        return delta

    def end(self) -> None:
        """结束拖动会话。"""
        self.active = False


class SharedPositionStore:
    """通过 Flet shared_preferences 读写一对浮动偏移。"""

    def __init__(self, page: ft.Page, key: str) -> None:
        """绑定页面与偏好键。

        Args:
            page: Flet 页面（提供 ``run_task`` / preferences）。
            key: 存储键名。
        """
        self._page = page
        self._key = key

    def load(self, apply: PositionCallback) -> None:
        """异步加载偏好并回调应用位置；失败静默忽略。

        Args:
            apply: ``(horizontal, vertical)`` 应用回调。
        """
        async def _load() -> None:
            position = await self._page.shared_preferences.get(self._key)
            if isinstance(position, list) and len(position) >= 2:
                apply(float(position[0]), float(position[1]))

        try:
            self._page.run_task(_load)
        except Exception:
            pass

    def save(self, horizontal: float, vertical: float) -> None:
        """异步持久化偏移；失败静默忽略。

        Args:
            horizontal: 水平偏移。
            vertical: 垂直偏移。
        """
        async def _save() -> None:
            await self._page.shared_preferences.set(
                self._key,
                [str(horizontal), str(vertical)],
            )

        try:
            self._page.run_task(_save)
        except Exception:
            pass
