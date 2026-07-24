"""Framework-neutral delivery of background results to a UI scheduler.

The channel deliberately knows nothing about Flet.  A composition root injects
an adapter that schedules a no-argument callback on the UI event loop.  The
channel owns delivery identity, generation checks, and UI-facing observability.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Protocol
from uuid import uuid4

from app.services.operation_progress import OperationState, ProgressSnapshot
from core.observability import OperationOutcome, OperationRecord


UiCallback = Callable[[], None]
UiCurrentCheck = Callable[[], bool]
OperationRecordSink = Callable[[OperationRecord], None]
ProgressCallback = Callable[[ProgressSnapshot], None]


class ProgressSource(Protocol):
    """Operation identity and progress subscription used by the UI channel."""

    @property
    def task_id(self) -> str:
        ...

    @property
    def operation(self) -> str:
        ...

    @property
    def feature(self) -> str:
        ...

    @property
    def world_id(self) -> str:
        ...

    @property
    def generation(self) -> int:
        ...

    @property
    def metadata(self) -> Mapping[str, object]:
        ...

    def subscribe_progress(
        self,
        callback: ProgressCallback,
    ) -> Callable[[], None]:
        """Subscribe to snapshots and return an unsubscribe callback."""
        ...


class UiSchedulePort(Protocol):
    """Adapter that schedules a callback on the application's UI loop."""

    def __call__(self, callback: UiCallback) -> bool:
        """Schedule ``callback`` and return ``False`` when it was rejected."""
        ...


class UiDeliveryPort(Protocol):
    """Port used by controllers and views to publish a UI projection."""

    def close(self) -> None:
        """Reject queued and future deliveries."""
        ...

    def post(
        self,
        spec: "UiDeliverySpec",
        callback: UiCallback,
        *,
        is_current: UiCurrentCheck,
        on_complete: Optional[UiCallback] = None,
    ) -> str:
        """Queue a callback and return its unique delivery identifier."""
        ...

    def observe_progress(
        self,
        source: ProgressSource,
        callback: ProgressCallback,
        *,
        is_current: UiCurrentCheck,
    ) -> Callable[[], None]:
        """Deliver progress snapshots through the guarded UI scheduler."""
        ...


