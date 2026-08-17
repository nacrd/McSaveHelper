"""Qt 日志面板测试。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDateTime

from app.qtui.log_alerts import QtAlertDialog
from app.qtui.log_panel import QtLogPanel, install_qt_log_handler
from app.services.log_alert_service import AlertRule, AlertService
from app.services.log_query_service import LogQueryService
from core.logger import logger
from core.logging.models import LogLevel, LogRecord
from core.logging.storage import JsonlLogStore, LogStatistics, LogTrendPoint


def test_log_panel_appends_escaped_text_and_bounds_history(qt_app: object) -> None:
    del qt_app
    panel = QtLogPanel("日志")

    panel._append("<unsafe>", "error")
    assert "unsafe" in panel._content.toPlainText()
    assert "<unsafe>" not in panel._content.toHtml()
    for index in range(panel.MAX_LINES + 5):
        panel._append(f"line {index}", "info")

    assert panel._content.document().blockCount() == panel.MAX_LINES
    panel.dispose()


def test_log_handler_is_explicitly_removable(qt_app: object) -> None:
    del qt_app
    panel = QtLogPanel("日志")
    handler = install_qt_log_handler(panel)

    assert handler in logger.handlers
    logger.remove_handler(handler)
    assert handler not in logger.handlers
    panel.dispose()


def test_log_views_use_injected_application_translations(
    qt_app: object,
    tmp_path: Path,
) -> None:
    del qt_app

    def translate(key: str, default: str = "", **kwargs: object) -> str:
        del default
        suffix = f":{kwargs['count']}" if "count" in kwargs else ""
        return f"translated:{key}{suffix}"

    panel = QtLogPanel("日志", translate=translate)
    alert_service = AlertService(JsonlLogStore(tmp_path))
    alert_service.create_rule(AlertRule(name="Paused", enabled=False))
    dialog = QtAlertDialog(alert_service, translate=translate)
    dialog._rules.setCurrentRow(0)

    assert panel._keyword.placeholderText() == "translated:log_panel.keyword"
    assert panel._total_label.text() == "translated:log_panel.today_total:-"
    assert dialog.windowTitle() == "translated:log_alerts.title"
    assert dialog._enabled.text() == "translated:log_alerts.enabled"
    assert dialog._enabled.isChecked() is False
    panel.dispose()
    dialog.close()


def test_log_statistics_show_level_percentages(qt_app: object) -> None:
    del qt_app
    panel = QtLogPanel("日志")
    today = datetime.now().astimezone().date()
    statistics = LogStatistics(
        total=4,
        by_category={"INFO": 3, "ERROR": 1},
        trend=(LogTrendPoint(today, 4, {"INFO": 3, "ERROR": 1}),),
    )

    panel._on_stats(panel._generation, statistics)

    assert panel._level_bars["INFO"].value() == 75
    assert panel._level_bars["ERROR"].value() == 25
    panel.dispose()


def test_live_record_advances_query_end_time(
    qt_app: object,
    tmp_path: Path,
) -> None:
    del qt_app
    panel = QtLogPanel(
        "日志",
        query_service=LogQueryService(JsonlLogStore(tmp_path)),
    )
    old_end = QDateTime.currentDateTime().addDays(-10)
    panel._end_edit.setDateTime(old_end)

    panel._append_record_ui(
        LogRecord(datetime.now().astimezone(), LogLevel.INFO, "new")
    )

    assert panel._end_edit.dateTime() > old_end
    panel._live_refresh_timer.stop()
    panel.dispose()
