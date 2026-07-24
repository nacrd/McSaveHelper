"""Explicit construction of application services."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from app.services.backup_service import BackupService
from app.services.cache_registry import CacheRegistry
from app.services.config_service import ConfigService
from app.services.execution_runtime import ExecutionRuntime
from app.services.i18n_service import I18nService
from app.services.item_service import ItemService
from app.services.mca_cache_adapter import register_mca_chunk_cache
from app.services.migration_service import MigrationService
from app.services.operation_metrics import OperationMetricsStore
from app.services.parallel_runner import create_runtime_parallel_runner
from app.services.save_repair_service import SaveRepairService
from app.services.texture_service import TextureService
from app.services.uuid_service import UUIDService
from app.services.world_compare_service import WorldCompareService
from app.services.world_index_service import WorldIndexRegistry
from app.services.world_repository import WorldRepository, WorldSessionPorts
from app.services.world_stats_service import WorldStatsService
from app.services.world_transaction import WorldTransactionService
from app.services.world_write_coordinator import WorldWriteCoordinator
from core.logger import logger
from core.parallel import ParallelRunner


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
    execution_runtime: ExecutionRuntime
    world_indexes: WorldIndexRegistry
    world_repository: WorldRepository
    world_stats: WorldStatsService
    world_compare: WorldCompareService
    world_transactions: WorldTransactionService
    cache_registry: CacheRegistry
    operation_metrics: OperationMetricsStore
    parallel_runner: ParallelRunner


def _default_world_indexes(cache_registry: CacheRegistry) -> WorldIndexRegistry:
    """默认工厂：把世界索引接入应用缓存预算。"""
    return WorldIndexRegistry(cache_registry=cache_registry)


def _default_cache_registry() -> CacheRegistry:
    """创建缓存预算并登记唯一的进程级 MCA 解码缓存。"""
    registry = CacheRegistry()
    register_mca_chunk_cache(registry)
    return registry


def _default_execution_runtime(
    operation_metrics: OperationMetricsStore,
) -> ExecutionRuntime:
    """创建向应用级指标仓库发布终态的统一运行时。"""
    return ExecutionRuntime(operation_sink=operation_metrics.record)


def _default_world_repository(
    indexes: WorldIndexRegistry,
    world_writes: WorldWriteCoordinator,
    backup: BackupService,
    world_transactions: WorldTransactionService,
) -> WorldRepository:
    """把共享写安全端口一次性装配到世界仓库。"""

    def backup_callback(world: Path) -> Path:
        return backup.create_backup(
            world,
            label="NBT 提交前自动备份",
        ).backup_path

    def transaction_callback(
        world: Path,
        mutation: Callable[[Path], Any],
        cancel_check: Optional[Callable[[], bool]],
    ) -> Any:
        return world_transactions.mutate(
            world,
            mutation,
            backup_label="NBT 提交前自动备份",
            cancel_check=cancel_check,
        )

    return WorldRepository(
        indexes,
        default_ports=WorldSessionPorts(
            write_lease_factory=world_writes.reserve,
            backup_callback=backup_callback,
            transaction_callback=transaction_callback,
        ),
    )


def _default_world_compare(world_repository: WorldRepository) -> WorldCompareService:
    """Bind comparison reads to the application-owned world index."""
    return WorldCompareService(index_provider=world_repository.get_index)


@dataclass(frozen=True)
class ServiceFactories:
    """可替换的服务工厂表，便于测试注入替身。"""

    config: Callable[[], ConfigService] = ConfigService
    i18n: Callable[[ConfigService], I18nService] = I18nService
    migration: Callable[
        [ConfigService, BackupService, WorldTransactionService, ParallelRunner],
        MigrationService,
    ] = MigrationService
    uuid: Callable[[], UUIDService] = UUIDService
    item: Callable[[], ItemService] = ItemService
    texture: Callable[
        [ExecutionRuntime, CacheRegistry], TextureService
    ] = TextureService
    cache_registry: Callable[[], CacheRegistry] = _default_cache_registry
    operation_metrics: Callable[[], OperationMetricsStore] = (
        OperationMetricsStore
    )
    execution_runtime: Callable[
        [OperationMetricsStore], ExecutionRuntime
    ] = _default_execution_runtime
    parallel_runner: Callable[[ExecutionRuntime], ParallelRunner] = (
        create_runtime_parallel_runner
    )
    world_indexes: Callable[[CacheRegistry], WorldIndexRegistry] = (
        _default_world_indexes
    )
    world_repository: Callable[
        [WorldIndexRegistry, WorldWriteCoordinator, BackupService, WorldTransactionService],
        WorldRepository,
    ] = _default_world_repository
    world_stats: Callable[[], WorldStatsService] = WorldStatsService
    world_compare: Callable[[WorldRepository], WorldCompareService] = (
        _default_world_compare
    )
    world_transactions: Callable[
        [WorldWriteCoordinator, BackupService, Callable[[Path], None]],
        WorldTransactionService,
    ] = WorldTransactionService
    world_writes: Callable[[], WorldWriteCoordinator] = WorldWriteCoordinator
    backup: Callable[[WorldWriteCoordinator], BackupService] = BackupService
    save_repair: Callable[
        [BackupService, WorldTransactionService, ExecutionRuntime],
        SaveRepairService,
    ] = SaveRepairService


def _create(service_name: str, factory: Callable[..., Any], *args: Any) -> Any:
    try:
        return factory(*args)
    except Exception as exc:
        raise ServiceInitializationError(service_name, exc) from exc


def _close_partial_services(
    execution_runtime: ExecutionRuntime,
    texture: Optional[TextureService],
    world_indexes: Optional[WorldIndexRegistry],
    cache_registry: Optional[CacheRegistry],
) -> None:
    """初始化失败时排空运行时，再按依赖逆序释放已创建的拥有者。

    工厂失败必须保留原始 ``ServiceInitializationError``；清理异常只记录，
    不得覆盖导致启动失败的根因。若运行时未能按期退出，则保留仍可能被任务引用的
    缓存资源直到进程结束，避免后台任务访问已关闭对象。
    """
    try:
        runtime_terminated = execution_runtime.shutdown(
            wait=True,
            timeout=5.0,
        )
    except Exception as exc:
        logger.warning(
            f"初始化回滚释放 execution_runtime 失败: {exc}",
            module="ServiceBootstrap",
        )
        return
    if not runtime_terminated:
        logger.warning(
            "初始化回滚等待后台任务超时，保留其依赖资源直到进程结束",
            module="ServiceBootstrap",
        )
        return

    cleanups: list[tuple[str, Callable[[], object]]] = []
    if texture is not None:
        cleanups.append(("texture", texture.close))
    if world_indexes is not None:
        cleanups.append(("world_indexes", world_indexes.close))
    if cache_registry is not None:
        cleanups.append(("cache_registry", cache_registry.close))
    for service_name, cleanup in cleanups:
        try:
            cleanup()
        except Exception as exc:
            logger.warning(
                f"初始化回滚释放 {service_name} 失败: {exc}",
                module="ServiceBootstrap",
            )


def create_app_services(
    factories: Optional[ServiceFactories] = None,
) -> AppServices:
    """Build services in dependency order or fail with an actionable error."""
    selected = factories or ServiceFactories()
    config = _create("config", selected.config)
    i18n = _create("i18n", selected.i18n, config)
    world_writes = _create("world_writes", selected.world_writes)
    backup = _create("backup", selected.backup, world_writes)
    operation_metrics = _create(
        "operation_metrics",
        selected.operation_metrics,
    )
    execution_runtime = _create(
        "execution_runtime",
        selected.execution_runtime,
        operation_metrics,
    )
    cache_registry: Optional[CacheRegistry] = None
    world_indexes: Optional[WorldIndexRegistry] = None
    texture: Optional[TextureService] = None
    try:
        parallel_runner = _create(
            "parallel_runner",
            selected.parallel_runner,
            execution_runtime,
        )
        active_cache_registry: CacheRegistry = _create(
            "cache_registry",
            selected.cache_registry,
        )
        cache_registry = active_cache_registry
        active_world_indexes: WorldIndexRegistry = _create(
            "world_indexes",
            selected.world_indexes,
            active_cache_registry,
        )
        world_indexes = active_world_indexes

        def invalidate_world_caches(world: Path) -> None:
            active_cache_registry.invalidate_world(world)

        world_transactions = _create(
            "world_transactions",
            selected.world_transactions,
            world_writes,
            backup,
            invalidate_world_caches,
        )
        world_repository = _create(
            "world_repository",
            selected.world_repository,
            active_world_indexes,
            world_writes,
            backup,
            world_transactions,
        )
        world_stats = _create("world_stats", selected.world_stats)
        world_compare = _create(
            "world_compare",
            selected.world_compare,
            world_repository,
        )
        migration = _create(
            "migration",
            selected.migration,
            config,
            backup,
            world_transactions,
            parallel_runner,
        )
        uuid = _create("uuid", selected.uuid)
        item = _create("item", selected.item)
        active_texture: TextureService = _create(
            "texture",
            selected.texture,
            execution_runtime,
            active_cache_registry,
        )
        texture = active_texture
        save_repair = _create(
            "save_repair",
            selected.save_repair,
            backup,
            world_transactions,
            execution_runtime,
        )
        return AppServices(
            config=config,
            i18n=i18n,
            migration=migration,
            uuid=uuid,
            item=item,
            texture=active_texture,
            backup=backup,
            save_repair=save_repair,
            world_writes=world_writes,
            execution_runtime=execution_runtime,
            world_indexes=active_world_indexes,
            world_repository=world_repository,
            world_stats=world_stats,
            world_compare=world_compare,
            world_transactions=world_transactions,
            cache_registry=active_cache_registry,
            operation_metrics=operation_metrics,
            parallel_runner=parallel_runner,
        )
    except Exception:
        _close_partial_services(
            execution_runtime,
            texture,
            world_indexes,
            cache_registry,
        )
        raise
