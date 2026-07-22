"""Feature context ports for views without full Application dependency."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

import flet as ft

from app.adapters.file_dialogs import FileType
from app.bootstrap.services import AppServices
from app.services.execution_runtime import ExecutionRuntime
from app.services.region_map import RegionMapService


class FeatureHost(Protocol):
    """Minimal host protocol required by FeatureContext."""

    page: ft.Page
    services: AppServices

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        """Translate UI text."""
        ...

    def log(self, msg: str, level: str = "INFO") -> None:
        """Write application log."""
        ...

    def info_dialog(self, title: str, message: str) -> None:
        """Show info dialog."""
        ...

    def warn_dialog(self, title: str, message: str) -> None:
        """Show warning dialog."""
        ...

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Optional[Exception] = None,
        show_details: bool = False,
    ) -> None:
        """Show error dialog."""
        ...

    def handle_exception(
        self,
        exception: Exception,
        title: Optional[str] = None,
        log: bool = True,
        show_dialog: bool = True,
    ) -> None:
        """Handle exception for UI."""
        ...

    def pick_directory(self) -> Optional[str]:
        """Pick directory."""
        ...

    def pick_file(
        self,
        title: str = "",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        """Pick file."""
        ...

    def pick_files(
        self,
        title: str = "",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[list[str]]:
        """Pick multiple files."""
        ...

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        """Save file dialog."""
        ...

    def show_progress(self, task_name: str = "") -> None:
        """Show progress."""
        ...

    def hide_progress(self) -> None:
        """Hide progress."""
        ...

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        """Update named progress."""
        ...

    def create_region_map_service(self) -> RegionMapService:
        """Create map service."""
        ...

    def update_uuid_mappings(self, mappings: dict[str, str]) -> None:
        """Persist UUID mappings."""
        ...

    @property
    def current_save_path(self) -> Optional[str]:
        """Selected save path."""
        ...

    @property
    def config(self) -> Any:
        """Config service."""
        ...

    @property
    def migration(self) -> Any:
        """Migration service."""
        ...

    @property
    def uuid(self) -> Any:
        """UUID service."""
        ...

    @property
    def item(self) -> Any:
        """Item service."""
        ...

    @property
    def texture(self) -> Any:
        """Texture service."""
        ...

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        """Execution runtime."""
        ...

    @property
    def save_context_manager(self) -> Any:
        """Save context manager."""
        ...

    @property
    def view_manager(self) -> Any:
        """View manager."""
        ...


@dataclass(frozen=True)
class FeatureContext:
    """Restricted port bag for feature views."""

    host: FeatureHost

    @property
    def page(self) -> ft.Page:
        return self.host.page

    @property
    def services(self) -> AppServices:
        return self.host.services

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        return self.host.execution_runtime

    @property
    def config(self) -> Any:
        return self.host.config

    @property
    def migration(self) -> Any:
        return self.host.migration

    @property
    def uuid(self) -> Any:
        return self.host.uuid

    @property
    def item(self) -> Any:
        return self.host.item

    @property
    def texture(self) -> Any:
        return self.host.texture

    @property
    def current_save_path(self) -> Optional[str]:
        return self.host.current_save_path

    @property
    def save_context_manager(self) -> Any:
        return self.host.save_context_manager

    @property
    def view_manager(self) -> Any:
        return self.host.view_manager

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        return self.host.translate(key, default, **kwargs)

    def log(self, msg: str, level: str = "INFO") -> None:
        self.host.log(msg, level)

    def info_dialog(self, title: str, message: str) -> None:
        self.host.info_dialog(title, message)

    def warn_dialog(self, title: str, message: str) -> None:
        self.host.warn_dialog(title, message)

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Optional[Exception] = None,
        show_details: bool = False,
    ) -> None:
        self.host.error_dialog(title, message, exception, show_details)

    def handle_exception(
        self,
        exception: Exception,
        title: Optional[str] = None,
        log: bool = True,
        show_dialog: bool = True,
    ) -> None:
        self.host.handle_exception(exception, title, log, show_dialog)

    def pick_directory(self) -> Optional[str]:
        return self.host.pick_directory()

    def pick_file(
        self,
        title: str = "",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        return self.host.pick_file(title, file_types)

    def pick_files(
        self,
        title: str = "",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[list[str]]:
        return self.host.pick_files(title, file_types)

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        return self.host.save_file(title, default_ext, file_types)

    def show_progress(self, task_name: str = "") -> None:
        self.host.show_progress(task_name)

    def hide_progress(self) -> None:
        self.host.hide_progress()

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        self.host.update_progress_with_task(task_name, value)

    def create_region_map_service(self) -> RegionMapService:
        return self.host.create_region_map_service()

    def update_uuid_mappings(self, mappings: dict[str, str]) -> None:
        self.host.update_uuid_mappings(mappings)

    def open_world_session(
        self,
        world_path: Path | str,
        *,
        log: Optional[Callable[[str, str], None]] = None,
    ) -> Any:
        """Open a world session with shared repository write ports."""
        from app.services.world_repository import WorldSessionPorts

        return self.services.world_repository.open_session(
            world_path,
            log=log or self.log,
            ports=WorldSessionPorts(
                write_lease_factory=self.services.world_writes.reserve,
                backup_callback=lambda world: self.services.backup.create_backup(
                    world,
                    label="NBT 提交前自动备份",
                ).backup_path,
                transaction_callback=lambda world, mutation: (
                    self.services.world_transactions.mutate(
                        world,
                        mutation,
                        backup_label="NBT 提交前自动备份",
                    )
                ),
            ),
        )


__all__ = ["FeatureContext", "FeatureHost"]
