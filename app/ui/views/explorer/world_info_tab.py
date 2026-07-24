"""World info tab mixin for ExplorerView."""
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Any, Callable

from app.services.backup_service import BackupCancelledError
from app.services.execution_runtime import (
    CancellationToken,
    OperationCancelledError,
    TaskPriority,
)
from app.ui.utils import run_on_ui
from app.ui.views.explorer.world_info_panel import WorldInfoPanel
from app.ui.views.explorer.mixin_context import ExplorerMixinHost


class WorldInfoTabMixin(ExplorerMixinHost):
    """Build and handle the Explorer world-info tab."""

    def _build_world_info_tab(self) -> None:
        self._world_info_panel = WorldInfoPanel(
            self.app.translate,
            on_select_save=self.app.save_context_manager.on_import_save,
            on_backup_click=self._create_backup,
            on_restore_click=self._restore_backup,
        )
        self._tab_world_info.content = self._world_info_panel

    def _create_backup(self, e: Any = None) -> None:
        del e
        try:
            if not self.world_session:
                self.app.warn_dialog("提示", "请先设置当前存档")
                return
            session = self.world_session
            world_path = session.world_path
            generation = self._world_load_generation

            def worker(token: CancellationToken) -> None:
                try:
                    token.raise_if_cancelled()
                    self._post_quick_backup_ui(
                        session,
                        world_path,
                        generation,
                        self.app.show_progress,
                        "正在创建备份...",
                    )

                    def progress(value: float, message: str) -> None:
                        self._post_quick_backup_ui(
                            session,
                            world_path,
                            generation,
                            self.app.update_progress_with_task,
                            message,
                            value,
                        )

                    record = self.app.backup.create_backup(
                        world_path,
                        label="Explorer 快速备份",
                        progress_callback=progress,
                        cancel_check=lambda: token.is_cancelled,
                    )
                    self._post_quick_backup_ui(
                        session,
                        world_path,
                        generation,
                        self.app.info_dialog,
                        "备份成功",
                        f"恢复点已创建：\n{record.backup_path}",
                    )
                except (
                    BackupCancelledError,
                    CancelledError,
                    OperationCancelledError,
                ):
                    return
                except Exception as exc:
                    self._post_quick_backup_ui(
                        session,
                        world_path,
                        generation,
                        self.app.handle_exception,
                        exc,
                        title="创建备份失败",
                    )
                finally:
                    self._post_quick_backup_ui(
                        session,
                        world_path,
                        generation,
                        self.app.hide_progress,
                    )

            self._task_scope.submit(
                "quick_backup",
                worker,
                priority=TaskPriority.INTERACTIVE,
            )
        except Exception as ex:
            self.app.handle_exception(ex, title="创建备份失败")

    def _post_quick_backup_ui(
        self,
        session: object,
        world_path: Path,
        generation: int,
        callback: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> None:
        """在投递前后校验快速备份仍属于当前世界。"""
        if not self._is_quick_backup_current(session, world_path, generation):
            return

        def guarded() -> None:
            if self._is_quick_backup_current(session, world_path, generation):
                callback(*args, **kwargs)

        run_on_ui(self.app.page, guarded)

    def _is_quick_backup_current(
        self,
        session: object,
        world_path: Path,
        generation: int,
    ) -> bool:
        """返回快速备份宿主会话是否仍为当前 Explorer 世界。"""
        current = self.world_session
        return (
            not getattr(self, "_disposed", False)
            and generation == self._world_load_generation
            and current is session
            and current is not None
            and current.world_path == world_path
        )

    def _restore_backup(self, e: Any = None) -> None:
        del e
        if not self.world_session:
            self.app.warn_dialog("提示", "请先设置当前存档")
            return
        self.app.view_manager.switch_view("backup_center")
