from types import SimpleNamespace
from typing import cast

import pytest

from app.bootstrap.services import (
    ServiceFactories,
    ServiceInitializationError,
    _close_partial_services,
    _default_cache_registry,
    create_app_services,
)
from app.services.backup_service import BackupService
from app.services.cache_registry import CacheRegistry
from app.services.config_service import ConfigService
from app.services.execution_runtime import ExecutionRuntime
from app.services.i18n_service import I18nService
from app.services.item_service import ItemService
from app.services.migration_service import MigrationService
from app.services.operation_metrics import OperationMetricsStore
from app.services.save_repair_service import SaveRepairService
from app.services.texture_service import TextureService
from app.services.uuid_service import UUIDService
from app.services.world_index_service import WorldIndexRegistry
from app.services.world_repository import WorldRepository
from app.services.world_transaction import WorldTransactionService
from app.services.world_write_coordinator import WorldWriteCoordinator
from core.mca.surface import CHUNK_DECODE_CACHE_MAX_BYTES
from core.parallel import ParallelRunner


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
    parallel_runner = cast(ParallelRunner, object())
    operation_metrics = cast(OperationMetricsStore, object())
    cache_invalidator_calls = []

    def invalidate_world_caches(world):
        cache_invalidator_calls.append(world)

    cache_registry = cast(
        CacheRegistry,
        SimpleNamespace(invalidate_world=invalidate_world_caches),
    )
    world_indexes = cast(
        WorldIndexRegistry,
        SimpleNamespace(invalidate=lambda world: None),
    )
    world_transactions = cast(WorldTransactionService, object())
    world_repository = cast(WorldRepository, object())

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
        received_parallel_runner,
    ):
        events.append((
            "migration",
            received_config,
            received_backup,
            received_transactions,
            received_parallel_runner,
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

    def create_operation_metrics():
        events.append("operation_metrics")
        return operation_metrics

    def create_execution_runtime(received_operation_metrics):
        events.append(("execution_runtime", received_operation_metrics))
        return execution_runtime

    def create_parallel_runner(received_runtime):
        events.append(("parallel_runner", received_runtime))
        return parallel_runner

    def create_cache_registry():
        events.append("cache_registry")
        return cache_registry

    def create_world_indexes(cache_registry):
        events.append("world_indexes")
        assert cache_registry is not None
        return world_indexes

    def create_world_transactions(
        received_world_writes,
        received_backup,
        invalidate_world,
    ):
        invalidate_world("world")
        events.append((
            "world_transactions",
            received_world_writes,
            received_backup,
        ))
        return world_transactions

    def create_world_repository(
        received_indexes,
        received_world_writes,
        received_backup,
        received_transactions,
    ):
        del received_world_writes, received_backup, received_transactions
        events.append(("world_repository", received_indexes))
        return world_repository

    def create_backup(received_world_writes):
        events.append(("backup", received_world_writes))
        return backup

    def create_save_repair(
        received_backup,
        received_transactions,
        received_runtime,
    ):
        events.append((
            "save_repair",
            received_backup,
            received_transactions,
            received_runtime,
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
            operation_metrics=create_operation_metrics,
            execution_runtime=create_execution_runtime,
            parallel_runner=create_parallel_runner,
            world_indexes=create_world_indexes,
            world_repository=create_world_repository,
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
    assert services.parallel_runner is parallel_runner
    assert services.operation_metrics is operation_metrics
    assert services.cache_registry is cache_registry
    assert services.world_indexes is world_indexes
    assert services.world_repository is world_repository
    assert services.world_transactions is world_transactions
    assert cache_invalidator_calls == ["world"]
    assert events == [
        "config",
        ("i18n", config),
        "world_writes",
        ("backup", world_writes),
        "operation_metrics",
        ("execution_runtime", operation_metrics),
        ("parallel_runner", execution_runtime),
        "cache_registry",
        "world_indexes",
        ("world_transactions", world_writes, backup),
        ("world_repository", world_indexes),
        (
            "migration",
            config,
            backup,
            world_transactions,
            parallel_runner,
        ),
        "uuid",
        "item",
        ("texture", execution_runtime, cache_registry),
        ("save_repair", backup, world_transactions, execution_runtime),
    ]


def test_service_container_reports_failed_service_and_stops() -> None:
    uuid_created = False

    def fail_migration(
        config: ConfigService,
        backup: BackupService,
        transactions: WorldTransactionService,
        parallel_runner: ParallelRunner,
    ) -> MigrationService:
        del config, backup, transactions, parallel_runner
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


def test_partial_service_cleanup_drains_runtime_before_dependencies() -> None:
    events: list[object] = []

    def shutdown_runtime(*, wait: bool, timeout: float) -> bool:
        events.append(("runtime", wait, timeout))
        return True

    runtime = cast(
        ExecutionRuntime,
        SimpleNamespace(shutdown=shutdown_runtime),
    )
    texture = cast(
        TextureService,
        SimpleNamespace(close=lambda: events.append("texture")),
    )
    world_indexes = cast(
        WorldIndexRegistry,
        SimpleNamespace(close=lambda: events.append("world_indexes")),
    )
    cache_registry = cast(
        CacheRegistry,
        SimpleNamespace(close=lambda: events.append("cache_registry")),
    )

    _close_partial_services(
        runtime,
        texture,
        world_indexes,
        cache_registry,
    )

    assert events == [
        ("runtime", True, 5.0),
        "texture",
        "world_indexes",
        "cache_registry",
    ]


def test_partial_service_cleanup_keeps_dependencies_after_runtime_timeout() -> None:
    events: list[str] = []
    runtime = cast(
        ExecutionRuntime,
        SimpleNamespace(
            shutdown=lambda **_kwargs: events.append("runtime") or False,
        ),
    )
    texture = cast(
        TextureService,
        SimpleNamespace(close=lambda: events.append("texture")),
    )
    world_indexes = cast(
        WorldIndexRegistry,
        SimpleNamespace(close=lambda: events.append("world_indexes")),
    )
    cache_registry = cast(
        CacheRegistry,
        SimpleNamespace(close=lambda: events.append("cache_registry")),
    )

    _close_partial_services(
        runtime,
        texture,
        world_indexes,
        cache_registry,
    )

    assert events == ["runtime"]


def test_default_cache_registry_owns_process_mca_cache() -> None:
    registry = _default_cache_registry()
    try:
        mca_stats = next(
            region
            for region in registry.stats().regions
            if region.name == "mca.chunk"
        )
        assert mca_stats.max_bytes == CHUNK_DECODE_CACHE_MAX_BYTES
    finally:
        registry.close()
