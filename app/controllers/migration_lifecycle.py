"""迁移 worker 兼容适配与任务生命周期状态。"""
from __future__ import annotations

import inspect
import threading
from dataclasses import dataclass
from typing import Callable, Generic, Optional, TypeVar, cast

from app.services.execution_runtime import (
    CancellationToken,
    OperationHandle,
)
from core.types import LogCallback, ProgressCallback


RequestT = TypeVar("RequestT")
WorkerTarget = Callable[[CancellationToken], None]
LegacyWorkerTarget = Callable[[str], None]
WorkerStarter = (
    Callable[[str, WorkerTarget], OperationHandle[None]]
    | Callable[[str, LegacyWorkerTarget, str], Optional[OperationHandle[None]]]
)
UiPost = Callable[[Callable[[], None]], None]


class MigrationAlreadyRunning(RuntimeError):
    """同一控制器已拥有迁移任务时抛出。"""


@dataclass(frozen=True)
class WorkerSubmission:
    """worker 适配器返回的提交方式与可选运行时句柄。"""

    handle: Optional[OperationHandle[None]]
    uses_legacy_target: bool


@dataclass(frozen=True)
class HandleInstallOutcome:
    """运行时句柄安装结果。"""

    accepted: bool
    restore_ui: bool = False


@dataclass(frozen=True)
class CancellationOutcome:
    """取消请求需要由控制器执行的外部动作。"""

    accepted: bool
    handle: Optional[OperationHandle[None]] = None


@dataclass(frozen=True)
class CloseOutcome:
    """关闭状态转换后需要由控制器执行的外部动作。"""

    changed: bool
    should_cancel_domain: bool = False
    handle: Optional[OperationHandle[None]] = None


class MigrationWorkerAdapter:
    """兼容当前 token worker 与旧三参数 worker 启动端口。"""

    @classmethod
    def submit(
        cls,
        starter: WorkerStarter,
        operation_id: str,
        worker: WorkerTarget,
        legacy_target: LegacyWorkerTarget,
        destination: str,
    ) -> WorkerSubmission:
        """按启动端口签名选择 worker 形态并提交任务。"""
        if cls._uses_legacy_shape(starter):
            legacy = cast(
                Callable[..., Optional[OperationHandle[None]]],
                starter,
            )
            return WorkerSubmission(
                handle=legacy(operation_id, legacy_target, destination),
                uses_legacy_target=True,
            )
        current = cast(
            Callable[[str, WorkerTarget], OperationHandle[None]],
            starter,
        )
        return WorkerSubmission(
            handle=current(operation_id, worker),
            uses_legacy_target=False,
        )

    @staticmethod
    def _uses_legacy_shape(starter: Callable[..., object]) -> bool:
        """识别迁移控制器旧版三参数 worker 适配器。"""
        try:
            parameters = tuple(inspect.signature(starter).parameters.values())
        except (TypeError, ValueError):
            return False
        positional = tuple(
            parameter
            for parameter in parameters
            if parameter.kind
            in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
        )
        has_varargs = any(
            parameter.kind == parameter.VAR_POSITIONAL
            for parameter in parameters
        )
        return not has_varargs and len(positional) >= 3


