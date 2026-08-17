"""Coordinate concurrent renders of the same top-view tile."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, Hashable, Optional, Set

CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class TopviewRenderResult:
    """Completed tile bytes and the source completeness flags."""

    png: Optional[bytes]
    status: tuple[bool, ...] = ()


RenderOperation = Callable[[CancelCheck], TopviewRenderResult]


@dataclass
class _InflightRender:
    completed: threading.Event = field(default_factory=threading.Event)
    participants: Set[object] = field(default_factory=set)
    result: TopviewRenderResult = field(
        default_factory=lambda: TopviewRenderResult(None),
    )


class TopviewRenderCoordinator:
    """Share one render while preserving per-caller cancellation."""

    def __init__(self, wait_interval: float = 0.01) -> None:
        self._wait_interval = wait_interval
        self._lock = threading.Lock()
        self._entries: Dict[Hashable, _InflightRender] = {}

    def run(
        self,
        key: Hashable,
        cancel_check: Optional[CancelCheck],
        operation: RenderOperation,
    ) -> TopviewRenderResult:
        """Run or join one keyed render.

        Args:
            key: Stable identity for equivalent render output.
            cancel_check: Cancellation probe owned by this caller.
            operation: Owner-only render accepting a shared cancellation probe.

        Returns:
            Shared render result, or an empty result when this caller cancels.
        """
        token = object()
        entry, is_owner = self._join(key, token)
        if is_owner:
            return self._run_owner(key, entry, token, cancel_check, operation)
        return self._wait_for_owner(entry, token, cancel_check)

    def _join(self, key: Hashable, token: object) -> tuple[_InflightRender, bool]:
        with self._lock:
            entry = self._entries.get(key)
            is_owner = entry is None
            if entry is None:
                entry = _InflightRender()
                self._entries[key] = entry
            entry.participants.add(token)
            return entry, is_owner

    def _run_owner(
        self,
        key: Hashable,
        entry: _InflightRender,
        token: object,
        cancel_check: Optional[CancelCheck],
        operation: RenderOperation,
    ) -> TopviewRenderResult:
        owner_cancelled = False

        def shared_cancel_check() -> bool:
            nonlocal owner_cancelled
            if not owner_cancelled and self._is_cancelled(cancel_check):
                owner_cancelled = True
                self._leave(entry, token)
            return self._has_no_participants(entry)

        try:
            result = operation(shared_cancel_check)
        except BaseException:
            self._publish(key, entry, TopviewRenderResult(None))
            raise
        else:
            self._publish(key, entry, result)
        finally:
            self._leave(entry, token)

        if owner_cancelled or self._is_cancelled(cancel_check):
            return TopviewRenderResult(None)
        return result

    def _wait_for_owner(
        self,
        entry: _InflightRender,
        token: object,
        cancel_check: Optional[CancelCheck],
    ) -> TopviewRenderResult:
        try:
            while not entry.completed.wait(self._wait_interval):
                if self._is_cancelled(cancel_check):
                    return TopviewRenderResult(None)
            if self._is_cancelled(cancel_check):
                return TopviewRenderResult(None)
            return entry.result
        finally:
            self._leave(entry, token)

    def _publish(
        self,
        key: Hashable,
        entry: _InflightRender,
        result: TopviewRenderResult,
    ) -> None:
        with self._lock:
            entry.result = result
            if self._entries.get(key) is entry:
                del self._entries[key]
            entry.completed.set()

    def _leave(self, entry: _InflightRender, token: object) -> None:
        with self._lock:
            entry.participants.discard(token)

    def _has_no_participants(self, entry: _InflightRender) -> bool:
        with self._lock:
            return not entry.participants

    @staticmethod
    def _is_cancelled(cancel_check: Optional[CancelCheck]) -> bool:
        return cancel_check is not None and cancel_check()
