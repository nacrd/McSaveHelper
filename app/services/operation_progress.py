"""后台操作的不可变进度快照与线程安全报告器。"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable, Optional

from core.observability import OperationOutcome


class OperationState(str, Enum):
    """后台操作生命周期状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    STALE = "stale"
    ERROR = "error"


@dataclass(frozen=True)
class ProgressSnapshot:
    """一次任务进度的不可变一致快照。"""

    task_id: str
    operation: str
    generation: int
    state: OperationState
    completed: float = 0.0
    total: Optional[float] = None
    message: str = ""
    error: str = ""
    updated_ns: int = 0

    @property
    def fraction(self) -> float:
        """返回 0..1 进度；总量未知时返回 0。"""
        if self.total is None or self.total <= 0:
            return 0.0
        return max(0.0, min(1.0, self.completed / self.total))

    @property
    def is_terminal(self) -> bool:
        """返回任务是否已经到达最终状态。"""
        return self.state in {
            OperationState.SUCCEEDED,
            OperationState.CANCELLED,
            OperationState.STALE,
            OperationState.ERROR,
        }


class ProgressReporter:
    """保证进度单调、可并发读取的任务内报告端口。"""

    def __init__(self, task_id: str, operation: str, generation: int) -> None:
        """创建排队态快照。"""
        if not task_id.strip():
            raise ValueError("任务 ID 不能为空")
        if not operation.strip():
            raise ValueError("后台操作名不能为空")
        if generation < 0:
            raise ValueError("任务 generation 不能为负数")
        self._lock = threading.Lock()
        self._listener_sequence = 0
        self._listeners: dict[
            int,
            Callable[[ProgressSnapshot], None],
        ] = {}
        self._snapshot = ProgressSnapshot(
            task_id=task_id,
            operation=operation,
            generation=generation,
            state=OperationState.QUEUED,
            updated_ns=time.monotonic_ns(),
        )

    def snapshot(self) -> ProgressSnapshot:
        """返回当前不可变快照。"""
        with self._lock:
            return self._snapshot

    def subscribe(
        self,
        callback: Callable[[ProgressSnapshot], None],
    ) -> Callable[[], None]:
        """订阅进度变化并返回幂等取消函数。

        Args:
            callback: 接收不可变快照的轻量回调。

        Returns:
            从此报告器移除该订阅的函数。
        """
        if not callable(callback):
            raise TypeError("进度订阅回调必须可调用")
        with self._lock:
            self._listener_sequence += 1
            listener_id = self._listener_sequence
            self._listeners[listener_id] = callback
        removed = False
        remove_lock = threading.Lock()

        def unsubscribe() -> None:
            nonlocal removed
            with remove_lock:
                if removed:
                    return
                removed = True
            with self._lock:
                self._listeners.pop(listener_id, None)

        return unsubscribe

    @staticmethod
    def _notify(
        snapshot: ProgressSnapshot,
        listeners: tuple[Callable[[ProgressSnapshot], None], ...],
    ) -> None:
        """在锁外通知订阅者，避免回调重入破坏状态不变量。"""
        for callback in listeners:
            try:
                callback(snapshot)
            except Exception:
                # Progress observers are best-effort and cannot fail work.
                continue

    def update(
        self,
        completed: float,
        total: Optional[float] = None,
        message: str = "",
    ) -> ProgressSnapshot:
        """发布单调进度并返回新快照。

        Args:
            completed: 已完成工作量，不能小于上一快照。
            total: 可选总工作量，必须大于零且不小于 completed。
            message: 简短阶段说明。

        Returns:
            发布后的不可变快照。

        Raises:
            ValueError: 数值为负、倒退或超出总量。
            RuntimeError: 任务已经结束。
        """
        completed_value = float(completed)
        total_value = None if total is None else float(total)
        if not math.isfinite(completed_value):
            raise ValueError("任务进度必须是有限数值")
        if total_value is not None and not math.isfinite(total_value):
            raise ValueError("任务进度总量必须是有限数值")
        if completed_value < 0:
            raise ValueError("任务进度不能为负数")
        if total_value is not None and total_value <= 0:
            raise ValueError("任务进度总量必须大于零")
        if total_value is not None and completed_value > total_value:
            raise ValueError("已完成工作量不能超过总量")
        with self._lock:
            current = self._snapshot
            if current.is_terminal:
                raise RuntimeError("任务已经结束，不能继续报告进度")
            if completed_value < current.completed:
                raise ValueError("任务进度不能倒退")
            selected_total = total_value if total is not None else current.total
            if selected_total is not None and completed_value > selected_total:
                raise ValueError("已完成工作量不能超过总量")
            if selected_total is not None:
                selected_fraction = completed_value / selected_total
                if selected_fraction < current.fraction:
                    raise ValueError("任务进度比例不能倒退")
            self._snapshot = replace(
                current,
                completed=completed_value,
                total=selected_total,
                message=message,
                updated_ns=time.monotonic_ns(),
            )
            snapshot = self._snapshot
            listeners = tuple(self._listeners.values())
        self._notify(snapshot, listeners)
        return snapshot

    def mark_running(self) -> None:
        """由运行时在工作函数开始前切换为执行态。"""
        with self._lock:
            if self._snapshot.state is not OperationState.QUEUED:
                return
            self._snapshot = replace(
                self._snapshot,
                state=OperationState.RUNNING,
                updated_ns=time.monotonic_ns(),
            )
            snapshot = self._snapshot
            listeners = tuple(self._listeners.values())
        self._notify(snapshot, listeners)

    def mark_cancel_requested(self) -> None:
        """立即发布取消请求，供 UI 在 100 ms 预算内观察。"""
        with self._lock:
            if (
                self._snapshot.is_terminal
                or self._snapshot.state is OperationState.CANCEL_REQUESTED
            ):
                return
            self._snapshot = replace(
                self._snapshot,
                state=OperationState.CANCEL_REQUESTED,
                updated_ns=time.monotonic_ns(),
            )
            snapshot = self._snapshot
            listeners = tuple(self._listeners.values())
        self._notify(snapshot, listeners)

    def mark_finished(
        self,
        outcome: OperationOutcome,
        error: Optional[BaseException] = None,
    ) -> None:
        """由运行时发布真实终态，不把迟到取消覆盖为成功。"""
        state = {
            OperationOutcome.OK: OperationState.SUCCEEDED,
            OperationOutcome.CANCELLED: OperationState.CANCELLED,
            OperationOutcome.STALE: OperationState.STALE,
            OperationOutcome.ERROR: OperationState.ERROR,
        }[outcome]
        with self._lock:
            current = self._snapshot
            stale_failed = (
                current.state is OperationState.STALE
                and outcome in {
                    OperationOutcome.CANCELLED,
                    OperationOutcome.ERROR,
                }
            )
            if current.is_terminal and not stale_failed:
                return
            total = current.total
            completed = current.completed
            if outcome is OperationOutcome.OK:
                total = total if total is not None else 1.0
                completed = total
            error_text = ""
            if error is not None:
                error_text = f"{type(error).__name__}: {error}"[:500]
            self._snapshot = replace(
                current,
                state=state,
                completed=completed,
                total=total,
                error=error_text,
                updated_ns=time.monotonic_ns(),
            )
            snapshot = self._snapshot
            listeners = tuple(self._listeners.values())
        self._notify(snapshot, listeners)

    def mark_stale(self) -> None:
        """将尚未交付到当前视图的结果标记为过期。"""
        with self._lock:
            if self._snapshot.state in {
                OperationState.ERROR,
                OperationState.CANCELLED,
                OperationState.STALE,
            }:
                return
            self._snapshot = replace(
                self._snapshot,
                state=OperationState.STALE,
                updated_ns=time.monotonic_ns(),
            )
            snapshot = self._snapshot
            listeners = tuple(self._listeners.values())
        self._notify(snapshot, listeners)


__all__ = [
    "OperationState",
    "ProgressReporter",
    "ProgressSnapshot",
]
