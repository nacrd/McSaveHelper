"""迁移页面拥有的批量扫描与 UUID 查询任务。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.qtui.utils import run_on_ui
from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
    OperationHandle,
    TaskPriority,
)
from app.services.migration_service import MigrationService
from app.services.uuid_service import UUIDService
from core.types import LogCallback


@dataclass(frozen=True)
class BatchScanResult:
    """一次批量目录扫描的不可变结果。"""

    worlds: tuple[Path, ...]
    message: str


@dataclass(frozen=True)
class UuidQueryResult:
    """一次 UUID 查询的不可变结果。"""

    offline_uuid: str
    online_uuid: str | None
    official_name: str | None


@dataclass(frozen=True)
class MigratorTaskCallbacks:
    """后台任务回到迁移视图的主线程回调。"""

    batch_success: Callable[[BatchScanResult, str, int], None]
    batch_error: Callable[[Exception, str, int], None]
    query_success: Callable[[UuidQueryResult, str, int], None]
    query_error: Callable[[Exception, str, int], None]


class MigratorTasks:
    """拥有迁移视图的后台句柄、generation 与取消状态。"""

    def __init__(
        self,
        runtime: ExecutionRuntime,
        migration: MigrationService,
        uuid: UUIDService,
        log: LogCallback,
        callbacks: MigratorTaskCallbacks,
    ) -> None:
        """创建页面级任务作用域。

        Args:
            runtime: 应用共享执行运行时。
            migration: 批量目录扫描服务。
            uuid: UUID 生成与在线查询服务。
            log: UUID 查询使用的日志回调。
            callbacks: 主线程结果回调。
        """
        self._scope = runtime.create_scope("migrator_view")
        self._migration = migration
        self._uuid = uuid
        self._log = log
        self._callbacks = callbacks
        self._scan_generation = 0
        self._query_generation = 0
        self._query_handle: OperationHandle[UuidQueryResult] | None = None
        self._disposed = False

    @property
    def scan_generation(self) -> int:
        """返回当前批量扫描 generation。"""
        return self._scan_generation

    @property
    def query_generation(self) -> int:
        """返回当前 UUID 查询 generation。"""
        return self._query_generation

    def scan(self, directory: str) -> None:
        """在 I/O 通道扫描目录，并把快照投递回 UI。"""
        if self._disposed:
            return
        self._scan_generation += 1
        generation = self._scan_generation
        try:
            handle = self._scope.submit(
                "scan_batch_dir",
                lambda token: self._scan_worker(directory, token),
                lane=ExecutionLane.IO,
                priority=TaskPriority.INTERACTIVE,
            )
            handle.add_done_callback(
                lambda completed: self._finish_scan(
                    completed, directory, generation
                )
            )
        except Exception as error:
            self._callbacks.batch_error(error, directory, generation)

    def _scan_worker(self, directory: str, token: object) -> BatchScanResult:
        self._raise_if_cancelled(token)
        worlds = tuple(self._migration.scan_batch_dir(directory))
        self._raise_if_cancelled(token)
        return BatchScanResult(worlds, self._migration.scan_result)

    def _finish_scan(
        self,
        handle: OperationHandle[BatchScanResult],
        directory: str,
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            run_on_ui(
                self._callbacks.batch_error, error, directory, generation
            )
            return
        run_on_ui(
            self._callbacks.batch_success, result, directory, generation
        )

    def query(self, name: str) -> None:
        """取消前一次查询并在 I/O 通道查询指定玩家。"""
        if self._disposed:
            return
        self.invalidate_query()
        generation = self._query_generation
        try:
            handle = self._scope.submit(
                "query_uuid",
                lambda token: self._query_worker(name, token),
                lane=ExecutionLane.IO,
                priority=TaskPriority.INTERACTIVE,
            )
            self._query_handle = handle
            handle.add_done_callback(
                lambda completed: self._finish_query(
                    completed, name, generation
                )
            )
        except Exception as error:
            self._callbacks.query_error(error, name, generation)

    def invalidate_query(self) -> None:
        """取消当前 UUID 查询并使其结果过期。"""
        self._query_generation += 1
        previous = self._query_handle
        self._query_handle = None
        if previous is not None:
            previous.cancel()

    def _query_worker(self, name: str, token: object) -> UuidQueryResult:
        self._raise_if_cancelled(token)
        offline_uuid = self._uuid.generate_offline_uuid(name)
        self._raise_if_cancelled(token)
        online_uuid, official_name = self._uuid.query_online_uuid(
            name, self._log
        )
        self._raise_if_cancelled(token)
        return UuidQueryResult(offline_uuid, online_uuid, official_name)

    def _finish_query(
        self,
        handle: OperationHandle[UuidQueryResult],
        name: str,
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            run_on_ui(self._callbacks.query_error, error, name, generation)
            return
        run_on_ui(self._callbacks.query_success, result, name, generation)

    def is_current_scan(self, generation: int) -> bool:
        """返回扫描结果是否仍属于当前页面状态。"""
        return not self._disposed and generation == self._scan_generation

    def is_current_query(self, generation: int) -> bool:
        """返回 UUID 结果是否仍属于当前页面状态。"""
        return not self._disposed and generation == self._query_generation

    def close(self) -> None:
        """幂等取消任务并关闭页面作用域。"""
        if self._disposed:
            return
        self._disposed = True
        self._scan_generation += 1
        self.invalidate_query()
        self._scope.close()

    @staticmethod
    def _raise_if_cancelled(token: object) -> None:
        raise_if_cancelled = getattr(token, "raise_if_cancelled", None)
        if callable(raise_if_cancelled):
            raise_if_cancelled()


__all__ = [
    "BatchScanResult",
    "MigratorTaskCallbacks",
    "MigratorTasks",
    "UuidQueryResult",
]
