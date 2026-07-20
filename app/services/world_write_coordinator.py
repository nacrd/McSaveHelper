"""Application-scoped coordination for world write operations.

Provides per-world reentrant leases so concurrent writes to different worlds
are allowed, while the same world is exclusive.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path


class WorldOperationBusyError(RuntimeError):
    """Raised when another thread is already writing the same world."""


@dataclass
class _LockEntry:
    """Reference-counted RLock for one normalized world path."""

    lock: threading.RLock
    users: int = 0


class WorldWriteLease:
    """Non-blocking, reentrant lease for one normalized world path.

    Acquisition happens in ``__enter__``; failing to acquire raises
    :class:`WorldOperationBusyError` and drops the coordinator reference.
    """

    def __init__(
        self,
        coordinator: WorldWriteCoordinator,
        key: str,
        entry: _LockEntry,
    ) -> None:
        """Create an unacquired lease.

        Args:
            coordinator: Owner that manages lock entry lifetimes.
            key: Normalized absolute world path key.
            entry: Shared lock entry for ``key``.
        """
        self._coordinator = coordinator
        self._key = key
        self._entry = entry
        self._acquired = False

    def __enter__(self) -> WorldWriteLease:
        """Attempt non-blocking acquisition of the world lock."""
        if not self._entry.lock.acquire(blocking=False):
            self._coordinator._release_reference(self._key, self._entry)
            raise WorldOperationBusyError(
                f"该存档已有写操作正在进行: {self._key}"
            )
        self._acquired = True
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        """Release the world lock and coordinator reference if acquired."""
        del exc_type, exc, traceback
        if not self._acquired:
            return
        self._entry.lock.release()
        self._acquired = False
        self._coordinator._release_reference(self._key, self._entry)


class WorldWriteCoordinator:
    """Provide independent locks for different worlds without global state."""

    def __init__(self) -> None:
        """Initialize an empty lock registry."""
        self._guard = threading.Lock()
        self._entries: dict[str, _LockEntry] = {}

    def reserve(self, world_path: Path | str) -> WorldWriteLease:
        """Create a lease; acquisition happens when entering its context.

        Args:
            world_path: World directory path.

        Returns:
            WorldWriteLease: Unacquired lease for the normalized path.

        Raises:
            ValueError: If ``world_path`` is empty.
        """
        key = self.normalize(world_path)
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                entry = _LockEntry(threading.RLock())
                self._entries[key] = entry
            entry.users += 1
        return WorldWriteLease(self, key, entry)

    @staticmethod
    def normalize(world_path: Path | str) -> str:
        """Return the stable, case-normalized absolute lock key.

        Args:
            world_path: World path to normalize.

        Returns:
            str: Absolute, ``normcase`` path string used as the lock key.

        Raises:
            ValueError: If the path is empty/blank.
        """
        if not str(world_path).strip():
            raise ValueError("存档路径不能为空")
        resolved = Path(world_path).expanduser().resolve()
        return os.path.normcase(str(resolved))

    def _release_reference(self, key: str, entry: _LockEntry) -> None:
        """Drop one user reference and delete idle lock entries."""
        with self._guard:
            entry.users -= 1
            if entry.users == 0 and self._entries.get(key) is entry:
                del self._entries[key]
