import asyncio
import threading
from pathlib import Path

import pytest

from app.services import mca_cache_adapter
from app.services.cache_registry import CacheRegistry
from app.services.region_map import topview as region_map_topview
from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    LaneLimits,
)
from app.services.region_map import RegionMapService
from core.mca.surface import (
    CHUNK_DECODE_CACHE_MAX_BYTES,
    CHUNK_DECODE_CACHE_MAX_ENTRIES,
)


def test_region_map_services_do_not_share_mutable_state() -> None:
    first = RegionMapService(ExecutionRuntime())
    second = RegionMapService(ExecutionRuntime())
    first._mca_data[(1, 2)] = 123

    assert first is not second
    assert first.get_all_data() == {(1, 2): 123}
    assert second.get_all_data() == {}

    first.close()
    second.close()


def test_region_map_service_instances_are_fresh() -> None:
    first = RegionMapService(ExecutionRuntime())
    second = RegionMapService(ExecutionRuntime())

    assert first is not second

    first.close()
    second.close()


def test_topview_outer_pool_is_bounded_for_nested_decode_work() -> None:
    service = RegionMapService(ExecutionRuntime())

    assert 1 <= service._topview_max_workers <= 2

    service.close()


def test_topview_queue_is_bounded_for_large_worlds() -> None:
    service = RegionMapService(ExecutionRuntime())
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
    service = RegionMapService(ExecutionRuntime())
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
    service = RegionMapService(ExecutionRuntime())
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
    service = RegionMapService(ExecutionRuntime())
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
    service = RegionMapService(ExecutionRuntime())
    service._topview_active = service._topview_max_workers
    coord = (0, 0)
    service._region_paths[coord] = "r.0.0.mca"

    service.request_topview_tiles([coord], tile_size=1000)

    assert list(service._topview_queue)[0][2] == 512
    assert service._topview_pending_sizes[coord] == 512
    service.close()


def test_cancelled_topview_worker_does_not_scan_failure_signature(monkeypatch) -> None:
    service = RegionMapService(ExecutionRuntime())
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


def test_topview_cache_hit_miss_and_stale_discard_are_measurable() -> None:
    runtime = ExecutionRuntime()
    service = RegionMapService(runtime)
    try:
        assert service.get_topview_tile((0, 0)) is None
        service._topview_tiles[(0, 0)] = b"\x89PNG"
        service._topview_memory_bytes = 4
        assert service.get_topview_tile((0, 0)) == b"\x89PNG"
        stats = service._topview_cache_stats()
        assert stats.hits >= 1
        assert stats.misses >= 1
        # Drop a queued job from a previous generation.
        service._topview_generation = 1
        service._topview_queue.append(
            ((1, 1), "r.1.1.mca", 32, 0, threading.Event(), 0)
        )
        service._pump_topview_queue()
        assert service.get_stale_callback_discards() >= 1
    finally:
        service.close()
        runtime.shutdown(wait=False)


def test_topview_cache_enforces_registered_entry_budget() -> None:
    runtime = ExecutionRuntime()
    service = RegionMapService(runtime)
    service.TOPVIEW_CACHE_ENTRY_LIMIT = 2
    try:
        with service._data_lock:
            for coord in ((0, 0), (1, 0), (2, 0)):
                service._store_topview_tile_locked(
                    coord,
                    b"png",
                    32,
                    True,
                    1,
                    3,
                    "source",
                )

        stats = service._topview_cache_stats()
        assert tuple(service._topview_tiles) == ((1, 0), (2, 0))
        assert stats.entries == 2
        assert stats.max_entries == 2
        assert stats.evictions == 1
    finally:
        service.close()
        runtime.shutdown(wait=False)


