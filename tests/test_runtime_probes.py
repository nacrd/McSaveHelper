"""Controlled cancel-latency probe against ExecutionRuntime."""
from __future__ import annotations

from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.runtime_probes import (
    cancel_within_budget,
    probe_cancel_latency_ms,
)


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
