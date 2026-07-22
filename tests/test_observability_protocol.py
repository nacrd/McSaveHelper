"""Unified observability protocol and UI adapter."""
from __future__ import annotations

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
