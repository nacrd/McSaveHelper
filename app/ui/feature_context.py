"""Feature context ports for views without full Application dependency."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol

import flet as ft

from app.adapters.file_dialogs import FileType

if TYPE_CHECKING:
    from app.core.save_context_manager import SaveContextManager
    from app.core.view_manager import ViewManager
    from app.services.backup_service import BackupService
    from app.services.cache_registry import CacheRegistry
    from app.services.config_service import ConfigService
    from app.services.execution_runtime import ExecutionRuntime
    from app.services.item_service import ItemService
    from app.services.migration_service import MigrationService
    from app.services.region_map import RegionMapService
    from app.services.save_repair_service import SaveRepairService
    from app.services.texture_service import TextureService
    from app.services.ui_delivery import UiDeliveryPort
    from app.services.uuid_service import UUIDService
    from app.services.world_compare_service import WorldCompareService
    from app.services.world_repository import WorldRepository
    from app.services.world_stats_service import WorldStatsService
    from app.services.world_transaction import WorldTransactionService
    from core.omni.world_session import WorldSession


class FeaturePagePort(Protocol):
    """UI page used by controls that must present or refresh content."""

    @property
    def page(self) -> ft.Page:
        """Return the page used to present the feature."""
        ...


class FeatureTranslationPort(Protocol):
    """Translation and lightweight application logging port."""

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        """Translate UI text."""
        ...

    def log(self, msg: str, level: str = "INFO") -> None:
        """Write application log."""
        ...


class FeatureDialogPort(Protocol):
    """Modal notification and exception presentation port."""

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


class FeatureMigrationPort(Protocol):
    """Migration command port exposed to the migration view."""

    @property
    def migration_commands(self) -> "MigrationCommands":
        """Return the narrow command port for migration UI actions."""
        ...


class FeatureFileDialogPort(Protocol):
    """Native file and directory chooser port."""

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


class FeatureProgressPort(Protocol):
    """Shared progress presentation port."""

    def show_progress(self, task_name: str = "") -> None:
        """Show progress."""
        ...

    def hide_progress(self) -> None:
        """Hide progress."""
        ...

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        """Update named progress."""
        ...


class FeatureMapPort(Protocol):
    """Factory for feature-scoped map services."""

    def create_region_map_service(self) -> RegionMapService:
        """Create map service."""
        ...


class FeatureUuidMappingPort(Protocol):
    """Persistence port for custom UUID mappings."""

    def update_uuid_mappings(self, mappings: dict[str, str]) -> None:
        """Persist UUID mappings."""
        ...


class FeatureRuntimePort(Protocol):
    """Background execution runtime owned by the application."""

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        """Return the shared execution runtime."""
        ...


class FeatureHost(
    FeaturePagePort,
    FeatureTranslationPort,
    FeatureDialogPort,
    FeatureFileDialogPort,
    FeatureProgressPort,
    FeatureMapPort,
    FeatureUuidMappingPort,
    FeatureRuntimePort,
    FeatureMigrationPort,
    Protocol,
):
    """Composition host that combines reusable UI and service ports."""

    @property
    def current_save_path(self) -> Optional[str]:
        """Selected save path."""
        ...

    @property
    def config(self) -> ConfigService:
        """Config service."""
        ...

    @property
    def migration(self) -> MigrationService:
        """Migration service."""
        ...

    @property
    def uuid(self) -> UUIDService:
        """UUID service."""
        ...

    @property
    def item(self) -> ItemService:
        """Item service."""
        ...

    @property
    def texture(self) -> TextureService:
        """Texture service."""
        ...

    @property
    def ui_delivery(self) -> UiDeliveryPort:
        """Framework-neutral UI result delivery port."""
        ...

    @property
    def backup(self) -> BackupService:
        """Managed backup service."""
        ...

    @property
    def save_repair(self) -> SaveRepairService:
        """World repair service."""
        ...

    @property
    def world_compare(self) -> WorldCompareService:
        """World comparison service."""
        ...

    @property
    def world_transactions(self) -> WorldTransactionService:
        """Shared world transaction service."""
        ...

    @property
    def world_repository(self) -> WorldRepository:
        """Shared world read repository."""
        ...

    @property
    def world_stats(self) -> WorldStatsService:
        """World statistics service."""
        ...

    @property
    def cache_registry(self) -> CacheRegistry:
        """Application cache registry."""
        ...

    @property
    def save_context_manager(self) -> SaveContextManager:
        """Save context manager."""
        ...

    @property
    def view_manager(self) -> ViewManager:
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
    def execution_runtime(self) -> ExecutionRuntime:
        return self.host.execution_runtime

    @property
    def ui_delivery(self) -> UiDeliveryPort:
        return self.host.ui_delivery

    @property
    def config(self) -> ConfigService:
        return self.host.config

    @property
    def migration(self) -> MigrationService:
        return self.host.migration

    @property
    def uuid(self) -> UUIDService:
        return self.host.uuid

    @property
    def item(self) -> ItemService:
        return self.host.item

    @property
    def texture(self) -> TextureService:
        return self.host.texture

    @property
    def backup(self) -> BackupService:
        return self.host.backup

    @property
    def save_repair(self) -> SaveRepairService:
        return self.host.save_repair

    @property
    def world_compare(self) -> WorldCompareService:
        return self.host.world_compare

    @property
    def world_transactions(self) -> WorldTransactionService:
        return self.host.world_transactions

    @property
    def world_repository(self) -> WorldRepository:
        return self.host.world_repository

    @property
    def world_stats(self) -> WorldStatsService:
        return self.host.world_stats

    @property
    def cache_registry(self) -> CacheRegistry:
        return self.host.cache_registry

    @property
    def current_save_path(self) -> Optional[str]:
        return self.host.current_save_path

    @property
    def save_context_manager(self) -> SaveContextManager:
        return self.host.save_context_manager

    @property
    def view_manager(self) -> ViewManager:
        return self.host.view_manager

    @property
    def migration_commands(self) -> "MigrationCommands":
        """Return migration commands without exposing the full host facade."""
        return self.host.migration_commands

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
    ) -> WorldSession:
        """Open a world session with shared repository write ports."""
        return self.world_repository.open_session(
            world_path,
            log=log or self.log,
        )


@dataclass(frozen=True)
class MigrationCommands:
    """UI command port owned by the application composition root."""

    start: Callable[[], None]
    cancel: Callable[[], bool]
    choose_destination: Callable[[], None]
    choose_batch_directory: Callable[[], None]
    close: Callable[[], None]


__all__ = [
    "FeatureContext",
    "FeatureDialogPort",
    "FeatureFileDialogPort",
    "FeatureHost",
    "FeatureMapPort",
    "FeatureMigrationPort",
    "FeaturePagePort",
    "FeatureProgressPort",
    "FeatureRuntimePort",
    "FeatureTranslationPort",
    "FeatureUuidMappingPort",
    "MigrationCommands",
]
