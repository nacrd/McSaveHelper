"""Deterministic tests for the framework-neutral UI delivery channel."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping

import pytest

from app.services.execution_runtime import (
    ExecutionRuntime,
    LaneLimits,
    OperationCancelledError,
    OperationContext,
)
from app.services.operation_progress import (
    OperationState,
    ProgressReporter,
    ProgressSnapshot,
)
from app.services.ui_delivery import UiDeliveryChannel, UiDeliverySpec
from core.observability import OperationOutcome, OperationRecord


class _QueuedScheduler:
    """Keep scheduled callbacks until a test explicitly drains them."""

    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []

    def __call__(self, callback: Callable[[], None]) -> bool:
        self.callbacks.append(callback)
        return True

    def drain(self) -> None:
        callbacks = tuple(self.callbacks)
        self.callbacks.clear()
        for callback in callbacks:
            callback()


class _Clock:
    """Return a controlled nanosecond sequence for timing assertions."""

    def __init__(self, *values: int) -> None:
        self.values = list(values)

    def __call__(self) -> int:
        if not self.values:
            raise AssertionError("test clock exhausted")
        return self.values.pop(0)


class _ProgressSource:
    """Typed progress source backed by a real reporter."""

    def __init__(self, task_id: str, reporter: ProgressReporter) -> None:
        self._task_id = task_id
        self._reporter = reporter

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def operation(self) -> str:
        return "render"

    @property
    def feature(self) -> str:
        return "map"

    @property
    def world_id(self) -> str:
        return "world-a"

    @property
    def generation(self) -> int:
        return 1

    @property
    def metadata(self) -> Mapping[str, object]:
        return {}

    def subscribe_progress(
        self,
        callback: Callable[[ProgressSnapshot], None],
    ) -> Callable[[], None]:
        return self._reporter.subscribe(callback)


def _spec() -> UiDeliverySpec:
    return UiDeliverySpec(
        task_id="task-1",
        operation="load_world",
        feature="explorer",
        generation=4,
        world_id="world-a",
        event="result",
        metadata={"phase": "session"},
    )


def test_post_records_success_with_unique_delivery_id_and_timings() -> None:
    scheduler = _QueuedScheduler()
    records: list[OperationRecord] = []
    clock = _Clock(
        1_000_000_000,
        1_005_000_000,
        1_025_000_000,
        1_030_000_000,
        1_045_000_000,
        1_050_000_000,
        1_055_000_000,
        1_060_000_000,
    )
    channel = UiDeliveryChannel(scheduler, records.append, clock=clock)
    delivered: list[str] = []

    first_id = channel.post(_spec(), lambda: delivered.append("first"), is_current=lambda: True)
    second_id = channel.post(_spec(), lambda: delivered.append("second"), is_current=lambda: True)

    scheduler.drain()

    assert first_id != second_id
    assert delivered == ["first", "second"]
    assert len(records) == 2
    assert records[0].operation_id == first_id
    assert records[0].outcome is OperationOutcome.OK
    assert records[0].queue_wait_ms == 25.0
    assert records[0].run_ms == 15.0
    assert records[0].metadata["task_id"] == "task-1"
    assert records[0].metadata["generation"] == 4
    assert records[0].metadata["phase"] == "session"


def test_post_drops_stale_result_at_drain_time_and_records_queue_delay() -> None:
    scheduler = _QueuedScheduler()
    records: list[OperationRecord] = []
    clock = _Clock(2_000_000_000, 2_125_000_000)
    channel = UiDeliveryChannel(scheduler, records.append, clock=clock)
    current = [True]
    delivered: list[str] = []

    delivery_id = channel.post(
        _spec(),
        lambda: delivered.append("stale"),
        is_current=lambda: current[0],
    )
    current[0] = False
    scheduler.drain()

    assert delivered == []
    assert records[0].operation_id == delivery_id
    assert records[0].outcome is OperationOutcome.STALE
    assert records[0].queue_wait_ms == 125.0
    assert records[0].run_ms == 0.0
    assert records[0].metadata["drop_reason"] == "generation_guard"


def test_scheduler_rejection_records_error_without_queuing_callback() -> None:
    records: list[OperationRecord] = []
    channel = UiDeliveryChannel(lambda callback: False, records.append)
    delivered: list[str] = []

    delivery_id = channel.post(
        _spec(),
        lambda: delivered.append("unexpected"),
        is_current=lambda: True,
    )

    assert delivered == []
    assert len(records) == 1
    assert records[0].operation_id == delivery_id
    assert records[0].outcome is OperationOutcome.ERROR
    assert records[0].metadata["stage"] == "schedule"
    assert records[0].metadata["error_type"] == "RuntimeError"


def test_scheduler_exception_records_error() -> None:
    records: list[OperationRecord] = []

    def fail(callback: Callable[[], None]) -> bool:
        del callback
        raise OSError("page closed")

    channel = UiDeliveryChannel(fail, records.append)
    delivery_id = channel.post(_spec(), lambda: None, is_current=lambda: True)

    assert records[0].operation_id == delivery_id
    assert records[0].outcome is OperationOutcome.ERROR
    assert records[0].metadata["stage"] == "schedule"
    assert records[0].metadata["error_type"] == "OSError"
    assert records[0].metadata["error"] == "page closed"


def test_guard_exception_and_callback_exception_are_recorded_as_errors() -> None:
    scheduler = _QueuedScheduler()
    records: list[OperationRecord] = []
    channel = UiDeliveryChannel(scheduler, records.append)

    channel.post(
        _spec(),
        lambda: None,
        is_current=lambda: (_ for _ in ()).throw(ValueError("guard failed")),
    )
    channel.post(
        _spec(),
        lambda: (_ for _ in ()).throw(RuntimeError("projection failed")),
        is_current=lambda: True,
    )
    scheduler.drain()

    assert [record.outcome for record in records] == [
        OperationOutcome.ERROR,
        OperationOutcome.ERROR,
    ]
    assert records[0].metadata["stage"] == "guard"
    assert records[0].metadata["error_type"] == "ValueError"
    assert records[1].metadata["stage"] == "callback"
    assert records[1].metadata["error_type"] == "RuntimeError"


def test_close_marks_queued_delivery_stale() -> None:
    scheduler = _QueuedScheduler()
    records: list[OperationRecord] = []
    channel = UiDeliveryChannel(scheduler, records.append)
    delivered: list[str] = []

    channel.post(_spec(), lambda: delivered.append("late"), is_current=lambda: True)
    channel.close()
    scheduler.drain()

    assert delivered == []
    assert records[0].outcome is OperationOutcome.STALE
    assert records[0].metadata["drop_reason"] == "channel_closed"


def test_cancel_progress_reaches_ui_callback_within_budget() -> None:
    limits = LaneLimits(max_workers=1, queue_capacity=1)
    runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
    records: list[OperationRecord] = []
    channel = UiDeliveryChannel(
        lambda callback: callback() is None,
        records.append,
    )
    started = threading.Event()
    release = threading.Event()
    observed = threading.Event()
    snapshots: list[ProgressSnapshot] = []

    def capture_progress(snapshot: ProgressSnapshot) -> None:
        snapshots.append(snapshot)
        observed.set()

    def work(context: OperationContext) -> None:
        started.set()
        release.wait(1)
        context.raise_if_cancelled()

    handle = runtime.submit(
        "cancel_ui",
        work,
        feature="test",
        generation=2,
    )
    unsubscribe = channel.observe_progress(
        handle,
        capture_progress,
        is_current=lambda: True,
    )
    try:
        assert started.wait(1)
        requested_at = time.perf_counter()
        assert handle.cancel() is True
        assert observed.wait(0.1)
        latency_ms = (time.perf_counter() - requested_at) * 1000.0
        assert latency_ms < 100.0
        assert snapshots[-1].state is OperationState.CANCEL_REQUESTED
        assert records[-1].metadata["event"] == "progress"
        assert records[-1].metadata["state"] == "cancel_requested"
    finally:
        unsubscribe()
        release.set()
        with pytest.raises(OperationCancelledError):
            handle.result(timeout=1)
        runtime.shutdown(wait=True)


def test_running_progress_is_coalesced_to_latest_queued_snapshot() -> None:
    scheduler = _QueuedScheduler()
    records: list[OperationRecord] = []
    reporter = ProgressReporter("task-progress", "render", generation=1)
    source = _ProgressSource("task-progress", reporter)
    channel = UiDeliveryChannel(scheduler, records.append)
    delivered: list[ProgressSnapshot] = []
    unsubscribe = channel.observe_progress(
        source,
        delivered.append,
        is_current=lambda: True,
    )

    reporter.mark_running()
    reporter.update(1, 10)
    reporter.update(5, 10)
    reporter.update(9, 10)

    assert len(scheduler.callbacks) == 1
    scheduler.drain()
    assert [snapshot.completed for snapshot in delivered] == [9.0]
    assert len(records) == 1
    assert records[0].metadata["state"] == "running"
    assert records[0].metadata["coalesced"] is True

    reporter.mark_finished(OperationOutcome.OK)
    assert len(scheduler.callbacks) == 1
    scheduler.drain()
    assert delivered[-1].state is OperationState.SUCCEEDED
    unsubscribe()


def test_rejected_running_progress_is_not_rescheduled_recursively() -> None:
    reporter = ProgressReporter("task-rejected", "render", generation=1)
    source = _ProgressSource("task-rejected", reporter)
    schedule_calls = 0
    records: list[OperationRecord] = []

    def reject(callback: Callable[[], None]) -> bool:
        nonlocal schedule_calls
        del callback
        schedule_calls += 1
        return False

    channel = UiDeliveryChannel(reject, records.append)
    unsubscribe = channel.observe_progress(
        source,
        lambda snapshot: None,
        is_current=lambda: True,
    )
    try:
        reporter.mark_running()
        assert schedule_calls == 1
        assert len(records) == 1

        reporter.update(1, 10)
        assert schedule_calls == 2
        assert len(records) == 2
    finally:
        unsubscribe()


@pytest.mark.parametrize("failing_factory", ["id", "clock"])
def test_running_progress_recovers_after_delivery_setup_failure(
    failing_factory: str,
) -> None:
    scheduler = _QueuedScheduler()
    reporter = ProgressReporter("task-retry", "render", generation=1)
    source = _ProgressSource("task-retry", reporter)
    id_attempts = 0
    clock_attempts = 0

    def id_factory() -> str:
        nonlocal id_attempts
        id_attempts += 1
        if failing_factory == "id" and id_attempts == 1:
            raise RuntimeError("transient id failure")
        return f"delivery-{id_attempts}"

    def clock() -> int:
        nonlocal clock_attempts
        clock_attempts += 1
        if failing_factory == "clock" and clock_attempts == 1:
            raise RuntimeError("transient clock failure")
        return time.monotonic_ns()

    channel = UiDeliveryChannel(
        scheduler,
        clock=clock,
        id_factory=id_factory,
    )
    delivered: list[ProgressSnapshot] = []
    unsubscribe = channel.observe_progress(
        source,
        delivered.append,
        is_current=lambda: True,
    )

    try:
        reporter.mark_running()
        assert scheduler.callbacks == []

        reporter.update(1, 10)
        assert len(scheduler.callbacks) == 1
        scheduler.drain()

        assert [snapshot.completed for snapshot in delivered] == [1.0]
    finally:
        unsubscribe()
