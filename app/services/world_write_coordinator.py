"""Application-scoped coordination for world write operations.

Provides per-world reentrant leases so concurrent writes to different worlds
are allowed, while the same world is exclusive.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional


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
    depth: int = 0
    process_lock: Optional[BinaryIO] = None
    session_lock: Optional[BinaryIO] = None
    publication_active: bool = False
    publication_error: Optional[Exception] = None


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
        try:
            if self._entry.depth == 0:
                self._entry.process_lock = (
                    self._coordinator._acquire_process_lock(self._key)
                )
                try:
                    self._entry.session_lock = (
                        self._coordinator._acquire_session_lock(
                            Path(self._key)
                        )
                    )
                except Exception:
                    self._coordinator._release_session_lock(
                        self._entry.process_lock
                    )
                    self._entry.process_lock = None
                    raise
            self._entry.depth += 1
        except Exception:
            self._entry.lock.release()
            self._coordinator._release_reference(self._key, self._entry)
            raise
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
        try:
            if self._entry.publication_active:
                self._end_publication_window()
            self._entry.depth -= 1
            if self._entry.depth == 0:
                self._coordinator._release_session_lock(
                    self._entry.session_lock
                )
                self._entry.session_lock = None
                self._coordinator._release_session_lock(
                    self._entry.process_lock
                )
                self._entry.process_lock = None
        finally:
            self._entry.lock.release()
            self._acquired = False
            self._coordinator._release_reference(self._key, self._entry)

    def publication_window(self) -> _PublicationWindow:
        """创建只包围目录 exchange/失败回滚的 session.lock handoff。

        Returns:
            可传给 ``publish_directory_tree(exchange_context=...)`` 的上下文。

        Raises:
            RuntimeError: 租约尚未进入或已有目录发布窗口。
        """
        if not self._acquired:
            raise RuntimeError("世界写租约尚未进入")
        return _PublicationWindow(self)

    def consume_publication_error(self) -> Optional[Exception]:
        """取出并清除最近一次发布后的 session.lock 重绑异常。"""
        error = self._entry.publication_error
        self._entry.publication_error = None
        return error

    def _begin_publication_window(self) -> None:
        """exchange 紧前释放旧锁；RLock 在整个窗口仍保持。"""
        if self._entry.publication_active:
            raise RuntimeError("世界目录发布窗口不能重入")
        self._entry.publication_error = None
        self._coordinator._release_session_lock(self._entry.session_lock)
        self._entry.session_lock = None
        self._entry.publication_active = True

    def _end_publication_window(self) -> None:
        """exchange 或失败回滚后立即重绑当前目标 session.lock。"""
        if not self._entry.publication_active:
            return
        try:
            self._entry.session_lock = (
                self._coordinator._acquire_session_lock(Path(self._key))
            )
        except Exception as exc:
            self._entry.session_lock = None
            self._entry.publication_error = exc
        finally:
            self._entry.publication_active = False


class _PublicationWindow:
    """仅在目录 exchange 期间暂停并重绑 session.lock 的上下文。"""

    def __init__(self, lease: WorldWriteLease) -> None:
        self._lease = lease

    def __enter__(self) -> None:
        """释放旧目标锁并保持应用内 RLock。"""
        self._lease._begin_publication_window()

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        """重绑当前目标锁，不覆盖 exchange 或回滚异常。"""
        del exc_type, exc, traceback
        self._lease._end_publication_window()


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
        session_lock = cls._acquire_session_lock(world_path)
        cls._release_session_lock(session_lock)

    @classmethod
    def _acquire_session_lock(
        cls,
        world_path: Path,
    ) -> Optional[BinaryIO]:
        """为现有世界持有 session.lock；不存在的目标不创建目录。"""
        cls._reject_linked_path(world_path)
        if not world_path.exists():
            return None
        if not world_path.is_dir():
            return None
        lock_path = world_path / "session.lock"
        cls._reject_linked_path(lock_path)
        handle: Optional[BinaryIO] = None
        try:
            handle = cls._open_session_lock(lock_path)
            cls._ensure_lock_byte(handle)
            if not cls._try_lock_handle(handle):
                raise WorldInUseError(
                    "存档可能仍被 Minecraft 客户端或服务端占用: "
                    f"{world_path}"
                )
            return handle
        except WorldInUseError:
            cls._release_session_lock(handle)
            raise
        except OSError as exc:
            cls._release_session_lock(handle)
            raise WorldInUseError(
                "无法持有存档 session.lock，可能仍被外部进程占用: "
                f"{world_path}: {exc}"
            ) from exc

    @classmethod
    def _acquire_process_lock(cls, key: str) -> BinaryIO:
        """持有不随世界目录 exchange 移动的跨进程应用写锁。"""
        lock_root = Path(tempfile.gettempdir()) / "mcsavehelper-world-locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        lock_path = lock_root / f"{digest}.lock"
        handle: Optional[BinaryIO] = None
        try:
            handle = cls._open_session_lock(lock_path)
            cls._ensure_lock_byte(handle)
            if not cls._try_lock_handle(handle):
                raise WorldOperationBusyError(
                    f"该存档已被另一个 MCSaveHelper 进程写入: {key}"
                )
            return handle
        except WorldOperationBusyError:
            cls._release_session_lock(handle)
            raise
        except OSError as exc:
            cls._release_session_lock(handle)
            raise WorldOperationBusyError(
                f"无法持有跨进程世界写锁: {key}: {exc}"
            ) from exc

    @classmethod
    def _release_session_lock(cls, handle: Optional[BinaryIO]) -> None:
        """释放 session.lock；关闭句柄本身也保证异常路径解除锁。"""
        if handle is None:
            return
        try:
            cls._unlock_handle(handle)
        except OSError:
            # 关闭文件仍会由操作系统释放锁，清理失败不应覆盖业务异常。
            pass
        finally:
            try:
                handle.close()
            except OSError:
                # 租约退出是清理边界，不能用关闭失败覆盖主要操作结果。
                pass

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
    def _open_session_lock(lock_path: Path) -> BinaryIO:
        """打开或创建 session.lock，Windows 允许目录原子换位。"""
        if os.name != "nt":
            return lock_path.open("a+b")
        return WorldWriteCoordinator._open_windows_session_lock(lock_path)

    @staticmethod
    def _open_windows_session_lock(lock_path: Path) -> BinaryIO:
        """用 FILE_SHARE_DELETE 打开锁文件，避免阻断目录原子发布。"""
        import ctypes
        import msvcrt
        from ctypes import wintypes

        generic_read = 0x80000000
        generic_write = 0x40000000
        share_read_delete = 0x00000001 | 0x00000004
        open_always = 4
        file_attribute_normal = 0x00000080
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        raw_handle = create_file(
            str(lock_path),
            generic_read | generic_write,
            share_read_delete,
            None,
            open_always,
            file_attribute_normal,
            None,
        )
        if raw_handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            descriptor = msvcrt.open_osfhandle(
                int(raw_handle),
                os.O_RDWR | os.O_BINARY,
            )
        except OSError:
            kernel32.CloseHandle(raw_handle)
            raise
        return os.fdopen(descriptor, "r+b", buffering=0)

    @staticmethod
    def _ensure_lock_byte(handle: BinaryIO) -> None:
        """确保 Windows 字节范围锁至少覆盖一个真实字节。"""
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)

    @staticmethod
    def _try_lock_handle(handle: BinaryIO) -> bool:
        """非阻塞取得跨进程排他锁，成功后保持到显式解锁。"""
        if os.name == "nt":
            # CreateFileW 已通过拒绝 FILE_SHARE_WRITE 持有写排他租约。
            return True

        handle.seek(0)
        fcntl = importlib.import_module("fcntl")
        try:
            getattr(fcntl, "flock")(
                handle.fileno(),
                int(getattr(fcntl, "LOCK_EX"))
                | int(getattr(fcntl, "LOCK_NB")),
            )
        except OSError:
            return False
        return True

    @staticmethod
    def _unlock_handle(handle: BinaryIO) -> None:
        """释放跨进程文件锁。"""
        if os.name == "nt":
            # Windows 共享模式租约由关闭 HANDLE 自动释放。
            return
        handle.seek(0)
        fcntl = importlib.import_module("fcntl")
        getattr(fcntl, "flock")(
            handle.fileno(),
            int(getattr(fcntl, "LOCK_UN")),
        )

    @classmethod
    def _session_lock_is_held(cls, lock_path: Path) -> bool:
        """兼容旧探测入口；真实租约使用持有式锁定。"""
        handle: Optional[BinaryIO] = None
        try:
            handle = cls._open_session_lock(lock_path)
            cls._ensure_lock_byte(handle)
            if not cls._try_lock_handle(handle):
                return True
            return False
        except OSError:
            return True
        finally:
            cls._release_session_lock(handle)

    def _release_reference(self, key: str, entry: _LockEntry) -> None:
        """Drop one user reference and delete idle lock entries."""
        with self._guard:
            entry.users -= 1
            if entry.users == 0 and self._entries.get(key) is entry:
                del self._entries[key]
