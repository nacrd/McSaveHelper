from types import SimpleNamespace
from typing import cast

from app.ui.performance import health_monitor, perf_monitor, resource_monitor
from app.ui.performance.resource import (
    HealthMonitorPort,
    PerformanceMonitorPort,
    ResourceUsageMonitor,
)
from core.performance import PerfTracker


def test_perf_tracker_publishes_metrics_without_ui_dependency() -> None:
    published = []
    tracker = PerfTracker(metrics_sink=published.append)

    with tracker.track("scan", {"dimension": "overworld"}):
        tracker.increment_files(2)
        tracker.increment_bytes(1024)

    assert len(published) == 1
    assert published[0].operation == "scan"
    assert published[0].files_processed == 2
    assert published[0].bytes_processed == 1024


def test_global_resource_monitor_uses_shared_monitors() -> None:
    assert resource_monitor._performance_monitor is perf_monitor
    assert resource_monitor._health_monitor is health_monitor


def test_resource_sample_is_sent_to_injected_monitors() -> None:
    recorded = []
    checked = []
    performance = cast(PerformanceMonitorPort, SimpleNamespace(
        record=lambda *args, **kwargs: recorded.append((args, kwargs)),
        summary=lambda: {},
        get_memory_usage=lambda: 0.0,
        get_cpu_percent=lambda: 0.0,
    ))
    health = cast(HealthMonitorPort, SimpleNamespace(
        check=lambda *args, **kwargs: checked.append((args, kwargs)),
    ))
    monitor = ResourceUsageMonitor(
        print_interval=0,
        performance_monitor=performance,
        health_monitor=health,
    )
    monitor._process = SimpleNamespace(
        memory_info=lambda: SimpleNamespace(rss=64 * 1024 * 1024),
        cpu_percent=lambda: 25.0,
    )

    monitor._sample_metrics()

    assert [entry[0][:3] for entry in recorded] == [
        ("memory_usage", 64.0, "MB"),
        ("cpu_usage", 25.0, "%"),
    ]
    assert checked == [((25.0, 64.0), {})]
