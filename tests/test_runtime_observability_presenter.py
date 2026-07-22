"""Settings observability text presenters."""
from __future__ import annotations

from types import SimpleNamespace

from app.presenters.runtime_observability import (
    format_cache_registry_report,
    format_runtime_snapshot,
)
from app.services.cache_registry import CacheStats
from app.services.execution_runtime import ExecutionLane


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
