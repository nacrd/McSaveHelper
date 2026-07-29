"""World info tab mixin for ExplorerView."""
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Any, Callable

from app.presenters.quick_backup_state import (
    QuickBackupState,
    begin_quick_backup,
    finish_quick_backup,
    invalidate_quick_backup,
    owns_quick_backup,
)
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
        self._quick_backup_state = QuickBackupState()
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
            state = self._get_quick_backup_state()
            if state.is_running:
                self.app.warn_dialog("提示", "快速备份正在进行中，请稍候")
                return
            session = self.world_session
            world_path = session.world_path
            host_generation = self._world_load_generation
            state = begin_quick_backup(
                state,
                world_path,
                host_generation,
            )
            self._quick_backup_state = state
            request_generation = state.generation

            def worker(token: CancellationToken) -> None:
                try:
                    token.raise_if_cancelled()
                    self._post_quick_backup_ui(
                        session,
                        world_path,
                        host_generation,
                        request_generation,
                        self.app.show_progress,
                        "正在创建备份...",
                    )

                    def progress(value: float, message: str) -> None:
                        self._post_quick_backup_ui(
                            session,
                            world_path,
                            host_generation,
                            request_generation,
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
                        host_generation,
                        request_generation,
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
                        host_generation,
                        request_generation,
                        self.app.handle_exception,
                        exc,
                        title="创建备份失败",
                    )
                finally:
                    self._post_quick_backup_ui(
                        session,
                        world_path,
                        host_generation,
                        request_generation,
                        self._finish_quick_backup,
                        request_generation,
                    )

            self._task_scope.submit(
                "quick_backup",
                worker,
                priority=TaskPriority.INTERACTIVE,
            )
        except Exception as ex:
            state = self._get_quick_backup_state()
            self._quick_backup_state = finish_quick_backup(
                state,
                state.generation,
            )
            self.app.handle_exception(ex, title="创建备份失败")

    def _post_quick_backup_ui(
        self,
        session: object,
        world_path: Path,
        host_generation: int,
        request_generation: int,
        callback: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> None:
        """在投递前后校验快速备份仍属于当前世界。"""
        if not self._is_quick_backup_current(
            session,
            world_path,
            host_generation,
            request_generation,
        ):
            return

        def guarded() -> None:
            if self._is_quick_backup_current(
                session,
                world_path,
                host_generation,
                request_generation,
            ):
                callback(*args, **kwargs)

        run_on_ui(self.app.page, guarded)

    def _is_quick_backup_current(
        self,
        session: object,
        world_path: Path,
        host_generation: int,
        request_generation: int,
    ) -> bool:
        """返回快速备份宿主会话是否仍为当前 Explorer 世界。"""
        current = self.world_session
        state = self._get_quick_backup_state()
        return (
            not getattr(self, "_disposed", False)
            and host_generation == self._world_load_generation
            and current is session
            and current is not None
            and current.world_path == world_path
            and owns_quick_backup(
                state,
                request_generation,
                world_path,
                host_generation,
            )
        )

    def _get_quick_backup_state(self) -> QuickBackupState:
        """Return initialized state for full views and isolated mixin tests."""
        return getattr(self, "_quick_backup_state", QuickBackupState())

    def _finish_quick_backup(self, request_generation: int) -> None:
        """Release matching quick-backup ownership and hide progress."""
        state = self._get_quick_backup_state()
        next_state = finish_quick_backup(state, request_generation)
        if next_state is state:
            return
        self._quick_backup_state = next_state
        self.app.hide_progress()

    def _invalidate_quick_backup_state(self) -> None:
        """Drop pending quick-backup callbacks after host identity changes."""
        self._quick_backup_state = invalidate_quick_backup(
            self._get_quick_backup_state()
        )

    def _restore_backup(self, e: Any = None) -> None:
        del e
        if not self.world_session:
            self.app.warn_dialog("提示", "请先设置当前存档")
            return
        self.app.view_manager.switch_view("backup_center")
