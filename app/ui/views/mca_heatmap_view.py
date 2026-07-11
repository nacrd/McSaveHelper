"""Backward-compatible shim for McaHeatmapView.

Prefer importing from ``app.ui.views.explorer.map``:

    from app.ui.views.explorer.map import McaMapView
"""
from app.ui.views.explorer.map.mca_map_view import McaHeatmapView, McaMapView

__all__ = ["McaMapView", "McaHeatmapView"]
