"""后台操作进度协议测试。"""
from __future__ import annotations

import pytest

from app.services.operation_progress import (
    OperationState,
    ProgressReporter,
)
from core.observability import OperationOutcome


def test_progress_is_monotonic_and_preserves_total() -> None:
    reporter = ProgressReporter("task-1", "scan", generation=2)

    reporter.mark_running()
    snapshot = reporter.update(2, total=4, message="half")

    assert snapshot.completed == 2
    assert snapshot.total == 4
    assert snapshot.fraction == 0.5
    assert snapshot.state is OperationState.RUNNING

    with pytest.raises(ValueError, match="不能倒退"):
        reporter.update(1)


def test_progress_rejects_invalid_total_and_completion() -> None:
    reporter = ProgressReporter("task-2", "scan", generation=0)

    with pytest.raises(ValueError, match="总量必须大于零"):
        reporter.update(0, total=0)
    with pytest.raises(ValueError, match="不能超过总量"):
        reporter.update(3, total=2)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_progress_rejects_non_finite_values(value: float) -> None:
    reporter = ProgressReporter("task-finite", "scan", generation=0)

    with pytest.raises(ValueError, match="必须是有限数值"):
        reporter.update(value)
    with pytest.raises(ValueError, match="总量必须是有限数值"):
        reporter.update(0, total=value)


def test_progress_total_change_cannot_reduce_fraction() -> None:
    reporter = ProgressReporter("task-fraction", "scan", generation=0)
    reporter.update(5, total=10)

    with pytest.raises(ValueError, match="比例不能倒退"):
        reporter.update(5, total=20)

    snapshot = reporter.update(10, total=20)
    assert snapshot.fraction == 0.5


def test_terminal_state_is_idempotent_and_rejects_later_updates() -> None:
    reporter = ProgressReporter("task-3", "scan", generation=0)
    reporter.mark_finished(OperationOutcome.ERROR, ValueError("bad"))
    first = reporter.snapshot()

    reporter.mark_finished(OperationOutcome.OK)
    assert reporter.snapshot() == first
    with pytest.raises(RuntimeError, match="已经结束"):
        reporter.update(1, total=1)


def test_stale_is_not_reported_as_cancelled() -> None:
    reporter = ProgressReporter("task-4", "scan", generation=4)
    reporter.mark_stale()

    snapshot = reporter.snapshot()
    assert snapshot.state is OperationState.STALE
    assert snapshot.is_terminal is True


def test_cancel_request_is_visible_before_final_cancellation() -> None:
    reporter = ProgressReporter("task-5", "scan", generation=0)
    reporter.mark_running()
    reporter.mark_cancel_requested()
    assert reporter.snapshot().state is OperationState.CANCEL_REQUESTED

    reporter.mark_finished(OperationOutcome.CANCELLED)
    assert reporter.snapshot().state is OperationState.CANCELLED


def test_cancel_request_notification_is_reentrant_and_idempotent() -> None:
    reporter = ProgressReporter("task-reentrant", "scan", generation=0)
    observed: list[OperationState] = []

    def observe(snapshot) -> None:
        observed.append(snapshot.state)
        if snapshot.state is OperationState.CANCEL_REQUESTED:
            reporter.mark_cancel_requested()

    reporter.subscribe(observe)
    reporter.mark_running()
    reporter.mark_cancel_requested()

    assert observed == [
        OperationState.RUNNING,
        OperationState.CANCEL_REQUESTED,
    ]


def test_progress_subscribers_run_outside_lock_and_can_unsubscribe() -> None:
    reporter = ProgressReporter("task-6", "scan", generation=0)
    observed: list[OperationState] = []

    def observe(snapshot) -> None:
        assert reporter.snapshot() == snapshot
        observed.append(snapshot.state)

    unsubscribe = reporter.subscribe(observe)
    reporter.mark_running()
    reporter.update(1, total=2)
    unsubscribe()
    unsubscribe()
    reporter.mark_finished(OperationOutcome.OK)

    assert observed == [OperationState.RUNNING, OperationState.RUNNING]
