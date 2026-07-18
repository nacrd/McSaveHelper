from pathlib import Path
import threading
from typing import Any

from app.services.backup_service import BackupError, BackupRecord, BackupService
from app.services.save_repair.models import IssueLevel
from app.services.save_repair_service import SaveRepairService


class _FailingBackupService(BackupService):
    def create_backup(self, *args: Any, **kwargs: Any) -> BackupRecord:
        del args, kwargs
        raise BackupError("disk full")


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
    service = SaveRepairService(_FailingBackupService())

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

    report = SaveRepairService().repair_world(
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
    backup_service = BackupService()
    service = SaveRepairService(backup_service)
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
