"""Qt Explorer 搜索功能与现有搜索控制器的协调。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

from app.adapters.file_dialogs import FileType
from app.controllers.entity_block_search_controller import (
    EntityBlockExportCompletion,
    EntityBlockSearchBusyError,
    EntityBlockSearchCompletion,
    EntityBlockSearchController,
    EntityBlockSearchUiPorts,
)
from app.qtui.context import (
    QtDialogPort,
    QtFileDialogPort,
    QtProgressPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.utils import run_on_ui
from app.qtui.views.entity_search import QtEntitySearchPanel
from app.services.entity_block_search.models import SearchResult
from app.services.entity_block_search_service import EntityBlockSearchService
from core.omni.world_session import WorldSession


class QtEntitySearchHost(
    QtTranslationPort,
    QtDialogPort,
    QtFileDialogPort,
    QtProgressPort,
    QtRuntimePort,
    Protocol,
):
    """搜索标签所需的应用端口。"""


class QtEntitySearchCoordinator:
    """连接 Qt 搜索面板、共享运行时与现有搜索控制器。"""

    def __init__(
        self,
        app: QtEntitySearchHost,
        service: Optional[EntityBlockSearchService] = None,
    ) -> None:
        """创建搜索协调器。

        Args:
            app: 搜索标签所需的应用端口。
            service: 可选搜索服务，生产环境使用新的无状态实例。
        """
        self._app = app
        self._service = service or EntityBlockSearchService()
        self._world_path: Path | None = None
        self._results: tuple[SearchResult, ...] = ()
        self.panel = QtEntitySearchPanel(
            app.translate,
            self.start_search,
            self.export_results,
        )
        scope = app.execution_runtime.create_scope("qt_entity_search")
        self._controller = EntityBlockSearchController(
            self._service,
            scope,
            EntityBlockSearchUiPorts(
                dispatch=lambda callback: run_on_ui(callback),
                search_started=self._search_started,
                search_succeeded=self._search_succeeded,
                search_failed=self._search_failed,
                search_cancelled=self._search_cancelled,
                export_started=self._export_started,
                export_succeeded=self._export_succeeded,
                export_failed=self._export_failed,
                export_cancelled=self._export_cancelled,
            ),
        )
        self._scope = scope

    @property
    def is_searching(self) -> bool:
        """返回搜索是否正在运行。"""
        return self._controller.is_searching

    def set_world(self, session: WorldSession) -> None:
        """绑定当前世界并清除旧结果。"""
        was_busy = (
            self._controller.is_searching or self._controller.is_exporting
        )
        path = session.world_path.resolve()
        self._controller.select_world(path)
        self._world_path = path
        self._results = ()
        self.panel.show_world(True)
        if was_busy:
            self._app.hide_progress()

    def clear_world(self) -> None:
        """清除当前世界并取消所有搜索/导出。"""
        was_busy = (
            self._controller.is_searching or self._controller.is_exporting
        )
        self._controller.clear_world()
        self._world_path = None
        self._results = ()
        self.panel.show_world(False)
        if was_busy:
            self._app.hide_progress()

    def start_search(self) -> None:
        """校验条件并启动搜索。"""
        world_path = self._world_path
        if world_path is None:
            self._warn("entity_search.no_world", "请先加载存档")
            return
        condition = self.panel.condition(world_path)
        if not condition.target:
            self._warn("entity_search.target_required", "请输入目标 ID")
            return
        if not condition.dimensions:
            self._warn(
                "entity_search.dimension_required",
                "至少选择一个维度",
            )
            return
        try:
            self._controller.start_search(condition)
        except EntityBlockSearchBusyError:
            self._warn("entity_search.busy", "搜索或导出正在进行")
        except (OSError, RuntimeError, ValueError) as error:
            self._app.handle_exception(
                error,
                title=self._app.translate(
                    "entity_search.failed", "搜索失败"
                ),
            )

    def export_results(self) -> None:
        """选择目标路径并导出完整搜索结果。"""
        results = self._results
        if not results:
            self._warn(
                "entity_search.no_results", "没有可导出的搜索结果"
            )
            return
        try:
            path = self._app.save_file(
                title=self._app.translate(
                    "entity_search.export_title", "导出搜索结果"
                ),
                default_ext=".txt",
                file_types=[self._text_file_type()],
            )
        except (OSError, RuntimeError, ValueError) as error:
            self._app.handle_exception(
                error,
                title=self._app.translate(
                    "entity_search.export_failed", "导出失败"
                ),
            )
            return
        if not path:
            return
        try:
            self._controller.start_export(results, Path(path))
        except EntityBlockSearchBusyError:
            self._warn("entity_search.busy", "搜索或导出正在进行")
        except (OSError, RuntimeError, ValueError) as error:
            self._app.handle_exception(
                error,
                title=self._app.translate(
                    "entity_search.export_failed", "导出失败"
                ),
            )

    def _text_file_type(self) -> FileType:
        return (
            self._app.translate("entity_search.text_files", "文本文件"),
            "*.txt",
        )

    def _warn(self, key: str, default: str) -> None:
        self._app.warn_dialog(
            self._app.translate("common.tip", "提示"),
            self._app.translate(key, default),
        )

    def _search_started(self) -> None:
        self.panel.show_search_started()
        self._app.show_progress(self._app.translate(
            "entity_search.searching", "正在搜索..."
        ))

    def _search_succeeded(
        self,
        completion: EntityBlockSearchCompletion,
    ) -> None:
        self._results = completion.results
        self.panel.show_search_success(completion.results)
        self._app.hide_progress()

    def _search_failed(self, error: Exception) -> None:
        self.panel.show_search_failure(error)
        self._app.hide_progress()
        self._app.handle_exception(error, title=self._app.translate(
            "entity_search.failed", "搜索失败"
        ))

    def _search_cancelled(self) -> None:
        self.panel.show_search_cancelled()
        self._app.hide_progress()

    def _export_started(self) -> None:
        self.panel.show_export_started()
        self._app.show_progress(self._app.translate(
            "entity_search.exporting", "正在导出..."
        ))

    def _export_succeeded(
        self,
        completion: EntityBlockExportCompletion,
    ) -> None:
        self.panel.show_export_finished()
        self._app.hide_progress()
        self._app.info_dialog(
            self._app.translate("entity_search.export_ok_title", "导出成功"),
            self._app.translate(
                "entity_search.export_ok_body",
                "已导出 {count} 个结果到：\n{path}",
                count=completion.result_count,
                path=completion.output_path,
            ),
        )

    def _export_failed(self, error: Exception) -> None:
        self.panel.show_export_finished()
        self._app.hide_progress()
        self._app.handle_exception(error, title=self._app.translate(
            "entity_search.export_failed", "导出失败"
        ))

    def _export_cancelled(self) -> None:
        self.panel.show_export_finished()
        self._app.hide_progress()

    def close(self) -> None:
        """幂等关闭搜索控制器与任务作用域。"""
        was_busy = (
            self._controller.is_searching or self._controller.is_exporting
        )
        self._controller.close()
        self._scope.close()
        if was_busy:
            self._app.hide_progress()


__all__ = ["QtEntitySearchCoordinator", "QtEntitySearchHost"]
