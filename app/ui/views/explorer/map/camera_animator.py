"""MCA 地图视口的相机动画控制器。"""
from __future__ import annotations

import time
from typing import Callable, Optional

from app.ui.delayed_scheduler import DelayScheduler, ScheduledCall
from core.mca.viewport import McaViewport, ViewportTarget


class MapCameraAnimator:
    """通过注入的 UI 调度器执行 ease-out 相机插值。"""

    def __init__(
        self,
        viewport: McaViewport,
        *,
        min_scale: float,
        max_scale: float,
        on_frame: Callable[[], None],
        on_complete: Callable[[], None],
        is_alive: Callable[[], bool],
        schedule: DelayScheduler,
    ) -> None:
        """绑定视口状态、回调和 UI 调度端口。

        Args:
            viewport: 可变相机状态。
            min_scale / max_scale: 缩放范围。
            on_frame: 每次插值后调用。
            on_complete: 最后一帧完成后调用一次。
            is_alive: 修改视口前执行的挂载状态检查。
            schedule: UI 循环延迟回调端口。
        """
        if not callable(schedule):
            raise TypeError("相机调度器必须可调用")
        self._viewport = viewport
        self._min_scale = min_scale
        self._max_scale = max_scale
        self._on_frame = on_frame
        self._on_complete = on_complete
        self._is_alive = is_alive
        self._schedule = schedule
        self._scheduled: Optional[ScheduledCall] = None
        self.active = False
        self.start = viewport.current_target
        self.target = viewport.current_target
        self._t0 = 0.0
        self._duration = 0.16
        self._generation = 0

    def cancel(self) -> None:
        """停止当前动画并取消等待中的 UI 回调。"""
        self._generation += 1
        self.active = False
        self._cancel_scheduled()

    def animate_to(
        self,
        target_scale: float,
        target_offset_x: float,
        target_offset_y: float,
        duration: float = 0.22,
    ) -> None:
        """从当前视口插值到经过范围约束的目标。"""
        self.start = self._viewport.current_target
        self.target = ViewportTarget(
            max(self._min_scale, min(self._max_scale, float(target_scale))),
            float(target_offset_x),
            float(target_offset_y),
        )
        self._t0 = time.monotonic()
        self._duration = max(0.05, duration)
        self._generation += 1
        generation = self._generation
        self.active = True
        self._kick(generation)

    def animate_zoom_about(
        self,
        factor: float,
        pivot_x: float,
        pivot_y: float,
        duration: float = 0.16,
    ) -> Optional[ViewportTarget]:
        """围绕屏幕支点缩放并动画到新目标。"""
        base = self.target if self.active else self._viewport.current_target
        target = self._viewport.zoom_about(factor, pivot_x, pivot_y, base)
        if abs(target.scale - base.scale) < 1e-6:
            return None
        self.animate_to(
            target.scale,
            target.offset_x,
            target.offset_y,
            duration=duration,
        )
        return target

    def _kick(self, generation: int) -> None:
        self._cancel_scheduled()
        self._schedule_tick(0.0, generation)

    def _cancel_scheduled(self) -> None:
        if self._scheduled is not None:
            self._scheduled.cancel()
        self._scheduled = None

    def _schedule_tick(self, delay: float, generation: int) -> None:
        try:
            self._scheduled = self._schedule(
                delay,
                lambda: self._tick(generation),
            )
        except Exception:
            self._scheduled = None
            self.active = False
            raise
        if self._scheduled is None:
            # 未挂载视图没有 UI 循环，不为此创建后备线程。
            self.active = False

    def _tick(self, generation: int) -> None:
        if generation != self._generation:
            return
        self._scheduled = None
        if not self.active or not self._is_alive():
            self.active = False
            return
        elapsed = time.monotonic() - self._t0
        progress = min(1.0, elapsed / self._duration)
        ease = 1.0 - (1.0 - progress) ** 3
        self._viewport.apply(self.start.interpolate(self.target, ease))
        self._notify_frame()
        if progress < 1.0:
            self._schedule_tick(1.0 / 60.0, generation)
            return
        self._complete_animation()

    def _notify_frame(self) -> None:
        self._safe_call(self._on_frame)

    def _complete_animation(self) -> None:
        self.active = False
        self._scheduled = None
        self._viewport.apply(self.target)
        self._safe_call(self._on_complete)

    @staticmethod
    def _safe_call(callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            # 过期 UI 回调异常不能中断后续动画。
            pass
