"""MCA 地图视口的相机动画控制器。"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from core.mca.viewport import McaViewport, ViewportTarget


class MapCameraAnimator:
    """由后台 Timer 驱动的 ease-out 相机插值器。

    帧回调可能跨线程；完成/取消均幂等，不抛出回调异常。
    """

    def __init__(
        self,
        viewport: McaViewport,
        *,
        min_scale: float,
        max_scale: float,
        on_frame: Callable[[], None],
        on_complete: Callable[[], None],
        is_alive: Callable[[], bool],
    ) -> None:
        """绑定视口与帧回调；动画由后台 Timer 驱动。

        Args:
            viewport: 可变相机状态。
            min_scale / max_scale: 缩放钳制。
            on_frame: 每帧插值后调用（应调度 UI 重绘）。
            on_complete: 动画结束。
            is_alive: 视图是否仍挂载；False 时停止调度。
        """
        self._viewport = viewport
        self._min_scale = min_scale
        self._max_scale = max_scale
        self._on_frame = on_frame
        self._on_complete = on_complete
        self._is_alive = is_alive
        self._timer: Optional[threading.Timer] = None
        self.active = False
        self.start = viewport.current_target
        self.target = viewport.current_target
        self._t0 = 0.0
        self._duration = 0.16

    def cancel(self) -> None:
        """立即停止动画并取消待执行 timer。"""
        self.active = False
        self._cancel_timer()

    def animate_to(
        self,
        target_scale: float,
        target_offset_x: float,
        target_offset_y: float,
        duration: float = 0.22,
    ) -> None:
        """从当前相机 ease-out 插值到目标。

        Args:
            target_scale: 目标缩放。
            target_offset_x / target_offset_y: 目标偏移。
            duration: 秒；过小会钳制到 0.05。
        """
        self.start = self._viewport.current_target
        self.target = ViewportTarget(
            max(self._min_scale, min(self._max_scale, float(target_scale))),
            float(target_offset_x),
            float(target_offset_y),
        )
        self._t0 = time.monotonic()
        self._duration = max(0.05, duration)
        self.active = True
        self._kick()

    def animate_zoom_about(
        self,
        factor: float,
        pivot_x: float,
        pivot_y: float,
        duration: float = 0.16,
    ) -> Optional[ViewportTarget]:
        """相对屏幕支点缩放并动画到新目标。

        Args:
            factor: 缩放倍率（相对当前/进行中目标）。
            pivot_x: 支点屏幕 X。
            pivot_y: 支点屏幕 Y。
            duration: 动画时长秒。

        Returns:
            目标 ViewportTarget；缩放几乎不变时为 None。
        """
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

    def _kick(self) -> None:
        self._cancel_timer()
        self._schedule_tick(0.0)

    def _cancel_timer(self) -> None:
        try:
            if self._timer is not None:
                self._timer.cancel()
        except RuntimeError:
            # Timer may already have finished or been GC'd.
            pass
        self._timer = None

    def _schedule_tick(self, delay: float) -> None:
        self._timer = threading.Timer(delay, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self) -> None:
        if not self.active or not self._is_alive():
            return
        elapsed = time.monotonic() - self._t0
        progress = min(1.0, elapsed / self._duration)
        ease = 1.0 - (1.0 - progress) ** 3
        self._viewport.apply(self.start.interpolate(self.target, ease))
        self._notify_frame()
        if progress < 1.0:
            self._schedule_tick(1.0 / 60.0)
            return
        self._complete_animation()

    def _notify_frame(self) -> None:
        self._safe_call(self._on_frame)

    def _complete_animation(self) -> None:
        self.active = False
        self._timer = None
        self._viewport.apply(self.target)
        self._safe_call(self._on_complete)

    @staticmethod
    def _safe_call(callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            # Camera frame callbacks must not stop the animation loop.
            pass
