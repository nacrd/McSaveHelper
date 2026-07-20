"""Explicit construction of application services."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.services.config_service import ConfigService
from app.services.backup_service import BackupService
from app.services.save_repair_service import SaveRepairService
from app.services.i18n_service import I18nService
from app.services.item_service import ItemService
from app.services.migration_service import MigrationService
from app.services.texture_service import TextureService
from app.services.uuid_service import UUIDService
from app.services.world_write_coordinator import WorldWriteCoordinator


class ServiceInitializationError(RuntimeError):
    """Raised when an essential service cannot be constructed safely."""

    def __init__(self, service_name: str, cause: Exception) -> None:
        """记录失败的服务名与原始异常。

        Args:
            service_name: 如 ``config`` / ``migration``。
            cause: 构造过程中捕获的异常。
        """
        self.service_name = service_name
        self.cause = cause
        super().__init__(f"服务初始化失败 [{service_name}]: {cause}")


@dataclass(frozen=True)
class AppServices:
    """应用级服务显式装配结果（组合根持有，非业务单例）。"""

    config: ConfigService
    i18n: I18nService
    migration: MigrationService
    uuid: UUIDService
    item: ItemService
    texture: TextureService
    backup: BackupService
    save_repair: SaveRepairService
    world_writes: WorldWriteCoordinator


@dataclass(frozen=True)
class ServiceFactories:
    """可替换的服务工厂表，便于测试注入替身。"""

    config: Callable[[], ConfigService] = ConfigService
    i18n: Callable[[ConfigService], I18nService] = I18nService
    migration: Callable[
        [ConfigService, BackupService],
        MigrationService,
    ] = MigrationService
    uuid: Callable[[], UUIDService] = UUIDService
    item: Callable[[], ItemService] = ItemService
    texture: Callable[[], TextureService] = TextureService
    world_writes: Callable[[], WorldWriteCoordinator] = WorldWriteCoordinator
    backup: Callable[[WorldWriteCoordinator], BackupService] = BackupService
    save_repair: Callable[
        [BackupService],
        SaveRepairService,
    ] = SaveRepairService


def _create(service_name: str, factory: Callable[..., Any], *args: Any) -> Any:
    try:
        return factory(*args)
    except Exception as exc:
        raise ServiceInitializationError(service_name, exc) from exc


def create_app_services(
    factories: Optional[ServiceFactories] = None,
) -> AppServices:
    """Build services in dependency order or fail with an actionable error."""
    selected = factories or ServiceFactories()
    config = _create("config", selected.config)
    i18n = _create("i18n", selected.i18n, config)
    world_writes = _create("world_writes", selected.world_writes)
    backup = _create("backup", selected.backup, world_writes)
    migration = _create("migration", selected.migration, config, backup)
    uuid = _create("uuid", selected.uuid)
    item = _create("item", selected.item)
    texture = _create("texture", selected.texture)
    save_repair = _create("save_repair", selected.save_repair, backup)
    return AppServices(
        config=config,
        i18n=i18n,
        migration=migration,
        uuid=uuid,
        item=item,
        texture=texture,
        backup=backup,
        save_repair=save_repair,
        world_writes=world_writes,
    )
