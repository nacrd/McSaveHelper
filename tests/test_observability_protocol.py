"""Unified observability protocol and UI adapter."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from core.observability import (
    OperationOutcome,
    metrics_to_operation_record,
    p95,
    percentile,
)
from core.performance import PerformanceMetrics, PerfTracker
from app.ui.performance.monitor import PerformanceMonitor


def test_metrics_to_operation_record_maps_fields() -> None:
    metrics = PerformanceMetrics(
        operation="scan_world",
        duration_seconds=0.125,
        memory_peak_mb=10.0,
        memory_delta_mb=1.0,
        files_processed=3,
        bytes_processed=1024,
        errors=0,
        metadata={"world_id": "/tmp/w", "cache_hits": 2, "cache_misses": 1},
    )
    record = metrics.to_operation_record(feature="stats")
    assert record.operation_id == "scan_world"
    assert record.feature == "stats"
    assert record.world_id == "/tmp/w"
    assert record.run_ms == 125.0
    assert record.files_processed == 3
    assert record.cache_hits == 2
    assert record.outcome is OperationOutcome.OK


def test_perf_tracker_sink_receives_metrics() -> None:
    published: list[PerformanceMetrics] = []
    tracker = PerfTracker(metrics_sink=published.append)
    with tracker.track("unit", {"k": "v"}):
        tracker.increment_files(2)
    assert len(published) == 1
    assert published[0].operation == "unit"
    assert published[0].files_processed == 2


def test_perf_tracker_publishes_independent_samples_and_keeps_aggregate() -> None:
    published: list[PerformanceMetrics] = []
    tracker = PerfTracker(metrics_sink=published.append)

    with tracker.track("repeat", {"run": "first"}):
        tracker.increment_files(2)
    with tracker.track("repeat", {"run": "second"}):
        tracker.increment_files(3)

    assert len(published) == 2
    assert published[0] is not published[1]
    assert [sample.files_processed for sample in published] == [2, 3]
    assert [sample.metadata["run"] for sample in published] == [
        "first",
        "second",
    ]
    aggregate = tracker.get_metrics("repeat")
    assert aggregate is not None
    assert aggregate.files_processed == 5
    assert aggregate.duration_seconds >= sum(
        sample.duration_seconds for sample in published
    )


def test_perf_tracker_isolates_concurrent_samples_for_same_operation() -> None:
    published: list[PerformanceMetrics] = []
    tracker = PerfTracker(metrics_sink=published.append)
    barrier = threading.Barrier(2)

    def run_sample(files: int) -> None:
        with tracker.track("concurrent"):
            tracker.increment_files(files)
            barrier.wait(timeout=2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_sample, files) for files in (2, 3)]
        for future in futures:
            future.result(timeout=2)

    assert sorted(sample.files_processed for sample in published) == [2, 3]
    aggregate = tracker.get_metrics("concurrent")
    assert aggregate is not None
    assert aggregate.files_processed == 5


def test_ui_monitor_records_operation_protocol() -> None:
    monitor = PerformanceMonitor()
    monitor.enable()
    record = metrics_to_operation_record(
        PerformanceMetrics(
            operation="tile",
            duration_seconds=0.03,
            memory_peak_mb=0.0,
            memory_delta_mb=0.0,
            files_processed=1,
            bytes_processed=64,
        ),
        feature="map",
    )
    monitor.record_operation(record)
    stored = monitor.get_metrics("operation.tile")
    assert len(stored) == 1
    assert stored[0].value == 30.0
    assert stored[0].metadata["feature"] == "map"


def test_p95_percentile() -> None:
    samples = [10.0, 20.0, 30.0, 40.0, 100.0]
    assert percentile(samples, 0.5) == 30.0
    assert p95(samples) >= 40.0
    assert p95([]) == 0.0
