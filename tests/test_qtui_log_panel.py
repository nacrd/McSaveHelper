"""Qt 日志面板测试。"""
from __future__ import annotations

from app.qtui.log_panel import QtLogPanel, install_qt_log_handler
from core.logger import logger


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
