"""Qt Explorer NBT 文档读取与提交后台任务。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from typing import Callable, Optional

from app.models.nbt_edit import NbtChange
from app.qtui.utils import run_on_ui
from app.services.execution_runtime import (
    ExecutionRuntime,
    OperationCancelledError,
    OperationHandle,
    TaskPriority,
)
from app.services.nbt_commit_service import NbtCommitResult, commit_nbt_changes
from app.services.nbt_document_service import (
    LoadedNbtDocument,
    NbtDocumentTarget,
    find_nbt_documents,
    load_nbt_document,
)
from core.omni.world_session import WorldSession


@dataclass(frozen=True)
class NbtCommitCompletion:
    """提交结果及其对应的不可变暂存快照。"""

    result: NbtCommitResult
    changes: tuple[NbtChange, ...]


@dataclass(frozen=True)
class NbtTaskCallbacks:
    """NBT 后台任务投递到 Qt 主线程的回调。"""

    targets_ready: Callable[[tuple[NbtDocumentTarget, ...], int], None]
    targets_error: Callable[[Exception, int], None]
    document_ready: Callable[[LoadedNbtDocument, int, int], None]
    document_error: Callable[[Exception, int, int], None]
    commit_success: Callable[[NbtCommitCompletion, int], None]
    commit_error: Callable[[Exception, int], None]
    commit_cancelled: Callable[[int], None]
    commit_finished: Callable[[int], None]


class NbtTasks:
    """拥有 NBT 读取与写事务，并拒绝世界切换后的过期结果。"""

    def __init__(
        self,
        runtime: ExecutionRuntime,
        callbacks: NbtTaskCallbacks,
    ) -> None:
        """创建 NBT 任务作用域。

        Args:
            runtime: 应用共享后台执行运行时。
            callbacks: Qt 主线程投影回调。
        """
        self._scope = runtime.create_scope("qt_explorer_nbt")
        self._callbacks = callbacks
        self._session: Optional[WorldSession] = None
        self._world_generation = 0
        self._document_generation = 0
        self._document_handle: Optional[
            OperationHandle[LoadedNbtDocument]
        ] = None
        self._commit_handle: Optional[OperationHandle[NbtCommitResult]] = None
        self._disposed = False

    @property
    def is_committing(self) -> bool:
        """返回当前世界是否有提交任务尚未消费终态。"""
        return self._commit_handle is not None

    @property
    def world_generation(self) -> int:
        """返回当前世界 generation。"""
        return self._world_generation

    def set_world(self, session: WorldSession) -> int:
        """切换世界、取消旧任务并扫描可编辑文档。"""
        if self._disposed:
            raise RuntimeError("NBT 任务已经释放")
        self._invalidate_world()
        self._session = session
        generation = self._world_generation
        handle = self._scope.submit(
            "scan_documents",
            lambda context: find_nbt_documents(session.world_path, context),
            priority=TaskPriority.VISIBLE,
            feature="explorer.nbt",
            world_id=str(session.world_path),
            generation=generation,
        )
        handle.add_done_callback(
            lambda completed: self._finish_targets(completed, generation)
        )
        return generation

    def load_document(self, target: NbtDocumentTarget) -> bool:
        """异步读取当前世界内的指定文档。"""
        session = self._session
        if self._disposed or session is None:
            return False
        self._document_generation += 1
        document_generation = self._document_generation
        self._cancel_document()
        world_generation = self._world_generation
        handle = self._scope.submit(
            "load_document",
            lambda context: load_nbt_document(
                session.world_path, target, context
            ),
            priority=TaskPriority.INTERACTIVE,
            feature="explorer.nbt",
            world_id=str(session.world_path),
            generation=world_generation,
            metadata={"target": target.relative_path.as_posix()},
        )
        self._document_handle = handle
        handle.add_done_callback(
            lambda completed: self._finish_document(
                completed, world_generation, document_generation
            )
        )
        return True

    def submit_commit(self, changes: tuple[NbtChange, ...]) -> bool:
        """提交当前世界的不可变暂存快照。"""
        session = self._session
        if (
            self._disposed
            or session is None
            or self._commit_handle is not None
            or not changes
        ):
            return False
        generation = self._world_generation
        handle = self._scope.submit(
            "commit_changes",
            lambda context: commit_nbt_changes(session, changes, context),
            priority=TaskPriority.INTERACTIVE,
            feature="explorer.nbt",
            world_id=str(session.world_path),
            generation=generation,
            metadata={"change_count": len(changes)},
        )
        self._commit_handle = handle
        handle.add_done_callback(
            lambda completed: self._finish_commit(
                completed, changes, generation
            )
        )
        return True

    def _finish_targets(
        self,
        handle: OperationHandle[tuple[NbtDocumentTarget, ...]],
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            targets = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            run_on_ui(self._deliver_targets_error, error, generation)
            return
        run_on_ui(self._deliver_targets, targets, generation)

    def _finish_document(
        self,
        handle: OperationHandle[LoadedNbtDocument],
        world_generation: int,
        document_generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            document = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            run_on_ui(
                self._deliver_document_error,
                error,
                world_generation,
                document_generation,
            )
            return
        run_on_ui(
            self._deliver_document,
            document,
            world_generation,
            document_generation,
        )

    def _finish_commit(
        self,
        handle: OperationHandle[NbtCommitResult],
        changes: tuple[NbtChange, ...],
        generation: int,
    ) -> None:
        if handle.cancelled:
            run_on_ui(self._deliver_commit_cancelled, generation)
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            run_on_ui(self._deliver_commit_cancelled, generation)
        except Exception as error:
            run_on_ui(self._deliver_commit_error, error, generation)
        else:
            completion = NbtCommitCompletion(result, changes)
            run_on_ui(self._deliver_commit_success, completion, generation)
        finally:
            run_on_ui(self._deliver_commit_finished, generation)

    def _deliver_targets(
        self,
        targets: tuple[NbtDocumentTarget, ...],
        generation: int,
    ) -> None:
        if self.is_current_world(generation):
            self._callbacks.targets_ready(targets, generation)

    def _deliver_targets_error(self, error: Exception, generation: int) -> None:
        if self.is_current_world(generation):
            self._callbacks.targets_error(error, generation)

    def _deliver_document(
        self,
        document: LoadedNbtDocument,
        world_generation: int,
        document_generation: int,
    ) -> None:
        if self.is_current_document(world_generation, document_generation):
            self._document_handle = None
            self._callbacks.document_ready(
                document, world_generation, document_generation
            )

    def _deliver_document_error(
        self,
        error: Exception,
        world_generation: int,
        document_generation: int,
    ) -> None:
        if self.is_current_document(world_generation, document_generation):
            self._document_handle = None
            self._callbacks.document_error(
                error, world_generation, document_generation
            )

    def _deliver_commit_success(
        self,
        completion: NbtCommitCompletion,
        generation: int,
    ) -> None:
        if self.is_current_world(generation):
            self._callbacks.commit_success(completion, generation)

    def _deliver_commit_error(self, error: Exception, generation: int) -> None:
        if self.is_current_world(generation):
            self._callbacks.commit_error(error, generation)

    def _deliver_commit_cancelled(self, generation: int) -> None:
        if self.is_current_world(generation):
            self._callbacks.commit_cancelled(generation)

    def _deliver_commit_finished(self, generation: int) -> None:
        if self.is_current_world(generation):
            self._commit_handle = None
            self._callbacks.commit_finished(generation)

    def is_current_world(self, generation: int) -> bool:
        """返回回调是否仍属于当前世界。"""
        return (
            not self._disposed
            and self._session is not None
            and generation == self._world_generation
        )

    def is_current_document(
        self,
        world_generation: int,
        document_generation: int,
    ) -> bool:
        """返回回调是否仍属于当前世界与最近文档请求。"""
        return (
            self.is_current_world(world_generation)
            and document_generation == self._document_generation
        )

    def clear_world(self) -> None:
        """取消任务并清除当前世界身份。"""
        if self._disposed:
            return
        self._invalidate_world()
        self._session = None

    def _invalidate_world(self) -> None:
        self._world_generation += 1
        self._document_generation += 1
        self._scope.cancel_all()
        self._document_handle = None
        self._commit_handle = None

    def _cancel_document(self) -> None:
        if self._document_handle is not None:
            self._document_handle.cancel()
        self._document_handle = None

    def close(self) -> None:
        """幂等释放全部 NBT 后台任务。"""
        if self._disposed:
            return
        self._disposed = True
        self._world_generation += 1
        self._document_generation += 1
        self._session = None
        self._document_handle = None
        self._commit_handle = None
        self._scope.close()


__all__ = ["NbtCommitCompletion", "NbtTaskCallbacks", "NbtTasks"]
