"""Qt log viewer dock with filtering, details, statistics, and live updates."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Callable, Optional

from PySide6.QtCore import (
    QDateTime,
    QModelIndex,
    QSettings,
    QThreadPool,
    QTimer,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStyle,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.qtui.log_viewer_support import (
    LOG_COLORS,
    LogTableModel,
    LogTrendChart,
    LogWorker,
)
from app.qtui.utils import run_on_ui
from app.services.log_alert_service import AlertService
from app.services.log_query_service import LogExportService, LogQueryService
from core.logging.handlers import LogHandler
from core.logging.models import LogLevel, LogRecord
from core.logging.storage import (
    LogPage,
    LogQuery,
    LogStatistics,
    StoredLog,
    _category_for_level,
    stored_to_payload,
)


class _QtLogHandler(LogHandler):
    """将结构化记录安全投递到日志面板。"""

    def __init__(self, panel: "QtLogPanel") -> None:
        super().__init__(LogLevel.DEBUG)
        self._panel = panel

    def handle(self, record: LogRecord) -> None:
        self._panel.append_record(record)

    def close(self) -> None:
        self._panel.dispose()


class QtLogPanel(QDockWidget):
    """显示本地 JSONL 日志的可停靠、可筛选面板。"""

    MAX_LINES = 300

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        query_service: LogQueryService | None = None,
        export_service: LogExportService | None = None,
        alert_service: AlertService | None = None,
        settings: QSettings | None = None,
        clear_logs: Callable[[], int] | None = None,
        translate: Callable[..., str] | None = None,
    ) -> None:
        super().__init__(title, parent)
        self.setObjectName("log_panel")
        self.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self._query_service = query_service
        self._export_service = export_service
        self._alert_service = alert_service
        self._settings = settings
        self._clear_logs = clear_logs
        self._translate = translate
        self._alert_dialog: QWidget | None = None
        self._pool = QThreadPool.globalInstance()
        self._generation = 0
        self._disposed = False
        self._live_mode = True
        self._new_count = 0
        self._selected: Optional[StoredLog] = None
        self._current_query = LogQuery()
        self._live_refresh_timer = QTimer(self)
        self._live_refresh_timer.setSingleShot(True)
        self._live_refresh_timer.setInterval(100)
        self._live_refresh_timer.timeout.connect(self.reload)
        self._build_ui(title)
        self._restore_settings()

    def _t(self, key: str, default: str, **kwargs: object) -> str:
        """Translate through the application catalog with a Qt fallback."""
        fallback = self.tr(default)
        if self._translate is not None:
            return self._translate(key, fallback, **kwargs)
        return fallback.format(**kwargs) if kwargs else fallback

    def _build_ui(self, title: str) -> None:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addLayout(self._build_stats())
        layout.addLayout(self._build_filters())

        self._table = QTableView()
        self._model = LogTableModel(
            self._table,
            tuple(
                self._t(f"log_panel.column_{key}", label)
                for key, label in (
                    ("time", "时间"),
                    ("level", "级别"),
                    ("module", "模块"),
                    ("message", "消息"),
                    ("thread", "线程"),
                )
            ),
        )
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(False)
        self._table.clicked.connect(self._on_row_clicked)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 4)

        detail_label = QLabel(self._t("log_panel.details", "日志详情"))
        layout.addWidget(detail_label)
        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        self._details.setMaximumHeight(150)
        layout.addWidget(self._details, 1)

        self._content = QTextEdit()
        self._content.setReadOnly(True)
        self._content.document().setMaximumBlockCount(self.MAX_LINES)
        self._content.setVisible(False)
        layout.addWidget(self._content)

        actions = QHBoxLayout()
        clear_button = QToolButton()
        clear_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton))
        clear_button.setToolTip(self._t("log_panel.clear", "清空日志"))
        clear_button.clicked.connect(self._clear_persisted)
        actions.addWidget(clear_button)
        self._export_button = QPushButton(
            self._t("log_panel.export", "导出筛选结果")
        )
        self._export_button.clicked.connect(self._export)
        actions.addWidget(self._export_button)
        self._copy_button = QPushButton(
            self._t("log_panel.copy", "复制选中日志")
        )
        self._copy_button.clicked.connect(self._copy_selected)
        actions.addWidget(self._copy_button)
        aggregate_button = QPushButton(
            self._t("log_panel.aggregate", "异常聚合")
        )
        aggregate_button.clicked.connect(self._show_aggregates)
        actions.addWidget(aggregate_button)
        if self._alert_service is not None:
            alert_button = QPushButton(
                self._t("log_panel.alert_rules", "告警规则")
            )
            alert_button.clicked.connect(self._open_alerts)
            actions.addWidget(alert_button)
        actions.addStretch(1)
        self._new_logs_button = QPushButton()
        self._new_logs_button.setVisible(False)
        self._new_logs_button.clicked.connect(self._reload_after_new_logs)
        actions.addWidget(self._new_logs_button)
        self._loading = QProgressBar()
        self._loading.setRange(0, 0)
        self._loading.setMaximumWidth(80)
        self._loading.setVisible(False)
        actions.addWidget(self._loading)
        self._status = QLabel(
            self._t("log_panel.empty", "暂无日志，应用启动后将自动记录")
        )
        actions.addWidget(self._status, 1)
        layout.addLayout(actions)
        self.setWidget(host)
        self.resize(760, 430)

    def _build_stats(self) -> QHBoxLayout:
        stats = QHBoxLayout()
        self._total_label = QLabel(
            self._t("log_panel.today_total", "今日总量：{count}", count="-")
        )
        stats.addWidget(self._total_label)
        self._level_bars: dict[str, QProgressBar] = {}
        for category in ("DEBUG", "INFO", "WARN", "ERROR", "FATAL"):
            bar = QProgressBar()
            bar.setFormat(f"{category} %p%")
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setMaximumWidth(130)
            bar.setToolTip(self._t("log_panel.level_share", "级别占比"))
            self._level_bars[category] = bar
            stats.addWidget(bar)
        self._trend_chart = LogTrendChart()
        self._trend_chart.setToolTip(
            self._t("log_panel.seven_day_trend", "近 7 天日志趋势")
        )
        stats.addWidget(self._trend_chart, 1)
        return stats

    def _build_filters(self) -> QHBoxLayout:
        filters = QHBoxLayout()
        self._level_combo = QComboBox()
        for key, label, value in (
            ("all", "全部", ""),
            ("debug", "调试", "DEBUG"),
            ("info", "信息", "INFO"),
            ("warn", "警告", "WARN"),
            ("error", "错误", "ERROR"),
            ("fatal", "严重", "FATAL"),
        ):
            self._level_combo.addItem(
                self._t(f"log_panel.level_{key}", label), value
            )
        filters.addWidget(self._level_combo)
        self._start_edit = QDateTimeEdit(QDateTime.currentDateTime().addDays(-1))
        self._start_edit.setCalendarPopup(True)
        self._start_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        filters.addWidget(self._start_edit)
        self._end_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self._end_edit.setCalendarPopup(True)
        self._end_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        filters.addWidget(self._end_edit)
        self._keyword = QLineEdit()
        self._keyword.setPlaceholderText(
            self._t("log_panel.keyword", "关键词")
        )
        filters.addWidget(self._keyword, 1)
        self._module = QLineEdit()
        self._module.setPlaceholderText(self._t("log_panel.module", "模块"))
        filters.addWidget(self._module)
        filter_button = QPushButton(self._t("log_panel.filter", "筛选"))
        filter_button.clicked.connect(self.reload)
        filters.addWidget(filter_button)
        self._realtime = QPushButton(self._t("log_panel.realtime", "实时"))
        self._realtime.setCheckable(True)
        self._realtime.setChecked(True)
        self._realtime.toggled.connect(self._set_realtime)
        filters.addWidget(self._realtime)
        return filters

    def _datetime_value(self, editor: QDateTimeEdit) -> datetime:
        seconds = editor.dateTime().toSecsSinceEpoch()
        return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone()

    def _build_query(self) -> LogQuery:
        level = str(self._level_combo.currentData() or "")
        return LogQuery(
            levels=frozenset({level}) if level else frozenset(),
            start=self._datetime_value(self._start_edit),
            end=self._datetime_value(self._end_edit) + timedelta(minutes=1),
            keyword=self._keyword.text().strip(),
            module=self._module.text().strip(),
            limit=300,
            descending=False,
        )

    def reload(self) -> None:
        """后台重新加载当前筛选条件。"""
        if self._query_service is None or self._disposed:
            return
        self._generation += 1
        generation = self._generation
        self._current_query = self._build_query()
        self._status.setText(self._t("log_panel.loading", "加载中…"))
        self._loading.setVisible(True)
        query = self._current_query
        query_service = self._query_service
        assert query_service is not None
        worker = LogWorker(lambda: query_service.query(query))
        worker.signals.finished.connect(lambda page: self._on_page(generation, page))
        worker.signals.failed.connect(lambda message: self._on_error(generation, message))
        self._pool.start(worker)
        now = datetime.now().astimezone()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        stats_start = today_start - timedelta(days=6)
        stats_end = today_start + timedelta(days=1)
        stats_worker = LogWorker(
            lambda: query_service.statistics(stats_start, stats_end)
        )
        stats_worker.signals.finished.connect(lambda stats: self._on_stats(generation, stats))
        self._pool.start(stats_worker)

    def _on_page(self, generation: int, page: object) -> None:
        if self._disposed or generation != self._generation or not isinstance(page, LogPage):
            return
        self._loading.setVisible(False)
        self._model.replace(page.entries)
        if page.entries:
            self._status.setText(
                self._t(
                    "log_panel.load_result",
                    "已加载 {count} 条日志",
                    count=len(page.entries),
                )
            )
            if self._live_mode:
                self._table.scrollToBottom()
        elif self._query_service:
            self._status.setText(
                self._t("log_panel.no_match", "无匹配日志")
            )
        if page.malformed_lines:
            self._status.setText(
                self._t(
                    "log_panel.malformed",
                    "发现 {count} 行损坏日志",
                    count=page.malformed_lines,
                )
            )

    def _on_stats(self, generation: int, stats: object) -> None:
        if self._disposed or generation != self._generation:
            return
        if not isinstance(stats, LogStatistics):
            return
        today = datetime.now().astimezone().date()
        today_point = next((point for point in stats.trend if point.day == today), None)
        by_category = dict(today_point.by_category) if today_point else {}
        total = today_point.total if today_point else 0
        self._total_label.setText(
            self._t("log_panel.today_total", "今日总量：{count}", count=total)
        )
        for category, bar in self._level_bars.items():
            percentage = round(100 * int(by_category.get(category, 0)) / total) if total else 0
            bar.setValue(percentage)
        trend_by_day = {point.day: point.total for point in stats.trend}
        values = tuple(
            trend_by_day.get(today - timedelta(days=offset), 0)
            for offset in range(6, -1, -1)
        )
        self._trend_chart.set_values(values)

    def _on_error(self, generation: int, message: str) -> None:
        if not self._disposed and generation == self._generation:
            self._loading.setVisible(False)
            self._status.setText(
                self._t(
                    "log_panel.load_failed",
                    "加载失败：{message}",
                    message=message,
                )
            )

    def _on_row_clicked(self, index: QModelIndex) -> None:
        if not index.isValid() or index.row() >= len(self._model.entries):
            return
        selected = self._model.entries[index.row()]
        self._selected = selected
        self._details.setPlainText(
            json.dumps(stored_to_payload(selected), ensure_ascii=False, indent=2)
        )

    def _set_realtime(self, enabled: bool) -> None:
        self._live_mode = enabled
        if enabled:
            self._end_edit.setDateTime(QDateTime.currentDateTime())
            self._reload_after_new_logs()

    def append_record(self, record: LogRecord) -> None:
        """从后台 handler 接收一条记录并投递到 Qt 主线程。"""
        if self._disposed:
            return
        run_on_ui(self._append_record_ui, record)

    def _append_record_ui(self, record: LogRecord) -> None:
        if self._disposed:
            return
        self._append(record.format_text(), _category_for_level(record.level).lower())
        if not self._live_mode and self._query_service:
            self._new_count += 1
            self._new_logs_button.setText(
                self._t(
                    "log_panel.new_logs",
                    "有 {count} 条新日志",
                    count=self._new_count,
                )
            )
            self._new_logs_button.setVisible(True)
            return
        if self._query_service:
            self._end_edit.setDateTime(QDateTime.currentDateTime())
            self._live_refresh_timer.start()

    def log(self, message: str, tag: str = "info") -> None:
        """兼容旧 UI handler 回调。"""
        if not self._disposed:
            run_on_ui(self._append, message, tag)

    def _append(self, message: str, tag: str = "info") -> None:
        if self._disposed:
            return
        normalized = tag.lower()
        color = LOG_COLORS.get(normalized.upper(), LOG_COLORS["INFO"])
        prefix = f"[{datetime.now().strftime('%H:%M:%S')}] [{normalized.upper()}]"
        self._content.append(
            f'<span style="color:{color}">{escape(prefix)} {escape(message)}</span>'
        )

    def _reload_after_new_logs(self) -> None:
        self._new_count = 0
        self._new_logs_button.setVisible(False)
        self.reload()

    def _copy_selected(self) -> None:
        selected = self._selected
        if selected is None:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(
            json.dumps(
                stored_to_payload(selected), ensure_ascii=False, indent=2
            )
        )
        self._show_transient(self._t("log_panel.copied", "已复制"))

    def _show_transient(self, message: str) -> None:
        self._status.setText(message)
        QTimer.singleShot(2500, self._restore_status)

    def _restore_status(self) -> None:
        if self._disposed:
            return
        message = (
            self._t("log_panel.empty", "暂无日志，应用启动后将自动记录")
            if not self._model.entries
            else self._t("log_panel.ready", "就绪")
        )
        self._status.setText(message)

    def _export(self) -> None:
        if self._export_service is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._t("log_panel.export_title", "导出日志"),
            "logs.jsonl",
            self._t("log_panel.jsonl_filter", "JSONL 文件 (*.jsonl)"),
        )
        if not path:
            return
        query = self._current_query
        export_service = self._export_service
        assert export_service is not None
        worker = LogWorker(lambda: export_service.export_jsonl(query, path))
        worker.signals.finished.connect(self._on_exported)
        worker.signals.failed.connect(self._show_worker_error)
        self._pool.start(worker)

    def _open_alerts(self) -> None:
        if self._alert_service is None:
            return
        from app.qtui.log_alerts import QtAlertDialog

        dialog = QtAlertDialog(
            self._alert_service,
            self,
            translate=self._translate,
        )
        self._alert_dialog = dialog
        dialog.exec()
        self._alert_dialog = None

    def _show_aggregates(self) -> None:
        query_service = self._query_service
        if query_service is None:
            return
        start = self._current_query.start or datetime.now().astimezone() - timedelta(days=7)
        end = self._current_query.end or datetime.now().astimezone()
        self._status.setText(
            self._t("log_panel.aggregate_loading", "正在聚合异常…")
        )
        worker = LogWorker(lambda: query_service.aggregate_errors(start, end))
        worker.signals.finished.connect(self._on_aggregates)
        worker.signals.failed.connect(self._show_worker_error)
        self._pool.start(worker)

    def _on_aggregates(self, result: object) -> None:
        if self._disposed or not isinstance(result, tuple):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self._t("log_panel.aggregate", "异常聚合"))
        dialog.resize(680, 360)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(result), 4)
        table.setHorizontalHeaderLabels([
            self._t("log_panel.aggregate_count", "次数"),
            self._t("log_panel.column_module", "模块"),
            self._t("log_panel.column_message", "消息"),
            self._t("log_panel.aggregate_last_seen", "最近出现"),
        ])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, group in enumerate(result):
            if not isinstance(group, dict):
                continue
            values = (
                str(group.get("count", 0)),
                str(group.get("module", "")),
                str(group.get("message", "")),
                str(group.get("last_seen", "")),
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(table)
        close_button = QPushButton(self._t("common.close", "关闭"))
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
        self._status.setText(
            self._t("log_panel.aggregate_ready", "异常聚合已更新")
        )

    def _clear_persisted(self) -> None:
        if self._clear_logs is None:
            self.clear()
            return
        answer = QMessageBox.question(
            self,
            self._t("log_panel.clear", "清空日志"),
            self._t(
                "log_panel.clear_confirm",
                "将永久删除全部本地日志归档。继续吗？",
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        worker = LogWorker(self._clear_logs)
        worker.signals.finished.connect(self._on_cleared)
        worker.signals.failed.connect(self._show_worker_error)
        self._pool.start(worker)

    def _on_cleared(self, count: object) -> None:
        if self._disposed:
            return
        self.clear()
        self._status.setText(
            self._t(
                "log_panel.clear_result",
                "已清理 {count} 个日志文件",
                count=count,
            )
        )

    def _on_exported(self, count: object) -> None:
        if self._disposed:
            return
        self._status.setText(
            self._t(
                "log_panel.export_result",
                "已导出 {count} 条日志",
                count=count,
            )
        )

    def _show_worker_error(self, message: str) -> None:
        if not self._disposed:
            self._status.setText(message)

    def show_storage_warning(self, message: str) -> None:
        """线程安全地显示日志存储告警。"""
        if not self._disposed:
            run_on_ui(self._show_storage_warning_ui, message)

    def _show_storage_warning_ui(self, message: str) -> None:
        if self._disposed:
            return
        messages = {
            "write_failed": self._t(
                "log_panel.write_failed",
                "日志存储写入失败，已切换紧急日志",
            ),
            "storage_full": self._t(
                "log_panel.storage_full",
                "日志存储空间已满，请清理旧日志",
            ),
        }
        self._status.setText(messages.get(message, message))

    def clear(self) -> None:
        """清空当前内存视图，不删除本地归档文件。"""
        self._model.clear()
        self._details.clear()
        self._content.clear()
        self._selected = None
        self._status.setText(
            self._t("log_panel.empty", "暂无日志，应用启动后将自动记录")
        )

    def _restore_settings(self) -> None:
        if self._settings is None:
            return
        level = str(self._settings.value("log_viewer/level", ""))
        level_index = self._level_combo.findData(level)
        self._level_combo.setCurrentIndex(max(0, level_index))
        self._keyword.setText(str(self._settings.value("log_viewer/keyword", "")))
        self._module.setText(str(self._settings.value("log_viewer/module", "")))
        live = bool(self._settings.value("log_viewer/realtime", True, type=bool))
        self._realtime.setChecked(live)
        start_text = str(self._settings.value("log_viewer/start_time", ""))
        end_text = str(self._settings.value("log_viewer/end_time", ""))
        for editor, text in ((self._start_edit, start_text), (self._end_edit, end_text)):
            restored = QDateTime.fromString(text, Qt.DateFormat.ISODate)
            if restored.isValid():
                editor.setDateTime(restored)
        widths = self._settings.value("log_viewer/column_widths", [])
        if isinstance(widths, list):
            for column, width in enumerate(widths[:self._model.columnCount()]):
                try:
                    self._table.setColumnWidth(column, int(width))
                except (TypeError, ValueError):
                    continue
        geometry = self._settings.value("log_viewer/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def _save_settings(self) -> None:
        if self._settings is None:
            return
        self._settings.setValue("log_viewer/level", self._level_combo.currentData() or "")
        self._settings.setValue("log_viewer/keyword", self._keyword.text())
        self._settings.setValue("log_viewer/module", self._module.text())
        self._settings.setValue("log_viewer/realtime", self._realtime.isChecked())
        self._settings.setValue(
            "log_viewer/start_time",
            self._start_edit.dateTime().toString(Qt.DateFormat.ISODate),
        )
        self._settings.setValue(
            "log_viewer/end_time",
            self._end_edit.dateTime().toString(Qt.DateFormat.ISODate),
        )
        self._settings.setValue(
            "log_viewer/column_widths",
            [self._table.columnWidth(column) for column in range(self._model.columnCount())],
        )
        self._settings.setValue("log_viewer/geometry", self.saveGeometry())
        self._settings.sync()

    def dispose(self) -> None:
        """阻止迟到查询和日志写入，操作幂等。"""
        if self._disposed:
            return
        self._save_settings()
        self._disposed = True
        self._generation += 1


def install_qt_log_handler(
    panel: QtLogPanel,
) -> LogHandler:
    """注册结构化 Qt handler 并返回其生命周期句柄。"""
    handler = _QtLogHandler(panel)
    from core.logger import logger

    logger.add_handler(handler)
    return handler


__all__ = ["LogTableModel", "QtLogPanel", "install_qt_log_handler"]
