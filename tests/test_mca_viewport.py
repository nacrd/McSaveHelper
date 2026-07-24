"""Behavioral tests for the pure MCA map viewport."""
import flet.canvas as cv
import pytest

from core.mca.viewport import (
    MAX_SCALE,
    MIN_SCALE,
    McaMapSelection,
    McaViewport,
    ViewportTarget,
    view_level_from_scale,
)
from core.mca.map_models import MapMarker
from app.services.cache_registry import CacheRegistry
from app.services.execution_runtime import ExecutionRuntime
from app.services.region_map import RegionMapService
from app.ui.views.explorer.map.mca_map_view import McaMapView
from app.ui.views.explorer.map.tile_source_cache import TileSourceCache


def test_view_level_thresholds() -> None:
    assert view_level_from_scale(0.5) == "world"
    assert view_level_from_scale(2.0) == "region"
    assert view_level_from_scale(6.5) == "chunk"
    assert view_level_from_scale(20.0) == "block"


def test_map_selection_preserves_level_invariants() -> None:
    selection = McaMapSelection()

    selection.select_region((-2, 3))
    assert selection.level == "region"
    assert selection.region == (-2, 3)
    assert selection.chunk is None

    selection.select_chunk((-33, 127), "block")
    assert selection.level == "block"
    assert selection.region == (-2, 3)
    assert selection.chunk == (-33, 127)

    assert selection.set_level("region") is True
    assert selection.chunk is None
    assert selection.region == (-2, 3)

    selection.reset()
    assert selection == McaMapSelection()


def test_region_and_chunk_projection_support_negative_coordinates() -> None:
    viewport = McaViewport(scale=2.0, offset_x=100.0, offset_y=80.0)
    rect = viewport.region_rect((-2, -1))
    screen_x = rect[0] + rect[2] * 0.75
    screen_y = rect[1] + rect[3] * 0.25

    assert viewport.region_at_screen(screen_x, screen_y, {(-2, -1)}) == (-2, -1)
    assert viewport.chunk_at_screen(screen_x, screen_y, {(-2, -1)}) == (-40, -24)


def test_region_projection_is_contiguous_and_rejects_missing_regions() -> None:
    viewport = McaViewport()

    assert viewport.region_at_screen(32.5, 10.0, {(0, 0), (1, 0)}) == (1, 0)
    assert viewport.region_at_screen(35.0, 10.0, {(0, 0)}) is None
    assert viewport.region_at_screen(35.0, 10.0, {(1, 0)}) == (1, 0)


def test_adjacent_region_rects_share_the_same_pixel_edge_at_fractional_scale() -> None:
    viewport = McaViewport(scale=1.37, offset_x=11.25, offset_y=-7.5)
    first = viewport.region_rect((0, 0))
    second = viewport.region_rect((1, 0))
    assert first[0] + first[2] == second[0]

    negative = viewport.region_rect((-1, 0))
    assert negative[0] + negative[2] == first[0]


def test_zoom_about_preserves_world_point_under_pointer_and_clamps() -> None:
    viewport = McaViewport(scale=2.0, offset_x=10.0, offset_y=-15.0)
    before = viewport.screen_to_world(210.0, 85.0)

    target = viewport.zoom_about(3.0, 210.0, 85.0)
    viewport.apply(target)

    assert viewport.screen_to_world(210.0, 85.0) == before
    assert viewport.zoom_about(10_000, 0, 0).scale == MAX_SCALE
    assert viewport.zoom_about(0.00001, 0, 0).scale == MIN_SCALE


def test_fit_centers_complete_region_extents() -> None:
    viewport = McaViewport()
    target = viewport.fit([(-1, -1), (0, 0)], 800, 600, padding=0.8)
    viewport.apply(target)

    left, top, _, _ = viewport.region_rect((-1, -1))
    right_x, bottom_y, size, _ = viewport.region_rect((0, 0))
    right = right_x + size
    bottom = bottom_y + size

    assert abs((left + right) / 2.0 - 400.0) < 1e-9
    assert abs((top + bottom) / 2.0 - 300.0) < 1e-9


