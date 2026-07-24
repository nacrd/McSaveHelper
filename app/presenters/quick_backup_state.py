"""Explorer quick-backup immutable operation state."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class QuickBackupState:
    """Ownership snapshot for one Explorer quick-backup generation."""

    generation: int = 0
    host_generation: int = -1
    world_path: Path | None = None
    is_running: bool = False


def begin_quick_backup(
    state: QuickBackupState,
    world_path: Path,
    host_generation: int,
) -> QuickBackupState:
    """Start a new operation generation for the selected world."""
    return QuickBackupState(
        generation=state.generation + 1,
        host_generation=host_generation,
        world_path=world_path,
        is_running=True,
    )


def finish_quick_backup(
    state: QuickBackupState,
    generation: int,
) -> QuickBackupState:
    """Release a matching operation while preserving callback identity."""
    if generation != state.generation or not state.is_running:
        return state
    return replace(state, is_running=False)


def invalidate_quick_backup(state: QuickBackupState) -> QuickBackupState:
    """Invalidate all pending callbacks after a world or lifecycle change."""
    return QuickBackupState(generation=state.generation + 1)


def owns_quick_backup(
    state: QuickBackupState,
    generation: int,
    world_path: Path,
    host_generation: int,
) -> bool:
    """Return whether callback identity still belongs to the latest request."""
    return (
        generation == state.generation
        and host_generation == state.host_generation
        and world_path == state.world_path
    )


__all__ = [
    "QuickBackupState",
    "begin_quick_backup",
    "finish_quick_backup",
    "invalidate_quick_backup",
    "owns_quick_backup",
]