@dataclass(frozen=True)
class UiDeliverySpec:
    """Identity and diagnostic dimensions for one UI delivery."""

    task_id: str
    operation: str
    feature: str
    generation: int
    world_id: str = ""
    event: str = "result"
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate and freeze caller-provided diagnostic metadata."""
        if not self.task_id.strip():
            raise ValueError("UI 投递 task_id 不能为空")
        if not self.operation.strip():
            raise ValueError("UI 投递 operation 不能为空")
        if not self.feature.strip():
            raise ValueError("UI 投递 feature 不能为空")
        if self.generation < 0:
            raise ValueError("UI 投递 generation 不能为负数")
        if not self.event.strip():
            raise ValueError("UI 投递 event 不能为空")
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


class _DeliveryCompletion:
    """Run one best-effort completion callback exactly once."""

    def __init__(self, callback: Optional[UiCallback]) -> None:
        self._callback = callback
        self._lock = threading.Lock()
        self._finished = False

    @property
    def is_finished(self) -> bool:
        with self._lock:
            return self._finished

    def finish(self) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
        if self._callback is None:
            return
        try:
            self._callback()
        except Exception:
            return


class _DeliveryAttempt:
    """Own one scheduled callback and its terminal observability record."""

    def __init__(
        self,
        channel: "UiDeliveryChannel",
        delivery_id: str,
        spec: UiDeliverySpec,
        callback: UiCallback,
        is_current: UiCurrentCheck,
        completion: _DeliveryCompletion,
        queued_ns: int,
    ) -> None:
        self._channel = channel
        self._delivery_id = delivery_id
        self._spec = spec
        self._callback = callback
        self._is_current = is_current
        self._completion = completion
        self._queued_ns = queued_ns

    def reject_closed(self, queue_wait_ms: float = 0.0) -> None:
        self._publish_stale("channel_closed", queue_wait_ms)
        self._completion.finish()

    def schedule(self) -> None:
        try:
            accepted = self._channel._schedule(self.drain)
        except Exception as error:
            self._reject_schedule(error)
            return
        if accepted is False:
            self._reject_schedule(RuntimeError("UI 调度器拒绝投递"))

    def drain(self) -> None:
        started_ns = self._channel._now_ns()
        queue_wait_ms = self._channel._elapsed_ms(
            self._queued_ns,
            started_ns,
        )
        try:
            self._drain_current(queue_wait_ms)
        finally:
            self._completion.finish()

    def _drain_current(self, queue_wait_ms: float) -> None:
        if self._channel.is_closed:
            self._publish_stale("channel_closed", queue_wait_ms)
            return
        if not self._passes_guard(queue_wait_ms):
            return
        self._run_callback(queue_wait_ms)

    def _passes_guard(self, queue_wait_ms: float) -> bool:
        try:
            is_current = bool(self._is_current())
        except Exception as error:
            self._channel._publish_error(
                self._delivery_id,
                self._spec,
                queue_wait_ms,
                0.0,
                error,
                stage="guard",
            )
            return False
        if is_current:
            return True
        self._publish_stale("generation_guard", queue_wait_ms)
        return False

    def _run_callback(self, queue_wait_ms: float) -> None:
        started_ns = self._channel._now_ns()
        try:
            self._callback()
        except Exception as error:
            run_ms = self._elapsed_since(started_ns)
            self._channel._publish_error(
                self._delivery_id,
                self._spec,
                queue_wait_ms,
                run_ms,
                error,
                stage="callback",
            )
            return
        self._channel._publish(
            self._delivery_id,
            self._spec,
            OperationOutcome.OK,
            queue_wait_ms=queue_wait_ms,
            run_ms=self._elapsed_since(started_ns),
        )

    def _elapsed_since(self, started_ns: int) -> float:
        return self._channel._elapsed_ms(
            started_ns,
            self._channel._now_ns(),
        )

    def _reject_schedule(self, error: Exception) -> None:
        if self._completion.is_finished:
            return
        self._channel._publish_error(
            self._delivery_id,
            self._spec,
            queue_wait_ms=0.0,
            run_ms=0.0,
            error=error,
            stage="schedule",
        )
        self._completion.finish()

    def _publish_stale(self, reason: str, queue_wait_ms: float) -> None:
        self._channel._publish(
            self._delivery_id,
            self._spec,
            OperationOutcome.STALE,
            queue_wait_ms=queue_wait_ms,
            run_ms=0.0,
            extra={"drop_reason": reason},
        )


class _ProgressObserver:
    """Coalesce running snapshots and own one progress subscription."""

    def __init__(
        self,
        channel: "UiDeliveryChannel",
        source: ProgressSource,
        callback: ProgressCallback,
        is_current: UiCurrentCheck,
    ) -> None:
        self._channel = channel
        self._source = source
        self._callback = callback
        self._is_current = is_current
        self._lock = threading.Lock()
        self._latest_running: Optional[ProgressSnapshot] = None
        self._running_scheduled = False
        self._running_consumed = False
        self._disposed = False
        self._source_unsubscribe: Optional[Callable[[], None]] = None

    def start(self) -> Callable[[], None]:
        self._source_unsubscribe = self._source.subscribe_progress(
            self._on_progress,
        )
        return self.close

    def close(self) -> None:
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            self._latest_running = None
            source_unsubscribe = self._source_unsubscribe
        if source_unsubscribe is not None:
            source_unsubscribe()

    def _on_progress(self, snapshot: ProgressSnapshot) -> None:
        if snapshot.state is OperationState.RUNNING:
            self._record_running(snapshot)
            return
        self._channel.post(
            self._build_spec(self._metadata(snapshot)),
            lambda: self._callback(snapshot),
            is_current=self._guarded_current,
        )

    def _record_running(self, snapshot: ProgressSnapshot) -> None:
        with self._lock:
            if self._disposed:
                return
            self._latest_running = snapshot
        self._schedule_running()

    def _schedule_running(self) -> None:
        with self._lock:
            if self._cannot_schedule_running():
                return
            self._running_scheduled = True
            self._running_consumed = False
            initial = self._latest_running
        if initial is None:
            return
        try:
            self._channel.post(
                self._build_spec(self._metadata(initial, coalesced=True)),
                self._deliver_latest_running,
                is_current=self._guarded_current,
                on_complete=self._finish_running_delivery,
            )
        except Exception:
            with self._lock:
                self._running_scheduled = False

    def _cannot_schedule_running(self) -> bool:
        return (
            self._disposed
            or self._running_scheduled
            or self._latest_running is None
        )

    def _deliver_latest_running(self) -> None:
        with self._lock:
            snapshot = self._latest_running
            self._latest_running = None
            self._running_consumed = True
        if snapshot is not None:
            self._callback(snapshot)

    def _finish_running_delivery(self) -> None:
        with self._lock:
            was_consumed = self._running_consumed
            self._running_consumed = False
            self._running_scheduled = False
            should_reschedule = (
                was_consumed
                and not self._disposed
                and self._latest_running is not None
            )
        if should_reschedule:
            self._schedule_running()

    def _guarded_current(self) -> bool:
        with self._lock:
            is_active = not self._disposed
        return is_active and bool(self._is_current())

    def _build_spec(self, metadata: Mapping[str, object]) -> UiDeliverySpec:
        return UiDeliverySpec(
            task_id=self._source.task_id,
            operation=self._source.operation,
            feature=self._source.feature,
            world_id=self._source.world_id,
            generation=self._source.generation,
            event="progress",
            metadata=metadata,
        )

    def _metadata(
        self,
        snapshot: ProgressSnapshot,
        *,
        coalesced: bool = False,
    ) -> dict[str, object]:
        metadata = dict(self._source.metadata)
        metadata.update(
            {
                "state": snapshot.state.value,
                "coalesced": coalesced,
            }
        )
        if not coalesced:
            metadata.update(
                {
                    "completed": snapshot.completed,
                    "total": snapshot.total,
                }
            )
        return metadata


class UiDeliveryChannel:
    """Queue UI callbacks and publish one operation record per delivery.

    ``schedule`` is an injected framework adapter.  It must invoke the given
    callback on the UI thread and return ``False`` when it cannot accept it.
    Returning ``None`` is treated as acceptance for compatibility with legacy
    adapters that do not return a value; new adapters should return ``bool``.
    """

    def __init__(
        self,
        schedule: UiSchedulePort,
        operation_sink: Optional[OperationRecordSink] = None,
        *,
        clock: Callable[[], int] = time.monotonic_ns,
        id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        """Create a delivery channel.

        Args:
            schedule: Framework-neutral callback scheduler.
            operation_sink: Optional sink for unified operation records.
            clock: Monotonic nanosecond clock, injectable for deterministic tests.
            id_factory: Factory for unique delivery IDs, injectable for tests.

        Raises:
            TypeError: If a required callable dependency is missing.
        """
        if not callable(schedule):
            raise TypeError("UI 调度端口必须可调用")
        if operation_sink is not None and not callable(operation_sink):
            raise TypeError("操作指标接收器必须可调用")
        if not callable(clock):
            raise TypeError("UI 投递时钟必须可调用")
        if not callable(id_factory):
            raise TypeError("UI 投递 ID 工厂必须可调用")
        self._schedule = schedule
        self._operation_sink = operation_sink
        self._clock = clock
        self._id_factory = id_factory
        self._lock = threading.Lock()
        self._closed = False

    @property
    def is_closed(self) -> bool:
        """Return whether the channel rejects new deliveries."""
        with self._lock:
            return self._closed

    def close(self) -> None:
        """Reject future and queued deliveries; already-running callbacks finish."""
        with self._lock:
            self._closed = True

    def post(
        self,
        spec: UiDeliverySpec,
        callback: UiCallback,
        *,
        is_current: UiCurrentCheck,
        on_complete: Optional[UiCallback] = None,
    ) -> str:
        """Schedule a guarded UI callback and record its terminal outcome.

        The generation predicate is intentionally evaluated only when the
        scheduler drains the callback (and once before scheduling only to
        reject an already-closed channel).  This prevents a result that was
        current at completion time from mutating a newer view.

        Args:
            spec: Task identity and diagnostic dimensions.
            callback: Small UI projection callback; it must not perform I/O.
            is_current: Drain-time predicate for the owning view/session.
            on_complete: Optional cleanup invoked once after drain or rejection.

        Returns:
            A unique ID for this delivery attempt, including rejected attempts.
        """
        self._validate_post(spec, callback, is_current, on_complete)
        delivery_id = self._new_delivery_id()
        queued_ns = self._now_ns()
        attempt = _DeliveryAttempt(
            self,
            delivery_id,
            spec,
            callback,
            is_current,
            _DeliveryCompletion(on_complete),
            queued_ns,
        )
        if self.is_closed:
            attempt.reject_closed()
            return delivery_id
        attempt.schedule()
        return delivery_id

    def observe_progress(
        self,
        source: ProgressSource,
        callback: ProgressCallback,
        *,
        is_current: UiCurrentCheck,
    ) -> Callable[[], None]:
        """Subscribe to a task and deliver snapshots on the UI thread.

        Consecutive ``RUNNING`` snapshots waiting for the UI loop are
        coalesced to the newest value.  State changes such as cancellation and
        terminal outcomes retain independent deliveries.

        Args:
            source: Task identity and progress subscription port.
            callback: UI projection receiving immutable progress snapshots.
            is_current: Drain-time predicate for the owning view/session.

        Returns:
            Idempotent function that removes the progress subscription.
        """
        self._validate_progress_observer(callback, is_current)
        return _ProgressObserver(
            self,
            source,
            callback,
            is_current,
        ).start()

    @staticmethod
    def _validate_post(
        spec: UiDeliverySpec,
        callback: UiCallback,
        is_current: UiCurrentCheck,
        on_complete: Optional[UiCallback],
    ) -> None:
        if not isinstance(spec, UiDeliverySpec):
            raise TypeError("UI 投递必须使用 UiDeliverySpec")
        if not callable(callback):
            raise TypeError("UI 投递回调必须可调用")
        if not callable(is_current):
            raise TypeError("UI 投递 current 检查必须可调用")
        if on_complete is not None and not callable(on_complete):
            raise TypeError("UI 投递完成回调必须可调用")

    @staticmethod
    def _validate_progress_observer(
        callback: ProgressCallback,
        is_current: UiCurrentCheck,
    ) -> None:
        if not callable(callback):
            raise TypeError("UI 进度回调必须可调用")
        if not callable(is_current):
            raise TypeError("UI 进度 current 检查必须可调用")

    def _new_delivery_id(self) -> str:
        """Create and validate one unique delivery identifier."""
        delivery_id = str(self._id_factory()).strip()
        if not delivery_id:
            raise ValueError("UI 投递 ID 工厂返回空值")
        return delivery_id

    def _now_ns(self) -> int:
        """Read the injected monotonic clock as an integer nanosecond value."""
        return int(self._clock())

    @staticmethod
    def _elapsed_ms(start_ns: int, end_ns: int) -> float:
        """Convert a monotonic interval to non-negative milliseconds."""
        return max(0.0, (end_ns - start_ns) / 1_000_000.0)

    def _publish_error(
        self,
        delivery_id: str,
        spec: UiDeliverySpec,
        queue_wait_ms: float,
        run_ms: float,
        error: Exception,
        *,
        stage: str,
    ) -> None:
        """Publish a bounded error description without leaking exception data."""
        self._publish(
            delivery_id,
            spec,
            OperationOutcome.ERROR,
            queue_wait_ms=queue_wait_ms,
            run_ms=run_ms,
            extra={
                "stage": stage,
                "error_type": type(error).__name__,
                "error": str(error)[:500],
            },
        )

    def _publish(
        self,
        delivery_id: str,
        spec: UiDeliverySpec,
        outcome: OperationOutcome,
        *,
        queue_wait_ms: float,
        run_ms: float,
        extra: Optional[Mapping[str, object]] = None,
    ) -> None:
        """Send one immutable operation record to the optional sink."""
        sink = self._operation_sink
        if sink is None:
            return
        metadata = dict(spec.metadata)
        metadata.update(
            {
                "delivery_id": delivery_id,
                "task_id": spec.task_id,
                "operation": spec.operation,
                "event": spec.event,
                "generation": spec.generation,
            }
        )
        if extra:
            metadata.update(extra)
        record = OperationRecord(
            operation_id=delivery_id,
            feature=spec.feature,
            world_id=spec.world_id,
            queue_wait_ms=max(0.0, float(queue_wait_ms)),
            run_ms=max(0.0, float(run_ms)),
            outcome=outcome,
            metadata=MappingProxyType(metadata),
        )
        try:
            sink(record)
        except Exception:
            # Metrics are best-effort and must not change UI callback semantics.
            return


__all__ = [
    "ProgressSource",
    "UiDeliveryChannel",
    "UiDeliveryPort",
    "UiDeliverySpec",
    "UiSchedulePort",
]
