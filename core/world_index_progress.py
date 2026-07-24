"""可取消的 WorldIndex 渐进构建协议与批次实现。"""
from __future__ import annotations

import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, Optional

from core.region_utils import (
    DimensionRegionDirectory,
    discover_dimension_region_dirs,
    scan_region_dir,
)
from core.utils import (
    find_advancements_dirs,
    find_data_dirs,
    find_player_data_dirs,
    find_stats_dirs,
)

if TYPE_CHECKING:
    from core.world_index import (
        WorldIndexBuilder,
        WorldIndexProbe,
        WorldIndexSnapshot,
    )


class WorldIndexBuildCancelledError(RuntimeError):
    """渐进世界索引在安全检查点收到取消请求。"""


class WorldIndexBuildPhase(str, Enum):
    """渐进世界索引构建阶段。"""

    VALIDATING = "validating"
    DISCOVERING = "discovering"
    PROBING = "probing"
    FINALIZING = "finalizing"
    COMPLETE = "complete"


@dataclass(frozen=True)
class WorldIndexProgressFrame:
    """渐进索引构建对外发布的不可变进度帧。"""

    world_path: Path
    phase: WorldIndexBuildPhase
    completed: int
    total: Optional[int]
    discovered_files: int
    stamped_files: int
    is_complete: bool = False
    snapshot: Optional[WorldIndexSnapshot] = None


WorldIndexCancelCheck = Callable[[], bool]
WorldIndexProgressCallback = Callable[[WorldIndexProgressFrame], None]


