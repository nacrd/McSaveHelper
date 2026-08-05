"""Qt Explorer 玩家列表、详情、导出与名称解析后台任务。"""
from __future__ import annotations

import json
from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence, TypeVar

from app.presenters.player_presenter import format_export_bundle_text
from app.qtui.utils import run_on_ui
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
    OperationContext,
    OperationHandle,
    TaskPriority,
)
from app.services.player.models import (
    PlayerContainersView,
    PlayerRef,
    PlayerSummary,
)
from app.services.player_service import PlayerService
from app.services.runtime_map import map_items
from app.services.uuid_service import UUIDService
from core.io_atomic import atomic_write_text
from core.nbt import Compound
from core.omni.player_manager import PlayerAttribute, PlayerEffect
from core.omni.world_session import WorldSession

ResultT = TypeVar("ResultT")
Translate = Callable[..., str]
_NAME_LOOKUP_MAX_WORKERS = 4


@dataclass(frozen=True)
class PlayerDetailResult:
    """一次玩家详情读取的不可变投影。"""

    player_data: Optional[Compound]
    summary: Optional[PlayerSummary]
    containers: Optional[PlayerContainersView]
    attributes: tuple[PlayerAttribute, ...]
    effects: tuple[PlayerEffect, ...]


@dataclass(frozen=True)
class NameLookupResult:
    """批量在线名称解析结果。"""

    resolved: dict[str, str]
    unresolved: tuple[str, ...]


@dataclass(frozen=True)
class PlayerTaskCallbacks:
    """玩家后台结果的 Qt 主线程投影回调。"""

    players_ready: Callable[[tuple[PlayerRef, ...], int], None]
    players_error: Callable[[Exception, int], None]
    detail_ready: Callable[
        [PlayerDetailResult, str, int, int],
        None,
    ]
    detail_error: Callable[[Exception, str, int, int], None]
    export_success: Callable[[Path, int], None]
    export_error: Callable[[Exception, int], None]
    usercache_success: Callable[[int, int], None]
    usercache_error: Callable[[Exception, int], None]
    name_lookup_success: Callable[[NameLookupResult, int], None]
    name_lookup_error: Callable[[Exception, int], None]


