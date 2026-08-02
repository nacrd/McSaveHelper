"""Qt Explorer 玩家列表、详情与导出后台任务。"""
from __future__ import annotations

import json
from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, TypeVar

from app.presenters.player_presenter import format_export_bundle_text
from app.qtui.utils import run_on_ui
from app.services.execution_runtime import (
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
from core.io_atomic import atomic_write_text
from core.nbt import Compound
from core.omni.player_manager import PlayerAttribute, PlayerEffect
from core.omni.world_session import WorldSession


ResultT = TypeVar("ResultT")
Translate = Callable[..., str]


@dataclass(frozen=True)
class PlayerDetailResult:
    """一次玩家详情读取的不可变投影。"""

    player_data: Optional[Compound]
    summary: Optional[PlayerSummary]
    containers: Optional[PlayerContainersView]
    attributes: tuple[PlayerAttribute, ...]
    effects: tuple[PlayerEffect, ...]


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
        self._scope = runtime.create_scope("qt_explorer_players")
        self._service = service
        self._callbacks = callbacks
        self._session: Optional[WorldSession] = None
        self._world_generation = 0
        self._detail_generation = 0
        self._export_generation = 0
        self._selected_uuid: Optional[str] = None
        self._list_handle: Optional[OperationHandle[tuple[PlayerRef, ...]]] = None
        self._detail_handle: Optional[OperationHandle[PlayerDetailResult]] = None
        self._export_handle: Optional[OperationHandle[Path]] = None
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
        self._selected_uuid = None
        self._cancel_handle(self._list_handle)
        self._cancel_handle(self._detail_handle)
        self._cancel_handle(self._export_handle)
        self._list_handle = None
        self._detail_handle = None
        self._export_handle = None

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
        self._selected_uuid = None
        self._session = None
        self._scope.close()


__all__ = [
    "PlayerDetailResult",
    "PlayerTaskCallbacks",
    "PlayerTasks",
]
