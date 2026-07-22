"""统一运行时批量并行映射测试。"""
from __future__ import annotations

import threading

import pytest

from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    LaneLimits,
    OperationCancelledError,
)
from app.services.runtime_map import map_items


def test_map_items_preserves_order_and_aggregates_errors() -> None:
    runtime = ExecutionRuntime(
        io_limits=LaneLimits(2, 4),
        cpu_limits=LaneLimits(2, 4),
    )
    try:
        def worker(token, item: int) -> int:
            del token
            if item == 2:
                raise ValueError("bad-item")
            return item * 10

        results = map_items(
            runtime,
            "scale",
            [1, 2, 3],
            worker,
            lane=ExecutionLane.CPU,
            max_in_flight=2,
        )

        assert results[0] == 10
        assert isinstance(results[1], ValueError)
        assert results[2] == 30
    finally:
        runtime.shutdown(wait=True)


def test_map_items_stops_on_cancel_check() -> None:
    runtime = ExecutionRuntime(
        io_limits=LaneLimits(1, 1),
        cpu_limits=LaneLimits(1, 1),
    )
    cancel = threading.Event()
    started = threading.Event()

    def worker(token, item: int) -> int:
        del token
        if item == 0:
            started.set()
            cancel.wait(1)
            cancel.set()
            return item
        return item

    try:
        with pytest.raises(OperationCancelledError):
            map_items(
                runtime,
                "cancel-batch",
                list(range(8)),
                worker,
                lane=ExecutionLane.CPU,
                cancel_check=cancel.is_set,
                max_in_flight=1,
            )
        assert started.is_set()
    finally:
        runtime.shutdown(wait=True)
