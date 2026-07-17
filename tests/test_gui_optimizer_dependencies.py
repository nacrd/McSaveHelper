"""Tests for GUIOptimizer's explicit configuration dependencies."""
from types import SimpleNamespace
from typing import cast

import flet as ft

from app.core.gui_optimizer import GUIOptimizer, GUIOptimizerDependencies


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
    optimizer = GUIOptimizer(GUIOptimizerDependencies(
        page=cast(ft.Page, SimpleNamespace()),
        get_ui_setting=lambda key, default: default,
        save_config=lambda: None,
    ))

    monkeypatch.setattr(
        "app.core.gui_optimizer.perf_monitor.enable",
        lambda: calls.append("enable"),
    )
    monkeypatch.setattr(
        "app.core.gui_optimizer.perf_monitor.disable",
        lambda: calls.append("disable"),
    )
    monkeypatch.setattr(
        "app.core.gui_optimizer.resource_monitor.start",
        lambda: calls.append("start"),
    )
    monkeypatch.setattr(
        "app.core.gui_optimizer.resource_monitor.stop",
        lambda: calls.append("stop"),
    )
    monkeypatch.setattr(
        "app.core.gui_optimizer.resource_monitor.set_print_interval",
        lambda value: calls.append(("interval", value)),
    )
    monkeypatch.setattr(
        "app.core.gui_optimizer.health_monitor.set_alert_callback",
        lambda callback: calls.append("callback"),
    )
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
