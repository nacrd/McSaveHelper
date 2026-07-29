"""设置页持久化与缓存操作的后台协调器。"""
from __future__ import annotations

import threading
from concurrent.futures import CancelledError
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable, Mapping, Optional, TypeVar, cast

from app.models.config import ApplicationSettings
from app.services.cache_registry import CacheRegistryStats
from app.services.diagnostic_report import write_diagnostic_report
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    ExecutionRuntime,
    ExecutionRuntimeSnapshot,
    OperationCancelledError,
    OperationHandle,
    TaskPriority,
)
from app.services.operation_metrics import UiDeliveryMetricsSummary


ResultT = TypeVar("ResultT")
CallbackDispatcher = Callable[[Callable[[], None]], None]
DebounceWait = Callable[[CancellationToken, float], bool]


@dataclass(frozen=True)
class SettingsCacheSnapshot:
    """设置页展示所需的一致缓存与运行时快照。"""

    cache: CacheRegistryStats
    runtime: Optional[ExecutionRuntimeSnapshot]
    ui_delivery: UiDeliveryMetricsSummary
    cache_path: str


DiagnosticReportBuilder = Callable[[SettingsCacheSnapshot], str]


@dataclass(frozen=True)
class CacheClearMetrics:
    """一次缓存清理的稳定结果。"""

    deleted_files: int
    freed_bytes: int
    memory_chunks_cleared: int

    @classmethod
    def from_mapping(cls, result: Mapping[str, int]) -> "CacheClearMetrics":
        """从缓存适配器结果构造规范化指标。"""
        return cls(
            deleted_files=int(result.get("deleted_files", 0) or 0),
            freed_bytes=int(result.get("freed_bytes", 0) or 0),
            memory_chunks_cleared=int(
                result.get("memory_chunks_cleared", 0) or 0
            ),
        )


@dataclass(frozen=True)
class CacheClearOutcome:
    """缓存清理指标及清理后的展示快照。"""

    metrics: CacheClearMetrics
    snapshot: SettingsCacheSnapshot


@dataclass(frozen=True)
class SettingsIOControllerDependencies:
    """设置后台控制器依赖端口。"""

    execution_runtime: ExecutionRuntime
    save_settings: Callable[[ApplicationSettings], None]
    reset_settings: Callable[[], ApplicationSettings]
    cache_snapshot: Callable[[], CacheRegistryStats]
    clear_caches: Callable[[], Mapping[str, int]]
    cache_path: Callable[[], str]
    runtime_snapshot: Callable[[], Optional[ExecutionRuntimeSnapshot]]
    ui_delivery_summary: Callable[[], UiDeliveryMetricsSummary]
    build_diagnostic_report: DiagnosticReportBuilder
    dispatch: CallbackDispatcher
    save_debounce_seconds: float = 0.35
    debounce_wait: Optional[DebounceWait] = None


