"""Map interaction snapshot helpers."""
from __future__ import annotations

from types import SimpleNamespace

from app.ui.views.explorer.map.map_interaction_state import (
    snapshot_from_map_view,
    snapshot_map_interaction,
)


def test_snapshot_map_interaction_fields() -> None:
    snap = snapshot_map_interaction(
        show_coordinates=True,
        show_grid=False,
        show_empty_regions=True,
        display_mode="topview",
        detail_level="chunk",
        use_topview=True,
        scale=2.5,
        center_x=10.0,
        center_z=-4.0,
    )
    assert snap.show_coordinates is True
    assert snap.detail_level == "chunk"
    assert snap.scale == 2.5


def test_snapshot_from_map_view_reads_private_flags() -> None:
    view = SimpleNamespace(
        _show_coordinates=False,
        _show_grid=True,
        _show_empty_regions=False,
        _display_mode="size",
        _detail_level="region",
        _use_topview=False,
        _viewport=SimpleNamespace(scale=1.25, center_x=1.0, center_z=2.0),
    )
    snap = snapshot_from_map_view(view)
    assert snap.display_mode == "size"
    assert snap.use_topview is False
    assert snap.center_z == 2.0
