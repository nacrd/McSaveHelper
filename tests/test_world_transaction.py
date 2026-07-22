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
    assert not list(tmp_path.glob(".world.rollback-*"))


def test_post_publish_observer_failure_keeps_committed_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = _world(tmp_path)
    coordinator = WorldWriteCoordinator()
    service = WorldTransactionService(
        coordinator,
        BackupService(coordinator),
        invalidate_world=lambda _world: (_ for _ in ()).throw(
            RuntimeError("cache unavailable")
        ),
    )
    monkeypatch.setattr(
        "app.services.world_transaction.logger.warning",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("logger unavailable")
        ),
    )

    result = service.mutate(
        world,
        lambda prepared: (prepared / "marker.txt").write_text(
            "committed",
            encoding="utf-8",
        ),
        backup_label="后置通知失败",
    )

    assert (world / "marker.txt").read_text(encoding="utf-8") == "committed"
    assert result.warnings[0].code == "post_publish_observer_failed"
    assert result.warnings[0].error_type == "RuntimeError"
    assert not list(tmp_path.glob(".world.rollback-*"))


def test_publish_prepared_does_not_create_missing_target_before_publish(
    tmp_path: Path,
) -> None:
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "level.dat").write_bytes(b"level")
    (prepared / "marker.txt").write_text("new", encoding="utf-8")
    target = tmp_path / "new-world"
    service = _service(tmp_path, [])

    backup = service.publish_prepared(
        prepared,
        target,
        backup_label="新世界发布",
    )

    assert backup is None
    assert (target / "marker.txt").read_text(encoding="utf-8") == "new"
    assert not prepared.exists()


def test_publish_prepared_allows_existing_empty_target_with_runtime_lock(
    tmp_path: Path,
) -> None:
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "level.dat").write_bytes(b"level")
    target = tmp_path / "empty-world"
    target.mkdir()
    service = _service(tmp_path, [])

    backup = service.publish_prepared(
        prepared,
        target,
        backup_label="空目录发布",
    )

    assert backup is None
    assert (target / "level.dat").read_bytes() == b"level"
    assert (target / "session.lock").is_file()
    assert not list(tmp_path.glob(".empty-world.rollback-*"))


def test_publish_prepared_observer_failure_does_not_report_commit_failure(
    tmp_path: Path,
) -> None:
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "level.dat").write_bytes(b"level")
    target = tmp_path / "new-world"
    coordinator = WorldWriteCoordinator()
    service = WorldTransactionService(
        coordinator,
        BackupService(coordinator),
        invalidate_world=lambda _world: (_ for _ in ()).throw(
            RuntimeError("observer unavailable")
        ),
    )

    backup = service.publish_prepared(
        prepared,
        target,
        backup_label="观察者失败",
    )

    assert backup is None
    assert (target / "level.dat").read_bytes() == b"level"


def test_publish_prepared_revalidates_after_backup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "level.dat").write_bytes(b"level-new")
    target = _world(tmp_path)
    service = _service(tmp_path, [])

    def invalidate_prepared(*_args, **_kwargs):
        (prepared / "level.dat").unlink()
        return None

    monkeypatch.setattr(
        service,
        "_backup_destination_if_present",
        invalidate_prepared,
    )

    with pytest.raises(WorldTransactionError, match="暂存世界无效"):
        service.publish_prepared(
            prepared,
            target,
            backup_label="二次验证",
        )

    assert (target / "marker.txt").read_text(encoding="utf-8") == "old"


def test_publish_prepared_reruns_custom_validator_after_backup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "level.dat").write_bytes(b"level-new")
    target = _world(tmp_path)
    service = _service(tmp_path, [])
    events: list[str] = []

    def record_backup(*_args, **_kwargs):
        events.append("backup")
        return None

    def validate(_prepared: Path) -> None:
        events.append("validate")
        if events == ["validate", "backup", "validate"]:
            raise ValueError("prepared changed after backup")

    monkeypatch.setattr(
        service,
        "_backup_destination_if_present",
        record_backup,
    )

    with pytest.raises(ValueError, match="changed after backup"):
        service.publish_prepared(
            prepared,
            target,
            backup_label="验证器二次检查",
            validator=validate,
        )

    assert events == ["validate", "backup", "validate"]
    assert (target / "marker.txt").read_text(encoding="utf-8") == "old"


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
