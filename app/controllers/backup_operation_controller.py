"""备份中心长时操作的后台生命周期协调。"""
from __future__ import annotations

import threading
from concurrent.futures import CancelledError
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from app.services.backup_service import BackupCancelledError
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    OperationCancelledError,
    OperationHandle,
    OperationScope,
    TaskPriority,
)


ProgressCallback = Callable[[float, str], None]
BackupOperation = Callable[[CancellationToken, ProgressCallback], object]
UiDispatcher = Callable[[Callable[[], None]], None]


class BackupOperationStatus(str, Enum):
    """一次备份中心操作的稳定终态。"""

    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class BackupOperationOutcome:
    """后台任务完成后交给 UI 投影的结构化结果。"""

    status: BackupOperationStatus
    result: object = None
    error: Optional[Exception] = None


@dataclass(frozen=True)
class BackupOperationRequest:
    """一次操作的不可变输入和终态回调。"""

    world_path: Path
    task_name: str
    operation: BackupOperation
    on_success: Callable[[object], None]
    on_error: Callable[[Exception], None]


@dataclass(frozen=True)
class BackupOperationUiPorts:
    """控制器投递进度和忙碌状态所需的 UI 端口。"""

    dispatch: UiDispatcher
    get_world_path: Callable[[], Optional[Path]]
    show_progress: Callable[[str], None]
    update_progress: Callable[[str, float], None]
    hide_progress: Callable[[], None]
    set_busy: Callable[[bool], None]
    set_cancel_pending: Callable[[], None]


@dataclass(frozen=True)
class _OperationContext:
    """捕获操作代数和发起时的世界身份。"""

    generation: int
    world_path: Path


class BackupOperationBusyError(RuntimeError):
    """已有备份操作尚未结束时抛出。"""


