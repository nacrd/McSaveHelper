"""World info tab mixin for ExplorerView."""
import threading
from typing import Any

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
            world_path = self.world_session.world_path

            def worker() -> None:
                try:
                    run_on_ui(self.app.page, self.app.show_progress, "正在创建备份...")

                    def progress(value: float, message: str) -> None:
                        run_on_ui(
                            self.app.page,
                            self.app.update_progress_with_task,
                            message,
                            value,
                        )

                    record = self.app.services.backup.create_backup(
                        world_path,
                        label="Explorer 快速备份",
                        progress_callback=progress,
                    )
                    run_on_ui(
                        self.app.page,
                        self.app.info_dialog,
                        "备份成功",
                        f"恢复点已创建：\n{record.backup_path}",
                    )
                except Exception as exc:
                    run_on_ui(
                        self.app.page,
                        self.app.handle_exception,
                        exc,
                        title="创建备份失败",
                    )
                finally:
                    run_on_ui(self.app.page, self.app.hide_progress)

            threading.Thread(target=worker, daemon=True).start()
        except Exception as ex:
            self.app.handle_exception(ex, title="创建备份失败")

    def _restore_backup(self, e: Any = None) -> None:
        del e
        if not self.world_session:
            self.app.warn_dialog("提示", "请先设置当前存档")
            return
        self.app.view_manager.switch_view("backup_center")
