"""Reusable model, worker, and trend chart for the Qt log viewer."""

from __future__ import annotations

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
            thread = entry.thread_name or "-"
            if entry.thread_id:
                thread = f"{thread} [{entry.thread_id}]"
            values = (
                entry.timestamp.astimezone().strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )[:-3],
                entry.category,
                entry.module or "-",
                entry.logger_name or "-",
                str(entry.process_id or "-"),
                thread,
                entry.exception_type or "-",
                entry.message,
            )
            return values[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            return QBrush(QColor(LOG_COLORS.get(entry.category, "#CFD8DC")))
        if role == Qt.ItemDataRole.ToolTipRole:
            if index.column() == 7:
                return entry.message
            if index.column() == 6 and entry.stack_trace:
                return entry.stack_trace
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

    def run(self) -> None:
        try:
            self.signals.finished.emit(self._operation())
        except Exception as exc:  # worker boundary reports failure to the UI
            self.signals.failed.emit(str(exc))


__all__ = ["LOG_COLORS", "LogTableModel", "LogTrendChart", "LogWorker"]