class MigrationLifecycle(Generic[RequestT]):
    """串行化迁移任务身份、取消与迟到回调失效。"""

    def __init__(self) -> None:
        """创建尚未启动且可接收请求的生命周期。"""
        self._lock = threading.Lock()
        self._generation = 0
        self._active_generation: Optional[int] = None
        self._starting_generation: Optional[int] = None
        self._active_operation: Optional[OperationHandle[None]] = None
        self._legacy_context: Optional[tuple[int, RequestT]] = None
        self._cancel_requested = False
        self._closed = False

    @property
    def active_operation(self) -> Optional[OperationHandle[None]]:
        """返回当前运行时句柄，供取消与诊断使用。"""
        with self._lock:
            return self._active_operation

    def reserve_start(self) -> int:
        """为新请求预留唯一代数并阻止并发重复启动。"""
        with self._lock:
            if self._closed:
                raise RuntimeError("迁移页面已经关闭")
            if self._has_active_locked():
                raise MigrationAlreadyRunning()
            self._generation += 1
            generation = self._generation
            self._active_generation = generation
            self._starting_generation = generation
            self._active_operation = None
            self._cancel_requested = False
            return generation

    def remember_legacy_request(
        self,
        generation: int,
        request: RequestT,
    ) -> None:
        """保存旧 worker 在稍后执行时需要的不可变请求快照。"""
        with self._lock:
            if generation == self._generation and not self._closed:
                self._legacy_context = (generation, request)

    def resolve_legacy_request(
        self,
        matches: Callable[[RequestT], bool],
    ) -> tuple[Optional[RequestT], int]:
        """解析旧 worker 快照；直接调用时建立兼容代数。"""
        with self._lock:
            context = self._legacy_context
            if context is not None:
                generation, request = context
                if matches(request):
                    return request, generation
            if self._has_active_locked():
                raise MigrationAlreadyRunning()
            generation = self._generation
            if self._active_generation is None:
                self._active_generation = generation
                self._cancel_requested = False
            return None, generation

    def install_handle(
        self,
        generation: int,
        handle: Optional[OperationHandle[None]],
    ) -> HandleInstallOutcome:
        """安装运行时句柄，或取消在提交期间已失效的句柄。"""
        if handle is None:
            raise RuntimeError("迁移运行时未返回任务句柄")
        with self._lock:
            self._starting_generation = None
            is_stale = self._closed or generation != self._generation
            if is_stale:
                restore_ui = not self._closed
                self._active_generation = None
                self._legacy_context = None
                self._cancel_requested = False
            else:
                restore_ui = False
                self._active_operation = handle
                self._legacy_context = None
        if is_stale:
            handle.cancel()
            return HandleInstallOutcome(False, restore_ui)
        return HandleInstallOutcome(True)

    def rollback_start(self) -> None:
        """回滚 worker 提交前后的启动预留。"""
        with self._lock:
            self._starting_generation = None
            self._active_generation = None
            self._active_operation = None
            self._legacy_context = None
            self._cancel_requested = False

    def is_current(
        self,
        generation: int,
        token: CancellationToken,
    ) -> bool:
        """判断 worker 回调是否仍属于当前可见任务。"""
        with self._lock:
            return (
                not self._closed
                and not token.is_cancelled
                and generation == self._generation
                and self._active_generation == generation
            )

    def complete_handle(
        self,
        handle: OperationHandle[None],
    ) -> Optional[bool]:
        """结束当前句柄；迟到句柄返回 None，否则返回是否恢复 UI。"""
        with self._lock:
            if handle is not self._active_operation:
                return None
            generation = self._active_generation
            self._clear_active_locked()
            return not self._closed and generation is not None

    def complete_legacy(self, generation: int) -> Optional[bool]:
        """结束旧 worker；迟到入口返回 None，否则返回是否恢复 UI。"""
        with self._lock:
            if self._active_operation is not None:
                return None
            if self._active_generation != generation:
                return None
            self._clear_active_locked()
            return not self._closed

    def request_cancel(self) -> CancellationOutcome:
        """使当前代数失效并返回需要取消的运行时句柄。"""
        with self._lock:
            if self._cancel_requested or not self._has_active_locked():
                return CancellationOutcome(False)
            self._cancel_requested = True
            self._generation += 1
            return CancellationOutcome(True, self._active_operation)

    def close(self) -> CloseOutcome:
        """幂等关闭生命周期并使所有迟到回调失效。"""
        with self._lock:
            if self._closed:
                return CloseOutcome(False)
            self._closed = True
            self._generation += 1
            self._active_generation = None
            was_starting = self._starting_generation is not None
            self._starting_generation = None
            handle = self._active_operation
            should_cancel_domain = (
                (handle is not None or was_starting)
                and not self._cancel_requested
            )
            self._cancel_requested = True
            return CloseOutcome(
                changed=True,
                should_cancel_domain=should_cancel_domain,
                handle=handle,
            )

    def _has_active_locked(self) -> bool:
        if self._starting_generation is not None:
            return True
        handle = self._active_operation
        return handle is not None and not self._handle_done(handle)

    @staticmethod
    def _handle_done(handle: OperationHandle[None]) -> bool:
        value = getattr(handle, "done", False)
        return bool(value() if callable(value) else value)

    def _clear_active_locked(self) -> None:
        self._active_operation = None
        self._active_generation = None
        self._starting_generation = None
        self._legacy_context = None
        self._cancel_requested = False


class MigrationUiPublisher(Generic[RequestT]):
    """经 UI 调度端口发布并双重校验迁移任务代数。"""

    def __init__(
        self,
        lifecycle: MigrationLifecycle[RequestT],
        post_ui: UiPost,
    ) -> None:
        """绑定任务生命周期与 UI 线程调度端口。"""
        self._lifecycle = lifecycle
        self._post_ui = post_ui

    def publish(
        self,
        generation: int,
        token: CancellationToken,
        callback: Callable[..., None],
        *args: object,
    ) -> None:
        """在投递前和执行时均校验任务身份。"""
        if not self._lifecycle.is_current(generation, token):
            return

        def guarded() -> None:
            if self._lifecycle.is_current(generation, token):
                callback(*args)

        self._post_ui(guarded)

    def log_callback(
        self,
        generation: int,
        token: CancellationToken,
        callback: LogCallback,
    ) -> LogCallback:
        """创建带任务身份校验的日志回调。"""
        def publish_log(message: str, level: str = "INFO") -> None:
            self.publish(generation, token, callback, message, level)

        return publish_log

    def progress_callback(
        self,
        generation: int,
        token: CancellationToken,
        callback: ProgressCallback,
    ) -> ProgressCallback:
        """创建带任务身份校验的进度回调。"""
        def publish_progress(value: float) -> None:
            self.publish(generation, token, callback, value)

        return publish_progress


__all__ = [
    "CancellationOutcome",
    "CloseOutcome",
    "HandleInstallOutcome",
    "LegacyWorkerTarget",
    "MigrationAlreadyRunning",
    "MigrationLifecycle",
    "MigrationUiPublisher",
    "MigrationWorkerAdapter",
    "WorkerStarter",
    "WorkerSubmission",
    "WorkerTarget",
]
