from app.ui.views.explorer.map import map_shapes
from core.mca.map_models import MapMarker


def _coord_label(coord: tuple[int, int], _size: float) -> str:
    return f"{coord[0]},{coord[1]}"


def test_empty_state_and_region_shapes_are_positioned() -> None:
    empty = map_shapes.empty_state(800, 600)
    assert len(empty) == 2
    assert getattr(empty[1], "value") == "设置当前存档后显示区域地图"

    region = map_shapes.empty_region((10.0, 20.0, 32.0, 32.0))
    assert (region.x, region.y, region.width, region.height) == (10.0, 20.0, 32.0, 32.0)


def test_chunk_grid_records_hit_bounds_for_selected_region() -> None:
    shapes, chunk_bounds, block_bounds = map_shapes.chunk_grid(
        0.0,
        0.0,
        2048.0,
        (1, -1),
        show_block_grid=True,
        show_coordinates=True,
        selected_chunk=(35, -20),
    )

    assert shapes
    assert (32, -32) in chunk_bounds
    assert (35, -20) in chunk_bounds
    assert block_bounds


def test_unselected_region_has_no_border_or_coordinate_text() -> None:
    shapes = map_shapes.region_cell(
        0.0,
        0.0,
        32.0,
        "#4CAF50",
        (0, 0),
        selected=False,
        view_level="world",
        show_coordinates=False,
        tile_src=None,
        coord_label=_coord_label,
    )

    assert len(shapes) == 1


def test_marker_overlay_projects_labels_and_hit_bounds() -> None:
    marker = MapMarker(
        id="home",
        name="基地",
        x=-12,
        y=64,
        z=30,
        dimension_id="overworld",
    )

    shapes, bounds = map_shapes.marker_overlay(
        [marker],
        block_to_screen=lambda x, z: (100 + x, 120 + z),
        width=800,
        height=600,
        scale=1.0,
        selected_id="home",
    )

    assert shapes
    assert "home" in bounds
    left, top, width, height = bounds["home"]
    assert left < 88 < left + width
    assert top < 150 < top + height
