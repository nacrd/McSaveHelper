"""Qt 日志面板测试。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDateTime, QEventLoop, QTimer, Qt

from app.qtui.log_alerts import QtAlertDialog
from app.qtui.log_panel import QtLogPanel, install_qt_log_handler
from app.qtui.log_viewer_support import LogWorker
from app.services.log_alert_service import AlertRule, AlertService
from app.services.log_query_service import LogQueryService
from core.logger import logger
from core.logging.models import LogLevel, LogRecord
from core.logging.storage import (
    JsonlLogStore,
    LogStatistics,
    LogTrendPoint,
    StoredLog,
)


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


def test_log_worker_is_owned_until_queued_result_is_delivered(
    qt_app: object,
) -> None:
    del qt_app
    panel = QtLogPanel("日志")
    loop = QEventLoop()
    results: list[object] = []
    worker = LogWorker(lambda: "done")
    worker.signals.finished.connect(results.append)
    worker.signals.finished.connect(lambda _result: loop.quit())

    panel._start_worker(worker)

    assert panel._active_workers == {id(worker): worker}
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    assert results == ["done"]
    assert panel._active_workers == {}
    panel.dispose()


def test_log_table_exposes_runtime_context_and_exception_details(
    qt_app: object,
) -> None:
    del qt_app
    panel = QtLogPanel("日志")
    entry = StoredLog(
        record_id="test:0",
        source_file="app.jsonl",
        source_offset=0,
        timestamp=datetime(2026, 1, 2, 3, 4, 5, 678000),
        timestamp_utc_us=0,
        level="ERROR",
        category="ERROR",
        module="Core",
        logger_name="core.worker",
        process_id=1234,
        thread_id=5678,
        thread_name="worker-1",
        message="请求失败",
        exception_type="TimeoutError",
        exception_message="deadline exceeded",
        stack_trace="Traceback...",
    )
    panel._model.replace((entry,))

    values = [
        panel._model.data(panel._model.index(0, column))
        for column in range(panel._model.columnCount())
    ]

    assert values == [
        "2026-01-02 03:04:05.678",
        "ERROR",
        "Core",
        "core.worker",
        "1234",
        "worker-1 [5678]",
        "TimeoutError",
        "请求失败",
    ]
    assert panel._model.data(
        panel._model.index(0, 6), Qt.ItemDataRole.ToolTipRole
    ) == "Traceback..."
    panel.dispose()
