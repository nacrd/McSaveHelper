"""Qt Explorer 世界统计后台任务与生命周期。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.presenters.stats_view_state import (
    StatsAnalysisState,
    begin_stats_analysis,
    finish_stats_analysis,
    invalidate_stats_analysis,
    owns_stats_analysis,
)
from app.qtui.utils import run_on_ui
from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
    OperationContext,
    OperationHandle,
    TaskPriority,
)
from app.services.world_repository import WorldRepository
from app.services.world_stats_service import (
    WorldStatistics,
    WorldStatsCancelledError,
    WorldStatsService,
)
from core.omni.world_session import WorldSession


@dataclass(frozen=True)
class StatsTaskCallbacks:
    """统计后台结果的 Qt 主线程投影回调。"""

    progress: Callable[[float, str, int], None]
    success: Callable[[WorldStatistics, int], None]
    error: Callable[[Exception, int], None]
    finished: Callable[[int], None]


class StatsTasks:
    """拥有单次世界统计分析并拒绝过期回调。"""

    def __init__(
        self,
        runtime: ExecutionRuntime,
        repository: WorldRepository,
        service: WorldStatsService,
        callbacks: StatsTaskCallbacks,
    ) -> None:
        """创建统计任务所有者。

        Args:
            runtime: 应用共享后台运行时。
            repository: 应用共享世界索引仓库。
            service: 应用共享统计服务。
            callbacks: Qt 主线程投影回调。
        """
        self._scope = runtime.create_scope("qt_explorer_stats")
        self._repository = repository
        self._service = service
        self._callbacks = callbacks
        self._session: Optional[WorldSession] = None
        self._host_generation = 0
        self._state = StatsAnalysisState()
        self._handle: Optional[OperationHandle[WorldStatistics]] = None
        self._disposed = False

    @property
    def is_running(self) -> bool:
        """返回当前世界是否正在分析。"""
        return not self._disposed and self._state.is_running

    def set_world(self, session: WorldSession) -> None:
        """切换当前世界并取消旧分析。"""
        if self._disposed:
            return
        self._invalidate()
        self._session = session

    def start(self) -> bool:
        """启动当前世界分析；无世界或已有分析时返回 False。"""
        session = self._session
        if self._disposed or session is None or self._state.is_running:
            return False
        world_path = session.world_path
        self._state = begin_stats_analysis(
            self._state,
            world_path,
            self._host_generation,
        )
        generation = self._state.generation
        name_map = self._player_name_map(session)
        try:
            handle = self._scope.submit(
                "analyze_world",
                lambda context: self._analyze(
                    world_path, name_map, generation, context
                ),
                lane=ExecutionLane.CPU,
                priority=TaskPriority.INTERACTIVE,
                feature="explorer.stats",
                world_id=str(world_path),
                generation=generation,
            )
        except Exception:
            self._state = finish_stats_analysis(self._state, generation)
            raise
        self._handle = handle
        handle.add_done_callback(
            lambda completed: self._finish(completed, generation)
        )
        return True

    @staticmethod
    def _player_name_map(
        session: WorldSession,
    ) -> dict[str, str | None]:
        """读取可选玩家名快照；失败不影响统计主流程。"""
        try:
            return dict(session.get_player_names())
        except Exception:
            return {}

    def _analyze(
        self,
        world_path: Path,
        name_map: dict[str, str | None],
        generation: int,
        context: OperationContext,
    ) -> WorldStatistics:
        context.raise_if_cancelled()
        snapshot = self._repository.get_index(world_path)

        def progress(value: float, stage: str) -> None:
            context.raise_if_cancelled()
            run_on_ui(
                self._deliver_progress,
                value,
                stage,
                generation,
            )

        return self._service.analyze_world(
            world_path,
            progress_callback=progress,
            name_map=name_map,
            index_snapshot=snapshot,
            cancel_check=lambda: context.is_cancelled,
        )

    def _finish(
        self,
        handle: OperationHandle[WorldStatistics],
        generation: int,
    ) -> None:
        if handle.cancelled:
            run_on_ui(self._deliver_finished, generation)
            return
        try:
            stats = handle.result()
        except (
            CancelledError,
            OperationCancelledError,
            WorldStatsCancelledError,
        ):
            run_on_ui(self._deliver_finished, generation)
            return
        except Exception as error:
            run_on_ui(self._deliver_error, error, generation)
            run_on_ui(self._deliver_finished, generation)
            return
        run_on_ui(self._deliver_success, stats, generation)
        run_on_ui(self._deliver_finished, generation)

    def _deliver_progress(
        self,
        value: float,
        stage: str,
        generation: int,
    ) -> None:
        if self.is_current(generation):
            self._callbacks.progress(value, stage, generation)

    def _deliver_success(
        self,
        stats: WorldStatistics,
        generation: int,
    ) -> None:
        if self.is_current(generation):
            self._callbacks.success(stats, generation)

    def _deliver_error(self, error: Exception, generation: int) -> None:
        if self.is_current(generation):
            self._callbacks.error(error, generation)

    def _deliver_finished(self, generation: int) -> None:
        if not self.is_current(generation):
            return
        self._state = finish_stats_analysis(self._state, generation)
        self._handle = None
        self._callbacks.finished(generation)

    def is_current(self, generation: int) -> bool:
        """返回回调是否仍属于当前世界的最新分析。"""
        session = self._session
        if self._disposed or session is None:
            return False
        return owns_stats_analysis(
            self._state,
            generation,
            session.world_path,
            self._host_generation,
        )

    def cancel(self) -> bool:
        """取消当前分析并立即使排队回调失效。"""
        if not self.is_running:
            return False
        handle = self._handle
        if handle is not None:
            handle.cancel()
        self._state = invalidate_stats_analysis(self._state)
        self._handle = None
        return True

    def clear_world(self) -> None:
        """清除当前世界并取消统计分析。"""
        if self._disposed:
            return
        self._invalidate()
        self._session = None

    def _invalidate(self) -> None:
        self._host_generation += 1
        if self._handle is not None:
            self._handle.cancel()
        self._handle = None
        self._state = invalidate_stats_analysis(self._state)

    def close(self) -> None:
        """幂等关闭统计任务作用域。"""
        if self._disposed:
            return
        self._disposed = True
        self._host_generation += 1
        self._state = invalidate_stats_analysis(self._state)
        self._session = None
        self._handle = None
        self._scope.close()


__all__ = ["StatsTaskCallbacks", "StatsTasks"]
