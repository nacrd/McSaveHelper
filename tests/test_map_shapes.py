from app.ui.views.explorer.map import map_shapes


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
