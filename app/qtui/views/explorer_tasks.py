"""Qt Explorer 的世界读取与快速备份任务。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Optional

from app.presenters.quick_backup_state import (
    QuickBackupState,
    begin_quick_backup,
    finish_quick_backup,
    invalidate_quick_backup,
    owns_quick_backup,
)
from app.qtui.utils import run_on_ui
from app.services.backup_service import (
    BackupCancelledError,
    BackupRecord,
    BackupService,
)
from app.services.execution_runtime import (
    ExecutionRuntime,
    OperationCancelledError,
    OperationContext,
    OperationHandle,
    TaskPriority,
)
from app.services.world_repository import WorldRepository
from core.omni.models import WorldInfo
from core.omni.world_session import WorldSession
from core.types import LogCallback
from core.world_index import WorldShellMetadata
from core.world_index_progress import WorldIndexProgressFrame


@dataclass(frozen=True)
class ExplorerWorldSnapshot:
    """完整世界会话及其首屏展示快照。"""

    session: WorldSession
    world_info: Optional[WorldInfo]
    stats: Mapping[str, object]


@dataclass(frozen=True)
class ExplorerTaskCallbacks:
    """Explorer 后台任务投递到 Qt 主线程的回调。"""

    shell_ready: Callable[[WorldShellMetadata, int], None]
    index_progress: Callable[[WorldIndexProgressFrame, int], None]
    load_success: Callable[[ExplorerWorldSnapshot, int], None]
    load_error: Callable[[Exception, int], None]
    backup_progress: Callable[[str, float, int], None]
    backup_success: Callable[[BackupRecord, int], None]
    backup_error: Callable[[Exception, int], None]
    backup_finished: Callable[[int], None]


class ExplorerTasks:
    """拥有 Explorer 的读取、备份句柄和 generation。"""

    def __init__(
        self,
        runtime: ExecutionRuntime,
        repository: WorldRepository,
        backup: BackupService,
        log: LogCallback,
        callbacks: ExplorerTaskCallbacks,
    ) -> None:
        """创建 Explorer 页面级任务作用域。

        Args:
            runtime: 应用共享执行运行时。
            repository: 共享世界读取仓库。
            backup: 共享事务备份服务。
            log: 世界会话日志回调。
            callbacks: Qt 主线程投影回调。
        """
        self._scope = runtime.create_scope("qt_explorer_view")
        self._repository = repository
        self._backup = backup
        self._log = log
        self._callbacks = callbacks
        self._load_generation = 0
        self._quick_backup = QuickBackupState()
        self._disposed = False

    @property
    def load_generation(self) -> int:
        """返回当前世界加载 generation。"""
        return self._load_generation

    @property
    def is_backup_running(self) -> bool:
        """返回当前世界是否正在创建快速备份。"""
        return self._quick_backup.is_running

    def load_world(self, world_path: Path) -> int:
        """取消旧任务并渐进加载指定世界。"""
        if self._disposed:
            raise RuntimeError("Explorer 已释放")
        self._load_generation += 1
        generation = self._load_generation
        self._quick_backup = invalidate_quick_backup(self._quick_backup)
        self._scope.cancel_all()
        handle = self._scope.submit(
            "load_world",
            lambda context: self._load_worker(
                world_path, generation, context
            ),
            priority=TaskPriority.VISIBLE,
            feature="explorer",
            world_id=str(world_path),
            generation=generation,
        )
        handle.add_done_callback(
            lambda completed: self._finish_load(completed, generation)
        )
        return generation

    def _load_worker(
        self,
        world_path: Path,
        generation: int,
        context: OperationContext,
    ) -> ExplorerWorldSnapshot:
        context.raise_if_cancelled()
        read_context = self._repository.open(world_path)
        self._post_if_current(
            self._callbacks.shell_ready,
            generation,
            read_context.shell,
        )
        snapshot = read_context.get_index_progressive(
            cancel_check=lambda: context.is_cancelled,
            progress_callback=lambda frame: self._publish_index_progress(
                frame, generation, context
            ),
        )
        context.raise_if_cancelled()
        session = read_context.open_session_with_index(snapshot, log=self._log)
        context.raise_if_cancelled()
        dimensions = session.get_dimensions()
        stats = MappingProxyType({
            "world_path": str(session.world_path),
            "player_count": len(session.get_player_uuids()),
            "region_count": len(snapshot.region_files),
            "dimension_count": len(dimensions),
        })
        return ExplorerWorldSnapshot(
            session=session,
            world_info=session.get_world_info(),
            stats=stats,
        )

    def _publish_index_progress(
        self,
        frame: WorldIndexProgressFrame,
        generation: int,
        context: OperationContext,
    ) -> None:
        context.raise_if_cancelled()
        self._post_if_current(
            self._callbacks.index_progress,
            generation,
            frame,
        )

    def _finish_load(
        self,
        handle: OperationHandle[ExplorerWorldSnapshot],
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            self._post_if_current(
                self._callbacks.load_error, generation, error
            )
            return
        self._post_if_current(
            self._callbacks.load_success, generation, result
        )

    def start_backup(self, session: WorldSession) -> bool:
        """为当前世界启动快速备份；已有任务时返回 False。"""
        if self._disposed or self._quick_backup.is_running:
            return False
        world_path = session.world_path
        self._quick_backup = begin_quick_backup(
            self._quick_backup,
            world_path,
            self._load_generation,
        )
        generation = self._quick_backup.generation
        handle = self._scope.submit(
            "quick_backup",
            lambda context: self._backup_worker(
                world_path, generation, context
            ),
            priority=TaskPriority.VISIBLE,
            feature="explorer",
            world_id=str(world_path),
            generation=self._load_generation,
        )
        handle.add_done_callback(
            lambda completed: self._finish_backup(completed, generation)
        )
        return True

    def _backup_worker(
        self,
        world_path: Path,
        generation: int,
        context: OperationContext,
    ) -> BackupRecord:
        context.raise_if_cancelled()

        def progress(value: float, message: str) -> None:
            context.raise_if_cancelled()
            self._post_backup_if_current(
                self._callbacks.backup_progress,
                generation,
                message,
                value,
            )

        return self._backup.create_backup(
            world_path,
            label="Explorer 快速备份",
            progress_callback=progress,
            cancel_check=lambda: context.is_cancelled,
        )

    def _finish_backup(
        self,
        handle: OperationHandle[BackupRecord],
        generation: int,
    ) -> None:
        if handle.cancelled:
            self._post_backup_finish(generation)
            return
        try:
            record = handle.result()
        except (CancelledError, OperationCancelledError, BackupCancelledError):
            self._post_backup_finish(generation)
            return
        except Exception as error:
            self._post_backup_if_current(
                self._callbacks.backup_error, generation, error
            )
            self._post_backup_finish(generation)
            return
        self._post_backup_if_current(
            self._callbacks.backup_success, generation, record
        )
        self._post_backup_finish(generation)

    def _post_if_current(
        self,
        callback: Callable[..., None],
        generation: int,
        *args: object,
    ) -> None:
        run_on_ui(self._deliver_if_current, callback, generation, args)

    def _deliver_if_current(
        self,
        callback: Callable[..., None],
        generation: int,
        args: tuple[object, ...],
    ) -> None:
        if self.is_current_load(generation):
            callback(*args, generation)

    def _post_backup_if_current(
        self,
        callback: Callable[..., None],
        generation: int,
        *args: object,
    ) -> None:
        run_on_ui(
            self._deliver_backup_if_current,
            callback,
            generation,
            args,
        )

    def _deliver_backup_if_current(
        self,
        callback: Callable[..., None],
        generation: int,
        args: tuple[object, ...],
    ) -> None:
        if self._owns_backup(generation):
            callback(*args, generation)

    def _post_backup_finish(self, generation: int) -> None:
        run_on_ui(self._finish_backup_ui, generation)

    def _finish_backup_ui(self, generation: int) -> None:
        if not self._owns_backup(generation):
            return
        self._quick_backup = finish_quick_backup(
            self._quick_backup, generation
        )
        self._callbacks.backup_finished(generation)

    def _owns_backup(self, generation: int) -> bool:
        world_path = self._quick_backup.world_path
        if self._disposed or world_path is None:
            return False
        return owns_quick_backup(
            self._quick_backup,
            generation,
            world_path,
            self._load_generation,
        )

    def is_current_load(self, generation: int) -> bool:
        """返回回调是否仍属于当前世界。"""
        return not self._disposed and generation == self._load_generation

    def clear_world(self) -> None:
        """取消当前世界任务并使所有结果过期。"""
        if self._disposed:
            return
        self._load_generation += 1
        self._quick_backup = invalidate_quick_backup(self._quick_backup)
        self._scope.cancel_all()

    def close(self) -> None:
        """幂等释放 Explorer 的全部后台任务。"""
        if self._disposed:
            return
        self._disposed = True
        self._load_generation += 1
        self._quick_backup = invalidate_quick_backup(self._quick_backup)
        self._scope.close()


__all__ = [
    "ExplorerTaskCallbacks",
    "ExplorerTasks",
    "ExplorerWorldSnapshot",
]