class PlayerTasks:
    """拥有玩家读取与导出任务，并丢弃世界或选择切换后的过期结果。"""

    def __init__(
        self,
        runtime: ExecutionRuntime,
        service: PlayerService,
        callbacks: PlayerTaskCallbacks,
    ) -> None:
        """创建玩家任务作用域。

        Args:
            runtime: 应用共享后台运行时。
            service: 无状态玩家读取服务。
            callbacks: Qt 主线程投影回调。
        """
        self._runtime = runtime
        self._scope = runtime.create_scope("qt_explorer_players")
        self._service = service
        self._callbacks = callbacks
        self._session: Optional[WorldSession] = None
        self._world_generation = 0
        self._detail_generation = 0
        self._export_generation = 0
        self._usercache_generation = 0
        self._name_lookup_generation = 0
        self._selected_uuid: Optional[str] = None
        self._list_handle: Optional[OperationHandle[tuple[PlayerRef, ...]]] = None
        self._detail_handle: Optional[OperationHandle[PlayerDetailResult]] = None
        self._export_handle: Optional[OperationHandle[Path]] = None
        self._usercache_handle: Optional[OperationHandle[int]] = None
        self._name_lookup_handle: Optional[
            OperationHandle[NameLookupResult]
        ] = None
        self._disposed = False

    def load_players(self, session: WorldSession) -> int:
        """切换到指定会话并异步读取玩家列表。"""
        if self._disposed:
            raise RuntimeError("玩家任务已经释放")
        self._invalidate_requests()
        self._session = session
        generation = self._world_generation
        handle = self._scope.submit(
            "list_players",
            lambda context: self._list_players(session, context),
            lane=ExecutionLane.CPU,
            priority=TaskPriority.VISIBLE,
            feature="explorer.players",
            world_id=str(session.world_path),
            generation=generation,
        )
        self._list_handle = handle
        handle.add_done_callback(
            lambda completed: self._finish_players(completed, generation)
        )
        return generation

    def _list_players(
        self,
        session: WorldSession,
        context: OperationContext,
    ) -> tuple[PlayerRef, ...]:
        context.raise_if_cancelled()
        players = tuple(self._service.list_players(session))
        context.raise_if_cancelled()
        return players

    def _finish_players(
        self,
        handle: OperationHandle[tuple[PlayerRef, ...]],
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            players = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            run_on_ui(self._deliver_players_error, error, generation)
            return
        run_on_ui(self._deliver_players, players, generation)

    def load_detail(self, session: WorldSession, uuid: str) -> bool:
        """异步读取当前世界内选中玩家的完整详情。"""
        if self._disposed or session is not self._session:
            return False
        self._detail_generation += 1
        generation = self._detail_generation
        self._selected_uuid = uuid
        self._cancel_handle(self._detail_handle)
        world_generation = self._world_generation
        handle = self._scope.submit(
            "load_detail",
            lambda context: self._load_detail(session, uuid, context),
            lane=ExecutionLane.CPU,
            priority=TaskPriority.INTERACTIVE,
            feature="explorer.players",
            world_id=str(session.world_path),
            generation=world_generation,
            metadata={"player_uuid": uuid},
        )
        self._detail_handle = handle
        handle.add_done_callback(
            lambda completed: self._finish_detail(
                completed,
                uuid,
                world_generation,
                generation,
            )
        )
        return True

    def _load_detail(
        self,
        session: WorldSession,
        uuid: str,
        context: OperationContext,
    ) -> PlayerDetailResult:
        context.raise_if_cancelled()
        result = PlayerDetailResult(
            player_data=session.load_player_data(uuid),
            summary=self._service.load_summary(session, uuid),
            containers=self._service.load_containers(session, uuid),
            attributes=self._service.load_attributes(session, uuid),
            effects=self._service.load_effects(session, uuid),
        )
        context.raise_if_cancelled()
        return result

    def _finish_detail(
        self,
        handle: OperationHandle[PlayerDetailResult],
        uuid: str,
        world_generation: int,
        detail_generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            detail = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            run_on_ui(
                self._deliver_detail_error,
                error,
                uuid,
                world_generation,
                detail_generation,
            )
            return
        run_on_ui(
            self._deliver_detail,
            detail,
            uuid,
            world_generation,
            detail_generation,
        )

    def export_summary(
        self,
        session: WorldSession,
        uuid: str,
        output_path: Path,
        translate: Translate,
    ) -> bool:
        """异步导出当前选中玩家的摘要。"""
        if self._disposed or session is not self._session:
            return False
        self._export_generation += 1
        generation = self._export_generation
        self._cancel_handle(self._export_handle)
        world_generation = self._world_generation
        handle = self._scope.submit(
            "export_summary",
            lambda context: self._export_summary(
                session,
                uuid,
                output_path,
                translate,
                context,
            ),
            lane=ExecutionLane.IO,
            priority=TaskPriority.INTERACTIVE,
            feature="explorer.players",
            world_id=str(session.world_path),
            generation=world_generation,
            metadata={"player_uuid": uuid, "path": str(output_path)},
        )
        self._export_handle = handle
        handle.add_done_callback(
            lambda completed: self._finish_export(completed, generation)
        )
        return True

    def _export_summary(
        self,
        session: WorldSession,
        uuid: str,
        output_path: Path,
        translate: Translate,
        context: OperationContext,
    ) -> Path:
        context.raise_if_cancelled()
        bundle = self._service.build_export(session, uuid, include_items=True)
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
        context.raise_if_cancelled()
        atomic_write_text(output_path, payload)
        return output_path

    def _finish_export(
        self,
        handle: OperationHandle[Path],
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            path = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            run_on_ui(self._deliver_export_error, error, generation)
            return
        run_on_ui(self._deliver_export_success, path, generation)

    def _deliver_players(
        self,
        players: tuple[PlayerRef, ...],
        generation: int,
    ) -> None:
        if self.is_current_world(generation):
            self._callbacks.players_ready(players, generation)

    def _deliver_players_error(
        self,
        error: Exception,
        generation: int,
    ) -> None:
        if self.is_current_world(generation):
            self._callbacks.players_error(error, generation)

    def _deliver_detail(
        self,
        detail: PlayerDetailResult,
        uuid: str,
        world_generation: int,
        detail_generation: int,
    ) -> None:
        if self.is_current_detail(uuid, world_generation, detail_generation):
            self._callbacks.detail_ready(
                detail, uuid, world_generation, detail_generation
            )

    def _deliver_detail_error(
        self,
        error: Exception,
        uuid: str,
        world_generation: int,
        detail_generation: int,
    ) -> None:
        if self.is_current_detail(uuid, world_generation, detail_generation):
            self._callbacks.detail_error(
                error, uuid, world_generation, detail_generation
            )

    def _deliver_export_success(self, path: Path, generation: int) -> None:
        if self.is_current_export(generation):
            self._callbacks.export_success(path, generation)

    def _deliver_export_error(self, error: Exception, generation: int) -> None:
        if self.is_current_export(generation):
            self._callbacks.export_error(error, generation)

    def import_usercache(self, session: WorldSession, path: Path) -> bool:
        """异步合并 usercache.json 到当前会话名称表。"""
        if self._disposed or session is not self._session:
            return False
        self._usercache_generation += 1
        generation = self._usercache_generation
        self._cancel_handle(self._usercache_handle)
        world_generation = self._world_generation
        handle = self._scope.submit(
            "import_usercache",
            lambda context: self._import_usercache(session, path, context),
            lane=ExecutionLane.IO,
            priority=TaskPriority.INTERACTIVE,
            feature="explorer.players",
            world_id=str(session.world_path),
            generation=world_generation,
        )
        self._usercache_handle = handle
        handle.add_done_callback(
            lambda completed: self._finish_usercache(
                completed,
                world_generation,
                generation,
            )
        )
        return True

    @staticmethod
    def _import_usercache(
        session: WorldSession,
        path: Path,
        context: OperationContext,
    ) -> int:
        context.raise_if_cancelled()
        imported = int(session.import_usercache(path) or 0)
        context.raise_if_cancelled()
        return imported

    def _finish_usercache(
        self,
        handle: OperationHandle[int],
        world_generation: int,
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            imported = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            run_on_ui(
                self._deliver_usercache_error,
                error,
                world_generation,
                generation,
            )
            return
        run_on_ui(
            self._deliver_usercache_success,
            imported,
            world_generation,
            generation,
        )

    def _deliver_usercache_success(
        self,
        imported: int,
        world_generation: int,
        generation: int,
    ) -> None:
        if (
            self.is_current_world(world_generation)
            and generation == self._usercache_generation
        ):
            self._callbacks.usercache_success(imported, generation)

    def _deliver_usercache_error(
        self,
        error: Exception,
        world_generation: int,
        generation: int,
    ) -> None:
        if (
            self.is_current_world(world_generation)
            and generation == self._usercache_generation
        ):
            self._callbacks.usercache_error(error, generation)

    def lookup_names(
        self,
        session: WorldSession,
        uuid_service: UUIDService,
        uuids: Sequence[str],
    ) -> bool:
        """异步在线解析未知名玩家的当前名称。"""
        if self._disposed or session is not self._session or not uuids:
            return False
        self._name_lookup_generation += 1
        generation = self._name_lookup_generation
        self._cancel_handle(self._name_lookup_handle)
        world_generation = self._world_generation
        uuid_list = list(uuids)
        handle = self._scope.submit(
            "resolve_player_names_online",
            lambda context: self._resolve_names(
                uuid_service,
                uuid_list,
                context,
            ),
            lane=ExecutionLane.IO,
            priority=TaskPriority.INTERACTIVE,
            feature="explorer.player_name",
            world_id=str(session.world_path),
            generation=world_generation,
        )
        self._name_lookup_handle = handle
        handle.add_done_callback(
            lambda completed: self._finish_name_lookup(
                completed,
                world_generation,
                generation,
            )
        )
        return True

    def _resolve_names(
        self,
        uuid_service: UUIDService,
        uuids: list[str],
        context: OperationContext,
    ) -> NameLookupResult:
        context.raise_if_cancelled()

        def lookup(
            worker_token: CancellationToken,
            player_uuid: str,
        ) -> Optional[str]:
            worker_token.raise_if_cancelled()
            return uuid_service.query_current_name(player_uuid)

        names = map_items(
            self._runtime,
            "resolve_player_name",
            uuids,
            lookup,
            lane=ExecutionLane.IO,
            priority=TaskPriority.INTERACTIVE,
            cancel_check=lambda: context.is_cancelled,
            max_in_flight=_NAME_LOOKUP_MAX_WORKERS,
            feature="explorer.player_name",
        )
        context.raise_if_cancelled()
        resolved: dict[str, str] = {}
        unresolved: list[str] = []
        for player_uuid, name in zip(uuids, names):
            if isinstance(name, BaseException):
                unresolved.append(player_uuid)
            elif name:
                resolved[player_uuid] = name
            else:
                unresolved.append(player_uuid)
        return NameLookupResult(
            resolved=resolved,
            unresolved=tuple(unresolved),
        )

    def _finish_name_lookup(
        self,
        handle: OperationHandle[NameLookupResult],
        world_generation: int,
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
                self._deliver_name_lookup_error,
                error,
                world_generation,
                generation,
            )
            return
        run_on_ui(
            self._deliver_name_lookup_success,
            result,
            world_generation,
            generation,
        )

    def _deliver_name_lookup_success(
        self,
        result: NameLookupResult,
        world_generation: int,
        generation: int,
    ) -> None:
        if (
            self.is_current_world(world_generation)
            and generation == self._name_lookup_generation
        ):
            self._callbacks.name_lookup_success(result, generation)

    def _deliver_name_lookup_error(
        self,
        error: Exception,
        world_generation: int,
        generation: int,
    ) -> None:
        if (
            self.is_current_world(world_generation)
            and generation == self._name_lookup_generation
        ):
            self._callbacks.name_lookup_error(error, generation)

    def is_current_world(self, generation: int) -> bool:
        """返回列表结果是否仍属于当前世界。"""
        return (
            not self._disposed
            and self._session is not None
            and generation == self._world_generation
        )

    def is_current_detail(
        self,
        uuid: str,
        world_generation: int,
        detail_generation: int,
    ) -> bool:
        """返回详情结果是否仍属于当前世界与玩家选择。"""
        return (
            self.is_current_world(world_generation)
            and uuid == self._selected_uuid
            and detail_generation == self._detail_generation
        )

    def is_current_export(self, generation: int) -> bool:
        """返回导出结果是否仍属于当前世界世代。"""
        return (
            self.is_current_world(self._world_generation)
            and generation == self._export_generation
        )

    def clear_world(self) -> None:
        """取消玩家任务并清除当前会话身份。"""
        if self._disposed:
            return
        self._invalidate_requests()
        self._session = None

    def _invalidate_requests(self) -> None:
        self._world_generation += 1
        self._detail_generation += 1
        self._export_generation += 1
        self._usercache_generation += 1
        self._name_lookup_generation += 1
        self._selected_uuid = None
        self._cancel_handle(self._list_handle)
        self._cancel_handle(self._detail_handle)
        self._cancel_handle(self._export_handle)
        self._cancel_handle(self._usercache_handle)
        self._cancel_handle(self._name_lookup_handle)
        self._list_handle = None
        self._detail_handle = None
        self._export_handle = None
        self._usercache_handle = None
        self._name_lookup_handle = None

    @staticmethod
    def _cancel_handle(handle: Optional[OperationHandle[ResultT]]) -> None:
        if handle is not None:
            handle.cancel()

    def close(self) -> None:
        """幂等释放玩家后台任务。"""
        if self._disposed:
            return
        self._disposed = True
        self._world_generation += 1
        self._detail_generation += 1
        self._export_generation += 1
        self._usercache_generation += 1
        self._name_lookup_generation += 1
        self._selected_uuid = None
        self._session = None
        self._scope.close()


__all__ = [
    "NameLookupResult",
    "PlayerDetailResult",
    "PlayerTaskCallbacks",
    "PlayerTasks",
]
