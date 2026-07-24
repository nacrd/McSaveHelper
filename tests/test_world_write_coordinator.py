from pathlib import Path
import os
import subprocess
import sys
import threading

import pytest

from app.services.world_write_coordinator import (
    UnsafeWorldPathError,
    WorldOperationBusyError,
    WorldWriteCoordinator,
)
from core.utils import publish_directory_tree


_EXTERNAL_PROBE = """
import sys
from pathlib import Path

from app.services.world_write_coordinator import (
    WorldInUseError,
    WorldOperationBusyError,
    WorldWriteCoordinator,
)

try:
    with WorldWriteCoordinator().reserve(Path(sys.argv[1])):
        print("acquired")
except (WorldInUseError, WorldOperationBusyError):
    print("busy")
"""


def _probe_external_lease(world: Path) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", _EXTERNAL_PROBE, str(world)],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_same_world_is_reentrant_in_owner_thread(tmp_path: Path) -> None:
    coordinator = WorldWriteCoordinator()
    world = tmp_path / "world"
    world.mkdir()

    with coordinator.reserve(world):
        assert _probe_external_lease(world) == "busy"
        with coordinator.reserve(world):
            assert _probe_external_lease(world) == "busy"
        assert _probe_external_lease(world) == "busy"

    assert _probe_external_lease(world) == "acquired"


def test_nested_lease_rebinds_lock_around_directory_publish(
    tmp_path: Path,
) -> None:
    coordinator = WorldWriteCoordinator()
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"old")
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "level.dat").write_bytes(b"new")

    with coordinator.reserve(world):
        with coordinator.reserve(world) as nested:
            publish_directory_tree(
                prepared,
                world,
                exchange_context=nested.publication_window(),
            )
            assert nested.consume_publication_error() is None
            assert _probe_external_lease(world) == "busy"
        assert _probe_external_lease(world) == "busy"

    assert (world / "level.dat").read_bytes() == b"new"
    assert _probe_external_lease(world) == "acquired"
    assert not list(tmp_path.glob(".world.rollback-*"))


def test_external_process_stays_blocked_in_publication_window(
    tmp_path: Path,
) -> None:
    coordinator = WorldWriteCoordinator()
    world = tmp_path / "world"
    world.mkdir()

    with coordinator.reserve(world) as lease:
        with lease.publication_window():
            assert _probe_external_lease(world) == "busy"
        assert lease.consume_publication_error() is None

    assert _probe_external_lease(world) == "acquired"


def test_failed_directory_exchange_rebinds_restored_world_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    coordinator = WorldWriteCoordinator()
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"old")
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "level.dat").write_bytes(b"new")
    real_replace = os.replace

    def fail_prepared_replace(source: Path, destination: Path) -> None:
        if Path(source) == prepared:
            raise OSError("exchange failed")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_prepared_replace)

    with coordinator.reserve(world) as lease:
        with pytest.raises(OSError, match="exchange failed"):
            publish_directory_tree(
                prepared,
                world,
                exchange_context=lease.publication_window(),
            )
        assert lease.consume_publication_error() is None
        assert _probe_external_lease(world) == "busy"

    assert (world / "level.dat").read_bytes() == b"old"
    assert _probe_external_lease(world) == "acquired"
    assert not list(tmp_path.glob(".world.rollback-*"))


def test_same_world_rejects_a_concurrent_writer(tmp_path: Path) -> None:
    coordinator = WorldWriteCoordinator()
    world = tmp_path / "world"
    result = []

    with coordinator.reserve(world):
        thread = threading.Thread(
            target=lambda: _capture_busy(coordinator, world, result)
        )
        thread.start()
        thread.join()

    assert result == ["busy"]


def _capture_busy(
    coordinator: WorldWriteCoordinator,
    world: Path,
    result: list[str],
) -> None:
    try:
        with coordinator.reserve(world):
            result.append("acquired")
    except WorldOperationBusyError:
        result.append("busy")


def test_different_worlds_can_be_reserved_concurrently(tmp_path: Path) -> None:
    coordinator = WorldWriteCoordinator()
    acquired = []

    with coordinator.reserve(tmp_path / "world-a"):
        thread = threading.Thread(
            target=lambda: _reserve_other(
                coordinator,
                tmp_path / "world-b",
                acquired,
            )
        )
        thread.start()
        thread.join()

    assert acquired == [True]


def _reserve_other(
    coordinator: WorldWriteCoordinator,
    world: Path,
    acquired: list[bool],
) -> None:
    with coordinator.reserve(world):
        acquired.append(True)


def test_empty_world_path_is_rejected() -> None:
    coordinator = WorldWriteCoordinator()

    with pytest.raises(ValueError, match="不能为空"):
        coordinator.reserve("")


def test_linked_world_path_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(UnsafeWorldPathError, match="符号链接"):
        WorldWriteCoordinator().reserve(linked)


def test_held_session_lock_blocks_world_write(tmp_path: Path) -> None:
    world = tmp_path / "world"
    world.mkdir()

    with WorldWriteCoordinator().reserve(world):
        assert (world / "session.lock").is_file()
        assert _probe_external_lease(world) == "busy"


def test_unheld_session_lock_allows_world_write(tmp_path: Path) -> None:
    world = tmp_path / "world"
    world.mkdir()
    (world / "session.lock").write_bytes(b"lock")

    with WorldWriteCoordinator().reserve(world):
        assert _probe_external_lease(world) == "busy"

    assert _probe_external_lease(world) == "acquired"
