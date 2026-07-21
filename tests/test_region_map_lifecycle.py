import asyncio

import pytest

from app.services import region_map_service as region_map_module
from app.services.region_map_service import RegionMapService


def test_region_map_services_do_not_share_mutable_state() -> None:
    first = RegionMapService()
    second = RegionMapService()
    first._mca_data[(1, 2)] = 123

    assert first is not second
    assert first.get_all_data() == {(1, 2): 123}
    assert second.get_all_data() == {}

    first.close()
    second.close()


def test_region_map_service_instances_are_fresh() -> None:
    first = RegionMapService()
    second = RegionMapService()

    assert first is not second

    first.close()
    second.close()


def test_topview_outer_pool_is_bounded_for_nested_decode_work() -> None:
    service = RegionMapService()

    assert 1 <= service._topview_max_workers <= 2

    service.close()


def test_topview_queue_is_bounded_for_large_worlds() -> None:
    service = RegionMapService()
    service._topview_active = service._topview_max_workers
    service._region_paths = {
        (index, 0): f"r.{index}.0.mca" for index in range(256)
    }

    service.request_topview_tiles([(index, 0) for index in range(256)])

    total = len(service._topview_queue) + service._topview_active
    assert total == service.TOPVIEW_QUEUE_LIMIT
    assert len(service._topview_pending) == len(service._topview_queue)

    service.request_topview_tiles([(64, 0)], force=True, priority=True)

    assert list(service._topview_queue)[0][0] == (64, 0)
    assert len(service._topview_pending) == len(service._topview_queue)
    assert len(service._topview_queue) + service._topview_active == total

    service._topview_failed_sizes[(200, 0)] = 32
    service._topview_failed_mtimes[(200, 0)] = 0
    before = list(service._topview_queue)
    service.request_topview_tiles([(200, 0)], priority=True)

    assert list(service._topview_queue) == before

    service.close()


def test_full_topview_queue_reports_only_retained_requests() -> None:
    service = RegionMapService()
    service._topview_active = service._topview_max_workers
    coords = [(index, 0) for index in range(service.TOPVIEW_QUEUE_LIMIT + 8)]
    service._region_paths = {
        coord: f"r.{coord[0]}.{coord[1]}.mca" for coord in coords
    }

    accepted = service.request_topview_tiles(coords, tile_size=32)

    queued_coords = {job[0] for job in service._topview_queue}
    assert accepted == queued_coords
    assert len(accepted) == service.TOPVIEW_QUEUE_LIMIT - service._topview_active
    rejected = coords[-1]
    assert rejected not in accepted
    assert service.is_topview_tile_pending(rejected, min_size=32) is False
    service.close()


def test_priority_eviction_removes_dropped_request_from_pending_state() -> None:
    service = RegionMapService()
    service._topview_active = service._topview_max_workers
    queued_count = service.TOPVIEW_QUEUE_LIMIT - service._topview_active
    normal_coords = [(index, 0) for index in range(queued_count)]
    priority_coord = (queued_count, 0)
    all_coords = [*normal_coords, priority_coord]
    service._region_paths = {
        coord: f"r.{coord[0]}.{coord[1]}.mca" for coord in all_coords
    }
    service.request_topview_tiles(normal_coords, tile_size=32)
    dropped_coord = normal_coords[-1]

    accepted = service.request_topview_tiles(
        [priority_coord],
        tile_size=64,
        priority=True,
    )

    assert accepted == {priority_coord}
    assert service.is_topview_tile_pending(priority_coord, min_size=64) is True
    assert service.is_topview_tile_pending(dropped_coord, min_size=32) is False
    service.close()


def test_detail_request_upgrades_a_queued_preview() -> None:
    service = RegionMapService()
    service._topview_active = service._topview_max_workers
    coord = (0, 0)
    service._region_paths[coord] = "r.0.0.mca"

    service.request_topview_tiles([coord], tile_size=32)
    service.request_topview_tiles([coord], tile_size=64, priority=True)

    assert list(service._topview_queue)[0][0] == coord
    assert list(service._topview_queue)[0][2] == 64
    assert service._topview_pending_sizes[coord] == 64
    service.close()


def test_topview_request_clamps_renderer_size() -> None:
    service = RegionMapService()
    service._topview_active = service._topview_max_workers
    coord = (0, 0)
    service._region_paths[coord] = "r.0.0.mca"

    service.request_topview_tiles([coord], tile_size=1000)

    assert list(service._topview_queue)[0][2] == 512
    assert service._topview_pending_sizes[coord] == 512
    service.close()


def test_cancelled_topview_worker_does_not_scan_failure_signature(monkeypatch) -> None:
    service = RegionMapService()
    coord = (0, 0)
    generation = service.get_topview_generation()
    cancelled = service._topview_cancel_event
    cancelled.set()
    calls = []
    monkeypatch.setattr(
        service,
        "_topview_source_signature",
        lambda *args, **kwargs: calls.append(args) or "signature",
    )

    service._topview_pending[coord] = generation
    service._topview_active = 1
    service._render_topview_worker(
        coord,
        "r.0.0.mca",
        32,
        generation,
        cancelled,
        0,
    )

    assert calls == []
    service.close()


def test_failure_signature_includes_mca_size() -> None:
    first = RegionMapService._topview_source_signature(
        "not-a-region.mca",
        (0, 0),
        10,
        100,
    )
    second = RegionMapService._topview_source_signature(
        "not-a-region.mca",
        (0, 0),
        10,
        101,
    )

    assert first != second


def test_close_releases_executor_and_rejects_new_scan(tmp_path) -> None:
    service = RegionMapService()
    executor = service._ensure_topview_executor()

    service.close()
    service.close()

    assert service._closed is True
    assert service._topview_executor is None
    assert executor.is_closed is True
    with pytest.raises(RuntimeError, match="已关闭"):
        asyncio.run(service.start_silent_scan(str(tmp_path)))


def test_old_worker_does_not_remove_new_generation_pending_marker() -> None:
    service = RegionMapService()
    coord = (3, 4)
    old_generation = service.get_topview_generation()
    service._topview_pending[coord] = old_generation + 1
    service._topview_active = 1
    cancelled = service._topview_cancel_event
    cancelled.set()

    service._render_topview_worker(
        coord,
        "old-world.mca",
        32,
        old_generation,
        cancelled,
        0,
    )

    assert service._topview_pending[coord] == old_generation + 1
    assert service._topview_active == 0
    service.close()


def test_failed_tile_retries_once_then_stops_rebuild_loop(
    tmp_path,
    monkeypatch,
) -> None:
    region_path = tmp_path / "r.0.0.mca"
    region_path.write_bytes(b"placeholder")
    service = RegionMapService()
    coord = (0, 0)
    generation = service.get_topview_generation()
    callbacks = []
    service.set_tile_ready_callback(callbacks.append)
    monkeypatch.setattr(
        region_map_module,
        "render_region_topview",
        lambda *_args, **_kwargs: None,
    )

    for _ in range(service.TOPVIEW_FAILURE_LIMIT):
        service._topview_pending[coord] = generation
        service._topview_active = 1
        service._render_topview_worker(
            coord,
            str(region_path),
            32,
            generation,
            service._topview_cancel_event,
            region_path.stat().st_mtime_ns,
        )

    assert callbacks == [coord, coord]
    assert service._topview_failed_sizes[coord] == 32

    service._region_paths[coord] = str(region_path)
    service.request_topview_tiles([coord], force=True, priority=True)
    assert list(service._topview_queue) == []
    assert coord not in service._topview_pending
    service.close()
