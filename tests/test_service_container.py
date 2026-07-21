from types import SimpleNamespace
from typing import cast

import pytest

from app.bootstrap.services import (
    ServiceFactories,
    ServiceInitializationError,
    create_app_services,
)
from app.services.config_service import ConfigService
from app.services.backup_service import BackupService
from app.services.cache_registry import CacheRegistry
from app.services.execution_runtime import ExecutionRuntime
from app.services.save_repair_service import SaveRepairService
from app.services.i18n_service import I18nService
from app.services.item_service import ItemService
from app.services.migration_service import MigrationService
from app.services.texture_service import TextureService
from app.services.uuid_service import UUIDService
from app.services.world_write_coordinator import WorldWriteCoordinator
from app.services.world_index_service import WorldIndexRegistry
from app.services.world_transaction import WorldTransactionService


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
    execution_runtime = cast(ExecutionRuntime, object())
    cache_registry = cast(CacheRegistry, object())
    world_indexes = cast(
        WorldIndexRegistry,
        SimpleNamespace(invalidate=lambda world: None),
    )
    world_transactions = cast(WorldTransactionService, object())

    def create_config():
        events.append("config")
        return config

    def create_i18n(received_config):
        events.append(("i18n", received_config))
        return i18n

    def create_migration(
        received_config,
        received_backup,
        received_transactions,
    ):
        events.append((
            "migration",
            received_config,
            received_backup,
            received_transactions,
        ))
        return migration

    def create_uuid():
        events.append("uuid")
        return uuid

    def create_item():
        events.append("item")
        return item

    def create_texture(received_runtime, received_cache_registry):
        events.append((
            "texture",
            received_runtime,
            received_cache_registry,
        ))
        return texture

    def create_world_writes():
        events.append("world_writes")
        return world_writes

    def create_execution_runtime():
        events.append("execution_runtime")
        return execution_runtime

    def create_cache_registry():
        events.append("cache_registry")
        return cache_registry

    def create_world_indexes():
        events.append("world_indexes")
        return world_indexes

    def create_world_transactions(
        received_world_writes,
        received_backup,
        invalidate_world,
    ):
        del invalidate_world
        events.append((
            "world_transactions",
            received_world_writes,
            received_backup,
        ))
        return world_transactions

    def create_backup(received_world_writes):
        events.append(("backup", received_world_writes))
        return backup

    def create_save_repair(received_backup, received_transactions):
        events.append((
            "save_repair",
            received_backup,
            received_transactions,
        ))
        return save_repair

    services = create_app_services(
        ServiceFactories(
            config=create_config,
            i18n=create_i18n,
            migration=create_migration,
            uuid=create_uuid,
            item=create_item,
            texture=create_texture,
            cache_registry=create_cache_registry,
            execution_runtime=create_execution_runtime,
            world_indexes=create_world_indexes,
            world_transactions=create_world_transactions,
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
    assert services.execution_runtime is execution_runtime
    assert services.cache_registry is cache_registry
    assert services.world_indexes is world_indexes
    assert services.world_transactions is world_transactions
    assert events == [
        "config",
        ("i18n", config),
        "world_writes",
        ("backup", world_writes),
        "execution_runtime",
        "cache_registry",
        "world_indexes",
        ("world_transactions", world_writes, backup),
        ("migration", config, backup, world_transactions),
        "uuid",
        "item",
        ("texture", execution_runtime, cache_registry),
        ("save_repair", backup, world_transactions),
    ]


def test_service_container_reports_failed_service_and_stops() -> None:
    uuid_created = False

    def fail_migration(
        config: ConfigService,
        backup: BackupService,
        transactions: WorldTransactionService,
    ) -> MigrationService:
        del config, backup, transactions
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
