"""core.parallel serial fallback and worker-budget helpers."""
from __future__ import annotations

import pytest

from core.parallel import (
    ABSOLUTE_MAX_WORKERS,
    ParallelCancelledError,
    SerialParallelRunner,
    clamp_workers,
)


def test_clamp_workers_hard_cap() -> None:
    assert clamp_workers(100, item_count=50) <= ABSOLUTE_MAX_WORKERS
    assert clamp_workers(None, item_count=3) == 3
    assert clamp_workers(0, item_count=5) == 1
    assert clamp_workers(4, item_count=2) == 2


def test_serial_runner_preserves_order_and_collects_errors() -> None:
    runner = SerialParallelRunner()

    def transform(value: int) -> int:
        if value == 2:
            raise ValueError("bad item")
        return value * value

    results = runner.map("test.serial", [1, 2, 3], transform)

    assert results[0] == 1
    assert isinstance(results[1], ValueError)
    assert results[2] == 9


def test_serial_runner_observes_cancellation_before_next_item() -> None:
    runner = SerialParallelRunner()
    cancelled = False

    def cancel_check() -> bool:
        return cancelled

    def transform(value: int) -> int:
        nonlocal cancelled
        cancelled = True
        return value

    with pytest.raises(ParallelCancelledError):
        runner.map(
            "test.cancel",
            [1, 2],
            transform,
            cancel_check=cancel_check,
        )
