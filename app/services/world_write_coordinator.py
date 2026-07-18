"""Application-scoped coordination for world write operations."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path


class WorldOperationBusyError(RuntimeError):
    """Raised when another thread is already writing the same world."""


@dataclass
class _LockEntry:
    lock: threading.RLock
    users: int = 0


class WorldWriteLease:
    """Non-blocking, reentrant lease for one normalized world path."""

    def __init__(
        self,
        coordinator: "WorldWriteCoordinator",
        key: str,
        entry: _LockEntry,
    ) -> None:
        self._coordinator = coordinator
        self._key = key
        self._entry = entry
        self._acquired = False

    def __enter__(self) -> "WorldWriteLease":
        if not self._entry.lock.acquire(blocking=False):
            self._coordinator._release_reference(self._key, self._entry)
            raise WorldOperationBusyError(
                f"该存档已有写操作正在进行: {self._key}"
            )
        self._acquired = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._acquired:
            return
        self._entry.lock.release()
        self._acquired = False
        self._coordinator._release_reference(self._key, self._entry)


class WorldWriteCoordinator:
    """Provide independent locks for different worlds without global state."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._entries: dict[str, _LockEntry] = {}

    def reserve(self, world_path: Path | str) -> WorldWriteLease:
        """Create a lease; acquisition happens when entering its context."""
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
        """Return the stable, case-normalized absolute lock key."""
        if not str(world_path).strip():
            raise ValueError("存档路径不能为空")
        resolved = Path(world_path).expanduser().resolve()
        return os.path.normcase(str(resolved))

    def _release_reference(self, key: str, entry: _LockEntry) -> None:
        with self._guard:
            entry.users -= 1
            if entry.users == 0 and self._entries.get(key) is entry:
                del self._entries[key]
