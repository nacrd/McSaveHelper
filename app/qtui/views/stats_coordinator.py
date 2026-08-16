"""Qt Explorer 统计功能的 UI 与后台任务协调。"""
from __future__ import annotations

from typing import Protocol

from app.qtui.context import (
    QtDialogPort,
    QtProgressPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.views.stats import QtStatsPanel, format_stats_stage
from app.qtui.views.stats_tasks import StatsTaskCallbacks, StatsTasks
from app.services.world_repository import WorldRepository
from app.services.world_stats_service import WorldStatistics, WorldStatsService
from core.omni.world_session import WorldSession


class QtStatsHost(
    QtTranslationPort,
    QtDialogPort,
    QtProgressPort,
    QtRuntimePort,
    Protocol,
):
    """统计标签所需的应用端口。"""

    @property
    def world_repository(self) -> WorldRepository:
        """返回共享世界索引仓库。"""
        ...

    @property
    def world_stats(self) -> WorldStatsService:
        """返回共享世界统计服务。"""
        ...


class QtStatsCoordinator:
    """连接统计面板、应用端口与后台分析生命周期。"""

    def __init__(self, app: QtStatsHost) -> None:
        """创建统计面板与任务所有者。

        Args:
            app: 统计功能所需应用端口。
        """
        self._app = app
        self._has_world = False
        self.panel = QtStatsPanel(
            app.translate,
            self.start,
            self.cancel,
        )
        self._tasks = StatsTasks(
            app.execution_runtime,
            app.world_repository,
            app.world_stats,
            StatsTaskCallbacks(
                progress=self._apply_progress,
                success=self._apply_success,
                error=self._apply_error,
                finished=self._finish,
            ),
        )

    @property
    def is_running(self) -> bool:
        """返回统计分析是否正在运行。"""
        return self._tasks.is_running

    def set_world(self, session: WorldSession) -> None:
        """切换统计目标世界。"""
        self._tasks.set_world(session)
        self._has_world = True
        self.panel.show_ready(True)

    def clear_world(self) -> None:
        """取消分析并清除世界投影。"""
        was_running = self._tasks.is_running
        self._tasks.clear_world()
        self._has_world = False
        self.panel.show_ready(False)
        if was_running:
            self._app.hide_progress()

    def start(self) -> None:
        """从面板命令启动统计分析。"""
        if not self._has_world:
            self._app.warn_dialog(
                self._app.translate("common.tip", "提示"),
                self._app.translate(
                    "stats.need_save", "请先通过侧边栏设置当前存档。"
                ),
            )
            return
        try:
            if not self._tasks.start():
                return
        except (OSError, RuntimeError, ValueError) as error:
            self._apply_error(error, -1)
            return
        self.panel.show_analyzing()
        self._app.show_progress(self._app.translate(
            "stats.progress_task", "统计存档"
        ))

    def cancel(self) -> None:
        """取消当前统计分析。"""
        if not self._tasks.cancel():
            return
        self.panel.show_cancelled()
        self._app.hide_progress()

    def _apply_progress(
        self,
        value: float,
        stage: str,
        generation: int,
    ) -> None:
        del generation
        message = format_stats_stage(self._app.translate, stage)
        self.panel.update_progress(value, message)
        self._app.update_progress_with_task(message, value * 100.0)

    def _apply_success(
        self,
        stats: WorldStatistics,
        generation: int,
    ) -> None:
        del generation
        self.panel.show_stats(stats)

    def _apply_error(self, error: Exception, generation: int) -> None:
        del generation
        self.panel.show_error()
        self._app.handle_exception(
            error,
            title=self._app.translate(
                "stats.error_title", "统计存档失败"
            ),
        )

    def _finish(self, generation: int) -> None:
        del generation
        self.panel.set_busy(False)
        self._app.hide_progress()

    def close(self) -> None:
        """幂等关闭统计任务。"""
        was_running = self._tasks.is_running
        self._tasks.close()
        if was_running:
            self._app.hide_progress()


__all__ = ["QtStatsCoordinator", "QtStatsHost"]
