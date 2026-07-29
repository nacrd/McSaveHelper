"""Map marker background persistence and stale-callback tests."""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, cast

import pytest

from app.controllers.map_controller import MapController
from app.services.execution_runtime import (
    ExecutionRuntime,
    LaneLimits,
    OperationCancelledError,
    OperationScope,
)
from app.services.map_marker_service import MapMarkerService
from app.ui.views.explorer.explorer_view import ExplorerView
from core.mca.map_models import MapMarker


class _UiQueue:
    """Capture controller UI deliveries for deterministic draining."""

    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []
        self.posted = threading.Event()

    def post(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)
        self.posted.set()

    def wait_for_post(self) -> None:
        assert self.posted.wait(2)
        self.posted.clear()

    def drain(self) -> None:
        callbacks = tuple(self.callbacks)
        self.callbacks.clear()
        for callback in callbacks:
            callback()


def _dimensions(tmp_path: Path) -> list[dict[str, object]]:
    return [
        {"id": "overworld", "name": "主世界", "region_dir": tmp_path},
        {"id": "nether", "name": "下界", "region_dir": tmp_path},
    ]


def _runtime() -> ExecutionRuntime:
    limits = LaneLimits(max_workers=2, queue_capacity=8)
    return ExecutionRuntime(io_limits=limits, cpu_limits=limits)


def _marker(marker_id: str, dimension_id: str = "overworld") -> MapMarker:
    return MapMarker(
        id=marker_id,
        name=marker_id,
        x=1,
        y=64,
        z=2,
        dimension_id=dimension_id,
    )


def _controller(
    runtime: ExecutionRuntime,
    service: MapMarkerService,
    ui_queue: _UiQueue,
    host_generation: list[int],
) -> tuple[MapController, OperationScope]:
    scope = runtime.create_scope("marker_test")
    controller = MapController(
        service,
        task_scope=scope,
        post_to_ui=ui_queue.post,
        get_generation=lambda: host_generation[0],
    )
    return controller, scope