def test_topview_tile_invalidates_when_region_source_changes(tmp_path) -> None:
    runtime = ExecutionRuntime()
    service = RegionMapService(runtime)
    service.TOPVIEW_SOURCE_CHECK_INTERVAL_SECONDS = 0.0
    invalidated = threading.Event()
    region_path = tmp_path / "r.0.0.mca"
    region_path.write_bytes(b"initial")
    coord = (0, 0)
    service._region_paths[coord] = str(region_path)
    source_stat = region_path.stat()
    with service._data_lock:
        service._store_topview_tile_locked(
            coord,
            b"cached-png",
            32,
            True,
            source_stat.st_mtime_ns,
            source_stat.st_size,
            "",
        )
    service.set_tile_ready_callback(lambda _coord: invalidated.set())

    try:
        region_path.write_bytes(b"changed-source")
        assert service.has_topview_tile(coord, min_size=32) is True
        assert invalidated.wait(1)
        assert service.has_topview_tile(coord, min_size=32) is False
        assert service.get_topview_tile(coord) is None
        assert service.get_topview_tile_size(coord) == 0
    finally:
        service.close()
        runtime.shutdown(wait=False)


def test_topview_source_stat_runs_without_holding_data_lock(
    tmp_path,
    monkeypatch,
) -> None:
    runtime = ExecutionRuntime()
    service = RegionMapService(runtime)
    region_path = tmp_path / "r.0.0.mca"
    region_path.write_bytes(b"region")
    coord = (0, 0)
    service._region_paths[coord] = str(region_path)
    source_stat = region_path.stat()
    with service._data_lock:
        service._store_topview_tile_locked(
            coord,
            b"cached-png",
            32,
            True,
            source_stat.st_mtime_ns,
            source_stat.st_size,
            "",
        )
    original_stat = type(region_path).stat
    lock_was_available = []
    stat_threads = []
    stat_checked = threading.Event()
    caller_thread = threading.get_ident()

    def checked_stat(path, *args, **kwargs):
        if path == region_path:
            acquired = service._data_lock.acquire(blocking=False)
            lock_was_available.append(acquired)
            stat_threads.append(threading.get_ident())
            if acquired:
                service._data_lock.release()
            stat_checked.set()
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(type(region_path), "stat", checked_stat)
    try:
        assert service.get_topview_tile(coord) == b"cached-png"
        assert stat_checked.wait(1)
        assert lock_was_available
        assert all(lock_was_available)
        assert all(thread_id != caller_thread for thread_id in stat_threads)
    finally:
        service.close()
        runtime.shutdown(wait=False)


def test_topview_tile_invalidates_when_external_signature_changes(
    tmp_path,
    monkeypatch,
) -> None:
    runtime = ExecutionRuntime()
    service = RegionMapService(runtime)
    service.TOPVIEW_SOURCE_CHECK_INTERVAL_SECONDS = 0.0
    region_path = tmp_path / "r.0.0.mca"
    external_path = tmp_path / "c.0.0.mcc"
    region_path.write_bytes(b"region")
    external_path.write_bytes(b"external")
    coord = (0, 0)
    service._region_paths[coord] = str(region_path)

    def external_signature(*_args, **_kwargs):
        stats = external_path.stat()
        return f"{stats.st_mtime_ns}:{stats.st_size}"

    monkeypatch.setattr(
        service,
        "_topview_source_signature",
        external_signature,
    )
    source_stat = region_path.stat()
    with service._data_lock:
        service._store_topview_tile_locked(
            coord,
            b"cached-png",
            32,
            True,
            source_stat.st_mtime_ns,
            source_stat.st_size,
            external_signature(),
        )
    invalidated = threading.Event()
    service.set_tile_ready_callback(lambda _coord: invalidated.set())

    try:
        external_path.write_bytes(b"changed-external-stream")
        assert service.has_topview_tile(coord, min_size=32) is True
        assert invalidated.wait(1)
        assert service.has_topview_tile(coord, min_size=32) is False
    finally:
        service.close()
        runtime.shutdown(wait=False)


