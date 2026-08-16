"""Qt 对话框与文件选择器端口实现。"""
from __future__ import annotations

import traceback
from typing import Callable, Optional, Protocol

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QWidget,
)

from app.adapters.file_dialogs import FileTypes
from app.qtui.utils import run_on_ui

_MainThread = QThread.currentThread


def _is_main_thread() -> bool:
    """当前线程是否 GUI 主线程。"""
    return QThread.currentThread() is _MainThread()


def _ensure_main_thread(callback: Callable[..., object], *args: object) -> None:
    """非主线程调用时投递回主线程；主线程直接执行。"""
    if _is_main_thread():
        callback(*args)
    else:
        run_on_ui(callback, *args)


class MessageDialogPort(Protocol):
    """应用壳层所需的消息对话框端口。"""

    def info_dialog(self, title: str, message: str) -> None:
        """展示信息对话框。"""
        ...

    def warn_dialog(self, title: str, message: str) -> None:
        """展示警告对话框。"""
        ...

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Optional[Exception] = None,
        show_details: bool = False,
    ) -> None:
        """展示错误对话框。"""
        ...

    def handle_exception(
        self,
        exception: Exception,
        title: Optional[str] = None,
        log: bool = True,
        show_dialog: bool = True,
    ) -> None:
        """处理异常：记录日志并可选择弹出对话框。"""
        ...


class QtMessageDialogs:
    """基于 QMessageBox 的消息对话框实现（线程安全）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """构建对话框服务。

        Args:
            parent: 对话框父窗口。
        """
        self._parent = parent

    def info_dialog(self, title: str, message: str) -> None:
        _ensure_main_thread(self._show_info, title, message)

    def warn_dialog(self, title: str, message: str) -> None:
        _ensure_main_thread(self._show_warn, title, message)

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Optional[Exception] = None,
        show_details: bool = False,
    ) -> None:
        _ensure_main_thread(self._show_error, title, message, exception, show_details)

    def handle_exception(
        self,
        exception: Exception,
        title: Optional[str] = None,
        log: bool = True,
        show_dialog: bool = True,
    ) -> None:
        del log
        dialog_title = title or "操作失败"
        message = str(exception) or type(exception).__name__
        if show_dialog:
            self.error_dialog(dialog_title, message, exception, show_details=True)

    # ─── 主线程实现 ───────────────────────────────

    def _show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self._parent, title, message)

    def _show_warn(self, title: str, message: str) -> None:
        QMessageBox.warning(self._parent, title, message)

    def _show_error(
        self,
        title: str,
        message: str,
        exception: Optional[Exception],
        show_details: bool,
    ) -> None:
        if show_details and exception is not None:
            details = "".join(
                traceback.format_exception(type(exception), exception, exception.__traceback__)
            )
            box = QMessageBox(self._parent)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(title)
            box.setText(message)
            box.setDetailedText(details)
            box.exec()
            return
        QMessageBox.critical(self._parent, title, message)


def _file_filter(file_types: FileTypes) -> str:
    """将 ``(说明, 扩展名)`` 过滤器序列转为 QFileDialog 过滤器字符串。"""
    if not file_types:
        return ""
    entries: list[str] = []
    for description, pattern in file_types:
        entries.append(f"{description} ({pattern})")
    return ";;".join(entries)


class QtFileDialogs:
    """基于 QFileDialog 的文件选择器实现（与 FileDialogPort 对齐）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """构建文件选择器。

        Args:
            parent: 对话框父窗口。
        """
        self._parent = parent

    def pick_directory(self, title: str) -> Optional[str]:
        return QFileDialog.getExistingDirectory(self._parent, title)

    def pick_file(self, title: str, file_types: FileTypes) -> Optional[str]:
        path, _selected = QFileDialog.getOpenFileName(
            self._parent,
            title,
            filter=_file_filter(file_types),
        )
        return path or None

    def pick_files(self, title: str, file_types: FileTypes) -> Optional[list[str]]:
        paths, _selected = QFileDialog.getOpenFileNames(
            self._parent,
            title,
            filter=_file_filter(file_types),
        )
        return list(paths) if paths else None

    def save_file(
        self,
        title: str,
        default_ext: str,
        file_types: FileTypes,
    ) -> Optional[str]:
        path, _selected = QFileDialog.getSaveFileName(
            self._parent,
            title,
            filter=_file_filter(file_types),
        )
        if not path:
            return None
        normalized_ext = default_ext if default_ext.startswith(".") else f".{default_ext}"
        if not path.lower().endswith(normalized_ext.lower()):
            path += normalized_ext
        return path

    def close(self) -> None:
        """Qt 文件对话框无后台资源，仅保持接口一致。"""
