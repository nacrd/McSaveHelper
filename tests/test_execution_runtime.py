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
    OperationRecordSink,
    RuntimeClosedError,
    TaskPriority,
    TaskQueueFullError,
)
from core.observability import OperationOutcome, OperationRecord


def _single_lane_runtime(
    queue_capacity: int = 1,
    *,
    operation_sink: OperationRecordSink | None = None,
) -> ExecutionRuntime:
    limits = LaneLimits(max_workers=1, queue_capacity=queue_capacity)
    return ExecutionRuntime(
        io_limits=limits,
        cpu_limits=limits,
        operation_sink=operation_sink,
    )


def _record_collector(
    records: list[OperationRecord],
    published: threading.Event,
) -> OperationRecordSink:
    """创建会通知测试线程的同步指标接收器。"""
    def collect(record: OperationRecord) -> None:
        records.append(record)
        published.set()

    return collect


def test_submit_returns_result_and_releases_capacity() -> None:
    runtime = _single_lane_runtime(queue_capacity=0)
    try:
        first = runtime.submit("first", lambda token: 7)

        assert first.result(timeout=1) == 7
        second = runtime.submit("second", lambda token: 9)
        assert second.result(timeout=1) == 9
        assert runtime.active_task_count == 0
        snapshot = runtime.snapshot()
        assert snapshot.queue_wait_samples >= 2
        assert snapshot.queue_wait_last_ms >= 0.0
        assert snapshot.queue_wait_max_ms >= 0.0
    finally:
        runtime.shutdown(wait=True)


def test_queue_wait_increases_when_task_waits_behind_running_work() -> None:
    runtime = _single_lane_runtime(queue_capacity=2)
    started = threading.Event()
    release = threading.Event()

    def blocker(token):
        del token
        started.set()
        release.wait(1)

    first = runtime.submit("blocker", blocker)
    assert started.wait(1)
    second = runtime.submit("queued", lambda token: "done")
    try:
        release.set()
        assert first.result(timeout=1) is None
        assert second.result(timeout=1) == "done"
        snapshot = runtime.snapshot()
        assert snapshot.queue_wait_samples >= 2
        # Second task waited in the single-worker queue.
        assert snapshot.queue_wait_max_ms >= snapshot.queue_wait_last_ms
        assert snapshot.queue_wait_max_ms >= 0.0
    finally:
        release.set()
        runtime.shutdown(wait=True)


def test_operation_sink_records_success_and_preserves_snapshot() -> None:
    records: list[OperationRecord] = []
    published = threading.Event()
    runtime = _single_lane_runtime(
        operation_sink=_record_collector(records, published),
    )
    try:
        handle = runtime.submit(
            "render_tile",
            lambda token: "done",
            lane=ExecutionLane.CPU,
            priority=TaskPriority.VISIBLE,
        )

        assert handle.result(timeout=1) == "done"
        assert published.wait(1)
        snapshot = runtime.snapshot()
    finally:
        runtime.shutdown(wait=True)

    assert len(records) == 1
    record = records[0]
    assert record.operation_id == "render_tile"
    assert record.feature == "runtime"
    assert record.outcome is OperationOutcome.OK
    assert record.metadata["lane"] == "cpu"
    assert record.metadata["priority"] == "visible"
    assert record.queue_wait_ms >= 0.0
    assert record.run_ms >= 0.0
    assert snapshot.active_tasks == 0
    assert snapshot.submitted_by_lane[ExecutionLane.CPU] == 1
    assert snapshot.queue_wait_samples == 1
    assert snapshot.queue_wait_last_ms == pytest.approx(record.queue_wait_ms)


def test_operation_sink_records_error_without_changing_exception() -> None:
    records: list[OperationRecord] = []
    published = threading.Event()
    runtime = _single_lane_runtime(
        operation_sink=_record_collector(records, published),
    )

    def fail(token) -> None:
        del token
        raise ValueError("boom")

    try:
        handle = runtime.submit("broken", fail)
        with pytest.raises(ValueError, match="boom"):
            handle.result(timeout=1)
        assert published.wait(1)
    finally:
        runtime.shutdown(wait=True)

    assert len(records) == 1
    assert records[0].operation_id == "broken"
    assert records[0].outcome is OperationOutcome.ERROR
    assert records[0].metadata["lane"] == "io"


