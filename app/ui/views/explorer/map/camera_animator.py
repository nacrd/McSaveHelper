"""Camera animation controller for the MCA map viewport."""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from core.mca.viewport import McaViewport, ViewportTarget


class MapCameraAnimator:
    """Ease-out camera interpolator driven by background timers."""

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
        self.active = False
        self._cancel_timer()

    def animate_to(
        self,
        target_scale: float,
        target_offset_x: float,
        target_offset_y: float,
        duration: float = 0.22,
    ) -> None:
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
