"""应用级后台任务运行时测试。"""
from __future__ import annotations

import threading
from concurrent.futures import CancelledError

import pytest

from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    LaneLimits,
    OperationCancelledError,
    RuntimeClosedError,
    TaskPriority,
    TaskQueueFullError,
)


def _single_lane_runtime(queue_capacity: int = 1) -> ExecutionRuntime:
    limits = LaneLimits(max_workers=1, queue_capacity=queue_capacity)
    return ExecutionRuntime(io_limits=limits, cpu_limits=limits)


def test_submit_returns_result_and_releases_capacity() -> None:
    runtime = _single_lane_runtime(queue_capacity=0)
    try:
        first = runtime.submit("first", lambda token: 7)

        assert first.result(timeout=1) == 7
        second = runtime.submit("second", lambda token: 9)
        assert second.result(timeout=1) == 9
        assert runtime.active_task_count == 0
    finally:
        runtime.shutdown(wait=True)


def test_lane_capacity_rejects_excess_without_blocking() -> None:
    runtime = _single_lane_runtime(queue_capacity=1)
    started = threading.Event()
    release = threading.Event()

    def wait_for_release(token):
        started.set()
        while not release.is_set():
            token.raise_if_cancelled()
            release.wait(0.01)

    first = runtime.submit("running", wait_for_release)
    assert started.wait(1)
    second = runtime.submit("queued", lambda token: None)
    try:
        with pytest.raises(TaskQueueFullError, match="通道已满"):
            runtime.submit("overflow", lambda token: None)
    finally:
        release.set()
        first.result(timeout=1)
        second.result(timeout=1)
        runtime.shutdown(wait=True)


def test_visible_task_runs_before_background_task_waiting_in_same_lane() -> None:
    runtime = _single_lane_runtime(queue_capacity=3)
    started = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def first(token):
        del token
        started.set()
        release.wait(1)
        order.append("first")

    def record(name: str):
        def work(token):
            del token
            order.append(name)

        return work

    first_handle = runtime.submit("first", first)
    assert started.wait(1)
    background = runtime.submit(
        "background",
        record("background"),
        priority=TaskPriority.BACKGROUND,
    )
    visible = runtime.submit(
        "visible",
        record("visible"),
        priority=TaskPriority.VISIBLE,
    )
    try:
        release.set()
        first_handle.result(timeout=1)
        visible.result(timeout=1)
        background.result(timeout=1)
        assert order == ["first", "visible", "background"]
    finally:
        runtime.shutdown(wait=True)


def test_snapshot_exposes_task_and_worker_budgets() -> None:
    runtime = _single_lane_runtime()
    started = threading.Event()
    release = threading.Event()

    def wait_for_release(token):
        del token
        started.set()
        release.wait(1)

    handle = runtime.submit(
        "measure",
        wait_for_release,
        lane=ExecutionLane.CPU,
    )
    try:
        assert started.wait(1)
        snapshot = runtime.snapshot()
        assert snapshot.active_tasks == 1
        assert snapshot.active_by_lane[ExecutionLane.CPU] == 1
        assert snapshot.submitted_by_lane[ExecutionLane.CPU] == 1
        assert snapshot.worker_count_by_lane[ExecutionLane.CPU] == 1
    finally:
        release.set()
        handle.result(timeout=1)
        runtime.shutdown(wait=True)


def test_scope_close_cancels_owned_tasks_and_rejects_late_submit() -> None:
    runtime = _single_lane_runtime()
    scope = runtime.create_scope("explorer")
    started = threading.Event()

    def wait_for_cancel(token):
        started.set()
        token.wait(1)
        token.raise_if_cancelled()

    handle = scope.submit("load_world", wait_for_cancel)
    assert started.wait(1)

    scope.close()

    with pytest.raises(OperationCancelledError):
        handle.result(timeout=1)
    with pytest.raises(RuntimeClosedError, match="作用域"):
        scope.submit("late", lambda token: None)
    runtime.shutdown(wait=True)


def test_scope_releases_completed_handle_ownership() -> None:
    runtime = _single_lane_runtime()
    scope = runtime.create_scope("compare")
    try:
        handle = scope.submit("run", lambda token: 42)
        assert handle.result(timeout=1) == 42
        assert scope.active_task_count == 0
    finally:
        scope.close()
        runtime.shutdown(wait=True)


def test_cancel_notifies_running_operation() -> None:
    runtime = _single_lane_runtime()
    started = threading.Event()

    def wait_for_cancel(token):
        started.set()
        token.wait(1)
        token.raise_if_cancelled()

    handle = runtime.submit("cancel-me", wait_for_cancel)
    assert started.wait(1)
    assert handle.cancel() is True
    with pytest.raises(OperationCancelledError):
        handle.result(timeout=1)
    assert handle.cancelled is True
    runtime.shutdown(wait=True)


def test_shutdown_cancels_queued_work_and_rejects_new_work() -> None:
    runtime = _single_lane_runtime(queue_capacity=1)
    started = threading.Event()

    def wait_for_shutdown(token):
        started.set()
        token.wait(1)
        token.raise_if_cancelled()

    running = runtime.submit(
        "running",
        wait_for_shutdown,
        lane=ExecutionLane.CPU,
    )
    assert started.wait(1)
    queued = runtime.submit(
        "queued",
        lambda token: None,
        lane=ExecutionLane.CPU,
    )

    runtime.shutdown(wait=True)

    with pytest.raises(OperationCancelledError):
        running.result(timeout=1)
    with pytest.raises(CancelledError):
        queued.result(timeout=1)
    with pytest.raises(RuntimeClosedError):
        runtime.submit("late", lambda token: None)


@pytest.mark.parametrize(
    ("workers", "capacity", "message"),
    ((0, 1, "工作线程数"), (1, -1, "排队容量")),
)
def test_lane_limits_reject_invalid_values(
    workers: int,
    capacity: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        LaneLimits(workers, capacity)
