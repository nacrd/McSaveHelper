"""Application-scoped coordination for world write operations.

Provides per-world reentrant leases so concurrent writes to different worlds
are allowed, while the same world is exclusive.
"""
from __future__ import annotations

import os
import threading
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


class WorldOperationBusyError(RuntimeError):
    """Raised when another thread is already writing the same world."""


class WorldInUseError(RuntimeError):
    """世界的 session.lock 正被外部进程持有时抛出。"""


class UnsafeWorldPathError(ValueError):
    """世界根路径包含符号链接或 junction 时抛出。"""


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
        try:
            self._coordinator.ensure_world_available(Path(self._key))
        except Exception:
            self._coordinator._release_reference(self._key, self._entry)
            raise
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

    @classmethod
    def ensure_world_available(cls, world_path: Path) -> None:
        """拒绝不安全根路径及被外部进程占用的世界。

        Args:
            world_path: 已规范化的世界根路径。

        Raises:
            UnsafeWorldPathError: 根路径或祖先是链接/junction。
            WorldInUseError: session.lock 无法取得非阻塞文件锁。
        """
        cls._reject_linked_path(world_path)
        lock_path = world_path / "session.lock"
        if lock_path.is_file() and cls._session_lock_is_held(lock_path):
            raise WorldInUseError(
                f"存档可能仍被 Minecraft 客户端或服务端占用: {world_path}"
            )

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
        candidate = Path(world_path).expanduser().absolute()
        WorldWriteCoordinator._reject_linked_path(candidate)
        resolved = candidate.resolve()
        return os.path.normcase(str(resolved))

    @staticmethod
    def _reject_linked_path(path: Path) -> None:
        """检查已存在路径链中的符号链接和 Windows junction。"""
        current = path
        existing: list[Path] = []
        while True:
            if current.exists():
                existing.append(current)
            if current.parent == current:
                break
            current = current.parent
        for candidate in existing:
            is_junction = getattr(candidate, "is_junction", lambda: False)
            if candidate.is_symlink() or bool(is_junction()):
                raise UnsafeWorldPathError(
                    f"世界路径不能包含符号链接或 junction: {candidate}"
                )

    @staticmethod
    def _session_lock_is_held(lock_path: Path) -> bool:
        """跨平台尝试取得 session.lock 的一个字节排他锁。"""
        try:
            with lock_path.open("r+b") as handle:
                handle.seek(0)
                if os.name == "nt":
                    return WorldWriteCoordinator._windows_lock_held(handle)
                return WorldWriteCoordinator._posix_lock_held(handle)
        except OSError:
            return True

    @staticmethod
    def _windows_lock_held(handle: BinaryIO) -> bool:
        """Windows 下使用 msvcrt 非阻塞锁探测。"""
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return True
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return False

    @staticmethod
    def _posix_lock_held(handle: BinaryIO) -> bool:
        """POSIX 下使用 flock 非阻塞锁探测。"""
        fcntl = importlib.import_module("fcntl")

        try:
            flock = getattr(fcntl, "flock")
            lock_ex = int(getattr(fcntl, "LOCK_EX"))
            lock_nb = int(getattr(fcntl, "LOCK_NB"))
            lock_un = int(getattr(fcntl, "LOCK_UN"))
            flock(handle.fileno(), lock_ex | lock_nb)
        except OSError:
            return True
        flock(handle.fileno(), lock_un)
        return False

    def _release_reference(self, key: str, entry: _LockEntry) -> None:
        """Drop one user reference and delete idle lock entries."""
        with self._guard:
            entry.users -= 1
            if entry.users == 0 and self._entries.get(key) is entry:
                del self._entries[key]
