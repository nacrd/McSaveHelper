from pathlib import Path
import threading
from typing import Any

from app.services.backup_service import BackupError, BackupRecord, BackupService
from app.services.save_repair.models import IssueLevel
from app.services.save_repair.models import RepairReport
from app.services.save_repair_service import SaveRepairService
from app.services.world_transaction import WorldTransactionService
from app.services.world_write_coordinator import WorldWriteCoordinator


class _FailingBackupService(BackupService):
    def create_backup(self, *args: Any, **kwargs: Any) -> BackupRecord:
        del args, kwargs
        raise BackupError("disk full")


def _service(
    backup: BackupService | None = None,
) -> SaveRepairService:
    coordinator = WorldWriteCoordinator()
    selected_backup = backup or BackupService(coordinator)
    transaction = WorldTransactionService(coordinator, selected_backup)
    return SaveRepairService(selected_backup, transaction)


def test_repair_aborts_before_mutation_when_backup_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"level")
    mutations = []

    class UnexpectedRepairer:
        def __init__(self, *args: Any) -> None:
            del args
            mutations.append("constructed")

    monkeypatch.setattr(
        "app.services.save_repair_service.ChunkRepairer",
        UnexpectedRepairer,
    )
    monkeypatch.setattr(
        "app.services.save_repair_service.PlayerRepairer",
        UnexpectedRepairer,
    )
    monkeypatch.setattr(
        "app.services.save_repair_service.LevelRepairer",
        UnexpectedRepairer,
    )
    failing_backup = _FailingBackupService(WorldWriteCoordinator())
    service = _service(failing_backup)

    report = service.repair_world(world, backup=True)

    assert report.success is False
    assert report.backup_path == ""
    assert mutations == []
    assert any(
        issue.level is IssueLevel.ERROR and "已中止修复" in issue.message
        for issue in report.issues
    )


def test_repair_without_mutation_options_reports_success(tmp_path: Path) -> None:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"level")

    report = _service().repair_world(
        world,
        fix_chunks=False,
        fix_players=False,
        fix_level_dat=False,
        backup=False,
    )

    assert report.success is True


def test_repair_fails_cleanly_while_another_backup_operation_is_reserved(
    tmp_path: Path,
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"level")
    coordinator = WorldWriteCoordinator()
    backup_service = BackupService(coordinator)
    transaction = WorldTransactionService(
        coordinator,
        backup_service,
    )
    service = SaveRepairService(backup_service, transaction)
    result = []

    with backup_service.exclusive_operation(world):
        thread = threading.Thread(
            target=lambda: result.append(service.repair_world(world, backup=False))
        )
        thread.start()
        thread.join()

    assert len(result) == 1
    assert result[0].success is False
    assert "正在进行" in result[0].issues[0].message


def test_staged_repair_failure_never_publishes_partial_world(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"level-old")
    (world / "marker.txt").write_text("original", encoding="utf-8")
    service = _service()

    def fail_in_staging(
        world_path: Path | None = None,
        **_kwargs: Any,
    ) -> RepairReport:
        if world_path is None:
            raise AssertionError("修复必须在暂存世界中执行")
        (world_path / "marker.txt").write_text("partial", encoding="utf-8")
        return RepairReport(success=False)

    monkeypatch.setattr(service, "_repair_world_exclusive", fail_in_staging)

    report = service.repair_world(world)

    assert report.success is False
    assert (world / "marker.txt").read_text(encoding="utf-8") == "original"


def test_cancel_during_staged_repair_never_publishes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"level-old")
    (world / "marker.txt").write_text("original", encoding="utf-8")
    service = _service()

    def cancel_in_staging(
        world_path: Path | None = None,
        **_kwargs: Any,
    ) -> RepairReport:
        if world_path is None:
            raise AssertionError("修复必须在暂存世界中执行")
        (world_path / "marker.txt").write_text("cancelled", encoding="utf-8")
        service._cancel_event.set()
        return RepairReport(success=False, cancelled=True)

    monkeypatch.setattr(service, "_repair_world_exclusive", cancel_in_staging)

    report = service.repair_world(world)

    assert report.cancelled is True
    assert (world / "marker.txt").read_text(encoding="utf-8") == "original"
