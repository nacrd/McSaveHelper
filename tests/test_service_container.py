from typing import cast

import pytest

from app.bootstrap.services import (
    ServiceFactories,
    ServiceInitializationError,
    create_app_services,
)
from app.services.config_service import ConfigService
from app.services.backup_service import BackupService
from app.services.save_repair_service import SaveRepairService
from app.services.i18n_service import I18nService
from app.services.item_service import ItemService
from app.services.migration_service import MigrationService
from app.services.texture_service import TextureService
from app.services.uuid_service import UUIDService
from app.services.world_write_coordinator import WorldWriteCoordinator


def test_service_container_builds_in_dependency_order() -> None:
    events = []
    config = cast(ConfigService, object())
    i18n = cast(I18nService, object())
    migration = cast(MigrationService, object())
    uuid = cast(UUIDService, object())
    item = cast(ItemService, object())
    texture = cast(TextureService, object())
    backup = cast(BackupService, object())
    save_repair = cast(SaveRepairService, object())
    world_writes = cast(WorldWriteCoordinator, object())

    def create_config():
        events.append("config")
        return config

    def create_i18n(received_config):
        events.append(("i18n", received_config))
        return i18n

    def create_migration(received_config, received_backup):
        events.append(("migration", received_config, received_backup))
        return migration

    def create_uuid():
        events.append("uuid")
        return uuid

    def create_item():
        events.append("item")
        return item

    def create_texture():
        events.append("texture")
        return texture

    def create_world_writes():
        events.append("world_writes")
        return world_writes

    def create_backup(received_world_writes):
        events.append(("backup", received_world_writes))
        return backup

    def create_save_repair(received_backup):
        events.append(("save_repair", received_backup))
        return save_repair

    services = create_app_services(
        ServiceFactories(
            config=create_config,
            i18n=create_i18n,
            migration=create_migration,
            uuid=create_uuid,
            item=create_item,
            texture=create_texture,
            world_writes=create_world_writes,
            backup=create_backup,
            save_repair=create_save_repair,
        )
    )

    assert services.config is config
    assert services.i18n is i18n
    assert services.migration is migration
    assert services.uuid is uuid
    assert services.item is item
    assert services.texture is texture
    assert services.backup is backup
    assert services.save_repair is save_repair
    assert services.world_writes is world_writes
    assert events == [
        "config",
        ("i18n", config),
        "world_writes",
        ("backup", world_writes),
        ("migration", config, backup),
        "uuid",
        "item",
        "texture",
        ("save_repair", backup),
    ]


def test_service_container_reports_failed_service_and_stops() -> None:
    uuid_created = False

    def fail_migration(
        config: ConfigService,
        backup: BackupService,
    ) -> MigrationService:
        del config, backup
        raise OSError("migration unavailable")

    def create_uuid() -> UUIDService:
        nonlocal uuid_created
        uuid_created = True
        return cast(UUIDService, object())

    def create_config() -> ConfigService:
        return cast(ConfigService, object())

    def create_i18n(config: ConfigService) -> I18nService:
        del config
        return cast(I18nService, object())

    factories = ServiceFactories(
        config=create_config,
        i18n=create_i18n,
        migration=fail_migration,
        uuid=create_uuid,
    )

    with pytest.raises(ServiceInitializationError) as captured:
        create_app_services(factories)

    assert captured.value.service_name == "migration"
    assert isinstance(captured.value.__cause__, OSError)
    assert "migration unavailable" in str(captured.value)
    assert uuid_created is False