class SettingsIOController:
    """在共享 I/O 通道协调设置保存与缓存维护。"""

    _SAVE = "save"
    _RESET = "reset"
    _CACHE = "cache"

    def __init__(self, dependencies: SettingsIOControllerDependencies) -> None:
        """创建可取消、可关闭的设置操作作用域。

        Args:
            dependencies: 运行时、业务端口与结果投递器。
        """
        if dependencies.save_debounce_seconds < 0:
            raise ValueError("设置保存防抖时长不能为负数")
        self._deps = dependencies
        self._scope = dependencies.execution_runtime.create_scope("settings_view")
        self._debounce_wait = dependencies.debounce_wait or self._wait_for_debounce
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()
        self._closed = False
        self._pending_save: Optional[ApplicationSettings] = None
        self._generations = {
            self._SAVE: 0,
            self._RESET: 0,
            self._CACHE: 0,
        }
        self._handles: dict[str, Optional[OperationHandle[object]]] = {
            self._SAVE: None,
            self._RESET: None,
            self._CACHE: None,
        }

    @property
    def is_closed(self) -> bool:
        """返回控制器是否已经关闭。"""
        with self._lock:
            return self._closed

    def schedule_save(
        self,
        settings: ApplicationSettings,
        on_success: Callable[[], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        """防抖保存最新设置快照，并取消旧的待保存任务。"""
        started = self._begin_operation(self._SAVE)
        if started is None:
            return
        generation, previous = started
        if not self._set_pending_save(generation, settings):
            self._cancel(previous)
            return
        self._cancel(previous)

        def work(token: CancellationToken) -> None:
            self._debounce_wait(token, self._deps.save_debounce_seconds)
            with self._save_lock:
                token.raise_if_cancelled()
                self._deps.save_settings(settings)
                self._mark_save_persisted(generation, settings)

        self._submit(
            self._SAVE,
            generation,
            "save",
            work,
            lambda _result: on_success(),
            on_error,
            priority=TaskPriority.BACKGROUND,
        )

    def reset(
        self,
        on_success: Callable[[ApplicationSettings], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        """取消待保存快照并在 I/O 通道重置配置。"""
        self._invalidate_operation(self._SAVE)
        started = self._begin_operation(self._RESET)
        if started is None:
            return
        generation, previous = started
        self._cancel(previous)

        def work(token: CancellationToken) -> ApplicationSettings:
            token.raise_if_cancelled()
            settings = self._deps.reset_settings()
            token.raise_if_cancelled()
            return settings

        self._submit(
            self._RESET,
            generation,
            "reset",
            work,
            on_success,
            on_error,
            priority=TaskPriority.INTERACTIVE,
        )

    def refresh_cache(
        self,
        on_success: Callable[[SettingsCacheSnapshot], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        """在 I/O 通道采集缓存、运行时与路径快照。"""
        started = self._begin_operation(self._CACHE)
        if started is None:
            return
        generation, previous = started
        self._cancel(previous)
        self._submit(
            self._CACHE,
            generation,
            "refresh_cache",
            self._capture_cache_snapshot,
            on_success,
            on_error,
            priority=TaskPriority.INTERACTIVE,
        )

    def clear_cache(
        self,
        on_success: Callable[[CacheClearOutcome], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        """在 I/O 通道清理缓存并返回清理后的快照。"""
        started = self._begin_operation(self._CACHE)
        if started is None:
            return
        generation, previous = started
        self._cancel(previous)

        def work(token: CancellationToken) -> CacheClearOutcome:
            token.raise_if_cancelled()
            metrics = CacheClearMetrics.from_mapping(self._deps.clear_caches())
            token.raise_if_cancelled()
            snapshot = self._capture_cache_snapshot(token)
            return CacheClearOutcome(metrics=metrics, snapshot=snapshot)

        self._submit(
            self._CACHE,
            generation,
            "clear_cache",
            work,
            on_success,
            on_error,
            priority=TaskPriority.INTERACTIVE,
        )

    def export_diagnostic_report(
        self,
        path: Path | str,
        on_success: Callable[[Path], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        """采集最新观测快照并在 I/O 通道原子写入报告。"""
        started = self._begin_operation(self._CACHE)
        if started is None:
            return
        generation, previous = started
        self._cancel(previous)

        def work(token: CancellationToken) -> Path:
            snapshot = self._capture_cache_snapshot(token)
            content = self._deps.build_diagnostic_report(snapshot)
            token.raise_if_cancelled()
            return write_diagnostic_report(path, content)

        self._submit(
            self._CACHE,
            generation,
            "export_diagnostic_report",
            work,
            on_success,
            on_error,
            priority=TaskPriority.INTERACTIVE,
        )

    def close(self) -> None:
        """关闭任务并同步落盘仍处于防抖窗口的最新设置。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pending_save = self._pending_save
            self._pending_save = None
            handles = tuple(self._handles.values())
            for operation in self._generations:
                self._generations[operation] += 1
            self._handles = {operation: None for operation in self._handles}
        for handle in handles:
            self._cancel(handle)
        self._scope.close()
        if pending_save is not None:
            with self._save_lock:
                self._deps.save_settings(pending_save)

    def _capture_cache_snapshot(
        self,
        token: CancellationToken,
    ) -> SettingsCacheSnapshot:
        token.raise_if_cancelled()
        cache = self._deps.cache_snapshot()
        token.raise_if_cancelled()
        runtime = self._deps.runtime_snapshot()
        ui_delivery = self._deps.ui_delivery_summary()
        cache_path = self._deps.cache_path()
        token.raise_if_cancelled()
        return SettingsCacheSnapshot(cache, runtime, ui_delivery, cache_path)

    def _begin_operation(
        self,
        operation: str,
    ) -> Optional[tuple[int, Optional[OperationHandle[object]]]]:
        with self._lock:
            if self._closed:
                return None
            self._generations[operation] += 1
            generation = self._generations[operation]
            previous = self._handles[operation]
            self._handles[operation] = None
            return generation, previous

    def _invalidate_operation(self, operation: str) -> None:
        with self._lock:
            if self._closed:
                return
            self._generations[operation] += 1
            if operation == self._SAVE:
                self._pending_save = None
            previous = self._handles[operation]
            self._handles[operation] = None
        self._cancel(previous)

    def _set_pending_save(
        self,
        generation: int,
        settings: ApplicationSettings,
    ) -> bool:
        """登记最新防抖快照；关闭或过期时拒绝登记。"""
        with self._lock:
            if self._closed or self._generations[self._SAVE] != generation:
                return False
            self._pending_save = settings
            return True

    def _mark_save_persisted(
        self,
        generation: int,
        settings: ApplicationSettings,
    ) -> None:
        """仅在当前 generation 成功落盘后清除待保存快照。"""
        with self._lock:
            if (
                self._generations[self._SAVE] == generation
                and self._pending_save == settings
            ):
                self._pending_save = None

    def _submit(
        self,
        operation_kind: str,
        generation: int,
        operation_name: str,
        work: Callable[[CancellationToken], ResultT],
        on_success: Callable[[ResultT], None],
        on_error: Callable[[Exception], None],
        *,
        priority: TaskPriority,
    ) -> None:
        try:
            handle = self._scope.submit(
                operation_name,
                work,
                lane=ExecutionLane.IO,
                priority=priority,
            )
        except Exception as error:
            self._deliver(
                operation_kind,
                generation,
                partial(on_error, error),
            )
            return
        tracked = cast(OperationHandle[object], handle)
        with self._lock:
            if self._closed or self._generations[operation_kind] != generation:
                tracked.cancel()
                return
            self._handles[operation_kind] = tracked
        handle.add_done_callback(
            lambda completed: self._finish(
                operation_kind,
                generation,
                completed,
                on_success,
                on_error,
            )
        )

    def _finish(
        self,
        operation_kind: str,
        generation: int,
        handle: OperationHandle[ResultT],
        on_success: Callable[[ResultT], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        try:
            if handle.cancelled:
                return
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            self._deliver(
                operation_kind,
                generation,
                partial(on_error, error),
            )
        else:
            self._deliver(
                operation_kind,
                generation,
                lambda: on_success(result),
            )
        finally:
            self._clear_handle(
                operation_kind,
                generation,
                cast(OperationHandle[object], handle),
            )

    def _deliver(
        self,
        operation: str,
        generation: int,
        callback: Callable[[], None],
    ) -> None:
        def guarded() -> None:
            if self._is_current(operation, generation):
                callback()

        self._deps.dispatch(guarded)

    def _is_current(self, operation: str, generation: int) -> bool:
        with self._lock:
            return (
                not self._closed
                and self._generations[operation] == generation
            )

    def _clear_handle(
        self,
        operation: str,
        generation: int,
        handle: OperationHandle[object],
    ) -> None:
        with self._lock:
            if (
                self._generations[operation] == generation
                and self._handles[operation] is handle
            ):
                self._handles[operation] = None

    @staticmethod
    def _cancel(handle: Optional[OperationHandle[object]]) -> None:
        if handle is not None:
            handle.cancel()

    @staticmethod
    def _wait_for_debounce(token: CancellationToken, delay: float) -> bool:
        return token.wait(delay)


__all__ = [
    "CacheClearMetrics",
    "CacheClearOutcome",
    "SettingsCacheSnapshot",
    "SettingsIOController",
    "SettingsIOControllerDependencies",
]
