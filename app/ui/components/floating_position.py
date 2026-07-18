"""Reusable drag positioning and persistence for floating controls."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import flet as ft

PositionCallback = Callable[[float, float], None]


@dataclass(frozen=True)
class FloatingBounds:
    viewport_width: float
    viewport_height: float
    control_width: float
    control_height: float


def clamp_position(
    horizontal: float,
    vertical: float,
    bounds: FloatingBounds,
) -> Tuple[float, float]:
    """Clamp either top-left or bottom-right offsets to the viewport."""
    return (
        max(0.0, min(bounds.viewport_width - bounds.control_width, horizontal)),
        max(0.0, min(bounds.viewport_height - bounds.control_height, vertical)),
    )


class DragTracker:
    """Track pointer deltas without depending on Flet event classes."""

    def __init__(self) -> None:
        self.active = False
        self._last_x = 0.0
        self._last_y = 0.0

    def start(self, x: float, y: float) -> None:
        self.active = True
        self._last_x = x
        self._last_y = y

    def update(self, x: float, y: float) -> Optional[Tuple[float, float]]:
        if not self.active:
            return None
        delta = (x - self._last_x, y - self._last_y)
        self._last_x = x
        self._last_y = y
        return delta

    def end(self) -> None:
        self.active = False


class SharedPositionStore:
    """Load and save a pair of floating offsets via Flet preferences."""

    def __init__(self, page: ft.Page, key: str) -> None:
        self._page = page
        self._key = key

    def load(self, apply: PositionCallback) -> None:
        async def _load() -> None:
            position = await self._page.shared_preferences.get(self._key)
            if isinstance(position, list) and len(position) >= 2:
                apply(float(position[0]), float(position[1]))

        try:
            self._page.run_task(_load)
        except Exception:
            pass

    def save(self, horizontal: float, vertical: float) -> None:
        async def _save() -> None:
            await self._page.shared_preferences.set(
                self._key,
                [str(horizontal), str(vertical)],
            )

        try:
            self._page.run_task(_save)
        except Exception:
            pass
