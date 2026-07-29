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


def test_map_items_preserves_none_worker_results() -> None:
    runtime = ExecutionRuntime(
        io_limits=LaneLimits(1, 1),
        cpu_limits=LaneLimits(1, 1),
    )
    try:
        results = map_items(
            runtime,
            "none-results",
            [1, 2],
            lambda token, item: None,
            lane=ExecutionLane.CPU,
        )

        assert results == [None, None]
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


def test_map_items_drains_running_tasks_before_returning_on_cancel() -> None:
    runtime = ExecutionRuntime(
        io_limits=LaneLimits(1, 1),
        cpu_limits=LaneLimits(1, 1),
    )
    cancel = threading.Event()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def worker(token, item: int) -> int:
        del item
        started.set()
        release.wait(1)
        token.raise_if_cancelled()
        return 1

    def run_map() -> None:
        try:
            map_items(
                runtime,
                "drain-cancel",
                [1, 2],
                worker,
                lane=ExecutionLane.CPU,
                cancel_check=cancel.is_set,
                max_in_flight=2,
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=run_map)
    thread.start()
    try:
        assert started.wait(1)
        cancel.set()
        assert not finished.wait(0.1)
        release.set()
        assert finished.wait(1)
        assert errors and isinstance(errors[0], OperationCancelledError)
    finally:
        release.set()
        thread.join(timeout=1)
        runtime.shutdown(wait=True)
