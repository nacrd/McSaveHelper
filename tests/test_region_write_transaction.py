"""Region destructive edits must use the shared world transaction port."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.backup_service import BackupService
from app.services.region_editor_service import delete_region_via_transaction
from app.services.world_transaction import (
    WorldTransactionCancelledError,
    WorldTransactionError,
    WorldTransactionService,
)
from app.services.world_write_coordinator import WorldWriteCoordinator


def _world_with_region(tmp_path: Path) -> tuple[Path, Path]:
    world = tmp_path / "world"
    region_dir = world / "region"
    region_dir.mkdir(parents=True)
    (world / "level.dat").write_bytes(b"level")
    region = region_dir / "r.0.0.mca"
    region.write_bytes(b"\x00" * 8192)
    (world / "keep.txt").write_text("keep", encoding="utf-8")
    return world, region


def _transactions(tmp_path: Path, invalidated: list[Path]) -> WorldTransactionService:
    coordinator = WorldWriteCoordinator()
    backup = BackupService(coordinator)
    return WorldTransactionService(
        coordinator,
        backup,
        invalidate_world=invalidated.append,
    )


def test_delete_region_via_transaction_backs_up_and_removes_file(
    tmp_path: Path,
) -> None:
    world, region = _world_with_region(tmp_path)
    invalidated: list[Path] = []
    service = _transactions(tmp_path, invalidated)

    result = delete_region_via_transaction(
        service,
        world,
        region,
        backup_label="区域删除测试",
    )

    assert result.value is True
    assert not region.exists()
    assert (world / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert result.backup.backup_path.is_dir()
    backed_region = (
        result.backup.backup_path / "world" / "region" / "r.0.0.mca"
    )
    assert backed_region.is_file()
    assert invalidated == [world.resolve()]


def test_delete_region_outside_world_is_rejected(tmp_path: Path) -> None:
    world, _region = _world_with_region(tmp_path)
    outside = tmp_path / "outside.mca"
    outside.write_bytes(b"\x00" * 16)
    service = _transactions(tmp_path, [])

    with pytest.raises(WorldTransactionError, match="不在目标世界内"):
        delete_region_via_transaction(service, world, outside)

    assert outside.exists()
    assert (world / "region" / "r.0.0.mca").exists()


def test_delete_region_cancel_preserves_original(tmp_path: Path) -> None:
    world, region = _world_with_region(tmp_path)
    coordinator = WorldWriteCoordinator()
    backup = BackupService(coordinator)
    service = WorldTransactionService(coordinator, backup)

    with pytest.raises(WorldTransactionCancelledError):
        service.mutate(
            world,
            lambda prepared: prepared,
            backup_label="cancel",
            cancel_check=lambda: True,
        )

    assert region.exists()
