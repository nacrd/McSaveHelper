from pathlib import Path
from types import SimpleNamespace
from typing import Callable, cast

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
from app.services.world_compare_service import WorldCompareService
from app.services.world_repository import WorldRepository
from app.services.world_stats_service import WorldStatsService
from app.services.world_transaction import WorldTransactionService
from app.services.world_write_coordinator import WorldWriteCoordinator
from core.mca.surface import CHUNK_DECODE_CACHE_MAX_BYTES
from core.parallel import ParallelRunner


class _ServiceFactoryProbe:
    """Typed service factories that record construction order."""

    def __init__(self) -> None:
        self.events: list[object] = []
        self.invalidated_worlds: list[Path] = []
        self.config = cast(ConfigService, object())
        self.i18n = cast(I18nService, object())
        self.migration = cast(MigrationService, object())
        self.uuid = cast(UUIDService, object())
        self.item = cast(ItemService, object())
        self.texture = cast(TextureService, object())
        self.backup = cast(BackupService, object())
        self.save_repair = cast(SaveRepairService, object())
        self.world_writes = cast(WorldWriteCoordinator, object())
        self.execution_runtime = cast(ExecutionRuntime, object())
        self.parallel_runner = cast(ParallelRunner, object())
        self.operation_metrics = cast(OperationMetricsStore, object())
        self.cache_registry = cast(
            CacheRegistry,
            SimpleNamespace(invalidate_world=self.invalidated_worlds.append),
        )
        self.world_indexes = cast(WorldIndexRegistry, object())
        self.world_transactions = cast(WorldTransactionService, object())
        self.world_repository = cast(WorldRepository, object())
        self.world_stats = cast(WorldStatsService, object())
        self.world_compare = cast(WorldCompareService, object())

    def factories(self) -> ServiceFactories:
        return ServiceFactories(
            config=self.create_config,
            i18n=self.create_i18n,
            migration=self.create_migration,
            uuid=self.create_uuid,
            item=self.create_item,
            texture=self.create_texture,
            cache_registry=self.create_cache_registry,
            operation_metrics=self.create_operation_metrics,
            execution_runtime=self.create_execution_runtime,
            parallel_runner=self.create_parallel_runner,
            world_indexes=self.create_world_indexes,
            world_repository=self.create_world_repository,
            world_stats=self.create_world_stats,
            world_compare=self.create_world_compare,
            world_transactions=self.create_world_transactions,
            world_writes=self.create_world_writes,
            backup=self.create_backup,
            save_repair=self.create_save_repair,
        )

    def create_config(self) -> ConfigService:
        self.events.append("config")
        return self.config

    def create_i18n(self, config: ConfigService) -> I18nService:
        self.events.append(("i18n", config))
        return self.i18n

    def create_world_writes(self) -> WorldWriteCoordinator:
        self.events.append("world_writes")
        return self.world_writes

    def create_backup(
        self,
        world_writes: WorldWriteCoordinator,
    ) -> BackupService:
        self.events.append(("backup", world_writes))
        return self.backup

    def create_operation_metrics(self) -> OperationMetricsStore:
        self.events.append("operation_metrics")
        return self.operation_metrics

    def create_execution_runtime(
        self,
        metrics: OperationMetricsStore,
    ) -> ExecutionRuntime:
        self.events.append(("execution_runtime", metrics))
        return self.execution_runtime

    def create_parallel_runner(
        self,
        runtime: ExecutionRuntime,
    ) -> ParallelRunner:
        self.events.append(("parallel_runner", runtime))
        return self.parallel_runner

    def create_cache_registry(self) -> CacheRegistry:
        self.events.append("cache_registry")
        return self.cache_registry

    def create_world_indexes(
        self,
        cache_registry: CacheRegistry,
    ) -> WorldIndexRegistry:
        assert cache_registry is self.cache_registry
        self.events.append("world_indexes")
        return self.world_indexes

    def create_world_transactions(
        self,
        world_writes: WorldWriteCoordinator,
        backup: BackupService,
        invalidate_world: Callable[[Path], None],
    ) -> WorldTransactionService:
        invalidate_world(Path("world"))
        self.events.append(("world_transactions", world_writes, backup))
        return self.world_transactions

    def create_world_repository(
        self,
        indexes: WorldIndexRegistry,
        world_writes: WorldWriteCoordinator,
        backup: BackupService,
        transactions: WorldTransactionService,
    ) -> WorldRepository:
        del world_writes, backup, transactions
        self.events.append(("world_repository", indexes))
        return self.world_repository

    def create_world_stats(self) -> WorldStatsService:
        self.events.append("world_stats")
        return self.world_stats

    def create_world_compare(
        self,
        repository: WorldRepository,
    ) -> WorldCompareService:
        self.events.append(("world_compare", repository))
        return self.world_compare

    def create_migration(
        self,
        config: ConfigService,
        backup: BackupService,
        transactions: WorldTransactionService,
        parallel_runner: ParallelRunner,
    ) -> MigrationService:
        self.events.append(
            ("migration", config, backup, transactions, parallel_runner)
        )
        return self.migration

    def create_uuid(self) -> UUIDService:
        self.events.append("uuid")
        return self.uuid

    def create_item(self) -> ItemService:
        self.events.append("item")
        return self.item

    def create_texture(
        self,
        runtime: ExecutionRuntime,
        cache_registry: CacheRegistry,
    ) -> TextureService:
        self.events.append(("texture", runtime, cache_registry))
        return self.texture

    def create_save_repair(
        self,
        backup: BackupService,
        transactions: WorldTransactionService,
        runtime: ExecutionRuntime,
    ) -> SaveRepairService:
        self.events.append(("save_repair", backup, transactions, runtime))
        return self.save_repair

    def expected_events(self) -> list[object]:
        return [
            "config",
            ("i18n", self.config),
            "world_writes",
            ("backup", self.world_writes),
            "operation_metrics",
            ("execution_runtime", self.operation_metrics),
            ("parallel_runner", self.execution_runtime),
            "cache_registry",
            "world_indexes",
            ("world_transactions", self.world_writes, self.backup),
            ("world_repository", self.world_indexes),
            "world_stats",
            ("world_compare", self.world_repository),
            (
                "migration",
                self.config,
                self.backup,
                self.world_transactions,
                self.parallel_runner,
            ),
            "uuid",
            "item",
            ("texture", self.execution_runtime, self.cache_registry),
            (
                "save_repair",
                self.backup,
                self.world_transactions,
                self.execution_runtime,
            ),
        ]


def test_service_container_builds_in_dependency_order() -> None:
    probe = _ServiceFactoryProbe()
    services = create_app_services(probe.factories())

    assert services.config is probe.config
    assert services.i18n is probe.i18n
    assert services.migration is probe.migration
    assert services.uuid is probe.uuid
    assert services.item is probe.item
    assert services.texture is probe.texture
    assert services.backup is probe.backup
    assert services.save_repair is probe.save_repair
    assert services.world_writes is probe.world_writes
    assert services.execution_runtime is probe.execution_runtime
    assert services.parallel_runner is probe.parallel_runner
    assert services.operation_metrics is probe.operation_metrics
    assert services.cache_registry is probe.cache_registry
    assert services.world_indexes is probe.world_indexes
    assert services.world_repository is probe.world_repository
    assert services.world_stats is probe.world_stats
    assert services.world_compare is probe.world_compare
    assert services.world_transactions is probe.world_transactions
    assert probe.invalidated_worlds == [Path("world")]
    assert probe.events == probe.expected_events()


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
