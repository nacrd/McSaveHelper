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

    task_id: str
    operation: str
    feature: str
    world_id: str
    generation: int
    metadata: Mapping[str, object]

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

    def post(
        self,
        spec: "UiDeliverySpec",
        callback: UiCallback,
        *,
        is_current: UiCurrentCheck,
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
        if not isinstance(spec, UiDeliverySpec):
            raise TypeError("UI 投递必须使用 UiDeliverySpec")
        if not callable(callback):
            raise TypeError("UI 投递回调必须可调用")
        if not callable(is_current):
            raise TypeError("UI 投递 current 检查必须可调用")
        if on_complete is not None and not callable(on_complete):
            raise TypeError("UI 投递完成回调必须可调用")

        delivery_id = self._new_delivery_id()
        queued_ns = self._now_ns()
        if self.is_closed:
            self._publish(
                delivery_id,
                spec,
                OperationOutcome.STALE,
                queue_wait_ms=0.0,
                run_ms=0.0,
                extra={"drop_reason": "channel_closed"},
            )
            self._run_completion(on_complete)
            return delivery_id

        state_lock = threading.Lock()
        state = {"finished": False}

        def finish_delivery() -> None:
            with state_lock:
                if state["finished"]:
                    return
                state["finished"] = True
            self._run_completion(on_complete)

        def drain() -> None:
            started_ns = self._now_ns()
            queue_wait_ms = self._elapsed_ms(queued_ns, started_ns)
            try:
                if self.is_closed:
                    self._publish(
                        delivery_id,
                        spec,
                        OperationOutcome.STALE,
                        queue_wait_ms=queue_wait_ms,
                        run_ms=0.0,
                        extra={"drop_reason": "channel_closed"},
                    )
                    return
                try:
                    current = bool(is_current())
                except Exception as error:
                    self._publish_error(
                        delivery_id,
                        spec,
                        queue_wait_ms,
                        0.0,
                        error,
                        stage="guard",
                    )
                    return
                if not current:
                    self._publish(
                        delivery_id,
                        spec,
                        OperationOutcome.STALE,
                        queue_wait_ms=queue_wait_ms,
                        run_ms=0.0,
                        extra={"drop_reason": "generation_guard"},
                    )
                    return

                callback_started_ns = self._now_ns()
                try:
                    callback()
                except Exception as error:
                    self._publish_error(
                        delivery_id,
                        spec,
                        queue_wait_ms,
                        self._elapsed_ms(callback_started_ns, self._now_ns()),
                        error,
                        stage="callback",
                    )
                    return
                self._publish(
                    delivery_id,
                    spec,
                    OperationOutcome.OK,
                    queue_wait_ms=queue_wait_ms,
                    run_ms=self._elapsed_ms(callback_started_ns, self._now_ns()),
                )
            finally:
                finish_delivery()

        try:
            accepted = self._schedule(drain)
        except Exception as error:
            with state_lock:
                already_finished = bool(state["finished"])
            if not already_finished:
                self._publish_error(
                    delivery_id,
                    spec,
                    queue_wait_ms=0.0,
                    run_ms=0.0,
                    error=error,
                    stage="schedule",
                )
                finish_delivery()
            return delivery_id

        # Legacy schedulers often return None.  Only an explicit False is a
        # rejection; this keeps migration compatible while making new adapters
        # able to report backpressure deterministically.
        if accepted is False:
            with state_lock:
                already_finished = bool(state["finished"])
            if not already_finished:
                self._publish_error(
                    delivery_id,
                    spec,
                    queue_wait_ms=0.0,
                    run_ms=0.0,
                    error=RuntimeError("UI 调度器拒绝投递"),
                    stage="schedule",
                )
                finish_delivery()
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
        if not callable(callback):
            raise TypeError("UI 进度回调必须可调用")
        if not callable(is_current):
            raise TypeError("UI 进度 current 检查必须可调用")

        state_lock = threading.Lock()
        latest_running: Optional[ProgressSnapshot] = None
        running_scheduled = False
        running_consumed = False
        disposed = False

        def progress_metadata(
            snapshot: ProgressSnapshot,
            *,
            coalesced: bool = False,
        ) -> dict[str, object]:
            metadata = dict(source.metadata)
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

        def guarded_current() -> bool:
            with state_lock:
                active = not disposed
            return active and bool(is_current())

        def build_spec(metadata: Mapping[str, object]) -> UiDeliverySpec:
            return UiDeliverySpec(
                task_id=source.task_id,
                operation=source.operation,
                feature=source.feature,
                world_id=source.world_id,
                generation=source.generation,
                event="progress",
                metadata=metadata,
            )

        def deliver_latest_running() -> None:
            nonlocal latest_running, running_consumed
            with state_lock:
                snapshot = latest_running
                latest_running = None
                running_consumed = True
            if snapshot is not None:
                callback(snapshot)

        def finish_running_delivery() -> None:
            nonlocal running_consumed, running_scheduled
            with state_lock:
                was_consumed = running_consumed
                running_consumed = False
                running_scheduled = False
                should_reschedule = (
                    was_consumed
                    and not disposed
                    and latest_running is not None
                )
            if should_reschedule:
                schedule_running_delivery()

        def schedule_running_delivery() -> None:
            nonlocal running_consumed, running_scheduled
            with state_lock:
                if disposed or running_scheduled or latest_running is None:
                    return
                running_scheduled = True
                running_consumed = False
                initial = latest_running
            try:
                self.post(
                    build_spec(progress_metadata(initial, coalesced=True)),
                    deliver_latest_running,
                    is_current=guarded_current,
                    on_complete=finish_running_delivery,
                )
            except Exception:
                # ID/clock/spec construction can fail before ``post`` owns
                # the completion callback.  Release the coalescing latch so
                # a later progress snapshot can retry after a transient
                # adapter failure.
                with state_lock:
                    running_scheduled = False

        def on_progress(snapshot: ProgressSnapshot) -> None:
            nonlocal latest_running
            if snapshot.state is OperationState.RUNNING:
                with state_lock:
                    if disposed:
                        return
                    latest_running = snapshot
                schedule_running_delivery()
                return
            self.post(
                build_spec(progress_metadata(snapshot)),
                lambda: callback(snapshot),
                is_current=guarded_current,
            )

        source_unsubscribe = source.subscribe_progress(on_progress)

        def unsubscribe() -> None:
            nonlocal disposed, latest_running
            with state_lock:
                if disposed:
                    return
                disposed = True
                latest_running = None
            source_unsubscribe()

        return unsubscribe

    @staticmethod
    def _run_completion(callback: Optional[UiCallback]) -> None:
        """Run best-effort delivery cleanup without changing UI semantics."""
        if callback is None:
            return
        try:
            callback()
        except Exception:
            return

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
