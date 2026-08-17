"""Qt 日志面板测试。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading

import pytest
from PySide6.QtCore import QDateTime, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

import app.qtui.log_panel as log_panel_module
from app.qtui.log_alerts import QtAlertDialog
from app.qtui.log_panel import QtLogPanel, install_qt_log_handler
from app.qtui.log_viewer_support import LogWorker
from app.services.log_alert_service import AlertRule, AlertService
from app.services.log_query_service import LogQueryService
from core.logger import logger
from core.logging.models import LogLevel, LogRecord
from core.logging.storage import (
    JsonlLogStore,
    LogPage,
    LogQuery,
    LogStatistics,
    LogTrendPoint,
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
    assert panel._live_refresh_timer.isActive() is False
    assert panel._new_count == 1
    panel._live_refresh_timer.stop()
    panel.dispose()


def test_log_handler_batches_main_thread_delivery(
    qt_app: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_app
    scheduled: list[tuple[object, tuple[object, ...]]] = []
    monkeypatch.setattr(
        log_panel_module,
        "run_on_ui",
        lambda callback, *args: scheduled.append((callback, args)),
    )
    panel = QtLogPanel("日志")

    for index in range(100):
        panel.append_record(
            LogRecord(datetime.now().astimezone(), LogLevel.INFO, f"line-{index}")
        )

    assert len(scheduled) == 1
    callback, args = scheduled[0]
    assert callable(callback)
    callback(*args)
    assert panel._content.toPlainText().count("line-") == 100
    panel.dispose()


def test_live_reload_does_not_recompute_statistics(qt_app: object) -> None:
    del qt_app

    class QueryProbe(LogQueryService):
        def __init__(self) -> None:
            self.query_count = 0
            self.statistics_count = 0

        def query(self, query: LogQuery) -> LogPage:
            del query
            self.query_count += 1
            return LogPage((), 0, 0, None)

        def statistics(self, start: datetime, end: datetime) -> LogStatistics:
            del start, end
            self.statistics_count += 1
            return LogStatistics(0, {}, ())

    probe = QueryProbe()
    panel = QtLogPanel("日志", query_service=probe)
    panel.reload(include_statistics=False)
    assert panel._pool.waitForDone(2000)
    QApplication.processEvents()

    assert probe.query_count == 1
    assert probe.statistics_count == 0
    panel.dispose()


def test_non_live_panel_loads_history_when_first_shown(
    qt_app: object,
    tmp_path: Path,
) -> None:
    del qt_app
    panel = QtLogPanel(
        "日志",
        query_service=LogQueryService(JsonlLogStore(tmp_path)),
    )
    panel._live_mode = False

    panel._on_visibility_changed(True)

    assert panel._has_loaded_once is True
    assert panel._pool.waitForDone(2000)
    QApplication.processEvents()
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


def test_dispose_cancels_delivery_from_running_log_worker(
    qt_app: object,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    results: list[object] = []
    panel = QtLogPanel("日志")

    def operation() -> object:
        entered.set()
        release.wait(timeout=2.0)
        return "late"

    worker = LogWorker(operation)
    worker.signals.finished.connect(results.append)
    panel._start_worker(worker)
    assert entered.wait(timeout=2.0)

    panel.dispose()
    release.set()
    assert panel._pool.waitForDone(2000)

    assert results == []
