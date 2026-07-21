import threading
from pathlib import Path

import pytest

from app.services.world_write_coordinator import (
    UnsafeWorldPathError,
    WorldInUseError,
    WorldOperationBusyError,
    WorldWriteCoordinator,
)


def test_same_world_is_reentrant_in_owner_thread(tmp_path: Path) -> None:
    coordinator = WorldWriteCoordinator()
    world = tmp_path / "world"

    with coordinator.reserve(world):
        with coordinator.reserve(world):
            pass


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


def test_held_session_lock_blocks_world_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    (world / "session.lock").write_bytes(b"lock")
    monkeypatch.setattr(
        WorldWriteCoordinator,
        "_session_lock_is_held",
        staticmethod(lambda path: True),
    )

    with pytest.raises(WorldInUseError, match="Minecraft"):
        with WorldWriteCoordinator().reserve(world):
            pass


def test_unheld_session_lock_allows_world_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    (world / "session.lock").write_bytes(b"lock")
    monkeypatch.setattr(
        WorldWriteCoordinator,
        "_session_lock_is_held",
        staticmethod(lambda path: False),
    )

    with WorldWriteCoordinator().reserve(world):
        pass
