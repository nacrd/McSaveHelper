"""Settings observability text presenters."""
from __future__ import annotations

from types import SimpleNamespace

from app.presenters.runtime_observability import (
    format_cache_registry_report,
    format_diagnostic_report,
    format_runtime_snapshot,
    format_ui_delivery_summary,
)
from app.services.cache_registry import CacheStats
from app.services.execution_runtime import ExecutionLane
from app.services.operation_metrics import UiDeliveryMetricsSummary


def test_format_cache_registry_report_lists_regions() -> None:
    stats = SimpleNamespace(
        bytes_used=2048,
        budget_bytes=4096,
        regions=(
            CacheStats(
                name="world.index",
                entries=2,
                bytes_used=1024,
                max_entries=8,
                max_bytes=2048,
                hits=3,
                misses=1,
                evictions=0,
            ),
            CacheStats(
                name="mca.chunk",
                entries=10,
                bytes_used=512,
                max_entries=100,
                max_bytes=1024,
                hits=0,
                misses=5,
                evictions=0,
            ),
        ),
    )
    text = format_cache_registry_report(stats, format_size=lambda n: f"{n}B")
    assert "2048B / 4096B" in text
    assert "world.index" in text
    assert "mca.chunk" in text


def test_format_runtime_snapshot_includes_queue_wait() -> None:
    snapshot = SimpleNamespace(
        active_tasks=2,
        queue_wait_last_ms=1.5,
        queue_wait_max_ms=12.0,
        queue_wait_samples=4,
        worker_count_by_lane={ExecutionLane.IO: 2, ExecutionLane.CPU: 1},
        rejected_by_lane={ExecutionLane.IO: 0, ExecutionLane.CPU: 1},
    )
    text = format_runtime_snapshot(snapshot)
    assert "active=2" in text
    assert "max=12.00ms" in text
    assert "拒绝提交: 1" in text


def test_format_ui_delivery_summary_includes_p95_and_stale_count() -> None:
    summary = UiDeliveryMetricsSummary(
        sample_count=8,
        ok_count=6,
        stale_count=1,
        error_count=1,
        queue_wait_p95_ms=12.345,
        queue_wait_max_ms=20.0,
        run_p95_ms=1.25,
        run_max_ms=2.0,
    )

    text = format_ui_delivery_summary(summary)

    assert "samples=8" in text
    assert "stale=1" in text
    assert "p95=12.35ms" in text
    assert "p95=1.25ms" in text


def test_format_diagnostic_report_combines_snapshot_sections() -> None:
    snapshot = SimpleNamespace(
        cache=SimpleNamespace(bytes_used=1, budget_bytes=2, regions=()),
        runtime=None,
        ui_delivery=UiDeliveryMetricsSummary(sample_count=1),
        cache_path="C:/cache",
    )

    text = format_diagnostic_report(snapshot, format_size=lambda n: f"{n}B")

    assert text.startswith("MCSaveHelper 诊断报告\n")
    assert "应用缓存: 1B / 2B" in text
    assert "后台运行时: 不可用" in text
    assert "UI 投递: samples=1" in text
    assert "地图瓦片路径: C:/cache" in text
