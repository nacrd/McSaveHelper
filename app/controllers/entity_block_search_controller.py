"""实体/方块搜索与结果导出的后台生命周期协调。"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from concurrent.futures import CancelledError
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable, Generic, Iterator, Optional, Sequence, TypeVar, cast

from app.services.entity_block_search.models import SearchCondition, SearchResult
from app.services.entity_block_search_service import EntityBlockSearchService
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    OperationCancelledError,
    OperationHandle,
    OperationScope,
    TaskPriority,
)


ResultT = TypeVar("ResultT")
UiDispatcher = Callable[[Callable[[], None]], None]


@dataclass(frozen=True)
class EntityBlockSearchCompletion:
    """一次搜索完成后交给视图投影的不可变快照。"""

    results: tuple[SearchResult, ...]
    search_type: str
    target: str
    dimensions: tuple[str, ...]


@dataclass(frozen=True)
class EntityBlockExportCompletion:
    """一次结果导出成功后的稳定摘要。"""

    output_path: Path
    result_count: int


@dataclass(frozen=True)
class EntityBlockSearchUiPorts:
    """控制器向 UI 投递忙碌状态与终态所需的类型化端口。"""

    dispatch: UiDispatcher
    search_started: Callable[[], None]
    search_succeeded: Callable[[EntityBlockSearchCompletion], None]
    search_failed: Callable[[Exception], None]
    search_cancelled: Callable[[], None]
    export_started: Callable[[], None]
    export_succeeded: Callable[[EntityBlockExportCompletion], None]
    export_failed: Callable[[Exception], None]
    export_cancelled: Callable[[], None]


class EntityBlockSearchBusyError(RuntimeError):
    """搜索或导出已有一个操作正在执行时抛出。"""


@dataclass(frozen=True)
class _OperationContext:
    """捕获操作类型、代数和发起时的世界身份。"""

    operation: str
    generation: int
    world_path: Path


@dataclass(frozen=True)
class _OperationCallbacks(Generic[ResultT]):
    """一次后台操作的类型化 UI 终态端口。"""

    started: Callable[[], None]
    succeeded: Callable[[ResultT], None]
    failed: Callable[[Exception], None]
    cancelled: Callable[[], None]


class EntityBlockSearchController:
    """协调搜索和导出，并丢弃世界切换后的迟到回调。"""

    _SEARCH = "search"
    _EXPORT = "export"
    _SERVICE_LOCK_POLL_SECONDS = 0.05

    def __init__(
        self,
        service: EntityBlockSearchService,
        scope: OperationScope,
        ui: EntityBlockSearchUiPorts,
    ) -> None:
        """绑定现有搜索服务、共享任务作用域和 UI 端口。"""
        self._service = service
        self._scope = scope
        self._ui = ui
        self._lock = threading.Lock()
        self._service_lock = threading.Lock()
        self._closed = False
        self._world_path: Optional[Path] = None
        self._generations = {self._SEARCH: 0, self._EXPORT: 0}
        self._starting = {self._SEARCH: False, self._EXPORT: False}
        self._handles: dict[str, Optional[OperationHandle[object]]] = {
            self._SEARCH: None,
            self._EXPORT: None,
        }
        self._search_callbacks = _OperationCallbacks(
            started=ui.search_started,
            succeeded=ui.search_succeeded,
            failed=ui.search_failed,
            cancelled=ui.search_cancelled,
        )
        self._export_callbacks = _OperationCallbacks(
            started=ui.export_started,
            succeeded=ui.export_succeeded,
            failed=ui.export_failed,
            cancelled=ui.export_cancelled,
        )

    @property
    def is_closed(self) -> bool:
        """返回控制器是否已经关闭。"""
        with self._lock:
            return self._closed

    @property
    def is_searching(self) -> bool:
        """返回搜索是否正在提交或执行。"""
        with self._lock:
            return self._is_operation_running_locked(self._SEARCH)

    @property
    def is_exporting(self) -> bool:
        """返回导出是否正在提交或执行。"""
        with self._lock:
            return self._is_operation_running_locked(self._EXPORT)

    def select_world(self, world_path: Path) -> None:
        """切换当前世界，取消现有操作并使全部旧回调失效。"""
        normalized = self._normalize_world_path(world_path)
        with self._lock:
            if self._closed:
                return
            self._world_path = normalized
            handles = self._invalidate_all_locked()
        self._cancel_handles(handles)

    def start_search(
        self,
        condition: SearchCondition,
    ) -> Optional[OperationHandle[EntityBlockSearchCompletion]]:
        """在计算通道提交一次搜索。

        Args:
            condition: 已从视图表单构造的搜索条件。

        Returns:
            已提交的搜索句柄；提交失败并已投递错误时返回 None。

        Raises:
            EntityBlockSearchBusyError: 搜索或导出仍在执行。
            RuntimeError: 控制器已经关闭。
            ValueError: 条件无效或不属于当前世界。
        """
        request = self._validated_condition_copy(condition)
        context = self._begin(self._SEARCH, request.world_path)
        return self._submit(
            context,
            "search",
            lambda token: self._execute_search(request, token),
            ExecutionLane.CPU,
            self._search_callbacks,
        )

    def start_export(
        self,
        results: Sequence[SearchResult],
        output_path: Path,
    ) -> Optional[OperationHandle[EntityBlockExportCompletion]]:
        """在 I/O 通道原子导出当前结果快照。

        Args:
            results: 要导出的搜索结果快照。
            output_path: 用户选择的输出路径。

        Returns:
            已提交的导出句柄；提交失败并已投递错误时返回 None。

        Raises:
            EntityBlockSearchBusyError: 搜索或导出仍在执行。
            RuntimeError: 控制器已经关闭。
            ValueError: 当前世界为空或结果列表为空。
        """
        result_snapshot = tuple(results)
        if not result_snapshot:
            raise ValueError("没有可导出的搜索结果")
        destination = Path(output_path).expanduser().absolute()
        context = self._begin(self._EXPORT)
        return self._submit(
            context,
            "export_results",
            lambda token: self._execute_export(
                result_snapshot,
                destination,
                token,
            ),
            ExecutionLane.IO,
            self._export_callbacks,
        )

    def close(self) -> None:
        """幂等关闭控制器并取消自身任务，不关闭共享作用域。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._world_path = None
            handles = self._invalidate_all_locked()
        self._cancel_handles(handles)

    def _begin(
        self,
        operation: str,
        requested_world: Optional[Path] = None,
    ) -> _OperationContext:
        with self._lock:
            if self._closed:
                raise RuntimeError("实体方块搜索控制器已经关闭")
            if self._is_busy_locked():
                raise EntityBlockSearchBusyError("搜索或导出操作正在执行")
            world_path = self._world_path
            if world_path is None:
                raise ValueError("尚未选择当前存档")
            if requested_world is not None:
                requested = self._normalize_world_path(requested_world)
                if requested != world_path:
                    raise ValueError("搜索条件不属于当前存档")
            self._generations[operation] += 1
            generation = self._generations[operation]
            self._starting[operation] = True
        return _OperationContext(operation, generation, world_path)

    def _submit(
        self,
        context: _OperationContext,
        operation_name: str,
        work: Callable[[CancellationToken], ResultT],
        lane: ExecutionLane,
        callbacks: _OperationCallbacks[ResultT],
    ) -> Optional[OperationHandle[ResultT]]:
        callbacks.started()
        try:
            handle = self._scope.submit(
                operation_name,
                work,
                lane=lane,
                priority=TaskPriority.INTERACTIVE,
            )
        except Exception as error:
            self._deliver_submission_failure(context, error, callbacks)
            return None
        tracked = cast(OperationHandle[object], handle)
        if not self._install_handle(context, tracked):
            handle.cancel()
            return handle
        handle.add_done_callback(
            lambda completed: self._finish(
                context,
                completed,
                callbacks,
            )
        )
        return handle

    def _execute_search(
        self,
        condition: SearchCondition,
        token: CancellationToken,
    ) -> EntityBlockSearchCompletion:
        token.raise_if_cancelled()
        with self._reserve_service(token):
            results = self._service.search_condition(condition)
            token.raise_if_cancelled()
        return EntityBlockSearchCompletion(
            results=tuple(results),
            search_type=condition.search_type,
            target=condition.target,
            dimensions=tuple(condition.dimensions),
        )

    def _execute_export(
        self,
        results: tuple[SearchResult, ...],
        output_path: Path,
        token: CancellationToken,
    ) -> EntityBlockExportCompletion:
        token.raise_if_cancelled()
        with self._reserve_service(token):
            self._service.export_results(list(results), output_path)
        return EntityBlockExportCompletion(output_path, len(results))

    @contextmanager
    def _reserve_service(
        self,
        token: CancellationToken,
    ) -> Iterator[None]:
        """可取消地串行访问持有可变搜索摘要的服务实例。"""
        while not self._service_lock.acquire(
            timeout=self._SERVICE_LOCK_POLL_SECONDS
        ):
            token.raise_if_cancelled()
        try:
            token.raise_if_cancelled()
            yield
        finally:
            self._service_lock.release()

    def _finish(
        self,
        context: _OperationContext,
        handle: OperationHandle[ResultT],
        callbacks: _OperationCallbacks[ResultT],
    ) -> None:
        tracked = cast(OperationHandle[object], handle)
        if handle.cancelled:
            self._deliver_terminal(context, tracked, callbacks.cancelled)
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            terminal = callbacks.cancelled
        except Exception as error:
            terminal = partial(callbacks.failed, error)
        else:
            terminal = partial(callbacks.succeeded, result)
        self._deliver_terminal(context, tracked, terminal)

    def _deliver_terminal(
        self,
        context: _OperationContext,
        handle: OperationHandle[object],
        terminal: Callable[[], None],
    ) -> None:
        if not self._is_current(context, handle):
            return

        def guarded() -> None:
            if self._claim_current(context, handle):
                terminal()

        self._ui.dispatch(guarded)

    def _deliver_submission_failure(
        self,
        context: _OperationContext,
        error: Exception,
        callbacks: _OperationCallbacks[ResultT],
    ) -> None:
        if not self._is_starting(context):
            return

        def guarded() -> None:
            if self._claim_starting(context):
                callbacks.failed(error)

        self._ui.dispatch(guarded)

    def _install_handle(
        self,
        context: _OperationContext,
        handle: OperationHandle[object],
    ) -> bool:
        with self._lock:
            if not self._matches_context_locked(context):
                return False
            if not self._starting[context.operation]:
                return False
            self._starting[context.operation] = False
            self._handles[context.operation] = handle
            return True

    def _is_current(
        self,
        context: _OperationContext,
        handle: OperationHandle[object],
    ) -> bool:
        with self._lock:
            return (
                self._matches_context_locked(context)
                and self._handles[context.operation] is handle
            )

    def _claim_current(
        self,
        context: _OperationContext,
        handle: OperationHandle[object],
    ) -> bool:
        with self._lock:
            if (
                not self._matches_context_locked(context)
                or self._handles[context.operation] is not handle
            ):
                return False
            self._handles[context.operation] = None
            return True

    def _is_starting(self, context: _OperationContext) -> bool:
        with self._lock:
            return (
                self._matches_context_locked(context)
                and self._starting[context.operation]
            )

    def _claim_starting(self, context: _OperationContext) -> bool:
        with self._lock:
            if (
                not self._matches_context_locked(context)
                or not self._starting[context.operation]
            ):
                return False
            self._starting[context.operation] = False
            return True

    def _matches_context_locked(self, context: _OperationContext) -> bool:
        return (
            not self._closed
            and self._world_path == context.world_path
            and self._generations[context.operation] == context.generation
        )

    def _invalidate_all_locked(
        self,
    ) -> tuple[Optional[OperationHandle[object]], ...]:
        handles = tuple(self._handles.values())
        for operation in self._generations:
            self._generations[operation] += 1
            self._starting[operation] = False
            self._handles[operation] = None
        return handles

    def _is_busy_locked(self) -> bool:
        return any(
            self._is_operation_running_locked(operation)
            for operation in self._generations
        )

    def _is_operation_running_locked(self, operation: str) -> bool:
        return (
            self._starting[operation]
            or self._handles[operation] is not None
        )

    @staticmethod
    def _validated_condition_copy(
        condition: SearchCondition,
    ) -> SearchCondition:
        request = SearchCondition(
            search_type=condition.search_type,
            target=condition.target,
            dimensions=list(condition.dimensions),
            world_path=EntityBlockSearchController._normalize_world_path(
                condition.world_path
            ),
        )
        errors = request.validate()
        if errors:
            raise ValueError(errors[0])
        return request

    @staticmethod
    def _normalize_world_path(world_path: Path) -> Path:
        return Path(world_path).expanduser().resolve()

    @staticmethod
    def _cancel_handles(
        handles: Sequence[Optional[OperationHandle[object]]],
    ) -> None:
        for handle in handles:
            if handle is not None:
                handle.cancel()


__all__ = [
    "EntityBlockExportCompletion",
    "EntityBlockSearchBusyError",
    "EntityBlockSearchCompletion",
    "EntityBlockSearchController",
    "EntityBlockSearchUiPorts",
]
