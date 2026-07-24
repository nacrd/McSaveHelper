"""由 Flet UI 事件循环投递的可取消延迟回调。"""
from __future__ import annotations

import asyncio
import threading
from typing import Callable, Optional, Protocol

import flet as ft

from app.ui.utils import ScheduledTask, is_control_update_error


UiCallback = Callable[[], None]
PageProvider = Callable[[], Optional[ft.Page]]


class ScheduledCall(Protocol):
    """单个延迟回调的可取消所有权句柄。"""

    def cancel(self) -> None:
        """回调尚未开始时阻止其执行。"""
        ...


class DelayScheduler(Protocol):
    """不创建工作线程的单次延迟调度端口。"""

    def __call__(
        self,
        delay: float,
        callback: UiCallback,
    ) -> Optional[ScheduledCall]:
        """异步投递到所属 UI 循环；循环不可用时返回 ``None``。"""
        ...


class UiDelayedScheduler:
    """在动态解析的 Flet 页面循环上运行延迟回调。"""

    def __init__(self, page_provider: PageProvider) -> None:
        """绑定页面提供器，避免挂载变化使适配器持有过期页面。"""
        if not callable(page_provider):
            raise TypeError("页面提供器必须可调用")
        self._page_provider = page_provider

    def __call__(
        self,
        delay: float,
        callback: UiCallback,
    ) -> Optional[ScheduledCall]:
        """延迟 ``delay`` 秒后在 UI 循环执行 ``callback``。

        Args:
            delay: 非负延迟秒数。
            callback: 轻量 UI 回调。

        Returns:
            可取消句柄；没有存活页面时返回 ``None``。

        Raises:
            TypeError: ``callback`` 不可调用。
            ValueError: ``delay`` 为负数。
        """
        if delay < 0:
            raise ValueError("延迟秒数不能为负数")
        if not callable(callback):
            raise TypeError("延迟回调必须可调用")
        page = self._resolve_page()
        if page is None:
            return None

        call = _UiScheduledCall()

        async def run_delayed() -> None:
            try:
                if delay > 0:
                    await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            if call.claim():
                callback()

        try:
            task = page.run_task(run_delayed)
        except Exception as exc:
            if is_control_update_error(exc):
                return None
            raise
        call.attach(task)
        return call

    def _resolve_page(self) -> Optional[ft.Page]:
        try:
            return self._page_provider()
        except (RuntimeError, AssertionError, AttributeError):
            return None


class _UiScheduledCall:
    """包装 Flet 调度任务的线程安全取消门。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._task: Optional[ScheduledTask] = None
        self._cancelled = False
        self._claimed = False

    def attach(self, task: Optional[ScheduledTask]) -> None:
        """关联 Flet 返回的任务，并处理关联前已经发生的取消。"""
        with self._lock:
            self._task = task
            should_cancel = self._cancelled and task is not None
        if should_cancel:
            self._cancel_task(task)

    def claim(self) -> bool:
        """原子抢占回调执行权；取消先发生时返回 False。"""
        with self._lock:
            if self._cancelled or self._claimed:
                return False
            self._claimed = True
            return True

    def cancel(self) -> None:
        """取消等待中的回调；重复调用无副作用。"""
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            task = self._task
        if task is not None:
            self._cancel_task(task)

    @staticmethod
    def _cancel_task(task: ScheduledTask) -> None:
        try:
            task.cancel()
        except (RuntimeError, AssertionError):
            return


__all__ = [
    "DelayScheduler",
    "ScheduledCall",
    "UiDelayedScheduler",
]
