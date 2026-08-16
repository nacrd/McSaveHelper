"""Qt UI 线程工具：后台回调投递与线程判断。"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QWidget


class _UiDispatcher(QObject):
    """跨线程投递回调到 GUI 线程的中转对象。

    必须创建于主线程；工作线程通过 ``run_on_ui`` 发射信号，
    经 ``QueuedConnection`` 在 GUI 线程执行回调。
    """

    invoked = Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.invoked.connect(
            self._dispatch,
            Qt.ConnectionType.QueuedConnection,
        )

    def _dispatch(self, callback: object, args: object) -> None:
        if not callable(callback):
            return
        arguments = args if isinstance(args, tuple) else (args,)
        callback(*arguments)


_dispatcher = _UiDispatcher()


def run_on_ui(callback: Callable[..., object], *args: Any) -> None:
    """将回调与参数投递到 GUI 线程执行（线程安全）。

    Args:
        callback: 在 GUI 线程执行的可调用对象。
        *args: 回调参数。
    """
    _dispatcher.invoked.emit(callback, args)


def invoke_later(callback: Callable[..., object], *args: Any) -> None:
    """在当前线程稍后执行回调（立即排入事件队列）。"""
    _dispatcher.invoked.emit(callback, args)


@contextmanager
def batch_widget_updates(widget: QWidget) -> Iterator[None]:
    """批量修改控件时暂停重绘和信号，退出时恢复原状态。

    大型表格和列表的逐项投影如果让 Qt 在每次写入后布局，会产生明显的
    重绘开销；调用方仍需在上下文结束后显式刷新依赖派生状态的控件。
    """
    updates_enabled = widget.updatesEnabled()
    signals_blocked = widget.signalsBlocked()
    widget.setUpdatesEnabled(False)
    widget.blockSignals(True)
    try:
        yield
    finally:
        widget.blockSignals(signals_blocked)
        widget.setUpdatesEnabled(updates_enabled)
        if updates_enabled:
            widget.update()


def format_size(size: int) -> str:
    """格式化文件大小为人类可读字符串（与 Flet 版 app/ui/utils 对齐）。"""
    kb = size / 1024
    mb = kb / 1024
    gb = mb / 1024
    if gb >= 1:
        return f"{gb:.2f} GB"
    if mb >= 1:
        return f"{mb:.1f} MB"
    if kb >= 1:
        return f"{kb:.1f} KB"
    return f"{size} B"
