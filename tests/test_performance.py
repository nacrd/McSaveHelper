from types import SimpleNamespace
from typing import cast
import threading

from app.ui.performance import health_monitor, perf_monitor, resource_monitor
from app.ui.performance.resource import (
    HealthMonitorPort,
    PerformanceMonitorPort,
    ResourceUsageMonitor,
)
from app.ui.hang_detector import HangDetector
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


def test_perf_tracker_supports_nested_operations() -> None:
    tracker = PerfTracker()
    with tracker.track("outer"):
        tracker.increment_files()
        with tracker.track("inner"):
            tracker.increment_files(2)
        tracker.increment_files()

    outer = tracker.get_metrics("outer")
    inner = tracker.get_metrics("inner")
    assert outer is not None
    assert inner is not None
    assert outer.files_processed == 2
    assert inner.files_processed == 2


def test_perf_tracker_separates_concurrent_operations() -> None:
    tracker = PerfTracker()
    barrier = threading.Barrier(2)

    def run(name: str, count: int) -> None:
        with tracker.track(name):
            barrier.wait(timeout=2)
            tracker.increment_files(count)

    threads = [
        threading.Thread(target=run, args=("first", 1)),
        threading.Thread(target=run, args=("second", 2)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    first = tracker.get_metrics("first")
    second = tracker.get_metrics("second")
    assert first is not None
    assert second is not None
    assert first.files_processed == 1
    assert second.files_processed == 2


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


def test_resource_monitor_stop_interrupts_long_sample_wait() -> None:
    sampled = threading.Event()
    performance = cast(PerformanceMonitorPort, SimpleNamespace(
        record=lambda *args, **kwargs: sampled.set(),
        summary=lambda: {},
        get_memory_usage=lambda: 0.0,
        get_cpu_percent=lambda: 0.0,
    ))
    health = cast(HealthMonitorPort, SimpleNamespace(
        check=lambda *args, **kwargs: None,
    ))
    monitor = ResourceUsageMonitor(
        sample_interval=60,
        performance_monitor=performance,
        health_monitor=health,
    )
    monitor._process = SimpleNamespace(
        memory_info=lambda: SimpleNamespace(rss=1024),
        cpu_percent=lambda: 0.0,
    )

    monitor.start()
    thread = monitor._thread
    assert sampled.wait(timeout=2)
    monitor.stop()

    assert thread is not None
    assert thread.is_alive() is False
    assert monitor._thread is None


def test_hang_detector_disable_interrupts_detection_wait() -> None:
    detector = HangDetector()

    detector.enable()
    thread = detector._thread
    detector.disable()
    detector.disable()

    assert thread is not None
    assert thread.is_alive() is False
    assert detector._thread is None