def test_operation_sink_records_cooperative_cancellation() -> None:
    records: list[OperationRecord] = []
    published = threading.Event()
    started = threading.Event()
    runtime = _single_lane_runtime(
        operation_sink=_record_collector(records, published),
    )

    def wait_for_cancel(token) -> None:
        started.set()
        token.wait(1)
        token.raise_if_cancelled()

    try:
        handle = runtime.submit("cancelled", wait_for_cancel)
        assert started.wait(1)
        assert handle.cancel() is True
        with pytest.raises(OperationCancelledError):
            handle.result(timeout=1)
        assert published.wait(1)
    finally:
        runtime.shutdown(wait=True)

    assert len(records) == 1
    assert records[0].outcome is OperationOutcome.CANCELLED
    assert records[0].run_ms >= 0.0


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


def test_cancelled_queued_items_keep_capacity_until_dequeued() -> None:
    runtime = _single_lane_runtime(queue_capacity=2)
    started = threading.Event()
    release = threading.Event()

    def block_worker(token) -> str:
        del token
        started.set()
        release.wait(1)
        return "released"

    running = runtime.submit("running", block_worker)
    assert started.wait(1)
    queued = [
        runtime.submit(f"queued-{index}", lambda token: None)
        for index in range(2)
    ]

    try:
        assert all(handle.cancel() for handle in queued)
        assert runtime.active_task_count == 3

        for index in range(20):
            with pytest.raises(TaskQueueFullError, match="通道已满"):
                runtime.submit(f"overflow-{index}", lambda token: None)

        assert runtime.active_task_count == 3
        release.set()
        assert running.result(timeout=1) == "released"
        assert runtime.shutdown(wait=True, timeout=1) is True
    finally:
        release.set()
        runtime.shutdown(wait=True, timeout=1)


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


def test_late_cancel_request_does_not_replace_successful_result() -> None:
    runtime = _single_lane_runtime()
    started = threading.Event()
    release = threading.Event()

    def commit_without_cancel_checkpoint(token) -> str:
        del token
        started.set()
        release.wait(1)
        return "committed"

    handle = runtime.submit("commit", commit_without_cancel_checkpoint)
    try:
        assert started.wait(1)
        assert handle.cancel() is True
        assert handle.cancel_requested is True
        assert handle.cancelled is False

        release.set()
        assert handle.result(timeout=1) == "committed"
        assert handle.cancel_requested is True
        assert handle.cancelled is False
    finally:
        release.set()
        runtime.shutdown(wait=True, timeout=1)


def test_shutdown_timeout_reports_late_worker_termination() -> None:
    runtime = _single_lane_runtime()
    started = threading.Event()
    release = threading.Event()

    def ignore_cancel_until_released(token) -> str:
        del token
        started.set()
        release.wait()
        return "finished"

    handle = runtime.submit("slow-shutdown", ignore_cancel_until_released)
    assert started.wait(1)

    try:
        assert runtime.shutdown(wait=True, timeout=0.01) is False
        assert runtime.is_closed is True
        assert runtime.is_terminated is False

        release.set()
        assert handle.result(timeout=1) == "finished"
        assert runtime.shutdown(wait=True, timeout=1) is True
        assert runtime.is_terminated is True
    finally:
        release.set()
        runtime.shutdown(wait=True, timeout=1)


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


def test_shutdown_rejects_negative_timeout_without_closing_runtime() -> None:
    runtime = _single_lane_runtime()
    try:
        with pytest.raises(ValueError, match="不能为负数"):
            runtime.shutdown(wait=True, timeout=-0.1)
        assert runtime.is_closed is False
    finally:
        runtime.shutdown(wait=True)
