"""Qt 进度呈现：状态栏进度条托管。"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QProgressBar, QStatusBar

from app.qtui.utils import run_on_ui


class QtProgressHost:
    """状态栏进度条 + 任务名标签（线程安全更新）。

    进度操作可能来自工作线程，所有更新都经 ``run_on_ui`` 投递到主线程。
    """

    def __init__(self, status_bar: QStatusBar) -> None:
        """构建进度宿主。

        Args:
            status_bar: 窗口状态栏。
        """
        self._status_bar = status_bar
        self._task_label = QLabel("")
        self._task_label.setProperty("role", "muted")
        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setValue(0)
        self._bar.setFixedWidth(220)
        self._bar.setVisible(False)
        self._task_label.setVisible(False)
        status_bar.addPermanentWidget(self._task_label)
        status_bar.addPermanentWidget(self._bar)
        self._visible = False

    def show_progress(self, task_name: str = "") -> None:
        """显示进度条（幂等）。"""
        run_on_ui(self._show, task_name)

    def hide_progress(self) -> None:
        """隐藏进度条（幂等）。"""
        run_on_ui(self._hide)

    def update_progress(self, value: float) -> None:
        """更新进度百分比（0~100）。"""
        run_on_ui(self._set_value, value)

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        """更新任务名与进度。"""
        run_on_ui(self._update_both, task_name, value)

    def set_progress_label(self, text: str) -> None:
        """更新任务名标签。"""
        run_on_ui(self._set_label, text)

    # ─── 主线程实现 ───────────────────────────────

    def _show(self, task_name: str) -> None:
        self._visible = True
        self._task_label.setText(task_name)
        self._task_label.setVisible(bool(task_name))
        self._bar.setVisible(True)

    def _hide(self) -> None:
        self._visible = False
        self._task_label.clear()
        self._task_label.setVisible(False)
        self._bar.setVisible(False)

    def _set_value(self, value: float) -> None:
        if not self._visible:
            self._bar.setVisible(True)
            self._visible = True
        self._bar.setValue(int(max(0.0, min(100.0, value)) * 10))

    def _update_both(self, task_name: str, value: float) -> None:
        self._show(task_name)
        self._set_value(value)

    def _set_label(self, text: str) -> None:
        self._task_label.setText(text)
        self._task_label.setVisible(bool(text))

    @property
    def bar(self) -> QProgressBar:
        """返回底层进度条（供壳层直接控制）。"""
        return self._bar
