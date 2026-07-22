import json
import os
import shutil
from pathlib import Path

import pytest

from app.services.backup_service import (
    BackupCancelledError,
    BackupError,
    BackupService,
)
from app.services.world_write_coordinator import WorldWriteCoordinator


def _world(tmp_path: Path) -> Path:
    world = tmp_path / "world"
    (world / "region").mkdir(parents=True)
    (world / "level.dat").write_bytes(b"level-v1")
    (world / "region" / "r.0.0.mca").write_bytes(b"region-v1")
    return world


def test_create_and_list_backup_with_metadata(tmp_path: Path) -> None:
    world = _world(tmp_path)
    progress = []
    service = BackupService(WorldWriteCoordinator())

    created = service.create_backup(
        world,
        label="升级前",
        progress_callback=lambda value, message: progress.append((value, message)),
    )
    listed = service.list_backups(world)

    assert created.label == "升级前"
    assert created.file_count == 2
    assert (created.backup_path / "world" / "level.dat").read_bytes() == b"level-v1"
    assert listed == [created]
    assert created.integrity_available is True
    assert (created.backup_path / "manifest.json").is_file()
    verification = service.verify_backup(world, created.backup_id)
    assert verification.valid is True
    assert verification.complete is True
    assert verification.checked_files == 2
    assert progress[-1] == (1.0, "备份创建完成")


def test_create_rejects_invalid_world_and_label(tmp_path: Path) -> None:
    service = BackupService(WorldWriteCoordinator())

    with pytest.raises(BackupError, match="有效存档"):
        service.create_backup(tmp_path / "missing")
    world = _world(tmp_path)
    with pytest.raises(BackupError, match="60"):
        service.create_backup(world, "x" * 61)
    with pytest.raises(BackupError, match="控制字符"):
        service.create_backup(world, "bad\nlabel")


def test_cancelled_create_removes_partial_directory(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())

    def cancel_after_first_file(value: float, message: str) -> None:
        del value
        if "1/2" in message:
            service.cancel()

    with pytest.raises(BackupCancelledError):
        service.create_backup(world, progress_callback=cancel_after_first_file)

    repository = tmp_path / ".mcsavehelper_backups" / "world"
    assert list(repository.iterdir()) == []


def test_create_rejects_world_changed_during_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    from app.services import backup_service as backup_module

    real_copy = backup_module.copy_file_with_checkpoints

    def mutate_after_copy(source, destination, checkpoint):
        result = real_copy(source, destination, checkpoint)
        if Path(source).name == "level.dat":
            Path(source).write_bytes(b"changed-after-copy")
        return result

    monkeypatch.setattr(
        backup_module,
        "copy_file_with_checkpoints",
        mutate_after_copy,
    )

    with pytest.raises(BackupError, match="复制期间源文件发生变化"):
        service.create_backup(world)

    repository = tmp_path / ".mcsavehelper_backups" / "world"
    assert list(repository.iterdir()) == []


def test_operation_cancel_check_stops_chunked_backup(tmp_path: Path) -> None:
    world = _world(tmp_path)
    (world / "large.bin").write_bytes(b"x" * (2 * 1024 * 1024))
    service = BackupService(WorldWriteCoordinator())
    checks = 0

    def cancel_check() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    with pytest.raises(BackupCancelledError):
        service.create_backup(world, cancel_check=cancel_check)

    repository = tmp_path / ".mcsavehelper_backups" / "world"
    assert list(repository.iterdir()) == []


