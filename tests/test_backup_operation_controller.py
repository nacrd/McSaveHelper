"""Backup operation cancellation and stale-callback lifecycle tests."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from app.controllers.backup_operation_controller import (
    BackupOperationController,
    BackupOperationRequest,
    BackupOperationStatus,
    BackupOperationUiPorts,
)
from app.services.execution_runtime import ExecutionRuntime, LaneLimits


class _UiQueue:
    """Capture UI deliveries and wait by count without fixed sleeps."""

    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []
        self._condition = threading.Condition()

    def post(self, callback: Callable[[], None]) -> None:
        with self._condition:
            self.callbacks.append(callback)
            self._condition.notify_all()

    def wait_for_count(self, count: int) -> None:
        with self._condition:
            assert self._condition.wait_for(
                lambda: len(self.callbacks) >= count,
                timeout=2,
            )

    def drain(self) -> None:
        callbacks = tuple(self.callbacks)
        self.callbacks.clear()
        for callback in callbacks:
            callback()


def _runtime() -> ExecutionRuntime:
    limits = LaneLimits(max_workers=1, queue_capacity=4)
    return ExecutionRuntime(io_limits=limits, cpu_limits=limits)


def _controller(
    runtime: ExecutionRuntime,
    world: list[Path],
    queue: _UiQueue,
    events: list[object],
) -> BackupOperationController:
    return BackupOperationController(
        runtime.create_scope("backup_operation_test"),
        BackupOperationUiPorts(
            dispatch=queue.post,
            get_world_path=lambda: world[0],
            show_progress=lambda task: events.append(("show", task)),
            update_progress=lambda task, value: events.append(
                ("progress", task, value)
            ),
            hide_progress=lambda: events.append("hide"),
            set_busy=lambda busy: events.append(("busy", busy)),
            set_cancel_pending=lambda: events.append("cancel_pending"),
        ),
    )


def test_cancel_after_atomic_publish_still_reports_success(tmp_path: Path) -> None:
    runtime = _runtime()
    world = [tmp_path / "world"]
    queue = _UiQueue()
    events: list[object] = []
    controller = _controller(runtime, world, queue, events)
    started = threading.Event()
    release = threading.Event()
    completed: list[object] = []

    def publish_then_return(token, progress):
        del token, progress
        started.set()
        assert release.wait(2)
        return "published"

    try:
        handle = controller.start(
            BackupOperationRequest(
                world_path=world[0],
                task_name="backup",
                operation=publish_then_return,
                on_success=completed.append,
                on_error=lambda error: events.append(error),
            )
        )
        assert handle is not None
        assert started.wait(2)
        assert controller.cancel() is True
        assert controller.cancel() is False
        release.set()

        outcome = handle.result(timeout=2)
        assert outcome.status is BackupOperationStatus.SUCCEEDED
        queue.wait_for_count(2)
        queue.drain()

        assert completed == ["published"]
        assert events[-2:] == ["hide", ("busy", False)]
    finally:
        release.set()
        controller.close()
        runtime.shutdown(wait=True)


def test_world_switch_discards_queued_terminal_callback(tmp_path: Path) -> None:
    runtime = _runtime()
    world = [tmp_path / "old"]
    queue = _UiQueue()
    events: list[object] = []
    controller = _controller(runtime, world, queue, events)
    completed: list[object] = []

    try:
        handle = controller.start(
            BackupOperationRequest(
                world_path=world[0],
                task_name="backup",
                operation=lambda token, progress: "old result",
                on_success=completed.append,
                on_error=lambda error: events.append(error),
            )
        )
        assert handle is not None
        handle.result(timeout=2)
        queue.wait_for_count(2)

        world[0] = tmp_path / "new"
        controller.invalidate()
        queue.drain()

        assert completed == []
        assert controller.is_running is False
    finally:
        controller.close()
        runtime.shutdown(wait=True)
