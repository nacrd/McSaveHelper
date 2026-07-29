"""地图标记持久化任务的后台生命周期协调。"""
from __future__ import annotations

import threading
from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    OperationCancelledError,
    OperationHandle,
    OperationScope,
    TaskPriority,
)
from app.services.map_marker_service import MapMarkerService
from core.mca.map_models import MapMarker


UiDispatcher = Callable[[Callable[[], None]], None]
MarkerSnapshotApplier = Callable[[str, tuple[MapMarker, ...]], None]


@dataclass(frozen=True)
class MapMarkerHostIdentity:
    """一次标记任务所依赖的 Explorer 当前世界身份。"""

    generation: int
    world_path: Optional[Path]
    dimension_id: str


@dataclass(frozen=True)
class MapMarkerOperationContext:
    """捕获一次标记任务的世界、维度和双重代数。"""

    generation: int
    host_generation: int
    world_path: Path
    dimension_id: str


@dataclass(frozen=True)
class MapMarkerOperationResult:
    """后台持久化完成后返回的权威维度快照。"""

    markers: tuple[MapMarker, ...]
    marker: Optional[MapMarker] = None
    deleted: bool = False


HostIdentityProvider = Callable[[], MapMarkerHostIdentity]
OperationCallback = Callable[[MapMarkerOperationResult], None]
ErrorCallback = Callable[[Exception], None]


