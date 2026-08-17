"""Qt 主题与工具函数测试。"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
)

from app.qtui.components.cards import loading_placeholder
from app.qtui.components.layout import page_header
from app.qtui.theme import (
    LIGHT_THEME,
    QtThemeManager,
    apply_theme,
    build_qss,
)
from app.qtui.utils import batch_widget_updates, run_on_ui


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
    assert 'QPushButton[role="warning"]' in qss
    assert 'QPushButton[role="sectionToggle"]' in qss
    assert 'QPushButton[role="icon"]' in qss
    assert 'QLabel[role="statusChip"]' in qss
    assert 'QWidget[role="interactiveCard"]' in qss
    assert 'QWidget[role="state"]' in qss
    assert 'QProgressBar[role="stateLoading"]' in qss
    assert 'QTabBar::tab:selected' in qss
    assert 'QListWidget::item:hover' in qss
    assert 'QWidget#page_header' in qss
    assert 'QWidget[role="card"]' in qss
    assert LIGHT_THEME.warning in qss
    assert LIGHT_THEME.error in qss
    assert LIGHT_THEME.success in qss


def test_page_header_uses_theme_roles_without_nested_layouts() -> None:
    header = page_header("备份与恢复", "管理世界快照", icon="◷")
    labels = header.findChildren(QLabel)

    assert header.objectName() == "page_header"
    assert header.layout() is not None
    assert any(label.property("role") == "pageIcon" for label in labels)
    assert any(label.property("role") == "title" for label in labels)


def test_loading_placeholder_exposes_theme_roles() -> None:
    state = loading_placeholder("读取中", "正在扫描备份")
    labels = state.findChildren(QLabel)
    progress = state.findChild(QProgressBar)

    assert state.property("role") == "state"
    assert any(label.property("role") == "stateTitle" for label in labels)
    assert any(label.property("role") == "stateSubtitle" for label in labels)
    assert progress is not None
    assert progress.property("role") == "stateLoading"
    assert progress.minimum() == 0
    assert progress.maximum() == 0


def test_apply_theme_switches_app_stylesheet(qt_app: QApplication) -> None:
    colors = apply_theme(qt_app, "light")

    assert colors.mode == "light"
    assert qt_app.styleSheet() != ""


def test_apply_theme_keeps_default_widget_font_in_point_units(
    qt_app: QApplication,
) -> None:
    apply_theme(qt_app, "light")
    label = QLabel("default font")
    label.show()
    qt_app.processEvents()

    assert label.font().pointSizeF() > 0
    assert label.font().pixelSize() == -1

    label.deleteLater()


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


def test_batch_widget_updates_restores_state_and_rows(qt_app: QApplication) -> None:
    table = QTableWidget()
    table.setUpdatesEnabled(False)
    table.blockSignals(True)

    with batch_widget_updates(table):
        table.setRowCount(2)
        table.setItem(0, 0, QTableWidgetItem("a"))

    assert table.rowCount() == 2
    assert table.updatesEnabled() is False
    assert table.signalsBlocked() is True

    table.setUpdatesEnabled(True)
    table.blockSignals(False)
    with batch_widget_updates(table):
        table.setRowCount(1)
    qt_app.processEvents()
    assert table.updatesEnabled() is True
    assert table.signalsBlocked() is False
