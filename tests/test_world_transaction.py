"""世界整树事务安全测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.backup_service import BackupService
from app.services.world_transaction import (
    WorldTransactionCancelledError,
    WorldTransactionError,
    WorldTransactionService,
)
from app.services.world_write_coordinator import WorldWriteCoordinator


def _world(tmp_path: Path) -> Path:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"level-old")
    (world / "marker.txt").write_text("old", encoding="utf-8")
    return world


def _service(tmp_path: Path, invalidated: list[Path]) -> WorldTransactionService:
    coordinator = WorldWriteCoordinator()
    backup = BackupService(coordinator)
    return WorldTransactionService(
        coordinator,
        backup,
        invalidate_world=invalidated.append,
    )


def test_successful_transaction_backs_up_and_atomically_publishes(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    invalidated: list[Path] = []
    service = _service(tmp_path, invalidated)

    result = service.mutate(
        world,
        lambda prepared: (prepared / "marker.txt").write_text(
            "new",
            encoding="utf-8",
        ),
        backup_label="测试事务",
    )

    assert result.world_path == world.resolve()
    assert result.backup.backup_path.is_dir()
    assert (world / "marker.txt").read_text(encoding="utf-8") == "new"
    assert invalidated == [world.resolve()]
    assert not list(tmp_path.glob(".world.transaction-*"))


def test_mutation_failure_preserves_original_world(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = _service(tmp_path, [])

    def fail(prepared: Path) -> None:
        (prepared / "marker.txt").write_text("partial", encoding="utf-8")
        raise RuntimeError("repair failed")

    with pytest.raises(WorldTransactionError, match="原存档保持不变"):
        service.mutate(world, fail, backup_label="测试失败")

    assert (world / "marker.txt").read_text(encoding="utf-8") == "old"


def test_validation_failure_preserves_original_world(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = _service(tmp_path, [])

    with pytest.raises(WorldTransactionError, match="原存档保持不变"):
        service.mutate(
            world,
            lambda prepared: (prepared / "level.dat").unlink(),
            backup_label="测试验证",
        )

    assert (world / "level.dat").read_bytes() == b"level-old"


def test_cancel_before_mutation_never_publishes(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = _service(tmp_path, [])
    calls: list[Path] = []

    with pytest.raises(WorldTransactionCancelledError):
        service.mutate(
            world,
            calls.append,
            backup_label="测试取消",
            cancel_check=lambda: True,
        )

    assert calls == []
    assert (world / "marker.txt").read_text(encoding="utf-8") == "old"


def test_link_inside_world_is_rejected(tmp_path: Path) -> None:
    world = _world(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = world / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    service = _service(tmp_path, [])
    with pytest.raises(WorldTransactionError, match="符号链接"):
        service.mutate(world, lambda prepared: None, backup_label="测试链接")

    assert outside.read_text(encoding="utf-8") == "outside"
