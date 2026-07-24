"""世界只读仓库：统一索引、会话装配与失效。

Explorer、统计、对比等读路径应通过本仓库获取不可变索引和会话，
避免在 UI 中直接拼装 WorldIndexRegistry 细节。
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from app.services.world_index_service import (
    WorldIndexCacheStats,
    WorldIndexRegistry,
)
from core.omni.world_session import WorldSession
from core.types import LogCallback
from core.world_index import WorldIndexBuilder, WorldIndexSnapshot, WorldShellMetadata


WorldMutation = Callable[[Path], Any]
CancelCheck = Callable[[], bool]
TransactionCallback = Callable[
    [Path, WorldMutation, Optional[CancelCheck]],
    Any,
]
WriteLeaseFactory = Callable[[Path], AbstractContextManager[Any]]
BackupCallback = Callable[[Path], Path]


@dataclass(frozen=True)
class WorldSessionPorts:
    """装配 WorldSession 时可选的应用写安全端口。"""

    write_lease_factory: Optional[WriteLeaseFactory] = None
    backup_callback: Optional[BackupCallback] = None
    transaction_callback: Optional[TransactionCallback] = None


@dataclass(frozen=True)
class WorldReadContext:
    """A lightweight, immutable handle for one validated world.

    Constructing this context only validates the world and reads shell metadata.
    Full directory indexing remains lazy until :meth:`get_index` or
    :meth:`open_session` is called.

    Attributes:
        world_path: Normalized world root.
        shell: Metadata suitable for the first UI paint.
    """

    world_path: Path
    shell: WorldShellMetadata
    _index_loader: Callable[[bool], WorldIndexSnapshot] = field(
        repr=False,
        compare=False,
    )
    _session_loader: Callable[
        [Optional[LogCallback], bool],
        WorldSession,
    ] = field(repr=False, compare=False)

    def get_index(
        self,
        *,
        force_refresh: bool = False,
    ) -> WorldIndexSnapshot:
        """Load or reuse the full immutable index for this world.

        Args:
            force_refresh: Whether to bypass the cached snapshot.

        Returns:
            The current full world index.
        """
        return self._index_loader(force_refresh)

    def open_session(
        self,
        *,
        log: Optional[LogCallback] = None,
        force_refresh: bool = False,
    ) -> WorldSession:
        """Open a session after lazily obtaining the shared index.

        Args:
            log: Optional session log callback.
            force_refresh: Whether to rebuild the index first.

        Returns:
            A world session backed by the application read model.
        """
        return self._session_loader(log, force_refresh)


class WorldRepository:
    """共享世界读模型：索引缓存 + 会话工厂。"""

    def __init__(
        self,
        indexes: WorldIndexRegistry,
        *,
        default_ports: Optional[WorldSessionPorts] = None,
    ) -> None:
        """注入索引注册表与默认会话写端口。

        Args:
            indexes: 应用作用域世界索引缓存。
            default_ports: 可选默认写安全端口，供会话提交使用。
        """
        self._indexes = indexes
        self._default_ports = default_ports or WorldSessionPorts()

    def get_index(
        self,
        world_path: Path | str,
        *,
        force_refresh: bool = False,
    ) -> WorldIndexSnapshot:
        """返回世界只读索引快照。"""
        return self._indexes.get(world_path, force_refresh=force_refresh)

    def open(self, world_path: Path | str) -> WorldReadContext:
        """Validate a world and return a lightweight read context.

        This method intentionally does not build the full directory index or
        parse ``level.dat``. Callers can publish :attr:`WorldReadContext.shell`
        immediately, then load the full index on the shared runtime.

        Args:
            world_path: World root containing ``level.dat``.

        Returns:
            A lazy, immutable read context for the normalized world.

        Raises:
            FileNotFoundError: The path is not a valid world.
        """
        shell = self.get_shell_metadata(world_path)
        world = shell.world_path
        return WorldReadContext(
            world_path=world,
            shell=shell,
            _index_loader=lambda force_refresh: self.get_index(
                world,
                force_refresh=force_refresh,
            ),
            _session_loader=lambda log, force_refresh: self.open_session(
                world,
                log=log,
                force_refresh=force_refresh,
            ),
        )

    def get_shell_metadata(
        self,
        world_path: Path | str,
    ) -> WorldShellMetadata:
        """返回首屏轻量元数据（完整索引之前可用）。"""
        return WorldIndexBuilder().shell_metadata(world_path)

    def open_session(
        self,
        world_path: Path | str,
        *,
        log: Optional[LogCallback] = None,
        force_refresh: bool = False,
    ) -> WorldSession:
        """打开带共享索引的世界会话。

        Args:
            world_path: 有效世界根路径。
            log: 可选日志回调。
            force_refresh: 是否强制重建索引。

        Returns:
            已注入索引快照的 WorldSession。
        """
        world = Path(world_path).expanduser().resolve()
        snapshot = self.get_index(world, force_refresh=force_refresh)
        selected = self._default_ports
        return WorldSession(
            world,
            log=log,
            index_snapshot=snapshot,
            write_lease_factory=selected.write_lease_factory,
            backup_callback=selected.backup_callback,
            transaction_callback=selected.transaction_callback,
            index_provider=self._provide_index,
        )

    def _provide_index(
        self,
        world_path: Path,
        force_refresh: bool,
    ) -> WorldIndexSnapshot:
        """为会话刷新提供同一注册表中的最新索引快照。"""
        return self.get_index(world_path, force_refresh=force_refresh)

    def invalidate(self, world_path: Path | str) -> None:
        """丢弃一个世界的缓存索引。"""
        self._indexes.invalidate(world_path)

    def clear(self) -> None:
        """清空全部索引缓存。"""
        self._indexes.clear()

    def stats(self) -> WorldIndexCacheStats:
        """返回索引缓存可观测统计。"""
        return self._indexes.stats()

    def close(self) -> None:
        """关闭底层索引注册表。"""
        self._indexes.close()


__all__ = [
    "WorldReadContext",
    "WorldRepository",
    "WorldSessionPorts",
    "WorldShellMetadata",
]
