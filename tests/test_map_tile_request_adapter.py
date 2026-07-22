"""Viewport tile request adapter."""
from __future__ import annotations

from app.ui.views.explorer.map.map_tile_request_adapter import (
    adapt_viewport_tile_requests,
)


def test_adapt_viewport_tile_requests_caps_and_orders() -> None:
    coords = [(0, 0), (2, 0), (1, 0), (5, 5)]
    batch = adapt_viewport_tile_requests(
        coords,
        center=(0, 0),
        preferred_tile_size=64,
        limit=3,
    )
    assert batch.preferred_tile_size == 64
    assert len(batch.coords) == 3
    assert batch.coords[0] == (0, 0)
