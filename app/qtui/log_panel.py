"""Qt 可停靠日志面板。"""
from __future__ import annotations

from html import escape
from time import strftime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QStyle,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.qtui.utils import run_on_ui
from core.logger import LogHandler, LogLevel, UIHandler, logger

_LOG_COLORS = {
    "api": "#42A5F5",
    "error": "#EF5350",
    "info": "#CFD8DC",
    "success": "#66BB6A",
    "warn": "#FFCA28",
}


class QtLogPanel(QDockWidget):
    """显示应用日志的可浮动、可停靠面板。"""

    MAX_LINES = 300

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        """构建只读日志视图和清空命令。"""
        super().__init__(title, parent)
        self.setObjectName("log_panel")
        self.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(title))
        toolbar.addStretch(1)
        clear_button = QToolButton()
        clear_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
        )
        clear_button.setToolTip("清除日志")
        clear_button.clicked.connect(self.clear)
        toolbar.addWidget(clear_button)
        layout.addLayout(toolbar)
        self._content = QTextEdit()
        self._content.setReadOnly(True)
        self._content.document().setMaximumBlockCount(self.MAX_LINES)
        layout.addWidget(self._content, 1)
        self.setWidget(host)
        self.resize(560, 260)
        self._disposed = False

    def log(self, message: str, tag: str = "info") -> None:
        """线程安全地追加一条带时间和级别的日志。"""
        if self._disposed:
            return
        run_on_ui(self._append, message, tag)

    def _append(self, message: str, tag: str) -> None:
        if self._disposed:
            return
        normalized = tag.lower()
        color = _LOG_COLORS.get(normalized, _LOG_COLORS["info"])
        prefix = f"[{strftime('%H:%M:%S')}] [{normalized.upper()}]"
        self._content.append(
            f'<span style="color:{color}">{escape(prefix)} '
            f"{escape(message)}</span>"
        )
        scroll_bar = self._content.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def clear(self) -> None:
        """清空当前日志视图。"""
        self._content.clear()

    def dispose(self) -> None:
        """阻止迟到日志写入；可重复调用。"""
        self._disposed = True


def install_qt_log_handler(panel: QtLogPanel) -> LogHandler:
    """注册面板日志处理器并返回其生命周期句柄。"""
    handler = UIHandler(panel.log, level=LogLevel.INFO)
    logger.add_handler(handler)
    return handler


__all__ = ["QtLogPanel", "install_qt_log_handler"]
