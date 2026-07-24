"""Tests for GUIOptimizer's explicit configuration dependencies."""
from types import SimpleNamespace
from typing import Any, cast

import flet as ft

from app.core.gui_optimizer import GUIOptimizer, GUIOptimizerDependencies
from core.observability import OperationRecord
from core.performance import PerformanceMetrics


def test_gui_optimizer_saves_config_without_application() -> None:
    saved = []
    settings = {
        "enable_performance_monitor": False,
        "performance_print_interval": 30,
    }
    optimizer = GUIOptimizer(GUIOptimizerDependencies(
        page=cast(ft.Page, SimpleNamespace()),
        get_ui_setting=lambda key, default: settings.get(key, default),
        save_config=lambda: saved.append("saved"),
    ))

    optimizer._shortcut_save_config(None)

    assert saved == ["saved"]
    assert optimizer._deps.get_ui_setting(
        "performance_print_interval",
        60,
    ) == 30


def test_gui_optimizer_owns_performance_monitor_lifecycle(monkeypatch) -> None:
    calls = []
    performance = SimpleNamespace(
        enable=lambda: calls.append("enable"),
        disable=lambda: calls.append("disable"),
        enabled=False,
        record=lambda *args, **kwargs: None,
    )
    resources = SimpleNamespace(
        start=lambda: calls.append("start"),
        stop=lambda: calls.append("stop"),
        set_print_interval=lambda value: calls.append(("interval", value)),
    )
    health = SimpleNamespace(
        set_alert_callback=lambda callback: calls.append("callback"),
        heartbeat=lambda: None,
    )
    optimizer = GUIOptimizer(GUIOptimizerDependencies(
        page=cast(ft.Page, SimpleNamespace()),
        get_ui_setting=lambda key, default: default,
        save_config=lambda: None,
        performance_monitor=cast(Any, performance),
        resource_monitor=cast(Any, resources),
        health_monitor=cast(Any, health),
    ))

    monkeypatch.setattr(
        optimizer,
        "_start_heartbeat",
        lambda: calls.append("heartbeat_start"),
    )
    monkeypatch.setattr(
        optimizer,
        "_stop_performance_heartbeat",
        lambda: calls.append("heartbeat_stop"),
    )

    optimizer.configure_performance_monitor(True, 12)
    optimizer.configure_performance_monitor(False, 12)

    assert calls == [
        ("interval", 12),
        "enable",
        "callback",
        "start",
        "heartbeat_start",
        ("interval", 12),
        "disable",
        "stop",
        "heartbeat_stop",
    ]


def test_gui_optimizer_records_business_metric_in_shared_store() -> None:
    stored: list[PerformanceMetrics] = []
    presented: list[OperationRecord] = []
    performance = SimpleNamespace(
        enabled=True,
        record_operation=presented.append,
        record=lambda *args, **kwargs: None,
    )

    def store(metrics: PerformanceMetrics) -> OperationRecord:
        stored.append(metrics)
        return metrics.to_operation_record(feature="business")

    optimizer = GUIOptimizer(GUIOptimizerDependencies(
        page=cast(ft.Page, SimpleNamespace()),
        get_ui_setting=lambda key, default: default,
        save_config=lambda: None,
        operation_metrics_sink=store,
        performance_monitor=cast(Any, performance),
    ))
    metrics = PerformanceMetrics(
        operation="scan",
        duration_seconds=0.01,
        memory_peak_mb=0.0,
        memory_delta_mb=0.0,
    )

    optimizer._record_business_metric(metrics)

    assert stored == [metrics]
    assert len(presented) == 1
    assert presented[0].metadata == {}