def test_cancelled_queued_topview_job_releases_local_worker_slot() -> None:
    limits = LaneLimits(max_workers=1, queue_capacity=2)
    runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
    blocker_started = threading.Event()
    release_blocker = threading.Event()

    def block_cpu(_token):
        blocker_started.set()
        if not release_blocker.wait(2):
            raise RuntimeError("测试阻塞任务等待超时")

    blocker = runtime.submit("block_cpu", block_cpu, lane=ExecutionLane.CPU)
    assert blocker_started.wait(1)
    service = RegionMapService(runtime)
    coord = (0, 0)
    service._region_paths[coord] = "r.0.0.mca"

    try:
        assert service.request_topview_tiles([coord]) == {coord}
        handle = next(iter(service._topview_handles))
        assert service._topview_active == 1
        assert service.request_topview_tiles([coord], tile_size=64) == {coord}
        assert service._topview_upgrade_sizes[coord] == 64

        assert handle.cancel() is True

        assert service._topview_active == 0
        assert coord not in service._topview_pending
        assert coord not in service._topview_upgrade_sizes
        assert service._topview_handles == set()
    finally:
        service.close()
        release_blocker.set()
        blocker.result(timeout=2)
        runtime.shutdown(wait=False)


def test_process_mca_cache_is_owned_by_application_registry(monkeypatch) -> None:
    clears = []
    monkeypatch.setattr(
        mca_cache_adapter,
        "clear_chunk_decode_cache",
        lambda: clears.append("clear"),
    )
    registry = CacheRegistry()
    mca_cache_adapter.register_mca_chunk_cache(registry)
    runtime = ExecutionRuntime()
    first = RegionMapService(runtime, registry)
    second = RegionMapService(runtime, registry)

    try:
        first.clear_data()
        first.close()
        second.close()
        assert clears == []
        assert "mca.chunk" in {
            region.name for region in registry.stats().regions
        }
        mca_stats = next(
            region
            for region in registry.stats().regions
            if region.name == "mca.chunk"
        )
        assert mca_stats.max_entries == CHUNK_DECODE_CACHE_MAX_ENTRIES
        assert mca_stats.max_bytes == CHUNK_DECODE_CACHE_MAX_BYTES

        registry.close()
        assert clears == ["clear"]
    finally:
        first.close()
        second.close()
        registry.close()
        runtime.shutdown(wait=False)


def test_process_mca_cache_registers_world_scoped_invalidation(
    monkeypatch,
    tmp_path,
) -> None:
    invalidated = []
    monkeypatch.setattr(
        mca_cache_adapter,
        "invalidate_chunk_decode_cache_for_world",
        lambda world: invalidated.append(world),
    )
    registry = CacheRegistry()
    mca_cache_adapter.register_mca_chunk_cache(registry)
    world = tmp_path / "world"

    try:
        assert registry.invalidate_world(world) == 1
        assert [Path(value) for value in invalidated] == [world.resolve()]
    finally:
        registry.close()


def test_process_mca_cache_clears_after_last_registry_owner(monkeypatch) -> None:
    clears = []
    monkeypatch.setattr(
        mca_cache_adapter,
        "clear_chunk_decode_cache",
        lambda: clears.append("clear"),
    )
    first = CacheRegistry()
    second = CacheRegistry()
    mca_cache_adapter.register_mca_chunk_cache(first)
    mca_cache_adapter.register_mca_chunk_cache(second)

    first.close()
    assert clears == []

    second.close()
    assert clears == ["clear"]


def test_close_releases_executor_and_rejects_new_scan(tmp_path) -> None:
    runtime = ExecutionRuntime()
    service = RegionMapService(runtime)
    executor = service._ensure_topview_executor()
    assert executor is runtime

    service.close()
    service.close()

    assert service._closed is True
    assert service._topview_executor is None
    # Shared runtime stays open; composition root owns shutdown.
    assert runtime.is_closed is False
    with pytest.raises(RuntimeError, match="已关闭"):
        asyncio.run(service.start_silent_scan(str(tmp_path)))
    runtime.shutdown(wait=False)


def test_old_worker_does_not_remove_new_generation_pending_marker() -> None:
    service = RegionMapService(ExecutionRuntime())
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
    service = RegionMapService(ExecutionRuntime())
    coord = (0, 0)
    generation = service.get_topview_generation()
    callbacks = []
    service.set_tile_ready_callback(callbacks.append)
    monkeypatch.setattr(
        region_map_topview,
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
