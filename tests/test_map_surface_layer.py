import asyncio
from typing import Any, Coroutine, Optional, cast

from app.controllers.topview_tile_requests import TopviewTileRequestCoordinator
from app.services.region_map_service import RegionMapService
from app.ui.utils import ScheduledTask
from app.ui.views.explorer.map.map_surface_layer import MapSurfaceLayer
from core.mca.viewport import McaViewport


class _ImageSink:
    def __init__(self) -> None:
        self.frames: list[tuple[int, int, bytes]] = []

    async def render_rgba(
        self,
        width: int,
        height: int,
        pixels: bytes,
        *,
        premultiplied: bool,
    ) -> None:
        assert premultiplied is True
        self.frames.append((width, height, pixels))


def test_surface_leaf_lod_only_activates_at_high_zoom() -> None:
    service = RegionMapService()
    layer = MapSurfaceLayer(
        service,
        execution_runtime=service._execution_runtime,
        schedule_task=lambda _coro: None,
        request_rebuild=lambda: None,
        is_active=lambda: False,
        background_color="#162016",
    )

    assert layer._pixels_per_region(4.0) == 256
    assert layer._pixels_per_region(7.99) == 256
    assert layer._pixels_per_region(8.0) == 512
    assert layer._pixels_per_region(100.0) == 512
    service.close()


def test_leaf_surface_accepts_256_parent_until_focus_tile_is_ready() -> None:
    service = RegionMapService()
    coord = (0, 0)
    service._topview_tiles[coord] = b"parent"
    service._topview_tile_sizes[coord] = 256
    layer = MapSurfaceLayer(
        service,
        execution_runtime=service._execution_runtime,
        schedule_task=lambda _coro: None,
        request_rebuild=lambda: None,
        is_active=lambda: False,
        background_color="#162016",
    )
    from app.ui.views.explorer.map.surface_renderer import MapSurfaceSpec

    spec = MapSurfaceSpec(0, 0, 0, 0, pixels_per_region=512)

    assert layer._missing_tiles({coord: 1}, spec) == []
    service.close()


def test_wide_view_reduces_surface_lod_without_cropping() -> None:
    service = RegionMapService()
    layer = MapSurfaceLayer(
        service,
        execution_runtime=service._execution_runtime,
        schedule_task=lambda _coro: None,
        request_rebuild=lambda: None,
        is_active=lambda: False,
        background_color="#162016",
    )
    viewport = McaViewport(scale=8.0)

    layer.sync(
        viewport,
        width=3840,
        height=2160,
        data={(0, 0): 1},
        display_mode="topview",
        use_topview=True,
        color_for_region=lambda _coord, _size: "#4CAF50",
    )

    assert layer._request_spec is not None
    assert layer._request_spec.pixels_per_region == 128
    visible_bounds = viewport.visible_region_bounds(3840, 2160, margin=0.0)
    assert layer._contains(layer._request_spec, visible_bounds)

    layer.sync(
        viewport,
        width=7680,
        height=4320,
        data={(0, 0): 1},
        display_mode="topview",
        use_topview=True,
        color_for_region=lambda _coord, _size: "#4CAF50",
    )
    assert layer._request_spec is not None
    assert layer._request_spec.pixels_per_region == 64
    ultra_wide_bounds = viewport.visible_region_bounds(7680, 4320, margin=0.0)
    assert layer._contains(layer._request_spec, ultra_wide_bounds)
    service.close()


def test_surface_layer_reuses_uploaded_frame_for_small_camera_pan() -> None:
    async def scenario() -> None:
        service = RegionMapService()
        service._mca_data[(0, 0)] = 1
        service._mark_data_dirty()
        active = True

        def schedule(
            coro: Coroutine[Any, Any, Any],
        ) -> Optional[ScheduledTask]:
            return asyncio.create_task(coro)

        layer = MapSurfaceLayer(
            service,
            execution_runtime=service._execution_runtime,
            schedule_task=schedule,
            request_rebuild=lambda: None,
            is_active=lambda: active,
            background_color="#162016",
        )
        sink = _ImageSink()
        layer.image = sink
        viewport = McaViewport(scale=1.0, offset_x=120.0, offset_y=90.0)

        missing = layer.sync(
            viewport,
            width=640,
            height=360,
            data=service.get_all_data(),
            display_mode="topview",
            use_topview=True,
            color_for_region=lambda _coord, _size: "#4CAF50",
        )
        assert missing == [(0, 0)]
        task = layer._task
        assert task is not None
        await cast(asyncio.Future[Any], task)
        assert len(sink.frames) == 1

        viewport.pan(8.0, -5.0)
        missing_after_reuse = layer.sync(
            viewport,
            width=640,
            height=360,
            data=service.get_all_data(),
            display_mode="topview",
            use_topview=True,
            color_for_region=lambda _coord, _size: "#4CAF50",
        )

        assert len(sink.frames) == 1
        assert missing_after_reuse == [(0, 0)]
        assert layer.control is not None
        assert layer.control.left is not None
        service.close()

    asyncio.run(scenario())


def test_surface_layer_ignores_tile_callbacks_outside_buffer() -> None:
    service = RegionMapService()
    layer = MapSurfaceLayer(
        service,
        execution_runtime=service._execution_runtime,
        schedule_task=lambda _coro: None,
        request_rebuild=lambda: None,
        is_active=lambda: False,
        background_color="#162016",
    )
    viewport = McaViewport()
    data = {(0, 0): 1}

    layer.sync(
        viewport,
        width=320,
        height=200,
        data=data,
        display_mode="topview",
        use_topview=True,
        color_for_region=lambda _coord, _size: "#4CAF50",
    )

    assert layer.mark_tile_ready((100, 100)) is False
    assert layer.mark_tile_ready((0, 0)) is True
    service.close()


def test_visible_request_ledger_retries_tiles_rejected_by_full_queue() -> None:
    service = RegionMapService()
    service._topview_active = service._topview_max_workers
    queued_count = service.TOPVIEW_QUEUE_LIMIT - service._topview_active
    queued_coords = [(index, 0) for index in range(queued_count)]
    visible_coords = [(1000 + index, 0) for index in range(80)]
    service._region_paths = {
        coord: f"r.{coord[0]}.{coord[1]}.mca"
        for coord in [*queued_coords, *visible_coords]
    }
    service.request_topview_tiles(queued_coords, tile_size=32)
    coordinator = TopviewTileRequestCoordinator(service)

    coordinator.request_visible(
        visible_coords,
        visible_regions=visible_coords,
        scale=1.0,
        center=visible_coords[0],
    )

    assert coordinator.requested_sizes == {}
    assert coordinator.has_deferred_requests is True
    assert coordinator.on_tile_ready(queued_coords[0]) is True

    released_job = service._topview_queue.popleft()
    service._topview_pending.pop(released_job[0], None)
    service._topview_pending_sizes.pop(released_job[0], None)
    coordinator.request_visible(
        visible_coords,
        visible_regions=visible_coords,
        scale=1.0,
        center=visible_coords[0],
    )

    assert len(coordinator.requested_sizes) == 1
    accepted_coord = next(iter(coordinator.requested_sizes))
    assert service.is_topview_tile_pending(accepted_coord, min_size=16)
    service.close()