def test_focus_chunk_and_target_interpolation() -> None:
    viewport = McaViewport()
    target = viewport.focus_chunk((32, -1), 1000, 600)

    assert target.scale >= 20.0
    viewport.apply(target)
    assert viewport.chunk_at_screen(500, 300, {(1, -1)}) == (32, -1)

    midpoint = ViewportTarget(1, 0, 0).interpolate(
        ViewportTarget(3, 20, -10),
        0.5,
    )
    assert midpoint == ViewportTarget(2, 10, -5)


def test_visible_region_bounds_expand_with_margin() -> None:
    viewport = McaViewport(scale=1.0, offset_x=0.0, offset_y=0.0)

    min_x, max_x, min_z, max_z = viewport.visible_region_bounds(100, 80)

    assert min_x <= -1
    assert min_z <= -1
    assert max_x >= 3
    assert max_z >= 2


def test_block_projection_round_trips_across_negative_regions() -> None:
    viewport = McaViewport(scale=1.75, offset_x=220.0, offset_y=-90.0)

    for block in [(-1025, -1), (-512, 0), (-1, -513), (0, 0), (511, 511), (512, 9)]:
        screen = viewport.block_to_screen(*block)
        assert viewport.screen_to_block(*screen) == block


def test_screen_to_block_crosses_region_boundary_without_a_gap() -> None:
    viewport = McaViewport()

    # Region 0 ends at map pixel 32 and region 1 starts at the same edge.
    assert viewport.world_to_block(33.0, 4.0) == (528, 64)
    assert viewport.screen_to_block(33.0, 4.0) == (528, 64)


def test_nearest_block_follows_the_contiguous_region_projection() -> None:
    viewport = McaViewport()

    assert viewport.nearest_block_at_screen(32.25, 4.0) == (516, 64)
    assert viewport.nearest_block_at_screen(33.75, 4.0) == (540, 64)


def test_map_view_center_uses_contiguous_block_projection() -> None:
    service = RegionMapService(ExecutionRuntime())
    view = McaMapView(map_service=service, width=640, height=360)
    view._viewport.offset_x = 320.0 - 33.75
    view._viewport.offset_y = 180.0 - 4.0

    assert view.get_center_block() == (540, 64)
    service.close()


def test_map_view_selects_marker_from_external_list_action() -> None:
    service = RegionMapService(ExecutionRuntime())
    view = McaMapView(map_service=service)
    view.set_markers(
        [
            MapMarker(
                id="home",
                name="Home",
                x=0,
                y=64,
                z=0,
                dimension_id="overworld",
            )
        ]
    )

    view.select_marker("home")

    assert view._marker_layer.selected_id == "home"
    service.close()


def test_map_view_rebuild_consumes_core_viewport() -> None:
    service = RegionMapService(ExecutionRuntime())
    service._mca_data.update({(-1, 0): 1024, (0, 0): 2048})
    view = McaMapView(map_service=service, width=640, height=360)
    view._use_topview = False

    view._rebuild_canvas()

    assert view._viewport.is_default is False
    assert set(view._cell_bounds) == {(-1, 0), (0, 0)}
    assert view._region_at_screen(*view._viewport.world_to_screen(1, 1)) == (0, 0)
    service.close()


def test_map_view_unmount_releases_only_its_own_tile_callback() -> None:
    service = RegionMapService(ExecutionRuntime())
    first = McaMapView(map_service=service)
    second = McaMapView(map_service=service)
    first.did_mount()
    second.did_mount()

    first.will_unmount()
    assert service._tile_ready_callback is second._tile_ready_callback

    second.will_unmount()
    assert service._tile_ready_callback is None
    service.close()


