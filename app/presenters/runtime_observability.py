"""运行时与缓存注册表的纯文本投影（设置页观测，无 Flet）。"""
from __future__ import annotations

from typing import Any, Callable, Optional


FormatSize = Callable[[int], str]


def format_cache_registry_report(
    stats: Any,
    *,
    format_size: Optional[FormatSize] = None,
    top_n: int = 8,
) -> str:
    """将 CacheRegistry.stats() 格式化为多行摘要。"""
    size_fmt = format_size or (lambda n: f"{int(n)} B")
    used = int(getattr(stats, "bytes_used", 0) or 0)
    budget = int(getattr(stats, "budget_bytes", 0) or 0)
    regions = tuple(getattr(stats, "regions", ()) or ())
    lines = [
        f"应用缓存: {size_fmt(used)} / {size_fmt(budget)}",
        f"受管分区: {len(regions)}",
    ]
    ordered = sorted(
        regions,
        key=lambda item: int(getattr(item, "bytes_used", 0) or 0),
        reverse=True,
    )
    for region in ordered[: max(1, top_n)]:
        name = str(getattr(region, "name", "?"))
        bytes_used = int(getattr(region, "bytes_used", 0) or 0)
        entries = int(getattr(region, "entries", 0) or 0)
        hits = int(getattr(region, "hits", 0) or 0)
        misses = int(getattr(region, "misses", 0) or 0)
        lines.append(
            f"  · {name}: {size_fmt(bytes_used)} "
            f"({entries} entries, hit {hits}/miss {misses})"
        )
    return "\n".join(lines)


def format_runtime_snapshot(snapshot: Any) -> str:
    """将 ExecutionRuntime.snapshot() 格式化为多行摘要。"""
    active = int(getattr(snapshot, "active_tasks", 0) or 0)
    wait_last = float(getattr(snapshot, "queue_wait_last_ms", 0.0) or 0.0)
    wait_max = float(getattr(snapshot, "queue_wait_max_ms", 0.0) or 0.0)
    wait_n = int(getattr(snapshot, "queue_wait_samples", 0) or 0)
    workers = getattr(snapshot, "worker_count_by_lane", {}) or {}
    rejected = getattr(snapshot, "rejected_by_lane", {}) or {}
    worker_text = ", ".join(
        f"{getattr(lane, 'value', lane)}={count}"
        for lane, count in workers.items()
    ) or "—"
    rejected_total = 0
    try:
        rejected_total = sum(int(value) for value in rejected.values())
    except (TypeError, ValueError):
        rejected_total = 0
    return (
        f"后台任务: active={active}\n"
        f"工作线程: {worker_text}\n"
        f"队列等待: last={wait_last:.2f}ms max={wait_max:.2f}ms "
        f"samples={wait_n}\n"
        f"拒绝提交: {rejected_total}"
    )


__all__ = [
    "format_cache_registry_report",
    "format_runtime_snapshot",
]
