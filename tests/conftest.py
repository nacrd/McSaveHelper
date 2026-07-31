"""pytest 共享 fixtures。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qt_app() -> QApplication:
    """会话级 QApplication 实例（离屏平台，供 Qt 控件测试使用）。"""
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    return QApplication([])