class BackupOperationController:
    """拥有单个备份操作，并仅向当前世界投递终态。"""

    def __init__(
        self,
        scope: OperationScope,
        ui: BackupOperationUiPorts,
    ) -> None:
        """绑定视图共享作用域与无 Flet 依赖的 UI 端口。"""
        self._scope = scope
        self._ui = ui
        self._lock = threading.Lock()
        self._generation = 0
        self._starting_generation: Optional[int] = None
        self._active: Optional[
            OperationHandle[BackupOperationOutcome]
        ] = None
        self._cancel_requested = False
        self._closed = False

    @property
    def is_running(self) -> bool:
        """返回是否已有操作正在提交或执行。"""
        with self._lock:
            return self._is_running_locked()

    @property
    def is_closed(self) -> bool:
        """返回控制器是否已经关闭。"""
        with self._lock:
            return self._closed

    def start(
        self,
        request: BackupOperationRequest,
    ) -> Optional[OperationHandle[BackupOperationOutcome]]:
        """提交一个可取消的备份中心操作。

        Args:
            request: 世界身份、工作函数和终态回调。

        Returns:
            已提交的任务句柄；提交失败并已投递错误时返回 None。

        Raises:
            BackupOperationBusyError: 已有操作尚未结束。
            RuntimeError: 控制器已经关闭。
        """
        context = self._begin(request.world_path)
        self._ui.set_busy(True)
        try:
            handle = self._scope.submit(
                "backup_operation",
                lambda token: self._execute(request, context, token),
                lane=ExecutionLane.IO,
                priority=TaskPriority.INTERACTIVE,
            )
        except Exception as error:
            self._apply_submission_error(context, error, request.on_error)
            return None
        cancel_requested = self._track(context, handle)
        if cancel_requested is None:
            handle.cancel()
            return handle
        if cancel_requested:
            handle.cancel()
        handle.add_done_callback(
            lambda completed: self._finish(completed, context, request)
        )
        return handle

    def cancel(self) -> bool:
        """请求当前操作在下一个安全检查点取消；可重复调用。"""
        with self._lock:
            if self._closed or not self._is_running_locked():
                return False
            first_request = not self._cancel_requested
            self._cancel_requested = True
            handle = self._active
        if first_request:
            self._ui.set_cancel_pending()
        if handle is not None:
            handle.cancel()
        return first_request

    def invalidate(self) -> None:
        """世界切换时取消操作、丢弃旧回调并复位进度 UI。"""
        with self._lock:
            if self._closed:
                return
            was_running = self._is_running_locked()
            self._generation += 1
            self._starting_generation = None
            handle = self._active
            self._active = None
            self._cancel_requested = False
        if handle is not None:
            handle.cancel()
        if was_running:
            self._ui.hide_progress()
            self._ui.set_busy(False)

    def close(self) -> None:
        """取消自身任务并拒绝迟到回调；不关闭共享作用域。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            self._starting_generation = None
            handle = self._active
            self._active = None
            self._cancel_requested = False
        if handle is not None:
            handle.cancel()

    def _begin(self, world_path: Path) -> _OperationContext:
        with self._lock:
            if self._closed:
                raise RuntimeError("备份操作控制器已经关闭")
            if self._is_running_locked():
                raise BackupOperationBusyError("已有备份操作正在执行")
            self._generation += 1
            generation = self._generation
            self._starting_generation = generation
            self._cancel_requested = False
        return _OperationContext(generation, world_path)

    def _track(
        self,
        context: _OperationContext,
        handle: OperationHandle[BackupOperationOutcome],
    ) -> Optional[bool]:
        with self._lock:
            if (
                self._closed
                or context.generation != self._generation
                or self._starting_generation != context.generation
            ):
                return None
            self._starting_generation = None
            self._active = handle
            return self._cancel_requested

    def _execute(
        self,
        request: BackupOperationRequest,
        context: _OperationContext,
        token: CancellationToken,
    ) -> BackupOperationOutcome:
        try:
            token.raise_if_cancelled()
            self._post_current(
                context,
                self._ui.show_progress,
                request.task_name,
            )

            def progress(value: float, message: str) -> None:
                self._post_current(
                    context,
                    self._ui.update_progress,
                    message,
                    value,
                )

            result = request.operation(token, progress)
        except (
            BackupCancelledError,
            CancelledError,
            OperationCancelledError,
        ) as error:
            return BackupOperationOutcome(
                BackupOperationStatus.CANCELLED,
                error=error,
            )
        except Exception as error:
            return BackupOperationOutcome(
                BackupOperationStatus.FAILED,
                error=error,
            )
        return BackupOperationOutcome(
            BackupOperationStatus.SUCCEEDED,
            result=result,
        )

    def _finish(
        self,
        handle: OperationHandle[BackupOperationOutcome],
        context: _OperationContext,
        request: BackupOperationRequest,
    ) -> None:
        try:
            outcome = handle.result()
        except (CancelledError, OperationCancelledError) as error:
            outcome = BackupOperationOutcome(
                BackupOperationStatus.CANCELLED,
                error=error,
            )
        except Exception as error:
            outcome = BackupOperationOutcome(
                BackupOperationStatus.FAILED,
                error=error,
            )
        self._deliver_outcome(context, handle, request, outcome)

    def _deliver_outcome(
        self,
        context: _OperationContext,
        handle: OperationHandle[BackupOperationOutcome],
        request: BackupOperationRequest,
        outcome: BackupOperationOutcome,
    ) -> None:
        if not self._is_current(context, handle):
            return

        def apply_outcome() -> None:
            if not self._claim_current(context, handle):
                return
            try:
                self._apply_terminal(request, outcome)
            finally:
                self._ui.hide_progress()
                self._ui.set_busy(False)

        self._ui.dispatch(apply_outcome)

    @staticmethod
    def _apply_terminal(
        request: BackupOperationRequest,
        outcome: BackupOperationOutcome,
    ) -> None:
        if outcome.status is BackupOperationStatus.SUCCEEDED:
            request.on_success(outcome.result)
        elif outcome.status is BackupOperationStatus.FAILED:
            error = outcome.error or RuntimeError("备份操作失败")
            request.on_error(error)

    def _apply_submission_error(
        self,
        context: _OperationContext,
        error: Exception,
        on_error: Callable[[Exception], None],
    ) -> None:
        with self._lock:
            if not self._matches_context_locked(context):
                return
            self._starting_generation = None
            self._cancel_requested = False
        try:
            on_error(error)
        finally:
            self._ui.hide_progress()
            self._ui.set_busy(False)

    def _post_current(
        self,
        context: _OperationContext,
        callback: Callable[..., None],
        *args: object,
    ) -> None:
        if not self._is_context_current(context):
            return

        def guarded() -> None:
            if self._is_context_current(context):
                callback(*args)

        self._ui.dispatch(guarded)

    def _is_context_current(self, context: _OperationContext) -> bool:
        world_path = self._ui.get_world_path()
        with self._lock:
            return (
                self._matches_context_locked(context)
                and context.world_path == world_path
            )

    def _is_current(
        self,
        context: _OperationContext,
        handle: OperationHandle[BackupOperationOutcome],
    ) -> bool:
        world_path = self._ui.get_world_path()
        with self._lock:
            return (
                self._matches_context_locked(context)
                and self._active is handle
                and context.world_path == world_path
            )

    def _claim_current(
        self,
        context: _OperationContext,
        handle: OperationHandle[BackupOperationOutcome],
    ) -> bool:
        world_path = self._ui.get_world_path()
        with self._lock:
            if (
                not self._matches_context_locked(context)
                or self._active is not handle
                or context.world_path != world_path
            ):
                return False
            self._active = None
            self._cancel_requested = False
            return True

    def _matches_context_locked(self, context: _OperationContext) -> bool:
        return (
            not self._closed
            and context.generation == self._generation
            and (
                self._starting_generation == context.generation
                or self._active is not None
            )
        )

    def _is_running_locked(self) -> bool:
        return self._starting_generation is not None or self._active is not None


__all__ = [
    "BackupOperationBusyError",
    "BackupOperationController",
    "BackupOperationOutcome",
    "BackupOperationRequest",
    "BackupOperationStatus",
    "BackupOperationUiPorts",
]
