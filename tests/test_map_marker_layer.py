from app.ui.views.explorer.map.marker_layer import MapMarkerLayer
from core.mca.map_models import MapMarker
from core.mca.viewport import McaViewport


def _marker(marker_id: str = "home") -> MapMarker:
    return MapMarker(
        id=marker_id,
        name="基地",
        x=0,
        y=64,
        z=0,
        dimension_id="overworld",
    )


def test_marker_layer_draws_hits_and_copies_snapshot() -> None:
    layer = MapMarkerLayer()
    marker = _marker()
    layer.set_markers([marker])
    viewport = McaViewport(scale=2, offset_x=100, offset_y=80)

    shapes = layer.draw(viewport, width=800, height=600)
    hit = layer.hit_test(100, 80)
    snapshot = layer.snapshot()

    assert shapes
    assert hit is not None and hit.id == "home"
    assert layer.selected_id == "home"
    assert snapshot == [marker]
    assert snapshot[0] is not marker


def test_marker_layer_toggle_clears_hits() -> None:
    layer = MapMarkerLayer()
    layer.set_markers([_marker()])
    layer.draw(McaViewport(), width=200, height=200)

    assert layer.toggle() is False
    assert layer.hit_test(0, 0) is None
    assert layer.draw(McaViewport(), width=200, height=200) == []


def test_marker_layer_applies_explicit_visibility() -> None:
    layer = MapMarkerLayer()

    assert layer.set_visible(False) is False
    assert layer.set_visible(True) is True