class ProgressiveWorldIndexBuild:
    """单次渐进索引构建，最终仍产出完整 ``WorldIndexSnapshot``。"""

    def __init__(
        self,
        builder: WorldIndexBuilder,
        *,
        batch_size: int,
        cancel_check: Optional[WorldIndexCancelCheck],
        progress_callback: Optional[WorldIndexProgressCallback],
    ) -> None:
        """绑定索引构建器与单次构建端口。"""
        if batch_size < 1:
            raise ValueError("世界索引渐进批次必须至少为 1")
        self._builder = builder
        self._batch_size = batch_size
        self._cancel_check = cancel_check
        self._progress_callback = progress_callback

    def build(self, world_path: Path | str) -> WorldIndexSnapshot:
        """执行可取消批次扫描，并在完成后返回完整快照。"""
        self._check_cancel()
        world = self._builder._validate_world(world_path)
        self._publish(
            WorldIndexProgressFrame(
                world,
                WorldIndexBuildPhase.VALIDATING,
                1,
                1,
                0,
                0,
            )
        )
        self._check_cancel()
        dimensions = tuple(discover_dimension_region_dirs(world))
        paths, active_dimensions = self._enumerate_paths(world, dimensions)
        probe = self._probe_paths(world, paths, active_dimensions)
        self._check_cancel()
        self._publish(
            WorldIndexProgressFrame(
                world,
                WorldIndexBuildPhase.FINALIZING,
                1,
                1,
                len(paths),
                len(probe.files),
            )
        )
        snapshot = self._builder._build_snapshot(world, probe)
        self._check_cancel()
        self._publish(
            WorldIndexProgressFrame(
                world,
                WorldIndexBuildPhase.COMPLETE,
                1,
                1,
                len(paths),
                len(probe.files),
                is_complete=True,
                snapshot=snapshot,
            )
        )
        return snapshot

    def _check_cancel(self) -> None:
        """在渐进扫描安全检查点检查取消请求。"""
        if self._cancel_check is not None and self._cancel_check():
            raise WorldIndexBuildCancelledError("世界索引构建已取消")

    def _publish(self, frame: WorldIndexProgressFrame) -> None:
        """向调用方发布一份不可变进度帧。"""
        if self._progress_callback is not None:
            self._progress_callback(frame)

    def _enumerate_paths(
        self,
        world: Path,
        dimensions: tuple[DimensionRegionDirectory, ...],
    ) -> tuple[tuple[Path, ...], tuple[DimensionRegionDirectory, ...]]:
        """分批枚举并验证影响索引的路径。"""
        paths: set[Path] = set()
        directory_safety: dict[Path, bool] = {}
        discovered = 0
        pending = 0

        def collect(path: Path, *, allow_external: bool = False) -> None:
            nonlocal discovered, pending
            self._check_cancel()
            discovered += 1
            if allow_external:
                is_accepted = path.is_file()
            else:
                is_accepted = self._is_safe_path(
                    world,
                    path,
                    directory_safety,
                )
            if is_accepted:
                paths.add(path)
            pending += 1
            if pending >= self._batch_size:
                self._publish_discovery(world, discovered, len(paths))
                pending = 0

        collect(world / "level.dat")
        for directories, pattern in self._path_sources(world):
            for path in self._iter_glob_files(directories, pattern):
                collect(path)
        for dimension in dimensions:
            for path in scan_region_dir(dimension.region_dir):
                collect(path)
        for candidate in self._builder._usercache_candidates(world):
            if self._builder._is_lexically_within(candidate, world):
                collect(candidate)
            else:
                collect(candidate, allow_external=True)
        if pending:
            self._publish_discovery(world, discovered, len(paths))
        active_region_dirs = {
            path.parent for path in paths if path.suffix.lower() == ".mca"
        }
        paths.update(active_region_dirs)
        active_dimensions = tuple(
            dimension
            for dimension in dimensions
            if dimension.region_dir in active_region_dirs
        )
        return tuple(sorted(paths, key=str)), active_dimensions

    def _is_safe_path(
        self,
        world: Path,
        path: Path,
        directory_safety: dict[Path, bool],
    ) -> bool:
        """用一次 lstat 验证世界内常规文件及其父目录。"""
        candidate = path.absolute()
        try:
            candidate.relative_to(world)
            metadata = candidate.lstat()
        except (OSError, ValueError):
            return False
        if not stat.S_ISREG(metadata.st_mode):
            return False
        directory = candidate.parent
        is_safe_directory = directory_safety.get(directory)
        if is_safe_directory is None:
            is_safe_directory = self._builder._is_safe_world_directory(
                world,
                directory,
            )
            directory_safety[directory] = is_safe_directory
        return is_safe_directory

    @staticmethod
    def _path_sources(
        world: Path,
    ) -> tuple[tuple[Iterable[Path], str], ...]:
        """返回按稳定类别顺序扫描的目录与模式。"""
        return (
            (find_player_data_dirs(world), "*.dat"),
            (find_data_dirs(world), "*.dat"),
            (find_stats_dirs(world), "*.json"),
            (find_advancements_dirs(world), "*.json"),
        )

    @staticmethod
    def _iter_glob_files(
        directories: Iterable[Path],
        pattern: str,
    ) -> Iterable[Path]:
        """逐项枚举直接文件，避免先物化整个目录。"""
        for directory in directories:
            if not directory.is_dir():
                continue
            try:
                for path in directory.glob(pattern):
                    yield path
            except OSError:
                continue

    def _publish_discovery(
        self,
        world: Path,
        completed: int,
        discovered_files: int,
    ) -> None:
        """发布路径发现阶段的一个批次。"""
        self._publish(
            WorldIndexProgressFrame(
                world,
                WorldIndexBuildPhase.DISCOVERING,
                completed,
                None,
                discovered_files,
                0,
            )
        )

    def _probe_paths(
        self,
        world: Path,
        paths: tuple[Path, ...],
        dimensions: tuple[DimensionRegionDirectory, ...],
    ) -> WorldIndexProbe:
        """分批读取文件属性并生成最终探针。"""
        from core.world_index import WorldFileStamp

        stamps: list[WorldFileStamp] = []
        total = len(paths)
        for index, path in enumerate(paths, start=1):
            self._check_cancel()
            try:
                stats = path.stat()
                stamps.append(
                    WorldFileStamp(
                        self._builder._display_path(world, path),
                        stats.st_size,
                        stats.st_mtime_ns,
                    )
                )
            except OSError:
                continue
            if index % self._batch_size == 0 or index == total:
                self._publish(
                    WorldIndexProgressFrame(
                        world,
                        WorldIndexBuildPhase.PROBING,
                        index,
                        total,
                        total,
                        len(stamps),
                    )
                )
        stamps.sort()
        return self._builder._probe_from_stamps(world, stamps, dimensions)


__all__ = [
    "ProgressiveWorldIndexBuild",
    "WorldIndexBuildCancelledError",
    "WorldIndexBuildPhase",
    "WorldIndexCancelCheck",
    "WorldIndexProgressCallback",
    "WorldIndexProgressFrame",
]
