"""Qt Explorer 玩家列表与摘要后台任务。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from typing import Callable, Optional, TypeVar

from app.qtui.utils import run_on_ui
from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
    OperationContext,
    OperationHandle,
    TaskPriority,
)
from app.services.player.models import PlayerRef, PlayerSummary
from app.services.player_service import PlayerService
from core.omni.world_session import WorldSession


ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class PlayerTaskCallbacks:
    """玩家后台结果的 Qt 主线程投影回调。"""

    players_ready: Callable[[tuple[PlayerRef, ...], int], None]
    players_error: Callable[[Exception, int], None]
    summary_ready: Callable[[Optional[PlayerSummary], str, int, int], None]
    summary_error: Callable[[Exception, str, int, int], None]


class PlayerTasks:
    """拥有玩家读取任务，并丢弃世界或选择切换后的过期结果。"""

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
        self._summary_generation = 0
        self._selected_uuid: Optional[str] = None
        self._list_handle: Optional[OperationHandle[tuple[PlayerRef, ...]]] = None
        self._summary_handle: Optional[
            OperationHandle[Optional[PlayerSummary]]
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

    def load_summary(self, session: WorldSession, uuid: str) -> bool:
        """异步读取当前世界内选中玩家的摘要。"""
        if self._disposed or session is not self._session:
            return False
        self._summary_generation += 1
        generation = self._summary_generation
        self._selected_uuid = uuid
        self._cancel_handle(self._summary_handle)
        world_generation = self._world_generation
        handle = self._scope.submit(
            "load_summary",
            lambda context: self._load_summary(session, uuid, context),
            lane=ExecutionLane.CPU,
            priority=TaskPriority.INTERACTIVE,
            feature="explorer.players",
            world_id=str(session.world_path),
            generation=world_generation,
            metadata={"player_uuid": uuid},
        )
        self._summary_handle = handle
        handle.add_done_callback(
            lambda completed: self._finish_summary(
                completed,
                uuid,
                world_generation,
                generation,
            )
        )
        return True

    def _load_summary(
        self,
        session: WorldSession,
        uuid: str,
        context: OperationContext,
    ) -> Optional[PlayerSummary]:
        context.raise_if_cancelled()
        summary = self._service.load_summary(session, uuid)
        context.raise_if_cancelled()
        return summary

    def _finish_summary(
        self,
        handle: OperationHandle[Optional[PlayerSummary]],
        uuid: str,
        world_generation: int,
        summary_generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            summary = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            run_on_ui(
                self._deliver_summary_error,
                error,
                uuid,
                world_generation,
                summary_generation,
            )
            return
        run_on_ui(
            self._deliver_summary,
            summary,
            uuid,
            world_generation,
            summary_generation,
        )

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

    def _deliver_summary(
        self,
        summary: Optional[PlayerSummary],
        uuid: str,
        world_generation: int,
        summary_generation: int,
    ) -> None:
        if self.is_current_summary(
            uuid, world_generation, summary_generation
        ):
            self._callbacks.summary_ready(
                summary, uuid, world_generation, summary_generation
            )

    def _deliver_summary_error(
        self,
        error: Exception,
        uuid: str,
        world_generation: int,
        summary_generation: int,
    ) -> None:
        if self.is_current_summary(
            uuid, world_generation, summary_generation
        ):
            self._callbacks.summary_error(
                error, uuid, world_generation, summary_generation
            )

    def is_current_world(self, generation: int) -> bool:
        """返回列表结果是否仍属于当前世界。"""
        return (
            not self._disposed
            and self._session is not None
            and generation == self._world_generation
        )

    def is_current_summary(
        self,
        uuid: str,
        world_generation: int,
        summary_generation: int,
    ) -> bool:
        """返回摘要结果是否仍属于当前世界与玩家选择。"""
        return (
            self.is_current_world(world_generation)
            and uuid == self._selected_uuid
            and summary_generation == self._summary_generation
        )

    def clear_world(self) -> None:
        """取消玩家任务并清除当前会话身份。"""
        if self._disposed:
            return
        self._invalidate_requests()
        self._session = None

    def _invalidate_requests(self) -> None:
        self._world_generation += 1
        self._summary_generation += 1
        self._selected_uuid = None
        self._cancel_handle(self._list_handle)
        self._cancel_handle(self._summary_handle)
        self._list_handle = None
        self._summary_handle = None

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
        self._summary_generation += 1
        self._selected_uuid = None
        self._session = None
        self._scope.close()


__all__ = ["PlayerTaskCallbacks", "PlayerTasks"]
