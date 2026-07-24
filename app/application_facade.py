"""Application public facade methods delegated to managers."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, cast

import flet as ft

from core.logger import LogLevel, logger

from app.adapters.file_dialogs import FileType
from app.ui.theme import THEME

if TYPE_CHECKING:
    from app.services.config_service import ConfigService
    from app.services.execution_runtime import ExecutionRuntime
    from app.services.i18n_service import I18nService
    from app.services.item_service import ItemService
    from app.services.migration_service import MigrationService
    from app.services.region_map import RegionMapService
    from app.services.texture_service import TextureService
    from app.services.ui_delivery import UiDeliveryPort
    from app.services.uuid_service import UUIDService
    from app.ui.feature_context import MigrationCommands


class ApplicationFacadeMixin:
    """View-facing convenience ports kept on the composition root."""

    page: Any
    services: Any
    dialog_manager: Any
    progress_manager: Any
    view_manager: Any
    gui_optimizer: Any
    migration_controller: Any
    save_context_manager: Any
    floating_log_panel: Any
    ui_delivery: "UiDeliveryPort"
    _sidebar: Any

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        return self._t(key, default, **kwargs)

    def _t(self, key: str, default: str = "", **kwargs: Any) -> str:
        try:
            return self.i18n.translate(key, default, **kwargs)
        except Exception:
            return default

    def log(self, msg: str, level: str = "INFO") -> None:
        log_level = LogLevel.from_string(level)
        logger.log(log_level, msg, module="App")

    def log_header(self, msg: str) -> None:
        self.floating_log_panel.log(f"\n{'=' * 50}", "separator")
        self.floating_log_panel.log(msg, "header")
        self.floating_log_panel.log(f"{'=' * 50}", "separator")

    def clear_log(self) -> None:
        self.floating_log_panel._clear()

    def update_progress(self, value: float) -> None:
        self.progress_manager.update_progress(value)

    def show_progress(self, task_name: str = "") -> None:
        self.progress_manager.show_progress(task_name)

    def hide_progress(self) -> None:
        self.progress_manager.hide_progress()

    def update_progress_with_task(
        self,
        task_name: str,
        value: float,
    ) -> None:
        self.progress_manager.update_progress_with_task(task_name, value)

    def set_progress_label(self, text: str) -> None:
        self.progress_manager.set_progress_label(text)

    def set_progress_value(self, value: float) -> None:
        self.progress_manager.set_progress_value(value)

    def _copy_to_clipboard(self, text: str) -> None:
        self.page.run_task(self.page.clipboard.set, text)

    def _show_snackbar(
        self,
        message: str,
        bgcolor: str,
        duration: int,
    ) -> None:
        self.page.show_dialog(ft.SnackBar(
            content=ft.Text(message, color=THEME.text_primary),
            bgcolor=bgcolor,
            duration=duration,
        ))

    def info_dialog(self, title: str, message: str) -> None:
        self.dialog_manager.info_dialog(title, message)

    def warn_dialog(self, title: str, message: str) -> None:
        self.dialog_manager.warn_dialog(title, message)

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Optional[Exception] = None,
        show_details: bool = False,
    ) -> None:
        self.dialog_manager.error_dialog(title, message, exception, show_details)

    def _show_success(self, title: str, message: str) -> None:
        notification_manager = self.gui_optimizer.notification_manager
        if notification_manager:
            notification_manager.show_success(message)
            return
        self.info_dialog(title, message)

    def handle_exception(
        self,
        exception: Exception,
        title: Optional[str] = None,
        log: bool = True,
        show_dialog: bool = True,
    ) -> None:
        self.dialog_manager.handle_exception(exception, title, log, show_dialog)

    def pick_directory(self) -> Optional[str]:
        return cast(Optional[str], self.dialog_manager.pick_directory())

    def pick_file(
        self,
        title: str = "",
        file_types: Optional[List[FileType]] = None,
    ) -> Optional[str]:
        return cast(Optional[str], self.dialog_manager.pick_file(title, file_types))

    def pick_files(
        self,
        title: str = "",
        file_types: Optional[List[FileType]] = None,
    ) -> Optional[List[str]]:
        return cast(Optional[List[str]], self.dialog_manager.pick_files(title, file_types))

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: Optional[List[FileType]] = None,
    ) -> Optional[str]:
        return cast(
            Optional[str],
            self.dialog_manager.save_file(title, default_ext, file_types),
        )

    def set_start_button_enabled(self, enabled: bool) -> None:
        view = self.view_manager.get_view("migrator")
        setter = getattr(view, "set_start_enabled", None)
        if callable(setter):
            setter(enabled)

    def start(self) -> None:
        self.migration_controller.start()

    def cancel_migration(self) -> bool:
        """请求取消当前迁移任务。"""
        return bool(self.migration_controller.cancel())

    @property
    def migration_commands(self) -> "MigrationCommands":
        """Return the narrow command port consumed by the migrator view."""
        from app.ui.feature_context import MigrationCommands

        return MigrationCommands(
            start=self.start,
            cancel=self.cancel_migration,
            choose_destination=self.set_dest,
            choose_batch_directory=self.set_batch_dir,
            close=self.migration_controller.close,
        )

    def _try_update_page(self) -> None:
        try:
            self.page.update()
        except Exception:
            pass

    def _save_config(self) -> None:
        self.config.save()

    def _run_single_thread(self, dest_dir: str) -> None:
        self.migration_controller.run_single_thread(dest_dir)

    def _run_batch_thread(self, dest_dir: str) -> None:
        self.migration_controller.run_batch_thread(dest_dir)

    def open_folder(self, path: str) -> None:
        self.migration_controller.open_folder(path)

    def set_src(self) -> None:
        self.save_context_manager.on_import_save()

    def set_dest(self) -> None:
        path = self.pick_directory()
        if path:
            self._update_migrator_path("dest", path)

    def set_batch_dir(self) -> None:
        path = self.pick_directory()
        if path:
            self._update_migrator_path("batch", path)

    def _update_migrator_path(
        self,
        target: str,
        value: str,
    ) -> None:
        view = self.view_manager.get_view("migrator")
        setter = getattr(view, "set_path_value", None)
        if callable(setter):
            setter(target, value)

    def update_uuid_mappings(
        self,
        mappings: Dict[str, str],
    ) -> None:
        self.config.custom_uuid_mappings = mappings
        self._save_config()

    @property
    def config(self) -> "ConfigService":
        return cast("ConfigService", self.services.config)

    @property
    def i18n(self) -> "I18nService":
        return cast("I18nService", self.services.i18n)

    @property
    def migration(self) -> "MigrationService":
        return cast("MigrationService", self.services.migration)

    @property
    def uuid(self) -> "UUIDService":
        return cast("UUIDService", self.services.uuid)

    @property
    def item(self) -> "ItemService":
        return cast("ItemService", self.services.item)

    @property
    def texture(self) -> "TextureService":
        return cast("TextureService", self.services.texture)

    @property
    def execution_runtime(self) -> "ExecutionRuntime":
        return cast("ExecutionRuntime", self.services.execution_runtime)

    def create_region_map_service(self) -> "RegionMapService":
        from app.services.region_map import RegionMapService

        return RegionMapService(
            self.execution_runtime,
            cache_registry=self.services.cache_registry,
        )

    @property
    def selected_view_id(self) -> Optional[str]:
        return self._sidebar.selected_id if hasattr(self, "_sidebar") else None

    @property
    def current_save_path(self) -> Optional[str]:
        return cast(Optional[str], self.save_context_manager.get_current_save_path())

    def open_world_session(
        self,
        world_path: Path | str,
        *,
        log: Optional[Callable[[str, str], None]] = None,
    ) -> Any:
        """Open a world session through the shared repository ports."""
        return self.feature_context.open_world_session(world_path, log=log)

    @property
    def feature_context(self) -> Any:
        from app.ui.feature_context import FeatureContext

        return FeatureContext(self)


__all__ = ["ApplicationFacadeMixin"]
