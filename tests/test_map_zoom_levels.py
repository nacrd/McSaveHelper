"""Unit tests for map zoom level thresholds and helpers."""
from app.ui.views.explorer.map.mca_map_view import (
    SCALE_BLOCK,
    SCALE_CHUNK,
    SCALE_REGION,
    view_level_from_scale,
)


def test_view_level_from_scale_thresholds():
    assert view_level_from_scale(0.5) == "world"
    assert view_level_from_scale(SCALE_REGION - 0.01) == "world"
    assert view_level_from_scale(SCALE_REGION) == "region"
    assert view_level_from_scale(SCALE_CHUNK - 0.01) == "region"
    assert view_level_from_scale(SCALE_CHUNK) == "chunk"
    assert view_level_from_scale(SCALE_BLOCK - 0.01) == "chunk"
    assert view_level_from_scale(SCALE_BLOCK) == "block"
    assert view_level_from_scale(200.0) == "block"


def test_scale_constants_are_ordered():
    assert SCALE_REGION < SCALE_CHUNK < SCALE_BLOCK
