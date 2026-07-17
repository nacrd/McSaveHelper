"""Explicit construction of application services."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.services.config_service import ConfigService
from app.services.i18n_service import I18nService
from app.services.item_service import ItemService
from app.services.migration_service import MigrationService
from app.services.texture_service import TextureService
from app.services.uuid_service import UUIDService


class ServiceInitializationError(RuntimeError):
    """Raised when an essential service cannot be constructed safely."""

    def __init__(self, service_name: str, cause: Exception) -> None:
        self.service_name = service_name
        self.cause = cause
        super().__init__(f"服务初始化失败 [{service_name}]: {cause}")


@dataclass(frozen=True)
class AppServices:
    config: ConfigService
    i18n: I18nService
    migration: MigrationService
    uuid: UUIDService
    item: ItemService
    texture: TextureService


@dataclass(frozen=True)
class ServiceFactories:
    config: Callable[[], ConfigService] = ConfigService
    i18n: Callable[[ConfigService], I18nService] = I18nService
    migration: Callable[[ConfigService], MigrationService] = MigrationService
    uuid: Callable[[], UUIDService] = UUIDService
    item: Callable[[], ItemService] = ItemService
    texture: Callable[[], TextureService] = TextureService


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
    migration = _create("migration", selected.migration, config)
    uuid = _create("uuid", selected.uuid)
    item = _create("item", selected.item)
    texture = _create("texture", selected.texture)
    return AppServices(
        config=config,
        i18n=i18n,
        migration=migration,
        uuid=uuid,
        item=item,
        texture=texture,
    )
