"""运行时与缓存注册表的纯文本投影（设置页观测，无 Flet）。"""
from __future__ import annotations

from typing import Any, Callable, Optional, cast

from app.services.operation_metrics import UiDeliveryMetricsSummary


FormatSize = Callable[[int], str]
Translate = Callable[..., str]


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


def format_ui_delivery_summary(
    summary: UiDeliveryMetricsSummary,
    *,
    translate: Optional[Translate] = None,
) -> str:
    """将真实 UI 投递终态与调度耗时格式化为诊断文本。"""
    if summary.sample_count == 0:
        return _translate(
            translate,
            "settings.cache.ui_delivery_empty",
            "UI 投递: 暂无样本",
        )
    return _translate(
        translate,
        "settings.cache.ui_delivery_summary",
        "UI 投递: samples={samples} ok={ok} stale={stale} error={errors}\n"
        "调度等待: p95={queue_p95}ms max={queue_max}ms\n"
        "回调执行: p95={run_p95}ms max={run_max}ms",
        samples=summary.sample_count,
        ok=summary.ok_count,
        stale=summary.stale_count,
        errors=summary.error_count,
        queue_p95=f"{summary.queue_wait_p95_ms:.2f}",
        queue_max=f"{summary.queue_wait_max_ms:.2f}",
        run_p95=f"{summary.run_p95_ms:.2f}",
        run_max=f"{summary.run_max_ms:.2f}",
    )


def format_diagnostic_report(
    snapshot: Any,
    *,
    format_size: Optional[FormatSize] = None,
    translate: Optional[Translate] = None,
) -> str:
    """将设置页观测快照组织为可导出的诊断报告。"""
    cache = getattr(snapshot, "cache", None)
    runtime = getattr(snapshot, "runtime", None)
    ui_delivery = cast(
        Optional[UiDeliveryMetricsSummary],
        getattr(snapshot, "ui_delivery", None),
    )
    cache_path = str(getattr(snapshot, "cache_path", "") or "")
    title = _translate(
        translate,
        "settings.cache.report_title",
        "MCSaveHelper 诊断报告",
    )
    path_label = _translate(
        translate,
        "settings.cache.path_value",
        "地图瓦片路径: {path}",
        path=cache_path,
    )
    runtime_text = (
        format_runtime_snapshot(runtime)
        if runtime is not None
        else _translate(
            translate,
            "settings.cache.runtime_unavailable",
            "后台运行时: 不可用",
        )
    )
    ui_text = format_ui_delivery_summary(
        ui_delivery or UiDeliveryMetricsSummary(),
        translate=translate,
    )
    return "\n\n".join(
        (
            title,
            format_cache_registry_report(cache, format_size=format_size),
            runtime_text,
            ui_text,
            path_label,
        )
    ) + "\n"


def _translate(
    translate: Optional[Translate],
    key: str,
    fallback: str,
    **kwargs: object,
) -> str:
    if translate is not None:
        return translate(key, fallback, **kwargs)
    return fallback.format(**kwargs)


__all__ = [
    "format_cache_registry_report",
    "format_diagnostic_report",
    "format_runtime_snapshot",
    "format_ui_delivery_summary",
]
