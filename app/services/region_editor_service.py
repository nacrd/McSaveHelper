"""Compatibility facade for the region editor now owned by ``core.mca``.

Destructive region edits used by the app must go through
``WorldTransactionService`` so backup, staging, publish, and index
invalidation stay on the shared write path.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.services.world_transaction import (
    WorldTransactionError,
    WorldTransactionResult,
    WorldTransactionService,
)
from core.mca.editor import ChunkInfo, RegionEditor, RegionInfo
from core.types import LogCallback

RegionEditorService = RegionEditor


def get_region_editor_service(
    log: Optional[LogCallback] = None,
) -> RegionEditorService:
    """Return an editor scoped to the caller instead of shared global state."""
    return RegionEditorService(log=log)


def delete_region_via_transaction(
    world_transactions: WorldTransactionService,
    world_path: Path | str,
    region_path: Path | str,
    *,
    backup_label: str = "删除区域前自动备份",
    log: Optional[LogCallback] = None,
) -> WorldTransactionResult[bool]:
    """Delete one region file inside a full world transaction.

    The mutation runs on a staged copy with ``backup=False`` for the
    single-file ``.bak`` side channel; the verified world backup is
    created by the transaction port itself.

    Args:
        world_transactions: Shared application world transaction port.
        world_path: Valid world root containing ``level.dat``.
        region_path: Absolute or relative region file under the world.
        backup_label: Label for the forced pre-publish backup.
        log: Optional editor log callback.

    Returns:
        Transaction result whose value is whether the staged delete ran.

    Raises:
        WorldTransactionError: Path escape, transaction failure, or missing
            region after staging.
    """
    world = Path(world_path).expanduser().resolve()
    region = Path(region_path).expanduser().resolve()
    try:
        relative = region.relative_to(world)
    except ValueError as exc:
        raise WorldTransactionError(
            f"区域文件不在目标世界内，拒绝写入: {region} (world={world})"
        ) from exc

    def mutation(prepared: Path) -> bool:
        staged = (prepared / relative).resolve()
        try:
            staged.relative_to(prepared.resolve())
        except ValueError as exc:
            raise WorldTransactionError(
                f"暂存区域路径越界: {staged}"
            ) from exc
        if not staged.is_file():
            raise WorldTransactionError(
                f"暂存世界中缺少区域文件: {relative.as_posix()}"
            )
        editor = get_region_editor_service(log=log)
        # World-level verified backup already performed by the transaction.
        return editor.reset_region(staged, backup=False)

    return world_transactions.mutate(
        world,
        mutation,
        backup_label=backup_label,
    )


__all__ = [
    "ChunkInfo",
    "RegionEditorService",
    "RegionInfo",
    "delete_region_via_transaction",
    "get_region_editor_service",
]
