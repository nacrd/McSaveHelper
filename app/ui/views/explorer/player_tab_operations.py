"""Explorer 玩家标签页的后台操作与生命周期协调。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Optional, TypeVar, cast

import flet as ft

from app.presenters.player_presenter import format_export_bundle_text
from app.services.asset_import import (
    AssetImportCounts,
    import_assets_from_sources,
)
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    OperationCancelledError,
    OperationHandle,
    OperationScope,
    TaskPriority,
)
from app.services.player.models import PlayerContainersView, PlayerSummary
from app.services.player_service import PlayerService
from app.ui.utils import run_on_ui
from core.io_atomic import atomic_write_text
from core.nbt import Compound
from core.omni.player_manager import PlayerAttribute, PlayerEffect
from core.omni.world_session import WorldSession


Translate = Callable[..., str]
ResultT = TypeVar("ResultT")
ResultCallback = Callable[[ResultT], None]
ErrorCallback = Callable[[Exception], None]
RequestGuard = Callable[[], bool]


@dataclass(frozen=True)
class PlayerLoadResult:
    """后台玩家解析结果，供 UI 线程一次性投影。"""

    player_data: Optional[Compound]
    summary: Optional[PlayerSummary]
    containers: Optional[PlayerContainersView]
    attributes: tuple[PlayerAttribute, ...]
    effects: tuple[PlayerEffect, ...]


@dataclass(frozen=True)
class AssetImportRequest:
    """一次语言与贴图导入的不可变后台请求。"""

    paths: tuple[Path, ...]
    locale: str
    configured_dir: Optional[Path]
    start_path: Optional[Path]
    empty_paths_fallback: bool = False
    empty_jar_results_fallback: bool = False


def load_player_data(
    service: PlayerService,
    session: WorldSession,
    uuid: str,
    token: CancellationToken,
) -> PlayerLoadResult:
    """加载玩家 NBT 及各展示投影，并观察协作取消。"""
    token.raise_if_cancelled()
    result = PlayerLoadResult(
        player_data=session.load_player_data(uuid),
        summary=service.load_summary(session, uuid),
        containers=service.load_containers(session, uuid),
        attributes=service.load_attributes(session, uuid),
        effects=service.load_effects(session, uuid),
    )
    token.raise_if_cancelled()
    return result


def export_player_summary(
    service: PlayerService,
    session: WorldSession,
    uuid: str,
    output_path: Path,
    translate: Translate,
    token: CancellationToken,
) -> int:
    """构建玩家摘要并通过同目录临时文件原子发布。"""
    token.raise_if_cancelled()
    bundle = service.build_export(session, uuid, include_items=True)
    if bundle is None:
        raise ValueError("无法导出玩家摘要")
    if output_path.suffix.lower() == ".txt":
        payload = format_export_bundle_text(bundle, translate=translate)
    else:
        payload = json.dumps(
            bundle.to_dict(),
            ensure_ascii=False,
            indent=2,
        )
    token.raise_if_cancelled()
    atomic_write_text(output_path, payload)
    return 1


def import_usercache(
    session: WorldSession,
    path: Path,
    token: CancellationToken,
) -> int:
    """读取并合并 usercache，同时在 I/O 前后检查取消。"""
    token.raise_if_cancelled()
    imported = int(session.import_usercache(path) or 0)
    token.raise_if_cancelled()
    return imported


def import_player_assets(
    request: AssetImportRequest,
    item_service: Any,
    texture_service: Any,
    token: CancellationToken,
) -> AssetImportCounts:
    """按不可变请求导入语言与贴图资源。"""
    token.raise_if_cancelled()
    counts = import_assets_from_sources(
        item_service=item_service,
        texture_service=texture_service,
        paths=request.paths,
        locale=request.locale,
        configured_dir=request.configured_dir,
        start_path=request.start_path,
        empty_paths_fallback=request.empty_paths_fallback,
        empty_jar_results_fallback=request.empty_jar_results_fallback,
    )
    token.raise_if_cancelled()
    return counts


class _OperationKind(Enum):
    PLAYER_LOAD = "player_load"
    PLAYER_EXPORT = "player_export"
    USERCACHE_IMPORT = "usercache_import"
    ASSET_IMPORT = "asset_import"


@dataclass
class _RequestState:
    """单类请求的最新 generation 与运行句柄。"""

    generation: int = 0
    handle: Optional[OperationHandle[object]] = None


class PlayerTabOperations:
    """提交玩家后台任务，并阻止关闭或过期结果触碰 Flet。"""

    def __init__(
        self,
        task_scope: OperationScope,
        *,
        get_page: Callable[[], Optional[ft.Page]],
        get_world_session: Callable[[], Optional[WorldSession]],
        get_current_uuid: Callable[[], Optional[str]],
    ) -> None:
        """绑定 Explorer 共享任务作用域和最小 UI 状态端口。"""
        self._task_scope = task_scope
        self._get_page = get_page
        self._get_world_session = get_world_session
        self._get_current_uuid = get_current_uuid
        self._lock = Lock()
        self._closed = False
        self._states = {kind: _RequestState() for kind in _OperationKind}

    def submit_player_load(
        self,
        service: PlayerService,
        session: WorldSession,
        uuid: str,
        on_success: ResultCallback[PlayerLoadResult],
        on_error: ErrorCallback,
    ) -> OperationHandle[PlayerLoadResult]:
        """提交玩家加载；新请求会取消同类旧句柄。"""
        return self._submit(
            _OperationKind.PLAYER_LOAD,
            "load_player_data",
            lambda token: load_player_data(service, session, uuid, token),
            on_success,
            on_error,
            lane=ExecutionLane.CPU,
            guard=lambda: (
                self._get_world_session() is session
                and self._get_current_uuid() == uuid
            ),
        )

    def submit_player_export(
        self,
        service: PlayerService,
        session: WorldSession,
        uuid: str,
        output_path: Path,
        translate: Translate,
        on_success: Callable[[Path], None],
        on_error: ErrorCallback,
    ) -> OperationHandle[int]:
        """提交玩家摘要导出并仅投影当前会话的结果。"""
        return self._submit(
            _OperationKind.PLAYER_EXPORT,
            "export_player_summary",
            lambda token: export_player_summary(
                service,
                session,
                uuid,
                output_path,
                translate,
                token,
            ),
            lambda _result: on_success(output_path),
            on_error,
            lane=ExecutionLane.IO,
            guard=lambda: self._get_world_session() is session,
        )

    def submit_usercache_import(
        self,
        session: WorldSession,
        path: Path,
        on_success: ResultCallback[int],
        on_error: ErrorCallback,
    ) -> OperationHandle[int]:
        """提交 usercache 合并并抑制世界切换后的结果。"""
        return self._submit(
            _OperationKind.USERCACHE_IMPORT,
            "import_usercache",
            lambda token: import_usercache(session, path, token),
            on_success,
            on_error,
            lane=ExecutionLane.IO,
            guard=lambda: self._get_world_session() is session,
        )

    def submit_asset_import(
        self,
        request: AssetImportRequest,
        item_service: Any,
        texture_service: Any,
        on_success: ResultCallback[AssetImportCounts],
        on_error: ErrorCallback,
    ) -> OperationHandle[AssetImportCounts]:
        """提交语言与贴图导入，并只投影最新一次结果。"""
        return self._submit(
            _OperationKind.ASSET_IMPORT,
            "import_player_assets",
            lambda token: import_player_assets(
                request,
                item_service,
                texture_service,
                token,
            ),
            on_success,
            on_error,
            lane=ExecutionLane.IO,
        )

    def close(self) -> None:
        """取消本协调器的句柄并让已排队 UI 回调失效；可重复调用。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            handles = tuple(
                state.handle
                for state in self._states.values()
                if state.handle is not None
            )
            for state in self._states.values():
                state.generation += 1
                state.handle = None
        for handle in handles:
            handle.cancel()

    def _submit(
        self,
        kind: _OperationKind,
        operation: str,
        work: Callable[[CancellationToken], ResultT],
        on_success: ResultCallback[ResultT],
        on_error: ErrorCallback,
        *,
        lane: ExecutionLane,
        guard: Optional[RequestGuard] = None,
    ) -> OperationHandle[ResultT]:
        """登记一类最新请求并统一完成、取消和 UI 投递协议。"""
        generation, previous = self._begin_request(kind)
        if previous is not None:
            previous.cancel()
        handle = self._task_scope.submit(
            operation,
            work,
            lane=lane,
            priority=TaskPriority.INTERACTIVE,
        )
        if not self._register_handle(kind, generation, handle):
            handle.cancel()
            return handle
        handle.add_done_callback(
            lambda completed: self._finish(
                kind,
                generation,
                completed,
                on_success,
                on_error,
                guard,
            )
        )
        return handle

    def _begin_request(
        self,
        kind: _OperationKind,
    ) -> tuple[int, Optional[OperationHandle[object]]]:
        """递增 generation 并取出待取消的同类旧句柄。"""
        with self._lock:
            if self._closed:
                raise RuntimeError("玩家后台操作协调器已经关闭")
            state = self._states[kind]
            state.generation += 1
            previous = state.handle
            state.handle = None
            return state.generation, previous

    def _register_handle(
        self,
        kind: _OperationKind,
        generation: int,
        handle: OperationHandle[ResultT],
    ) -> bool:
        """仅为仍然最新且未关闭的请求登记句柄。"""
        with self._lock:
            state = self._states[kind]
            if self._closed or state.generation != generation:
                return False
            state.handle = cast(OperationHandle[object], handle)
            return True

    def _finish(
        self,
        kind: _OperationKind,
        generation: int,
        handle: OperationHandle[ResultT],
        on_success: ResultCallback[ResultT],
        on_error: ErrorCallback,
        guard: Optional[RequestGuard],
    ) -> None:
        """读取后台终态并把成功或失败投递到 Flet UI 线程。"""
        self._clear_handle(kind, generation, handle)
        if handle.cancelled or not self._is_current(kind, generation, guard):
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            self._post_to_ui(kind, generation, guard, on_error, error)
            return
        self._post_to_ui(kind, generation, guard, on_success, result)

    def _clear_handle(
        self,
        kind: _OperationKind,
        generation: int,
        handle: OperationHandle[ResultT],
    ) -> None:
        """完成时只清除仍指向当前句柄的状态。"""
        tracked = cast(OperationHandle[object], handle)
        with self._lock:
            state = self._states[kind]
            if state.generation == generation and state.handle is tracked:
                state.handle = None

    def _post_to_ui(
        self,
        kind: _OperationKind,
        generation: int,
        guard: Optional[RequestGuard],
        callback: Callable[[Any], None],
        value: Any,
    ) -> None:
        """页面不存在时安全跳过；真正消费前再次校验身份。"""
        page = self._get_page()
        if page is None:
            return

        def deliver() -> None:
            if self._is_current(kind, generation, guard):
                callback(value)

        run_on_ui(page, deliver)

    def _is_current(
        self,
        kind: _OperationKind,
        generation: int,
        guard: Optional[RequestGuard],
    ) -> bool:
        """检查关闭状态、generation 及调用方会话身份。"""
        with self._lock:
            if self._closed or self._states[kind].generation != generation:
                return False
        return guard is None or guard()
