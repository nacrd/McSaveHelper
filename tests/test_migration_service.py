import os
import threading
from pathlib import Path

import pytest

from app.services.backup_service import BackupService
from app.services.config_service import ConfigService
from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.migration_service import MigrationOptions, MigrationService
from app.services.parallel_runner import RuntimeParallelRunner
from app.services.world_transaction import WorldTransactionService
from app.services.world_write_coordinator import WorldWriteCoordinator
from core.batch_processor import BatchCancelledError
from core.parallel import ParallelRunner, SerialParallelRunner


def test_migration_options_parses_manual_names() -> None:
    options = MigrationOptions.from_manual_names_str(
        mode="fast",
        offline=True,
        clean=False,
        pure_clean=True,
        target_platform="java",
        target_version="",
        manual_names_str=" Alice, Bob , ,Carol ",
    )
    assert options.mode == "fast"
    assert options.offline is True
    assert options.pure_clean is True
    assert options.manual_names == ("Alice", "Bob", "Carol")


def _service(
    tmp_path: Path,
    runner: ParallelRunner | None = None,
) -> tuple[MigrationService, BackupService]:
    coordinator = WorldWriteCoordinator()
    backup = BackupService(coordinator)
    transaction = WorldTransactionService(coordinator, backup)
    config = ConfigService(tmp_path / "config")
    return MigrationService(
        config,
        backup,
        transaction,
        runner or SerialParallelRunner(),
    ), backup


def test_single_migration_builds_in_staging_and_backs_up_existing_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "level.dat").write_bytes(b"source")
    destination = tmp_path / "server"
    existing = destination / "world"
    existing.mkdir(parents=True)
    (existing / "level.dat").write_bytes(b"existing")
    service, backup = _service(tmp_path)
    run_destinations = []

    def fake_run_fast(src, dest, world_name, *args):
        del src, args
        run_destinations.append(dest)
        output = dest / world_name
        output.mkdir()
        (output / "level.dat").write_bytes(b"converted")

    monkeypatch.setattr("core.fast_mode.run_fast", fake_run_fast)

    output = service.run_single(
        str(source),
        str(destination),
        "world",
        "fast",
        True,
        False,
        False,
        "java",
        "",
        "",
        lambda message, level: None,
        lambda value: None,
    )

    assert Path(output) == existing
    assert (existing / "level.dat").read_bytes() == b"converted"
    assert run_destinations[0] != destination
    records = backup.list_backups(existing)
    assert len(records) == 1
    assert (records[0].backup_path / "world" / "level.dat").read_bytes() == b"existing"