def test_load_queued_callback_is_dropped_after_host_generation_changes(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    service = MapMarkerService(tmp_path / "markers")
    world = tmp_path / "world"
    world.mkdir()
    service.upsert(world, _marker("home"))
    ui_queue = _UiQueue()
    host_generation = [1]
    controller, _scope = _controller(
        runtime,
        service,
        ui_queue,
        host_generation,
    )
    completed: list[str] = []

    try:
        controller.bind_world(world, _dimensions(tmp_path))
        handle = controller.submit_load_markers(
            lambda: completed.append("load"),
            lambda error: completed.append(str(error)),
        )
        handle.result(timeout=2)
        ui_queue.wait_for_post()

        host_generation[0] += 1
        ui_queue.drain()

        assert controller.markers() == []
        assert completed == []
    finally:
        controller.close()
        runtime.shutdown(wait=True)


def test_add_queued_callback_does_not_mutate_new_world(tmp_path: Path) -> None:
    runtime = _runtime()
    service = MapMarkerService(tmp_path / "markers")
    old_world = tmp_path / "old"
    new_world = tmp_path / "new"
    old_world.mkdir()
    new_world.mkdir()
    ui_queue = _UiQueue()
    controller, _scope = _controller(runtime, service, ui_queue, [1])
    completed: list[MapMarker] = []

    try:
        controller.bind_world(old_world, _dimensions(tmp_path))
        handle = controller.submit_upsert_marker(
            "基地",
            10,
            20,
            on_complete=completed.append,
            on_error=lambda error: pytest.fail(str(error)),
        )
        handle.result(timeout=2)
        ui_queue.wait_for_post()

        controller.bind_world(new_world, _dimensions(tmp_path))
        ui_queue.drain()

        assert controller.markers() == []
        assert completed == []
        assert [item.name for item in service.list(old_world)] == ["基地"]
        assert service.list(new_world) == []
    finally:
        controller.close()
        runtime.shutdown(wait=True)


def test_delete_queued_callback_does_not_touch_new_dimension(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    service = MapMarkerService(tmp_path / "markers")
    world = tmp_path / "world"
    world.mkdir()
    ui_queue = _UiQueue()
    controller, _scope = _controller(runtime, service, ui_queue, [1])
    completed: list[bool] = []

    try:
        controller.bind_world(world, _dimensions(tmp_path))
        marker = controller.upsert_marker("基地", 10, 20)
        handle = controller.submit_delete_marker(
            marker.id,
            on_complete=completed.append,
            on_error=lambda error: pytest.fail(str(error)),
        )
        handle.result(timeout=2)
        ui_queue.wait_for_post()

        controller.switch_dimension("nether")
        ui_queue.drain()

        assert controller.markers() == []
        assert completed == []
        assert service.list(world) == []
    finally:
        controller.close()
        runtime.shutdown(wait=True)


def test_successful_add_and_delete_apply_authoritative_snapshot(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    service = MapMarkerService(tmp_path / "markers")
    world = tmp_path / "world"
    world.mkdir()
    ui_queue = _UiQueue()
    controller, _scope = _controller(runtime, service, ui_queue, [1])
    added: list[MapMarker] = []
    deleted: list[bool] = []

    try:
        controller.bind_world(world, _dimensions(tmp_path))
        add_handle = controller.submit_upsert_marker(
            "基地",
            10,
            20,
            on_complete=added.append,
            on_error=lambda error: pytest.fail(str(error)),
        )
        add_handle.result(timeout=2)
        ui_queue.wait_for_post()
        ui_queue.drain()

        assert [item.id for item in controller.markers()] == [added[0].id]

        delete_handle = controller.submit_delete_marker(
            added[0].id,
            on_complete=deleted.append,
            on_error=lambda error: pytest.fail(str(error)),
        )
        delete_handle.result(timeout=2)
        ui_queue.wait_for_post()
        ui_queue.drain()

        assert deleted == [True]
        assert controller.markers() == []
    finally:
        controller.close()
        runtime.shutdown(wait=True)


def test_close_cancels_active_marker_task_without_closing_shared_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = _runtime()
    service = MapMarkerService(tmp_path / "markers")
    world = tmp_path / "world"
    world.mkdir()
    ui_queue = _UiQueue()
    controller, scope = _controller(runtime, service, ui_queue, [1])
    started = threading.Event()
    release = threading.Event()
    original_list = service.list

    def blocked_list(*args, **kwargs):
        started.set()
        if not release.wait(2):
            raise TimeoutError("标记加载测试未获准继续")
        return original_list(*args, **kwargs)

    monkeypatch.setattr(service, "list", blocked_list)

    try:
        controller.bind_world(world, _dimensions(tmp_path))
        handle = controller.submit_load_markers(
            lambda: pytest.fail("关闭后不应完成加载回调"),
            lambda error: pytest.fail(str(error)),
        )
        assert started.wait(2)

        controller.close()
        controller.close()

        assert controller.is_closed
        assert handle.cancel_requested
        assert not handle.cancelled
        assert not scope.is_closed
        release.set()
        with pytest.raises(OperationCancelledError):
            handle.result(timeout=2)
        runtime.shutdown(wait=True)
        assert ui_queue.callbacks == []
    finally:
        release.set()
        runtime.shutdown(wait=True)


def test_explorer_dispose_closes_marker_controller_before_shared_scope() -> None:
    calls: list[str] = []
    view = cast(Any, ExplorerView.__new__(ExplorerView))
    view._disposed = False
    view._world_load_generation = 3
    view._map_controller = SimpleNamespace(
        close=lambda: calls.append("marker_controller")
    )
    view._data_loader = None
    view._task_scope = SimpleNamespace(close=lambda: calls.append("scope"))
    view._dispose_player_tab = lambda: calls.append("player_tab")
    view._dispose_region_tab = lambda: calls.append("region_tab")
    view._map_service = SimpleNamespace(close=lambda: calls.append("map_service"))

    view.dispose()
    view.dispose()

    assert calls.count("marker_controller") == 1
    assert calls.count("scope") == 1
    assert calls.index("marker_controller") < calls.index("scope")