class MapMarkerOperations:
    """拥有单个地图标记任务并安全投递其权威快照。"""

    def __init__(
        self,
        marker_service: MapMarkerService,
        task_scope: Optional[OperationScope],
        dispatch: Optional[UiDispatcher],
        get_host_identity: HostIdentityProvider,
        apply_snapshot: MarkerSnapshotApplier,
    ) -> None:
        """注入标记端口、共享作用域和宿主身份回调。

        Args:
            marker_service: 标记持久化服务。
            task_scope: Explorer 共享任务作用域；同步用法可不提供。
            dispatch: 与 task_scope 配套的 UI 投递函数。
            get_host_identity: 返回当前世界、维度和宿主代数。
            apply_snapshot: 在 UI 线程投影权威标记快照。

        Raises:
            ValueError: task_scope 与 dispatch 未成对提供。
        """
        if (task_scope is None) != (dispatch is None):
            raise ValueError("task_scope 与 post_to_ui 必须成对提供")
        self._marker_service = marker_service
        self._task_scope = task_scope
        self._dispatch = dispatch
        self._get_host_identity = get_host_identity
        self._apply_snapshot = apply_snapshot
        self._lock = threading.Lock()
        self._generation = 0
        self._active: Optional[
            OperationHandle[MapMarkerOperationResult]
        ] = None
        self._closed = False

    @property
    def is_closed(self) -> bool:
        """返回协调器是否已经关闭。"""
        with self._lock:
            return self._closed

    def submit_load(
        self,
        on_complete: OperationCallback,
        on_error: ErrorCallback,
    ) -> OperationHandle[MapMarkerOperationResult]:
        """在共享 I/O 通道加载当前维度标记。

        Args:
            on_complete: 快照投影成功后的回调。
            on_error: 当前任务失败后的回调。

        Returns:
            可等待或取消的标记任务句柄。
        """
        context = self._begin()
        return self._submit(
            "load_markers",
            context,
            lambda token: self._load_snapshot(context, token),
            on_complete,
            on_error,
        )

    def submit_upsert(
        self,
        marker: MapMarker,
        on_complete: OperationCallback,
        on_error: ErrorCallback,
    ) -> OperationHandle[MapMarkerOperationResult]:
        """在共享 I/O 通道写入标记并加载权威快照。

        Args:
            marker: 要持久化的完整标记值。
            on_complete: 快照投影成功后的回调。
            on_error: 当前任务失败后的回调。

        Returns:
            可等待或取消的标记任务句柄。
        """
        context = self._begin()
        return self._submit(
            "upsert_marker",
            context,
            lambda token: self._upsert_snapshot(context, marker, token),
            on_complete,
            on_error,
        )

    def submit_delete(
        self,
        marker_id: str,
        on_complete: OperationCallback,
        on_error: ErrorCallback,
    ) -> OperationHandle[MapMarkerOperationResult]:
        """在共享 I/O 通道删除标记并加载权威快照。

        Args:
            marker_id: 当前维度中要删除的标记 id。
            on_complete: 快照投影成功后的回调。
            on_error: 当前任务失败后的回调。

        Returns:
            可等待或取消的标记任务句柄。
        """
        context = self._begin()
        return self._submit(
            "delete_marker",
            context,
            lambda token: self._delete_snapshot(context, marker_id, token),
            on_complete,
            on_error,
        )

    def invalidate(self) -> None:
        """使当前任务过期并请求取消；仍允许后续提交。"""
        with self._lock:
            self._generation += 1
            handle = self._active
            self._active = None
        self._cancel(handle)

    def close(self) -> None:
        """取消自身任务并拒绝迟到回调；不关闭共享作用域。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            handle = self._active
            self._active = None
        self._cancel(handle)

    def _begin(self) -> MapMarkerOperationContext:
        with self._lock:
            if self._closed:
                raise RuntimeError("地图控制器已经关闭")
        if self._task_scope is None or self._dispatch is None:
            raise RuntimeError("地图标记后台运行时未注入")
        identity = self._get_host_identity()
        if identity.world_path is None:
            raise RuntimeError("尚未绑定地图标记世界")
        with self._lock:
            if self._closed:
                raise RuntimeError("地图控制器已经关闭")
            self._generation += 1
            generation = self._generation
            previous = self._active
            self._active = None
        self._cancel(previous)
        return MapMarkerOperationContext(
            generation=generation,
            host_generation=identity.generation,
            world_path=identity.world_path,
            dimension_id=identity.dimension_id,
        )

    def _submit(
        self,
        operation: str,
        context: MapMarkerOperationContext,
        work: Callable[[CancellationToken], MapMarkerOperationResult],
        on_complete: OperationCallback,
        on_error: ErrorCallback,
    ) -> OperationHandle[MapMarkerOperationResult]:
        scope = self._task_scope
        if scope is None:
            raise RuntimeError("地图标记后台运行时未注入")
        handle = scope.submit(
            operation,
            work,
            lane=ExecutionLane.IO,
            priority=TaskPriority.INTERACTIVE,
        )
        if not self._track(context, handle):
            handle.cancel()
        handle.add_done_callback(
            lambda completed: self._finish(
                completed,
                context,
                on_complete,
                on_error,
            )
        )
        return handle

    def _track(
        self,
        context: MapMarkerOperationContext,
        handle: OperationHandle[MapMarkerOperationResult],
    ) -> bool:
        with self._lock:
            if self._closed or context.generation != self._generation:
                return False
            self._active = handle
            return True

    def _finish(
        self,
        handle: OperationHandle[MapMarkerOperationResult],
        context: MapMarkerOperationContext,
        on_complete: OperationCallback,
        on_error: ErrorCallback,
    ) -> None:
        if handle.cancelled or not self._is_current(context, handle):
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            self._deliver_error(context, handle, error, on_error)
        else:
            self._deliver_result(context, handle, result, on_complete)

    def _deliver_result(
        self,
        context: MapMarkerOperationContext,
        handle: OperationHandle[MapMarkerOperationResult],
        result: MapMarkerOperationResult,
        on_complete: OperationCallback,
    ) -> None:
        if not self._is_current(context, handle):
            return
        dispatch = self._dispatch
        if dispatch is None:
            return

        def apply_result() -> None:
            if not self._claim_current(context, handle):
                return
            self._apply_snapshot(context.dimension_id, result.markers)
            on_complete(result)

        dispatch(apply_result)

    def _deliver_error(
        self,
        context: MapMarkerOperationContext,
        handle: OperationHandle[MapMarkerOperationResult],
        error: Exception,
        on_error: ErrorCallback,
    ) -> None:
        if not self._is_current(context, handle):
            return
        dispatch = self._dispatch
        if dispatch is None:
            return

        def apply_error() -> None:
            if self._claim_current(context, handle):
                on_error(error)

        dispatch(apply_error)

    def _is_current(
        self,
        context: MapMarkerOperationContext,
        handle: OperationHandle[MapMarkerOperationResult],
    ) -> bool:
        identity = self._get_host_identity()
        with self._lock:
            return self._matches_locked(context, handle, identity)

    def _claim_current(
        self,
        context: MapMarkerOperationContext,
        handle: OperationHandle[MapMarkerOperationResult],
    ) -> bool:
        identity = self._get_host_identity()
        with self._lock:
            if not self._matches_locked(context, handle, identity):
                return False
            self._active = None
            return True

    def _matches_locked(
        self,
        context: MapMarkerOperationContext,
        handle: OperationHandle[MapMarkerOperationResult],
        identity: MapMarkerHostIdentity,
    ) -> bool:
        return (
            not self._closed
            and self._active is handle
            and context.generation == self._generation
            and context.host_generation == identity.generation
            and context.world_path == identity.world_path
            and context.dimension_id == identity.dimension_id
        )

    def _load_snapshot(
        self,
        context: MapMarkerOperationContext,
        token: CancellationToken,
    ) -> MapMarkerOperationResult:
        token.raise_if_cancelled()
        markers = self._marker_service.list(
            context.world_path,
            context.dimension_id,
            include_disabled=True,
        )
        token.raise_if_cancelled()
        return MapMarkerOperationResult(tuple(markers))

    def _upsert_snapshot(
        self,
        context: MapMarkerOperationContext,
        marker: MapMarker,
        token: CancellationToken,
    ) -> MapMarkerOperationResult:
        token.raise_if_cancelled()
        stored = self._marker_service.upsert(context.world_path, marker)
        token.raise_if_cancelled()
        markers = self._marker_service.list(
            context.world_path,
            context.dimension_id,
            include_disabled=True,
        )
        token.raise_if_cancelled()
        return MapMarkerOperationResult(tuple(markers), marker=stored)

    def _delete_snapshot(
        self,
        context: MapMarkerOperationContext,
        marker_id: str,
        token: CancellationToken,
    ) -> MapMarkerOperationResult:
        token.raise_if_cancelled()
        deleted = self._marker_service.delete(context.world_path, marker_id)
        token.raise_if_cancelled()
        markers = self._marker_service.list(
            context.world_path,
            context.dimension_id,
            include_disabled=True,
        )
        token.raise_if_cancelled()
        return MapMarkerOperationResult(tuple(markers), deleted=deleted)

    @staticmethod
    def _cancel(
        handle: Optional[OperationHandle[MapMarkerOperationResult]],
    ) -> None:
        if handle is not None:
            handle.cancel()


__all__ = [
    "MapMarkerHostIdentity",
    "MapMarkerOperationContext",
    "MapMarkerOperationResult",
    "MapMarkerOperations",
]
