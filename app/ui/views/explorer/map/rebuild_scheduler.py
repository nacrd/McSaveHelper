"""地图画布重建请求的线程安全限速器。"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from app.ui.delayed_scheduler import DelayScheduler, ScheduledCall


class RebuildScheduler:
    """合并高频重建信号并只调用一次请求回调。"""

    def __init__(
        self,
        request_rebuild: Callable[[], None],
        *,
        is_active: Callable[[], bool],
        schedule_delayed: DelayScheduler,
        min_interval: float = 1.0 / 60.0,
    ) -> None:
        """创建由所属 UI 循环驱动的合并调度器。"""
        if min_interval < 0:
            raise ValueError("最小重建间隔不能为负数")
        if not callable(schedule_delayed):
            raise TypeError("重建延迟调度器必须可调用")
        self._request_rebuild = request_rebuild
        self._is_active = is_active
        self._schedule_delayed = schedule_delayed
        self._min_interval = min_interval
        self._last_request_at = 0.0
        self._pending = False
        self._scheduled: Optional[ScheduledCall] = None
        self._generation = 0
        self._lock = threading.Lock()

    def schedule(self) -> None:
        """请求立即或延迟重建，并合并重复请求。"""
        if not self._is_active():
            return
        request_now = False
        delayed: Optional[tuple[float, int]] = None
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            if elapsed >= self._min_interval and not self._pending:
                self._last_request_at = now
                request_now = True
            elif not self._pending:
                self._pending = True
                delayed = (
                    max(0.0, self._min_interval - elapsed),
                    self._generation,
                )
        if request_now:
            self._request_rebuild()
        elif delayed is not None:
            self._schedule_pending(*delayed)

    def cancel(self) -> None:
        """取消延迟请求并重置调度状态。"""
        with self._lock:
            self._generation += 1
            scheduled = self._scheduled
            self._scheduled = None
            self._pending = False
        if scheduled is not None:
            scheduled.cancel()

    def _schedule_pending(self, delay: float, generation: int) -> None:
        try:
            scheduled = self._schedule_delayed(
                delay,
                lambda: self._fire(generation),
            )
        except Exception:
            self._clear_pending(generation)
            raise
        if scheduled is None:
            self._recover_rejected_schedule(generation)
            return
        with self._lock:
            is_current = self._pending and generation == self._generation
            if is_current:
                self._scheduled = scheduled
        if not is_current:
            scheduled.cancel()

    def _recover_rejected_schedule(self, generation: int) -> None:
        if not self._clear_pending(generation, update_last_request=True):
            return
        if self._is_active():
            self._request_rebuild()

    def _clear_pending(
        self,
        generation: int,
        *,
        update_last_request: bool = False,
    ) -> bool:
        with self._lock:
            if not self._pending or generation != self._generation:
                return False
            self._pending = False
            if update_last_request:
                self._last_request_at = time.monotonic()
            return True

    def _fire(self, generation: int) -> None:
        with self._lock:
            if not self._pending or generation != self._generation:
                return
            self._pending = False
            self._scheduled = None
            self._last_request_at = time.monotonic()
        if self._is_active():
            self._request_rebuild()
