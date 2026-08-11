"""Qt 主题与工具函数测试。"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from app.qtui.theme import (
    LIGHT_THEME,
    QtThemeManager,
    apply_theme,
    build_qss,
)
from app.qtui.utils import run_on_ui


def test_build_qss_contains_theme_colors() -> None:
    qss = build_qss(LIGHT_THEME)

    assert LIGHT_THEME.bg_primary in qss
    assert LIGHT_THEME.accent in qss
    assert LIGHT_THEME.text_primary in qss
    assert "QPushButton" in qss
    assert "QLineEdit" in qss


def test_build_qss_defines_status_roles() -> None:
    qss = build_qss(LIGHT_THEME)

    assert 'QLabel[role="warning"]' in qss
    assert 'QLabel[role="error"]' in qss
    assert 'QLabel[role="success"]' in qss
    assert 'QPushButton:checked' in qss
    assert 'QTabBar::tab:selected' in qss
    assert 'QListWidget::item:hover' in qss
    assert LIGHT_THEME.warning in qss
    assert LIGHT_THEME.error in qss
    assert LIGHT_THEME.success in qss


def test_apply_theme_switches_app_stylesheet(qt_app: QApplication) -> None:
    colors = apply_theme(qt_app, "light")

    assert colors.mode == "light"
    assert qt_app.styleSheet() != ""


def test_theme_manager_ignores_duplicate_mode() -> None:
    manager = QtThemeManager()
    initial = manager.mode

    manager.set_mode(initial)

    assert manager.mode == initial


def test_theme_manager_raises_on_unknown_mode() -> None:
    manager = QtThemeManager()

    with pytest.raises(ValueError):
        manager.set_mode("solarized")


def test_theme_manager_toggle_and_listeners() -> None:
    manager = QtThemeManager()
    events: list[str] = []
    manager.register_listener(events.append)
    previous = manager.mode

    new_mode = manager.toggle()

    assert new_mode != previous
    assert events == [new_mode]
    manager.unregister_listener(events.append)
    manager.set_mode(previous)
    assert events == [new_mode]


def test_run_on_ui_dispatches_callback_from_current_thread(
    qt_app: QApplication,
) -> None:
    received: list[int] = []

    run_on_ui(lambda value: received.append(value), 42)

    # 信号经事件队列投递，处理一次事件循环后生效。
    qt_app.processEvents()
    assert received == [42]


def test_run_on_ui_ignores_non_callable(qt_app: QApplication) -> None:
    run_on_ui("not-a-callable")  # type: ignore[arg-type]
    qt_app.processEvents()
