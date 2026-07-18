"""Thread-safe rate limiter for map canvas rebuild requests."""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class RebuildScheduler:
    """Coalesce frequent rebuild signals and invoke one request callback."""

    def __init__(
        self,
        request_rebuild: Callable[[], None],
        *,
        is_active: Callable[[], bool],
        min_interval: float = 1.0 / 60.0,
    ) -> None:
        self._request_rebuild = request_rebuild
        self._is_active = is_active
        self._min_interval = min_interval
        self._last_request_at = 0.0
        self._pending = False
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def schedule(self) -> None:
        """Request an immediate or delayed rebuild, coalescing duplicates."""
        if not self._is_active():
            return
        request_now = False
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            if elapsed >= self._min_interval and not self._pending:
                self._last_request_at = now
                request_now = True
            elif not self._pending:
                self._pending = True
                delay = max(0.0, self._min_interval - elapsed)
                self._timer = threading.Timer(delay, self._fire)
                self._timer.daemon = True
                self._timer.start()
        if request_now:
            self._request_rebuild()

    def cancel(self) -> None:
        """Cancel any delayed request and reset scheduler state."""
        with self._lock:
            timer = self._timer
            self._timer = None
            self._pending = False
        if timer is not None:
            timer.cancel()

    def _fire(self) -> None:
        with self._lock:
            self._pending = False
            self._timer = None
            self._last_request_at = time.monotonic()
        if self._is_active():
            self._request_rebuild()
