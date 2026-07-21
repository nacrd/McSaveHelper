"""多文件世界修改的备份、暂存、验证与原子发布事务。"""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, Optional, TypeVar

from app.services.backup_service import BackupRecord, BackupService
from app.services.world_write_coordinator import WorldWriteCoordinator
from core.utils import publish_directory_tree


ResultT = TypeVar("ResultT")
WorldMutation = Callable[[Path], ResultT]
WorldValidator = Callable[[Path], None]
CancelCheck = Callable[[], bool]


class WorldTransactionError(RuntimeError):
    """世界事务无法安全完成时抛出。"""


class WorldTransactionCancelledError(WorldTransactionError):
    """事务在发布前安全检查点观察到取消请求时抛出。"""


class WorldTransactionMutationError(WorldTransactionError):
    """业务变更明确拒绝发布时抛出，保留调用方的结构化结果。"""


@dataclass(frozen=True)
class WorldTransactionResult(Generic[ResultT]):
    """成功发布后的业务结果和安全备份信息。"""

    value: ResultT
    world_path: Path
    backup: BackupRecord


class WorldTransactionService:
    """对一个世界执行强制备份与整树暂存事务。"""

    def __init__(
        self,
        coordinator: WorldWriteCoordinator,
        backup_service: BackupService,
        invalidate_world: Optional[Callable[[Path], None]] = None,
    ) -> None:
        """注入共享租约、备份能力和发布后索引失效端口。"""
        self._coordinator = coordinator
        self._backup_service = backup_service
        self._invalidate_world = invalidate_world or (lambda world: None)

    def mutate(
        self,
        world_path: Path | str,
        mutation: WorldMutation[ResultT],
        *,
        backup_label: str,
        cancel_check: Optional[CancelCheck] = None,
        validator: Optional[WorldValidator] = None,
    ) -> WorldTransactionResult[ResultT]:
        """在同盘暂存副本上修改，验证后原子替换原世界。

        Args:
            world_path: 要修改的有效世界目录。
            mutation: 只允许修改传入暂存世界的业务函数。
            backup_label: 发布前强制安全备份的标签。
            cancel_check: 可选协作取消检查。
            validator: 可选业务验证器；基础世界验证始终执行。

        Returns:
            业务结果、世界路径和安全备份记录。

        Raises:
            WorldTransactionCancelledError: 在安全检查点取消。
            WorldTransactionError: 路径、复制、验证或发布失败。
        """
        world = self._validate_world(world_path)
        with self._coordinator.reserve(world):
            self._raise_if_cancelled(cancel_check)
            self._reject_linked_tree(world)
            try:
                backup = self._backup_service.create_backup(
                    world,
                    label=backup_label,
                )
            except Exception as exc:
                raise WorldTransactionError(
                    f"安全备份失败，已中止写入: {world}: {exc}"
                ) from exc
            self._raise_if_cancelled(cancel_check)
            return self._mutate_staged(
                world,
                mutation,
                backup,
                cancel_check,
                validator,
            )

    def publish_prepared(
        self,
        prepared_world: Path | str,
        destination: Path | str,
        *,
        backup_label: str,
        cancel_check: Optional[CancelCheck] = None,
        validator: Optional[WorldValidator] = None,
    ) -> Optional[BackupRecord]:
        """验证并原子发布外部暂存世界，覆盖前强制备份。

        Args:
            prepared_world: 已完整生成、与目标同一文件系统的暂存世界。
            destination: 目标世界目录，可尚不存在。
            backup_label: 覆盖既有世界前的备份标签。
            cancel_check: 发布前取消检查。
            validator: 可选业务验证器。

        Returns:
            覆盖既有世界时的备份记录；新建目标时为 None。
        """
        prepared = Path(prepared_world).expanduser().resolve()
        target = Path(destination).expanduser().absolute()
        self._validate_prepared_world(prepared)
        if validator is not None:
            validator(prepared)
        with self._coordinator.reserve(target):
            self._raise_if_cancelled(cancel_check)
            backup = self._backup_destination_if_present(
                target,
                backup_label,
            )
            self._raise_if_cancelled(cancel_check)
            try:
                publish_directory_tree(prepared, target)
            except (OSError, ValueError, TypeError, RuntimeError) as exc:
                raise WorldTransactionError(
                    f"发布世界失败，原目标保持不变: {target}: {exc}"
                ) from exc
            self._invalidate_world(target.resolve())
            return backup

    def _backup_destination_if_present(
        self,
        destination: Path,
        label: str,
    ) -> Optional[BackupRecord]:
        """目标是既有世界时创建强制备份，否则校验为空目录。"""
        if not destination.exists():
            return None
        if not destination.is_dir():
            raise WorldTransactionError(f"目标路径不是目录: {destination}")
        if not any(destination.iterdir()):
            return None
        if not (destination / "level.dat").is_file():
            raise WorldTransactionError(
                f"目标目录不是 Minecraft 存档，拒绝覆盖: {destination}"
            )
        return self._backup_service.create_backup(destination, label=label)

    def _mutate_staged(
        self,
        world: Path,
        mutation: WorldMutation[ResultT],
        backup: BackupRecord,
        cancel_check: Optional[CancelCheck],
        validator: Optional[WorldValidator],
    ) -> WorldTransactionResult[ResultT]:
        """管理暂存目录生命周期并在成功后失效读模型。"""
        staging_root = Path(tempfile.mkdtemp(
            prefix=f".{world.name}.transaction-",
            dir=world.parent,
        ))
        prepared = staging_root / world.name
        try:
            self._copy_world(world, prepared)
            self._raise_if_cancelled(cancel_check)
            value = mutation(prepared)
            self._raise_if_cancelled(cancel_check)
            self._validate_prepared_world(prepared)
            if validator is not None:
                validator(prepared)
            self._raise_if_cancelled(cancel_check)
            publish_directory_tree(prepared, world)
            self._invalidate_world(world)
            return WorldTransactionResult(value, world, backup)
        except (
            WorldTransactionCancelledError,
            WorldTransactionMutationError,
        ):
            raise
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            raise WorldTransactionError(
                f"世界事务失败，原存档保持不变: {world}: {exc}"
            ) from exc
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

    @staticmethod
    def _copy_world(world: Path, prepared: Path) -> None:
        """复制世界但排除运行锁和应用自己的备份仓库。"""
        ignored = {"session.lock", ".mcsavehelper_backups"}

        def ignore(directory: str, names: list[str]) -> set[str]:
            del directory
            return ignored.intersection(names)

        shutil.copytree(world, prepared, ignore=ignore)

    @staticmethod
    def _validate_prepared_world(prepared: Path) -> None:
        """验证暂存世界根、level.dat 和路径安全。"""
        if not prepared.is_dir() or not (prepared / "level.dat").is_file():
            raise WorldTransactionError(
                f"暂存世界无效或缺少 level.dat: {prepared}"
            )
        WorldTransactionService._reject_linked_tree(prepared)

    @staticmethod
    def _validate_world(world_path: Path | str) -> Path:
        """规范化并验证世界路径。"""
        world = Path(world_path).expanduser().resolve()
        if not world.is_dir() or not (world / "level.dat").is_file():
            raise WorldTransactionError(f"不是有效 Minecraft 存档: {world}")
        return world

    @staticmethod
    def _reject_linked_tree(root: Path) -> None:
        """拒绝世界树中的符号链接和 Windows junction。"""
        for directory, directory_names, file_names in os.walk(root):
            base = Path(directory)
            for name in [*directory_names, *file_names]:
                path = base / name
                is_junction = getattr(path, "is_junction", lambda: False)
                if path.is_symlink() or bool(is_junction()):
                    raise WorldTransactionError(
                        f"世界内容不能包含符号链接或 junction: {path}"
                    )

    @staticmethod
    def _raise_if_cancelled(cancel_check: Optional[CancelCheck]) -> None:
        """在安全检查点将取消转换为结构化事务异常。"""
        if cancel_check is not None and cancel_check():
            raise WorldTransactionCancelledError("世界事务已取消，未发布任何修改")


__all__ = [
    "WorldTransactionCancelledError",
    "WorldTransactionError",
    "WorldTransactionMutationError",
    "WorldTransactionResult",
    "WorldTransactionService",
]
