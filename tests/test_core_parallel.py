"""core.parallel bounds and map helpers."""
from __future__ import annotations

import threading

from core.parallel import (
    ABSOLUTE_MAX_WORKERS,
    bounded_executor,
    clamp_workers,
    map_unordered,
)


def test_clamp_workers_hard_cap() -> None:
    assert clamp_workers(100, item_count=50) <= ABSOLUTE_MAX_WORKERS
    assert clamp_workers(None, item_count=3) == 3
    assert clamp_workers(0, item_count=5) == 1
    assert clamp_workers(4, item_count=2) == 2


def test_map_unordered_preserves_results() -> None:
    results = map_unordered([1, 2, 3, 4], lambda n: n * n, max_workers=2)
    assert sorted(results) == [1, 4, 9, 16]


def test_map_unordered_empty_and_single() -> None:
    assert map_unordered([], lambda n: n) == []
    assert map_unordered([7], lambda n: n + 1) == [8]


def test_bounded_executor_applies_cap_and_thread_prefix() -> None:
    with bounded_executor(max_workers=99, item_count=3) as executor:
        futures = [
            executor.submit(lambda: threading.current_thread().name)
            for _ in range(3)
        ]
        names = [future.result(timeout=1) for future in futures]

    assert len(set(names)) <= ABSOLUTE_MAX_WORKERS
    assert all(name.startswith("MCSaveCore") for name in names)