def test_create_operation_cancel_check_preserves_legacy_cancel_state(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    service.cancel()

    created = service.create_backup(world, cancel_check=lambda: False)

    assert created.backup_path.is_dir()
    with pytest.raises(BackupCancelledError):
        service.verify_backup(world, created.backup_id)


def test_create_ignores_progress_observer_failure(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())

    def fail_progress(value: float, message: str) -> None:
        del value, message
        raise RuntimeError("observer failed")

    created = service.create_backup(world, progress_callback=fail_progress)

    assert service.list_backups(world) == [created]
    assert (created.backup_path / "world" / "level.dat").read_bytes() == b"level-v1"


def test_create_cancelled_at_final_checkpoint_is_not_published(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    cancelled = False

    def request_cancel(value: float, message: str) -> None:
        nonlocal cancelled
        del message
        if value == 0.96:
            cancelled = True

    with pytest.raises(BackupCancelledError):
        service.create_backup(
            world,
            progress_callback=request_cancel,
            cancel_check=lambda: cancelled,
        )

    repository = tmp_path / ".mcsavehelper_backups" / "world"
    assert list(repository.iterdir()) == []


def test_restore_operation_cancel_check_preserves_legacy_cancel_state(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    backup = service.create_backup(world)
    (world / "level.dat").write_bytes(b"changed")
    service.cancel()

    restored = service.restore_backup(
        world,
        backup.backup_id,
        cancel_check=lambda: False,
    )

    assert restored.backup_id == backup.backup_id
    assert (world / "level.dat").read_bytes() == b"level-v1"
    with pytest.raises(BackupCancelledError):
        service.verify_backup(world, backup.backup_id)


def test_restore_ignores_progress_observer_failure(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    backup = service.create_backup(world)
    (world / "level.dat").write_bytes(b"changed")

    def fail_progress(value: float, message: str) -> None:
        del value, message
        raise RuntimeError("observer failed")

    restored = service.restore_backup(
        world,
        backup.backup_id,
        progress_callback=fail_progress,
    )

    assert restored.backup_id == backup.backup_id
    assert (world / "level.dat").read_bytes() == b"level-v1"


def test_restore_cancelled_at_final_checkpoint_preserves_world(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    backup = service.create_backup(world)
    (world / "level.dat").write_bytes(b"current")
    cancelled = False

    def request_cancel(value: float, message: str) -> None:
        nonlocal cancelled
        del message
        if value == 0.92:
            cancelled = True

    with pytest.raises(BackupCancelledError):
        service.restore_backup(
            world,
            backup.backup_id,
            progress_callback=request_cancel,
            cancel_check=lambda: cancelled,
        )

    assert (world / "level.dat").read_bytes() == b"current"
    assert not list(tmp_path.glob(".world.restore-*"))
    assert not list(tmp_path.glob(".world.rollback-*"))


def test_restore_replaces_world_and_preserves_backup(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    backup = service.create_backup(world, "原始")
    (world / "level.dat").write_bytes(b"level-v2")
    (world / "new.dat").write_bytes(b"new")

    restored = service.restore_backup(world, backup.backup_id)

    assert restored.backup_id == backup.backup_id
    assert (world / "level.dat").read_bytes() == b"level-v1"
    assert not (world / "new.dat").exists()
    assert (backup.backup_path / "world" / "level.dat").exists()
    assert not list(tmp_path.glob(".world.rollback-*"))
    assert not list(tmp_path.glob(".world.restore-*"))


def test_restore_rolls_back_when_publish_fails(tmp_path: Path, monkeypatch) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    backup = service.create_backup(world)
    (world / "level.dat").write_bytes(b"current")
    real_replace = os.replace
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("publish failed")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_replace)

    with pytest.raises(OSError, match="publish failed"):
        service.restore_backup(world, backup.backup_id)

    assert (world / "level.dat").read_bytes() == b"current"
    assert not list(tmp_path.glob(".world.rollback-*"))


def test_damaged_backup_is_listed_but_cannot_be_restored(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    backup = service.create_backup(world)
    (backup.backup_path / "world" / "level.dat").unlink()

    records = service.list_backups(world)

    assert len(records) == 1
    assert records[0].valid is False
    assert "level.dat" in records[0].validation_error
    with pytest.raises(BackupError, match="level.dat"):
        service.restore_backup(world, backup.backup_id)

    service.delete_backup(world, backup.backup_id)
    assert service.list_backups(world) == []


def test_restore_remains_successful_when_rollback_cleanup_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    backup = service.create_backup(world)
    (world / "level.dat").write_bytes(b"changed")
    real_rmtree = shutil.rmtree

    def fail_rollback_cleanup(path, *args, **kwargs):
        if ".rollback-" in Path(path).name:
            raise OSError("cleanup failed")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", fail_rollback_cleanup)

    restored = service.restore_backup(world, backup.backup_id)

    assert restored.backup_id == backup.backup_id
    assert (world / "level.dat").read_bytes() == b"level-v1"


def test_backup_metadata_cannot_be_rebound_to_another_world(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    backup = service.create_backup(world)
    metadata_path = backup.backup_path / "backup.json"
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    data["source_path"] = str(tmp_path / "other")
    metadata_path.write_text(json.dumps(data), encoding="utf-8")

    record = service.list_backups(world)[0]

    assert record.valid is False
    assert "不属于当前存档" in record.validation_error


def test_delete_accepts_only_managed_backup_ids(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    backup = service.create_backup(world)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(BackupError, match="无效的备份标识"):
        service.delete_backup(world, "../../outside")
    assert outside.exists()

    service.delete_backup(world, backup.backup_id)
    assert not backup.backup_path.exists()


def test_verify_detects_same_size_tampering_and_restore_refuses_it(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    backup = service.create_backup(world)
    snapshot_file = backup.backup_path / "world" / "region" / "r.0.0.mca"
    snapshot_file.write_bytes(b"region-v2")
    (world / "level.dat").write_bytes(b"current")

    verification = service.verify_backup(world, backup.backup_id)

    assert verification.valid is False
    assert any("摘要不匹配" in issue for issue in verification.issues)
    with pytest.raises(BackupError, match="完整性校验失败"):
        service.restore_backup(world, backup.backup_id)
    assert (world / "level.dat").read_bytes() == b"current"


def test_verify_detects_manifest_tampering_and_extra_files(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    first = service.create_backup(world)
    (first.backup_path / "manifest.json").write_text("{}", encoding="utf-8")

    manifest_result = service.verify_backup(world, first.backup_id)

    assert manifest_result.valid is False
    assert "清单摘要不匹配" in manifest_result.issues[0]

    second = service.create_backup(world)
    (second.backup_path / "world" / "extra.dat").write_bytes(b"extra")

    extra_result = service.verify_backup(world, second.backup_id)

    assert extra_result.valid is False
    assert any("清单外文件" in issue for issue in extra_result.issues)


def test_legacy_backup_without_manifest_remains_compatible(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    backup = service.create_backup(world)
    metadata_path = backup.backup_path / "backup.json"
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    data.pop("manifest_sha256")
    metadata_path.write_text(json.dumps(data), encoding="utf-8")
    (backup.backup_path / "manifest.json").unlink()

    record = service.list_backups(world)[0]
    verification = service.verify_backup(world, backup.backup_id)

    assert record.integrity_available is False
    assert verification.valid is True
    assert verification.complete is False


def test_prune_backups_keeps_latest_records(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    created = []
    for index in range(4):
        (world / "level.dat").write_bytes(f"level-{index}".encode())
        created.append(service.create_backup(world, f"backup-{index}"))

    removed = service.prune_backups(world, keep_latest=2)
    remaining = service.list_backups(world)

    assert len(removed) == 2
    assert {record.backup_id for record in remaining} == {
        created[2].backup_id,
        created[3].backup_id,
    }
    with pytest.raises(BackupError, match="至少需要保留"):
        service.prune_backups(world, keep_latest=0)


def test_prune_checks_cancellation_only_before_delete_commit(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    service = BackupService(WorldWriteCoordinator())
    created = []
    for index in range(3):
        (world / "level.dat").write_bytes(f"level-{index}".encode())
        created.append(service.create_backup(world, f"backup-{index}"))
    checks = 0

    def cancel_after_commit_starts() -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    removed = service.prune_backups(
        world,
        keep_latest=1,
        cancel_check=cancel_after_commit_starts,
    )

    assert checks == 1
    assert {record.backup_id for record in removed} == {
        created[0].backup_id,
        created[1].backup_id,
    }
    assert [record.backup_id for record in service.list_backups(world)] == [
        created[2].backup_id,
    ]
