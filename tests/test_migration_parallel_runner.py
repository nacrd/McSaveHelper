"""MigrationService parallel-runner forwarding contracts."""
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from app.services.backup_service import BackupService
from app.services.config_service import ConfigService
from app.services.migration_service import MigrationOptions, MigrationService
from app.services.world_transaction import WorldTransactionService
from core.parallel import ParallelRunner
from core.types import LogCallback, ProgressCallback


@pytest.mark.parametrize("mode", ["fast", "full"])
def test_single_migration_forwards_shared_parallel_runner(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = cast(ParallelRunner, object())
    service = _service(runner)
    received: list[object] = []

    def capture(*args: object) -> None:
        received.append(args[-1])

    monkeypatch.setattr(f"core.{mode}_mode.run_{mode}", capture)

    _run_mode(service, mode=mode, region_workers=None)

    assert received == [runner]


@pytest.mark.parametrize("mode", ["fast", "full"])
def test_batch_world_keeps_inner_region_work_serial(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = cast(ParallelRunner, object())
    service = _service(runner)
    received: list[object] = []

    def capture(*args: object) -> None:
        received.append(args[-1])

    monkeypatch.setattr(f"core.{mode}_mode.run_{mode}", capture)

    _run_mode(service, mode=mode, region_workers=1)

    assert received == [None]


def _service(runner: ParallelRunner) -> MigrationService:
    config = cast(
        ConfigService,
        SimpleNamespace(
            use_custom_mapping=False,
            custom_uuid_mappings={},
        ),
    )
    return MigrationService(
        config,
        cast(BackupService, object()),
        cast(WorldTransactionService, object()),
        runner,
    )


def _run_mode(
    service: MigrationService,
    *,
    mode: str,
    region_workers: int | None,
) -> None:
    def log(message: str, level: str) -> None:
        del message, level

    def progress(value: float) -> None:
        del value

    typed_log: LogCallback = log
    typed_progress: ProgressCallback = progress
    service._run_migration_modes(
        src_path=Path("source"),
        staging_root=Path("staging"),
        world_name="world",
        options=MigrationOptions(mode=mode),
        manual=[],
        log_cb=typed_log,
        progress_cb=typed_progress,
        region_workers=region_workers,
        cancel_check=None,
    )
