"""Qt scheduler for local log alert checks."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.log_alert_service import (
    AlertCheckResult,
    AlertEvent,
    AlertRule,
    AlertService,
    Notification,
)


class _AlertWorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _AlertWorker(QRunnable):
    def __init__(self, service: AlertService) -> None:
        super().__init__()
        self.signals = _AlertWorkerSignals()
        self._service = service

    def run(self) -> None:
        try:
            self.signals.finished.emit(self._service.check())
        except Exception as exc:  # worker boundary reports to the UI
            self.signals.failed.emit(str(exc))


class QtAlertController(QObject):
    """每五分钟后台检查告警并把通知事件投递到 Qt 主线程。"""

    alert_triggered = Signal(object)
    check_failed = Signal(str)

    def __init__(
        self,
        service: AlertService,
        on_event: Callable[[AlertEvent], None],
        email_notify: Optional[Notification] = None,
        parent: QObject | None = None,
        interval_ms: int = 5 * 60 * 1000,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._on_event = on_event
        self._pool = QThreadPool.globalInstance()
        self._running = False
        self._disposed = False
        self._timer = QTimer(self)
        self._timer.setInterval(max(1000, interval_ms))
        self._timer.timeout.connect(self.check_now)
        self.alert_triggered.connect(self._on_event)
        self._service.configure_notifications(self._emit_event, email_notify)

    def start(self) -> None:
        """启动周期检查并立即执行一次。"""
        if self._disposed:
            return
        self._timer.start()
        self.check_now()

    def check_now(self) -> None:
        if self._disposed or self._running:
            return
        self._running = True
        worker = _AlertWorker(self._service)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.failed.connect(self._on_failed)
        self._pool.start(worker)

    def _emit_event(self, event: AlertEvent) -> None:
        if not self._disposed:
            self.alert_triggered.emit(event)

    def _on_finished(self, result: object) -> None:
        self._running = False
        if not isinstance(result, AlertCheckResult):
            return
        # Callbacks may be absent when the service is used outside Qt; emit once
        # here only for notification ports that did not run in the worker.

    def _on_failed(self, message: str) -> None:
        self._running = False
        if not self._disposed:
            self.check_failed.emit(message)

    def dispose(self) -> None:
        """停止定时器并忽略迟到 worker 结果。"""
        if self._disposed:
            return
        self._disposed = True
        self._timer.stop()


class QtAlertDialog(QDialog):
    """告警规则 CRUD 和历史查看对话框。"""

    def __init__(
        self,
        service: AlertService,
        parent: QWidget | None = None,
        translate: Callable[..., str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._translate = translate
        self._selected_id = ""
        self.setWindowTitle(
            self._t("log_alerts.title", "日志告警规则")
        )
        self.resize(680, 430)
        self._build_ui()
        self._reload_rules()
        self._reload_history()

    def _t(self, key: str, default: str, **kwargs: object) -> str:
        """Translate through the application catalog with a Qt fallback."""
        fallback = self.tr(default)
        if self._translate is not None:
            return self._translate(key, fallback, **kwargs)
        return fallback.format(**kwargs) if kwargs else fallback

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        body = QHBoxLayout()
        self._rules = QListWidget()
        self._rules.currentRowChanged.connect(self._load_selected)
        body.addWidget(self._rules, 1)

        form = QFormLayout()
        self._name = QLineEdit()
        form.addRow(self._t("log_alerts.rule_name", "规则名称"), self._name)
        self._level = QComboBox()
        self._level.addItems(["ERROR", "FATAL", "WARN", "INFO", "DEBUG"])
        form.addRow(self._t("log_alerts.level", "级别"), self._level)
        self._window = QSpinBox()
        self._window.setRange(1, 7 * 24 * 60)
        self._window.setValue(60)
        form.addRow(
            self._t("log_alerts.window_minutes", "时间窗口（分钟）"),
            self._window,
        )
        self._threshold = QSpinBox()
        self._threshold.setRange(1, 1_000_000)
        self._threshold.setValue(10)
        form.addRow(self._t("log_alerts.threshold", "阈值"), self._threshold)
        self._cooldown = QSpinBox()
        self._cooldown.setRange(0, 7 * 24 * 60)
        self._cooldown.setValue(60)
        form.addRow(
            self._t("log_alerts.cooldown_minutes", "冷却（分钟）"),
            self._cooldown,
        )
        self._enabled = QCheckBox(self._t("log_alerts.enabled", "启用"))
        self._enabled.setChecked(True)
        form.addRow(self._enabled)
        self._notification = QComboBox()
        self._notification.addItem(
            self._t("log_alerts.notification_system", "系统通知"), "system"
        )
        self._notification.addItem(
            self._t("log_alerts.notification_email", "邮件"), "email"
        )
        self._notification.addItem(
            self._t("log_alerts.notification_both", "系统通知 + 邮件"),
            "both",
        )
        form.addRow(
            self._t("log_alerts.notification", "通知方式"),
            self._notification,
        )
        self._recipients = QLineEdit()
        self._recipients.setPlaceholderText(
            self._t("log_alerts.recipients_hint", "邮件地址，以逗号分隔")
        )
        form.addRow(
            self._t("log_alerts.recipients", "收件人"), self._recipients
        )
        self._feedback = QLabel()
        form.addRow(self._feedback)
        buttons = QHBoxLayout()
        add_button = QPushButton(self._t("log_alerts.new", "新建"))
        add_button.clicked.connect(self._new_rule)
        buttons.addWidget(add_button)
        save_button = QPushButton(self._t("common.save", "保存"))
        save_button.clicked.connect(self._save_rule)
        buttons.addWidget(save_button)
        delete_button = QPushButton(self._t("common.delete", "删除"))
        delete_button.clicked.connect(self._delete_rule)
        buttons.addWidget(delete_button)
        form.addRow(buttons)
        body.addLayout(form, 2)
        root.addLayout(body)

        root.addWidget(QLabel(self._t("log_panel.alert_history", "告警历史")))
        self._history = QTableWidget(0, 5)
        self._history.setHorizontalHeaderLabels([
            self._t("log_alerts.history_time", "时间"),
            self._t("log_alerts.history_rule", "规则"),
            self._t("log_alerts.level", "级别"),
            self._t("log_alerts.history_count", "数量"),
            self._t("log_alerts.history_result", "通知结果"),
        ])
        self._history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self._history, 1)

    def _reload_rules(self) -> None:
        self._rules.clear()
        for rule in self._service.list_rules():
            self._rules.addItem(rule.name)
            self._rules.item(self._rules.count() - 1).setData(
                Qt.ItemDataRole.UserRole,
                rule.rule_id,
            )

    def _load_selected(self, row: int) -> None:
        if row < 0:
            self._new_rule()
            return
        rule_id = self._rules.item(row).data(Qt.ItemDataRole.UserRole)
        rule = next((item for item in self._service.list_rules() if item.rule_id == rule_id), None)
        if rule is None:
            return
        self._selected_id = rule.rule_id
        self._name.setText(rule.name)
        self._level.setCurrentText(rule.level)
        self._window.setValue(rule.window_minutes)
        self._threshold.setValue(rule.threshold)
        self._cooldown.setValue(rule.cooldown_minutes)
        self._enabled.setChecked(rule.enabled)
        self._notification.setCurrentIndex(self._notification.findData(rule.notification))
        self._recipients.setText(",".join(rule.recipients))

    def _new_rule(self) -> None:
        self._selected_id = ""
        self._name.clear()
        self._level.setCurrentText("ERROR")
        self._window.setValue(60)
        self._threshold.setValue(10)
        self._cooldown.setValue(60)
        self._enabled.setChecked(True)
        self._notification.setCurrentIndex(0)
        self._recipients.clear()
        self._rules.clearSelection()

    def _save_rule(self) -> None:
        rule = AlertRule(
            rule_id=self._selected_id,
            name=self._name.text().strip(),
            level=str(self._level.currentText()),
            window_minutes=self._window.value(),
            threshold=self._threshold.value(),
            notification=str(self._notification.currentData()),
            cooldown_minutes=self._cooldown.value(),
            enabled=self._enabled.isChecked(),
            recipients=tuple(
                value.strip() for value in self._recipients.text().split(",") if value.strip()
            ),
        )
        try:
            saved = (
                self._service.create_rule(rule)
                if not rule.rule_id
                else self._service.upsert_rule(rule)
            )
        except ValueError as exc:
            self._feedback.setText(self._validation_message(exc))
            return
        self._selected_id = saved.rule_id
        self._feedback.clear()
        self._reload_rules()
        self._reload_history()

    def _validation_message(self, error: ValueError) -> str:
        messages = {
            "告警规则名称不能为空": (
                "log_alerts.validation_name",
                "规则名称不能为空",
                "Rule name is required",
            ),
            "不支持的告警级别": (
                "log_alerts.validation_level",
                "不支持的告警级别",
                "Unsupported alert level",
            ),
            "时间窗口和阈值必须为正数": (
                "log_alerts.validation_positive",
                "时间窗口和阈值必须为正数",
                "Window and threshold must be positive",
            ),
            "冷却时间不能为负数": (
                "log_alerts.validation_cooldown",
                "冷却时间不能为负数",
                "Cooldown cannot be negative",
            ),
            "不支持的通知方式": (
                "log_alerts.validation_notification",
                "不支持的通知方式",
                "Unsupported notification method",
            ),
            "邮件通知需要至少一个收件人": (
                "log_alerts.validation_recipients",
                "邮件通知需要至少一个收件人",
                "Email notifications require at least one recipient",
            ),
        }
        key, chinese, english = messages.get(
            str(error), ("log_alerts.validation", str(error), str(error))
        )
        return self._t(key, chinese if self._translate is None else english)

    def _delete_rule(self) -> None:
        if self._selected_id:
            self._service.delete_rule(self._selected_id)
            self._new_rule()
            self._reload_rules()

    def _reload_history(self) -> None:
        events = self._service.history(100)
        self._history.setRowCount(len(events))
        for row, event in enumerate(events):
            values = (
                event.triggered_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                event.rule_name,
                event.level,
                str(event.count),
                self._t("log_alerts.failed", "失败")
                if event.notification_errors
                else self._t("log_alerts.sent", "已发送"),
            )
            for column, value in enumerate(values):
                self._history.setItem(row, column, QTableWidgetItem(value))


__all__ = ["QtAlertController", "QtAlertDialog"]
