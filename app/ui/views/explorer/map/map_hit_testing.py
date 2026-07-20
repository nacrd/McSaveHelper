"""Hit testing helpers for map canvas bounds."""
from __future__ import annotations

from typing import Collection, Mapping, Optional, Tuple

Coord = Tuple[int, int]
ScreenRect = Tuple[float, float, float, float]


def hit_bounds(
    tap_x: float,
    tap_y: float,
    bounds: Mapping[Coord, ScreenRect],
    *,
    allowed: Optional[Collection[Coord]] = None,
) -> Optional[Coord]:
    """Return the first bound containing the screen point."""
    for coord, (bx, by, bw, bh) in bounds.items():
        if bx <= tap_x <= bx + bw and by <= tap_y <= by + bh:
            if allowed is not None and coord not in allowed:
                continue
            return coord
    return None


def rect_contains(
    tap_x: float,
    tap_y: float,
    rect: ScreenRect,
) -> bool:
    """判断点是否落在矩形 (x,y,w,h) 内。"""
    bx, by, bw, bh = rect
    return bx <= tap_x <= bx + bw and by <= tap_y <= by + bh
