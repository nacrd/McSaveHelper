"""Minecraft 世界目录的不可变只读索引。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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


@dataclass(frozen=True, order=True)
class WorldFileStamp:
    """相对路径及其失效所需文件属性。"""

    relative_path: str
    size: int
    modified_ns: int


@dataclass(frozen=True)
class WorldDimensionIndex:
    """一个维度的展示信息和有序区域文件。"""

    id: str
    name: str
    region_dir: Path
    coordinate_scale: float
    region_files: tuple[Path, ...]


@dataclass(frozen=True)
class WorldIndexProbe:
    """判断目录索引是否失效的轻量文件签名集合。"""

    fingerprint: str
    files: tuple[WorldFileStamp, ...]


@dataclass(frozen=True)
class WorldIndexSnapshot:
    """世界目录扫描结果的不可变快照。"""

    world_path: Path
    probe: WorldIndexProbe
    player_files: tuple[tuple[str, Path], ...]
    region_files: tuple[Path, ...]
    data_files: tuple[Path, ...]
    stats_files: tuple[Path, ...]
    advancement_files: tuple[Path, ...]
    usercache: tuple[tuple[str, str], ...]
    dimensions: tuple[WorldDimensionIndex, ...]

    def player_file_map(self) -> dict[str, Path]:
        """返回可由会话独立持有的玩家文件映射副本。"""
        return dict(self.player_files)

    def usercache_map(self) -> dict[str, str]:
        """返回玩家 UUID 到名称的映射副本。"""
        return dict(self.usercache)

    def region_file_map(self) -> dict[str, Path]:
        """返回相对路径到区域文件的稳定映射。"""
        return {
            path.relative_to(self.world_path).as_posix(): path
            for path in self.region_files
        }


class WorldIndexBuilder:
    """扫描一个世界目录并构造可复用读模型。"""

    def build(self, world_path: Path | str) -> WorldIndexSnapshot:
        """扫描有效世界并返回不可变快照。

        Args:
            world_path: 含 ``level.dat`` 的世界根目录。

        Returns:
            完整世界索引快照。

        Raises:
            FileNotFoundError: 路径不是有效世界。
        """
        world = self._validate_world(world_path)
        from core.omni.world_scanner import WorldScanner

        scanner = WorldScanner(world)
        scanned = scanner.scan_all()
        player_files = tuple(sorted(scanned["player_files"].items()))
        region_files = tuple(
            sorted(set(scanned["region_files"].values()), key=str)
        )
        data_files = tuple(sorted(set(scanned["data_files"]), key=str))
        stats_files = self._glob_files(find_stats_dirs(world), "*.json")
        advancement_files = self._glob_files(
            find_advancements_dirs(world),
            "*.json",
        )
        usercache = tuple(sorted(scanned["usercache"].items()))
        dimensions = self._build_dimensions(world, region_files)
        stamped_paths = self._stamped_paths(
            world,
            player_files=(path for _, path in player_files),
            region_files=region_files,
            data_files=data_files,
            stats_files=stats_files,
            advancement_files=advancement_files,
        )
        return WorldIndexSnapshot(
            world_path=world,
            probe=self._probe_from_paths(world, stamped_paths),
            player_files=player_files,
            region_files=region_files,
            data_files=data_files,
            stats_files=stats_files,
            advancement_files=advancement_files,
            usercache=usercache,
            dimensions=dimensions,
        )

    def probe(self, world_path: Path | str) -> WorldIndexProbe:
        """重新枚举相关文件并返回当前失效签名。"""
        world = self._validate_world(world_path)
        return self._probe_from_paths(world, self._enumerate_stamped_paths(world))

    def refresh(
        self,
        previous: WorldIndexSnapshot,
    ) -> WorldIndexSnapshot:
        """探针未变则复用快照，否则全量重建（增量一致性入口）。

        Args:
            previous: 此前构建的不可变快照。

        Returns:
            仍有效时返回同一 ``previous`` 实例，否则返回新快照。
        """
        world = self._validate_world(previous.world_path)
        current_probe = self._probe_from_paths(
            world,
            self._enumerate_stamped_paths(world),
        )
        if current_probe == previous.probe:
            return previous
        return self.build(world)

    def _enumerate_stamped_paths(self, world: Path) -> tuple[Path, ...]:
        """枚举会影响读模型的全部文件路径。"""
        player_files = self._glob_files(find_player_data_dirs(world), "*.dat")
        dimensions = discover_dimension_region_dirs(world)
        region_files = tuple(
            sorted(
                {
                    path
                    for dimension in dimensions
                    for path in scan_region_dir(dimension.region_dir)
                },
                key=str,
            )
        )
        data_files = self._glob_files(find_data_dirs(world), "*.dat")
        stats_files = self._glob_files(find_stats_dirs(world), "*.json")
        advancement_files = self._glob_files(
            find_advancements_dirs(world),
            "*.json",
        )
        return self._stamped_paths(
            world,
            player_files=player_files,
            region_files=region_files,
            data_files=data_files,
            stats_files=stats_files,
            advancement_files=advancement_files,
        )

    def _build_dimensions(
        self,
        world: Path,
        region_files: tuple[Path, ...],
    ) -> tuple[WorldDimensionIndex, ...]:
        """按已扫描文件分组构造维度索引，避免再次枚举目录。"""
        files_by_directory: dict[Path, list[Path]] = {}
        for region_file in region_files:
            files_by_directory.setdefault(region_file.parent, []).append(
                region_file
            )
        return tuple(
            self._build_dimension(
                dimension,
                tuple(files_by_directory.get(dimension.region_dir, ())),
            )
            for dimension in discover_dimension_region_dirs(world)
        )

    @staticmethod
    def _build_dimension(
        dimension: DimensionRegionDirectory,
        region_files: tuple[Path, ...],
    ) -> WorldDimensionIndex:
        """把底层维度目录转换为不可变索引项。"""
        return WorldDimensionIndex(
            id=dimension.id,
            name=dimension.name,
            region_dir=dimension.region_dir,
            coordinate_scale=dimension.coordinate_scale,
            region_files=region_files,
        )

    def _stamped_paths(
        self,
        world: Path,
        *,
        player_files: Iterable[Path],
        region_files: Iterable[Path],
        data_files: Iterable[Path],
        stats_files: Iterable[Path],
        advancement_files: Iterable[Path],
    ) -> tuple[Path, ...]:
        """汇总所有会改变读模型的文件路径。"""
        paths = {
            world / "level.dat",
            *player_files,
            *region_files,
            *data_files,
            *stats_files,
            *advancement_files,
            *self._usercache_candidates(world),
        }
        return tuple(sorted((path for path in paths if path.is_file()), key=str))

    @staticmethod
    def _probe_from_paths(
        world: Path,
        paths: Iterable[Path],
    ) -> WorldIndexProbe:
        """为有序路径生成确定性 SHA-256 签名。"""
        stamps: list[WorldFileStamp] = []
        for path in paths:
            try:
                stats = path.stat()
                relative = WorldIndexBuilder._display_path(world, path)
                stamps.append(
                    WorldFileStamp(
                        relative_path=relative,
                        size=stats.st_size,
                        modified_ns=stats.st_mtime_ns,
                    )
                )
            except OSError:
                continue
        stamps.sort()
        digest = hashlib.sha256()
        for stamp in stamps:
            digest.update(
                f"{stamp.relative_path}\0{stamp.size}\0{stamp.modified_ns}\n".encode(
                    "utf-8"
                )
            )
        return WorldIndexProbe(digest.hexdigest(), tuple(stamps))

    @staticmethod
    def _display_path(world: Path, path: Path) -> str:
        """世界内使用相对路径，外部 usercache 使用绝对规范路径。"""
        resolved = path.resolve()
        try:
            return resolved.relative_to(world).as_posix()
        except ValueError:
            return str(resolved)

    @staticmethod
    def _glob_files(
        directories: Iterable[Path],
        pattern: str,
    ) -> tuple[Path, ...]:
        """确定性枚举存在目录中的直接文件。"""
        files = {
            path
            for directory in directories
            if directory.is_dir()
            for path in directory.glob(pattern)
            if path.is_file()
        }
        return tuple(sorted(files, key=str))

    @staticmethod
    def _usercache_candidates(world: Path) -> tuple[Path, ...]:
        """返回与 WorldScanner 一致的有限 usercache 候选集合。"""
        candidates = [world / "usercache.json", world.parent / "usercache.json"]
        current = world
        for _ in range(5):
            parent = current.parent
            if parent == current:
                break
            if parent.name == ".minecraft":
                candidates.append(parent / "usercache.json")
                break
            current = parent
        return tuple(dict.fromkeys(candidates))

    @staticmethod
    def _validate_world(world_path: Path | str) -> Path:
        """规范化并验证世界根目录。"""
        world = Path(world_path).expanduser().resolve()
        if not world.is_dir() or not (world / "level.dat").is_file():
            raise FileNotFoundError(f"不是有效 Minecraft 存档: {world}")
        return world


__all__ = [
    "WorldDimensionIndex",
    "WorldFileStamp",
    "WorldIndexBuilder",
    "WorldIndexProbe",
    "WorldIndexSnapshot",
]