def test_map_view_sparse_remote_regions_use_complete_canvas_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = RegionMapService(ExecutionRuntime())
    service._mca_data.update({(-14, -19): 1024, (195, 195): 2048})
    view = McaMapView(map_service=service, width=1760, height=1050)
    view._use_topview = False
    rendered_shapes: list[cv.Shape] = []

    def capture_shapes(shapes: list[cv.Shape]) -> None:
        rendered_shapes.extend(shapes)

    monkeypatch.setattr(view, "_apply_shapes", capture_shapes)

    view._rebuild_canvas()

    assert view._scale < 0.2
    assert view._surface_enabled is False
    assert view._surface_layer.covers_viewport is False
    assert view._visible_regions == {(-14, -19), (195, 195)}
    assert set(view._cell_bounds) == {(-14, -19), (195, 195)}
    assert len(rendered_shapes) > len(view._empty_shapes())

    view._scale = 1.0
    view.fit_to_view()
    assert view._scale < 0.2
    view.dispose()
    service.close()


def test_map_view_falls_back_to_canvas_when_surface_becomes_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = RegionMapService(ExecutionRuntime())
    service._mca_data[(0, 0)] = 2048
    view = McaMapView(map_service=service, width=640, height=360)
    view._use_topview = False
    rendered_shapes: list[cv.Shape] = []

    def capture_shapes(shapes: list[cv.Shape]) -> None:
        rendered_shapes.extend(shapes)

    monkeypatch.setattr(view, "_apply_shapes", capture_shapes)

    view._rebuild_canvas()

    assert view._surface_enabled is False
    assert view._surface_layer.enabled is True
    assert set(view._cell_bounds) == {(0, 0)}
    assert len(rendered_shapes) > len(view._empty_shapes())

    rendered_shapes.clear()
    view._surface_layer._disable_after_upload_failure(TimeoutError())
    view._rebuild_canvas()

    assert view._surface_enabled is False
    assert view._surface_layer.enabled is False
    assert set(view._cell_bounds) == {(0, 0)}
    assert len(rendered_shapes) > len(view._empty_shapes())
    view.dispose()
    service.close()


def test_map_view_dispose_unregisters_tile_source_cache() -> None:
    runtime = ExecutionRuntime()
    registry = CacheRegistry(budget_bytes=32 * 1024 * 1024)
    service = RegionMapService(runtime)
    view = McaMapView(map_service=service, cache_registry=registry)

    assert any(
        item.name.startswith(TileSourceCache.CACHE_NAME_PREFIX)
        for item in registry.stats().regions
    )

    view.dispose()
    view.dispose()

    assert registry.stats().regions == ()
    service.close()
    runtime.shutdown()


def test_map_view_constructor_failure_releases_tile_source_registration(
    monkeypatch,
) -> None:
    runtime = ExecutionRuntime()
    registry = CacheRegistry(budget_bytes=32 * 1024 * 1024)
    service = RegionMapService(runtime)

    def fail_interaction_state(_view) -> None:
        raise RuntimeError("interaction setup failed")

    monkeypatch.setattr(McaMapView, "_init_interaction_state", fail_interaction_state)
    try:
        with pytest.raises(RuntimeError, match="interaction setup failed"):
            McaMapView(map_service=service, cache_registry=registry)
        assert registry.stats().regions == ()
    finally:
        service.close()
        runtime.shutdown()
        registry.close()


def test_map_view_remount_rebuilds_after_detached_resize() -> None:
    runtime = ExecutionRuntime()
    service = RegionMapService(runtime)
    view = McaMapView(map_service=service)
    view._mounted = True
    view._needs_initial_draw = False
    view._surface_layer._dirty = False
    surface_token = view._surface_layer._token

    view.will_unmount()
    view.resize_map(1200, 700)

    assert view._mounted is False
    assert view._needs_initial_draw is True
    assert view._surface_layer._dirty is True
    assert view._surface_layer._token == surface_token + 1

    rebuilds = []
    setattr(view, "_request_rebuild", lambda: rebuilds.append("rebuild"))
    view.did_mount()

    assert view._mounted is True
    assert rebuilds == ["rebuild"]
    view.dispose()
    service.close()
    runtime.shutdown()
