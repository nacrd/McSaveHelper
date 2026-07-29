"""Explorer quick-backup immutable state transitions."""
from pathlib import Path

from app.presenters.quick_backup_state import (
    QuickBackupState,
    begin_quick_backup,
    finish_quick_backup,
    invalidate_quick_backup,
    owns_quick_backup,
)


def test_quick_backup_state_tracks_request_identity() -> None:
    world = Path("world")
    state = begin_quick_backup(QuickBackupState(), world, 3)

    assert state.is_running
    assert owns_quick_backup(state, state.generation, world, 3)
    assert not owns_quick_backup(state, state.generation, world, 4)


def test_quick_backup_state_rejects_stale_finish_and_invalidation() -> None:
    world = Path("world")
    running = begin_quick_backup(QuickBackupState(), world, 3)

    assert finish_quick_backup(running, running.generation - 1) is running
    finished = finish_quick_backup(running, running.generation)
    assert not finished.is_running
    assert owns_quick_backup(finished, finished.generation, world, 3)

    invalidated = invalidate_quick_backup(finished)
    assert not invalidated.is_running
    assert not owns_quick_backup(invalidated, finished.generation, world, 3)
