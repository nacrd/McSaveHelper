"""映射页面后台操作的最新任务协调器。"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import CancelledError
from threading import Lock
from typing import Optional, TypeVar, cast

from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
    OperationHandle,
    OperationScope,
    TaskPriority,
)


ResultT = TypeVar("ResultT")
PostUi = Callable[[Callable[[], None]], None]


class _LatestOperationGroup:
    """为多个操作 key 保留最新任务，并在关闭后丢弃迟到结果。"""

    def __init__(
        self,
        runtime: ExecutionRuntime,
        scope_name: str,
        post_ui: PostUi,
    ) -> None:
        """创建由页面拥有的运行时作用域。

        Args:
            runtime: 应用共享后台执行运行时。
            scope_name: 运行时诊断使用的作用域名。
            post_ui: 将无参回调投递到 UI 线程的函数。
        """
        self._scope: OperationScope = runtime.create_scope(scope_name)
        self._post_ui = post_ui
        self._lock = Lock()
        self._generations: dict[str, int] = {}
        self._handles: dict[str, OperationHandle[object]] = {}
        self._closed = False

    def submit(
        self,
        key: str,
        work: Callable[[CancellationToken], ResultT],
        on_success: Optional[Callable[[ResultT], object]],
        on_error: Callable[[Exception], object],
        *,
        priority: TaskPriority = TaskPriority.INTERACTIVE,
    ) -> None:
        """替换同 key 任务，并只发布最新 generation 的结果。"""
        with self._lock:
            if self._closed:
                return
            generation = self._generations.get(key, 0) + 1
            self._generations[key] = generation
            previous = self._handles.pop(key, None)
        if previous is not None:
            previous.cancel()

        try:
            handle = self._scope.submit(
                key,
                work,
                lane=ExecutionLane.IO,
                priority=priority,
            )
        except Exception as error:
            self._deliver(key, generation, on_error, error)
            return

        tracked = cast(OperationHandle[object], handle)
        with self._lock:
            is_current = (
                not self._closed
                and self._generations.get(key) == generation
            )
            if is_current:
                self._handles[key] = tracked
        if not is_current:
            handle.cancel()
            return
        handle.add_done_callback(
            lambda completed: self._finish(
                key,
                generation,
                completed,
                on_success,
                on_error,
            )
        )

    def _finish(
        self,
        key: str,
        generation: int,
        handle: OperationHandle[ResultT],
        on_success: Optional[Callable[[ResultT], object]],
        on_error: Callable[[Exception], object],
    ) -> None:
        """解析后台终态并投递成功或失败回调。"""
        tracked = cast(OperationHandle[object], handle)
        with self._lock:
            if self._handles.get(key) is tracked:
                self._handles.pop(key, None)
        if handle.cancelled:
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            self._deliver(key, generation, on_error, error)
            return
        if on_success is not None:
            self._deliver(key, generation, on_success, result)

    def _deliver(
        self,
        key: str,
        generation: int,
        callback: Callable[..., object],
        *args: object,
    ) -> None:
        """投递结果，并在 UI 真正执行时再次校验 generation。"""
        def guarded() -> None:
            with self._lock:
                is_current = (
                    not self._closed
                    and self._generations.get(key) == generation
                )
            if is_current:
                callback(*args)

        self._post_ui(guarded)

    def close(self) -> None:
        """取消全部任务并使已排队的 UI 回调失效；可重复调用。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generations = {
                key: generation + 1
                for key, generation in self._generations.items()
            }
            self._handles.clear()
        self._scope.close()


class _DebouncedLatestSave:
    """串行保存最新内存状态，并在关闭时刷新防抖窗口。"""

    def __init__(
        self,
        operations: _LatestOperationGroup,
        save: Callable[[], None],
    ) -> None:
        self._operations = operations
        self._save = save
        self._lock = Lock()
        self._generation = 0
        self._pending = False

    def schedule(
        self,
        delay_seconds: float,
        on_error: Callable[[Exception], object],
    ) -> None:
        """合并连续请求，并只让最新 generation 清除待保存标记。"""
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._pending = True
        self._operations.submit(
            "uuid_save",
            lambda token: self._persist(token, generation, delay_seconds),
            None,
            on_error,
            priority=TaskPriority.BACKGROUND,
        )

    def flush(self) -> None:
        """同步保存仍在防抖窗口的最新状态；适用于页面关闭。"""
        with self._lock:
            self._generation += 1
            if not self._pending:
                return
            self._save()
            self._pending = False

    def _persist(
        self,
        token: CancellationToken,
        generation: int,
        delay_seconds: float,
    ) -> None:
        if token.wait(delay_seconds):
            token.raise_if_cancelled()
        with self._lock:
            token.raise_if_cancelled()
            self._save()
            if generation == self._generation:
                self._pending = False
