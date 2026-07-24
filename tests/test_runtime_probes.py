"""Controlled runtime acceptance probes."""
from __future__ import annotations

from collections.abc import Callable

from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.runtime_probes import (
    cancel_within_budget,
    probe_cancel_latency_ms,
    probe_stale_ui_delivery,
    probe_ui_delivery_latency,
)
from core.observability import OperationOutcome


class _Clock:
    """Return controlled monotonic nanosecond values."""

    def __init__(self, *values: int) -> None:
        self._values = list(values)

    def __call__(self) -> int:
        if not self._values:
            raise AssertionError("探针测试时钟已耗尽")
        return self._values.pop(0)


def _run_immediately(callback: Callable[[], None]) -> bool:
    callback()
    return True


def test_probe_cancel_latency_under_100ms() -> None:
    limits = LaneLimits(max_workers=1, queue_capacity=2)
    runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
    try:
        latency = probe_cancel_latency_ms(runtime)
        assert latency < 100.0
        bounded = cancel_within_budget(runtime, budget_ms=100.0)
        assert bounded < 100.0
    finally:
        runtime.shutdown(wait=True)


def test_probe_ui_delivery_reports_queue_and_callback_latency() -> None:
    clock = _Clock(
        1_000_000_000,
        1_005_000_000,
        1_010_000_000,
        1_012_000_000,
    )

    result = probe_ui_delivery_latency(_run_immediately, clock=clock)

    assert result.outcome is OperationOutcome.OK
    assert result.callback_delivered is True
    assert result.queue_wait_ms == 5.0
    assert result.run_ms == 2.0
    assert result.drop_reason == ""


def test_probe_stale_ui_delivery_suppresses_callback() -> None:
    clock = _Clock(2_000_000_000, 2_125_000_000)

    result = probe_stale_ui_delivery(_run_immediately, clock=clock)

    assert result.outcome is OperationOutcome.STALE
    assert result.callback_delivered is False
    assert result.queue_wait_ms == 125.0
    assert result.run_ms == 0.0
    assert result.drop_reason == "generation_guard"