def test_single_migration_failure_leaves_existing_target_untouched(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "level.dat").write_bytes(b"source")
    destination = tmp_path / "server"
    existing = destination / "world"
    existing.mkdir(parents=True)
    (existing / "level.dat").write_bytes(b"existing")
    service, _ = _service(tmp_path)

    def fail_run_fast(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("conversion failed")

    monkeypatch.setattr("core.fast_mode.run_fast", fail_run_fast)

    with pytest.raises(RuntimeError, match="conversion failed"):
        service.run_single(
            str(source),
            str(destination),
            "world",
            "fast",
            True,
            False,
            False,
            "java",
            "",
            "",
            lambda message, level: None,
            lambda value: None,
        )

    assert (existing / "level.dat").read_bytes() == b"existing"
    assert not list(destination.glob(".mcsavehelper_migrate_*"))


def test_single_migration_rejects_empty_destination(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    with pytest.raises(ValueError, match="不能为空"):
        service.run_single(
            str(tmp_path / "source"),
            "",
            "world",
            "fast",
            True,
            False,
            False,
            "java",
            "",
            "",
            lambda message, level: None,
            lambda value: None,
        )


@pytest.mark.parametrize(
    ("platform", "version"),
    [("bedrock", ""), ("java", "1343")],
)
def test_migration_rejects_unsupported_platform_or_version(
    tmp_path: Path,
    platform: str,
    version: str,
) -> None:
    service, _ = _service(tmp_path)
    logs = []

    result = service._apply_version_conversion(
        tmp_path,
        platform,
        version,
        lambda message, level: logs.append((message, level)),
    )

    assert result is False
    assert logs[-1][1] == "ERROR"


def test_single_migration_rejects_invalid_source_and_mode(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    destination = str(tmp_path / "output")

    with pytest.raises(ValueError, match="有效 Minecraft 存档"):
        service.run_single(
            str(tmp_path / "missing"), destination, "world", "fast",
            True, False, False, "java", "", "",
            lambda message, level: None, lambda value: None,
        )

    source = tmp_path / "source"
    source.mkdir()
    (source / "level.dat").write_bytes(b"level")
    with pytest.raises(ValueError, match="不支持的迁移模式"):
        service.run_single(
            str(source), destination, "world", "unknown",
            True, False, False, "java", "", "",
            lambda message, level: None, lambda value: None,
        )


def test_directory_publication_restores_target_when_exchange_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from core.utils import publish_directory_tree

    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "level.dat").write_bytes(b"new")
    target = tmp_path / "world"
    target.mkdir()
    (target / "level.dat").write_bytes(b"old")
    real_replace = os.replace
    calls = 0

    def fail_publish(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("publish failed")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_publish)

    with pytest.raises(OSError, match="publish failed"):
        publish_directory_tree(prepared, target)

    assert (target / "level.dat").read_bytes() == b"old"
    assert not list(tmp_path.glob(".world.rollback-*"))


def test_batch_migration_is_concurrent_transactional_and_task_keyed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first = tmp_path / "one" / "world"
    second = tmp_path / "two" / "world"
    for source, content in ((first, b"one"), (second, b"two")):
        source.mkdir(parents=True)
        (source / "level.dat").write_bytes(content)
    destination = tmp_path / "server"
    for name in ("world_1", "world_2"):
        target = destination / name
        target.mkdir(parents=True)
        (target / "level.dat").write_bytes(f"old-{name}".encode())
    runtime = ExecutionRuntime(
        io_limits=LaneLimits(1, 2),
        cpu_limits=LaneLimits(2, 2),
    )
    service, backup = _service(tmp_path, RuntimeParallelRunner(runtime))
    service._batch_worlds = [first, second]
    barrier = threading.Barrier(2)

    def fake_run_fast(source, staging, world_name, *args):
        del args
        barrier.wait(timeout=2)
        output = staging / world_name
        output.mkdir()
        (output / "level.dat").write_bytes(
            (source / "level.dat").read_bytes() + b"-converted"
        )

    monkeypatch.setattr("core.fast_mode.run_fast", fake_run_fast)

    try:
        results = service.run_batch(
            str(destination), "fast", True, False, False,
            "java", "", "", 2,
            lambda message, level: None, lambda value: None,
        )
    finally:
        runtime.shutdown(wait=True)

    assert set(results) == {"task-1", "task-2"}
    assert all(result["success"] for result in results.values())
    assert (destination / "world_1" / "level.dat").read_bytes() == b"one-converted"
    assert (destination / "world_2" / "level.dat").read_bytes() == b"two-converted"
    assert len(backup.list_backups(destination / "world_1")) == 1
    assert len(backup.list_backups(destination / "world_2")) == 1


def test_batch_task_failure_preserves_only_that_existing_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first = tmp_path / "source-a"
    second = tmp_path / "source-b"
    for source in (first, second):
        source.mkdir()
        (source / "level.dat").write_bytes(source.name.encode())
    destination = tmp_path / "server"
    for name in ("world_1", "world_2"):
        target = destination / name
        target.mkdir(parents=True)
        (target / "level.dat").write_bytes(f"old-{name}".encode())
    service, _ = _service(tmp_path)
    service._batch_worlds = [first, second]

    def fake_run_fast(source, staging, world_name, *args):
        del args
        if source == second:
            raise RuntimeError("second failed")
        output = staging / world_name
        output.mkdir()
        (output / "level.dat").write_bytes(b"first-converted")

    monkeypatch.setattr("core.fast_mode.run_fast", fake_run_fast)

    results = service.run_batch(
        str(destination), "fast", True, False, False,
        "java", "", "", 2,
        lambda message, level: None, lambda value: None,
    )

    assert results["task-1"]["success"] is True
    assert results["task-2"]["success"] is False
    assert "second failed" in results["task-2"]["error"]
    assert (destination / "world_1" / "level.dat").read_bytes() == b"first-converted"
    assert (destination / "world_2" / "level.dat").read_bytes() == b"old-world_2"


def test_batch_cancel_before_publish_keeps_existing_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "level.dat").write_bytes(b"source")
    destination = tmp_path / "server"
    target = destination / "world_1"
    target.mkdir(parents=True)
    (target / "level.dat").write_bytes(b"old")
    service, _ = _service(tmp_path)
    service._batch_worlds = [source]
    started = threading.Event()
    release = threading.Event()

    def fake_run_fast(source_path, staging, world_name, *args):
        del source_path, args
        output = staging / world_name
        output.mkdir()
        (output / "level.dat").write_bytes(b"converted")
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr("core.fast_mode.run_fast", fake_run_fast)
    returned = []
    thread = threading.Thread(
        target=lambda: returned.append(service.run_batch(
            str(destination), "fast", True, False, False,
            "java", "", "", 1,
            lambda message, level: None, lambda value: None,
        ))
    )
    thread.start()
    assert started.wait(timeout=2)

    assert service.cancel_batch() is True
    release.set()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert returned[0]["task-1"]["cancelled"] is True
    assert (target / "level.dat").read_bytes() == b"old"
    assert service.cancel_batch() is False


def test_single_cancel_before_publish_keeps_existing_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "level.dat").write_bytes(b"source")
    destination = tmp_path / "server"
    target = destination / "world"
    target.mkdir(parents=True)
    (target / "level.dat").write_bytes(b"old")
    service, _ = _service(tmp_path)
    started = threading.Event()
    release = threading.Event()
    returned: list[BaseException] = []

    def fake_run_fast(source_path, staging, world_name, *args):
        del source_path, args
        output = staging / world_name
        output.mkdir()
        (output / "level.dat").write_bytes(b"converted")
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr("core.fast_mode.run_fast", fake_run_fast)

    def run() -> None:
        try:
            service.run_single(
                str(source),
                str(destination),
                "world",
                "fast",
                True,
                False,
                False,
                "java",
                "",
                "",
                lambda message, level: None,
                lambda value: None,
            )
        except BaseException as exc:
            returned.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert started.wait(timeout=2)
    assert service.cancel_active() is True
    release.set()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert returned
    assert isinstance(returned[0], BatchCancelledError)
    assert (target / "level.dat").read_bytes() == b"old"


def test_migration_service_rejects_reentrant_operation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "level.dat").write_bytes(b"source")
    destination = tmp_path / "server"
    service, _ = _service(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def fake_run_fast(source_path, staging, world_name, *args):
        del source_path, args
        output = staging / world_name
        output.mkdir()
        (output / "level.dat").write_bytes(b"converted")
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr("core.fast_mode.run_fast", fake_run_fast)

    errors: list[BaseException] = []

    def run() -> None:
        try:
            service.run_single(
                str(source),
                str(destination),
                "world",
                "fast",
                True,
                False,
                False,
                "java",
                "",
                "",
                lambda message, level: None,
                lambda value: None,
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(
        target=run,
    )
    thread.start()
    assert started.wait(timeout=2)

    with pytest.raises(RuntimeError, match="迁移任务"):
        service.run_single(
            str(source),
            str(destination),
            "world",
            "fast",
            True,
            False,
            False,
            "java",
            "",
            "",
            lambda message, level: None,
            lambda value: None,
        )

    assert service.cancel_active() is True
    release.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], BatchCancelledError)
