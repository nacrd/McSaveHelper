"""Reusable model, worker, and trend chart for the Qt log viewer."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPointF,
    QRunnable,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QPaintEvent, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from core.logging.storage import StoredLog

LOG_COLORS = {
    "DEBUG": "#90A4AE",
    "INFO": "#CFD8DC",
    "WARN": "#FFCA28",
    "ERROR": "#EF5350",
    "FATAL": "#FF7043",
}


class LogTrendChart(QWidget):
    """使用 Qt 原生绘制近七天日志量折线。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: tuple[int, ...] = ()
        self.setMinimumSize(150, 42)
        self.setMaximumHeight(54)

    def set_values(self, values: tuple[int, ...]) -> None:
        self._values = values
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.rect().adjusted(6, 5, -6, -5)
        painter.setPen(QPen(QColor("#607D8B"), 1))
        painter.drawLine(area.bottomLeft(), area.bottomRight())
        if not self._values:
            painter.end()
            return
        maximum = max(1, max(self._values))
        count = max(1, len(self._values) - 1)
        points = QPolygonF()
        for index, value in enumerate(self._values):
            x = area.left() + area.width() * index / count
            y = area.bottom() - area.height() * value / maximum
            points.append(QPointF(x, y))
        painter.setPen(QPen(QColor("#42A5F5"), 2))
        painter.drawPolyline(points)
        painter.end()


class LogTableModel(QAbstractTableModel):
    """轻量日志表格模型，记录摘要而非完整堆栈。"""

    def __init__(
        self,
        parent: QObject | None = None,
        headers: tuple[str, ...] = ("Time", "Level", "Module", "Message", "Thread"),
    ) -> None:
        super().__init__(parent)
        self.headers = headers
        self.entries: list[StoredLog] = []

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or index.row() >= len(self.entries):
            return None
        entry = self.entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            values = (
                entry.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                entry.category,
                entry.module,
                entry.message,
                entry.thread_name or str(entry.thread_id),
            )
            return values[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            return QBrush(QColor(LOG_COLORS.get(entry.category, "#CFD8DC")))
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 3:
            return entry.message
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and section < len(self.headers):
            return self.headers[section]
        return section + 1 if orientation == Qt.Orientation.Vertical else None

    def replace(self, entries: tuple[StoredLog, ...] | list[StoredLog]) -> None:
        self.beginResetModel()
        self.entries = list(entries)
        self.endResetModel()

    def append(self, entry: StoredLog) -> None:
        self.beginInsertRows(QModelIndex(), len(self.entries), len(self.entries))
        self.entries.append(entry)
        self.endInsertRows()

    def clear(self) -> None:
        self.replace(())


class _WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class LogWorker(QRunnable):
    """在 Qt 线程池运行一个无 UI 的 service 调用。"""

    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.signals = _WorkerSignals()
        self._operation = operation
        self._delivery_cancelled = threading.Event()

    def cancel_delivery(self) -> None:
        """Stop delivering a result when the owning panel is disposed."""
        self._delivery_cancelled.set()

    def run(self) -> None:
        try:
            result = self._operation()
        except Exception as exc:  # worker boundary reports failure to the UI
            self._emit_failure(str(exc))
            return
        self._emit_result(result)

    def _emit_result(self, result: object) -> None:
        """Deliver a completed result only while the UI signal source is valid."""
        if self._delivery_cancelled.is_set():
            return
        try:
            self.signals.finished.emit(result)
        except RuntimeError:
            # Qt may tear down the signal object during interpreter shutdown.
            return

    def _emit_failure(self, message: str) -> None:
        """Deliver an operation failure unless the owning UI has gone away."""
        if self._delivery_cancelled.is_set():
            return
        try:
            self.signals.failed.emit(message)
        except RuntimeError:
            # A deleted signal source means there is no remaining UI consumer.
            return


__all__ = ["LOG_COLORS", "LogTableModel", "LogTrendChart", "LogWorker"]
