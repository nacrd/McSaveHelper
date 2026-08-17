"""Minecraft 世界目录的不可变只读索引。"""
from __future__ import annotations

import hashlib
import os
import stat
from fnmatch import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

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
from core.uuid_utils import normalize_uuid
from core.world_index_cache import (
    WorldIndexCacheGuard,
    build_world_index_cache_guard,
    is_world_index_cache_guard_current,
)
from core.world_index_progress import (
    WorldIndexBuildCancelledError,
    WorldIndexBuildPhase,
    WorldIndexCancelCheck,
    WorldIndexProgressCallback,
    WorldIndexProgressFrame,
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
    dimensions: tuple[DimensionRegionDirectory, ...]


@dataclass(frozen=True)
class WorldShellMetadata:
    """世界首屏轻量元数据（不做完整玩家/区域索引扫描）。"""

    world_path: Path
    display_name: str
    has_level_dat: bool
    overworld_region_count: int
    dimension_hint_count: int


@dataclass(frozen=True)
class WorldIndexSnapshot:
    """世界目录扫描结果的不可变快照。"""

    world_path: Path
    probe: WorldIndexProbe
    cache_guard: WorldIndexCacheGuard
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

    def shell_metadata(self, world_path: Path | str) -> WorldShellMetadata:
        """快速构造首屏元数据：目录名、level.dat 存在性与区域计数。

        不做完整 NBT/玩家扫描，供 UI 在完整索引前显示占位信息。
        """
        world = self._validate_world(world_path)
        display_name = world.name
        try:
            level_path = world / "level.dat"
            if level_path.is_file() and level_path.stat().st_size > 0:
                # Prefer folder name for speed; optional LevelName is expensive.
                display_name = world.name
        except OSError:
            pass
        overworld = 0
        region_dir = world / "region"
        if region_dir.is_dir():
            try:
                overworld = sum(1 for _ in region_dir.glob("r.*.*.mca"))
            except OSError:
                overworld = 0
        dim_hints = 0
        for relative in ("DIM-1/region", "DIM1/region", "dimensions"):
            candidate = world / relative
            if candidate.exists():
                dim_hints += 1
        return WorldShellMetadata(
            world_path=world,
            display_name=display_name,
            has_level_dat=(world / "level.dat").is_file(),
            overworld_region_count=overworld,
            dimension_hint_count=dim_hints,
        )

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
        return self._build_snapshot(world, self._current_probe(world))

    def build_progressive(
        self,
        world_path: Path | str,
        *,
        batch_size: int = 512,
        cancel_check: Optional[WorldIndexCancelCheck] = None,
        progress_callback: Optional[WorldIndexProgressCallback] = None,
    ) -> WorldIndexSnapshot:
        """以可取消批次构造完整索引，并发布不可变阶段帧。

        渐进帧不包含可供 ``WorldSession`` 使用的半成品快照；只有最终帧
        才携带完整索引。这样调用方可以展示冷启动进度，同时保持现有
        ``WorldIndexSnapshot`` 的完整性契约。

        Args:
            world_path: 含 ``level.dat`` 的世界根目录。
            batch_size: 每发布一次进度帧处理的路径数量。
            cancel_check: 在批次边界检查取消请求的回调。
            progress_callback: 接收不可变进度帧的回调。

        Returns:
            完整世界索引快照。

        Raises:
            WorldIndexBuildCancelledError: 构建期间收到取消请求。
            FileNotFoundError: 路径不是有效世界。
        """
        from core.world_index_progress import ProgressiveWorldIndexBuild

        operation = ProgressiveWorldIndexBuild(
            self,
            batch_size=batch_size,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        return operation.build(world_path)

    def _build_snapshot(
        self,
        world: Path,
        probe: WorldIndexProbe,
    ) -> WorldIndexSnapshot:
        """从同一份文件探针派生路径索引，避免扫描与签名发生漂移。"""
        paths = self._probe_paths_by_category(world, probe)
        player_files = tuple(sorted(
            self._select_player_files(world, paths["players"]).items()
        ))
        region_files = tuple(
            path for path in paths["regions"]
            if path.suffix.lower() == ".mca"
        )
        data_files = self._select_data_files(world, paths["data"])
        stats_files = paths["stats"]
        advancement_files = paths["advancements"]
        usercache = self._load_usercache(
            world,
            player_files,
            paths["usercache"],
        )
        dimensions = self._build_dimensions(region_files, probe.dimensions)
        return WorldIndexSnapshot(
            world_path=world,
            probe=probe,
            cache_guard=self._build_cache_guard(world, probe),
            player_files=player_files,
            region_files=region_files,
            data_files=data_files,
            stats_files=stats_files,
            advancement_files=advancement_files,
            usercache=usercache,
            dimensions=dimensions,
        )

    def _player_files_from_probe(
        self,
        world: Path,
        probe: WorldIndexProbe,
    ) -> tuple[tuple[str, Path], ...]:
        """Build the player index from the exact paths captured by a probe."""
        paths = self._probe_paths(world, probe, "players")
        return tuple(sorted(self._select_player_files(world, paths).items()))

    def _region_files_from_probe(
        self,
        world: Path,
        probe: WorldIndexProbe,
    ) -> tuple[Path, ...]:
        """Build the region index from the exact paths captured by a probe."""
        return tuple(sorted(
            (
                path
                for path in self._probe_paths(world, probe, "regions")
                if path.suffix.lower() == ".mca"
            ),
            key=str,
        ))

    def _data_files_from_probe(
        self,
        world: Path,
        probe: WorldIndexProbe,
    ) -> tuple[Path, ...]:
        """Build the data index from the exact paths captured by a probe."""
        paths = self._probe_paths(world, probe, "data")
        return self._select_data_files(world, paths)

    def _load_usercache(
        self,
        world: Path,
        player_files: tuple[tuple[str, Path], ...],
        available_paths: tuple[Path, ...],
    ) -> tuple[tuple[str, str], ...]:
        """Load names from the exact candidates represented by the probe."""
        from core.omni.world_scanner import load_usercache_candidate

        player_ids = {player_id for player_id, _path in player_files}
        available = set(available_paths)
        candidates = tuple(
            path for path in self._usercache_candidates(world)
            if path in available
        )
        best_cache: dict[str, str] = {}
        best_match = -1
        read_errors: list[OSError] = []
        for path in candidates:
            try:
                cache, match_count = load_usercache_candidate(path, player_ids)
            except OSError as exc:
                read_errors.append(exc)
                continue
            except (TypeError, ValueError, UnicodeError):
                continue
            if match_count > best_match:
                best_cache = cache
                best_match = match_count
            if match_count == len(player_ids):
                break
        if best_match < 0 and read_errors:
            raise OSError(
                f"读取 usercache 失败: {candidates[0]}"
            ) from read_errors[0]
        return tuple(sorted(best_cache.items()))

    def _probe_paths(
        self,
        world: Path,
        probe: WorldIndexProbe,
        category: str,
    ) -> tuple[Path, ...]:
        """Return deterministic paths of one category from a probe snapshot."""
        paths = {
            self._path_from_probe(world, stamp.relative_path)
            for stamp in probe.files
            if self._path_category(stamp.relative_path) == category
        }
        return tuple(sorted(paths, key=str))

    def _probe_paths_by_category(
        self,
        world: Path,
        probe: WorldIndexProbe,
    ) -> dict[str, tuple[Path, ...]]:
        """Partition all probe paths in one pass for a cold snapshot build."""
        categories: dict[str, set[Path]] = {
            "players": set(),
            "regions": set(),
            "data": set(),
            "stats": set(),
            "advancements": set(),
            "usercache": set(),
        }
        for stamp in probe.files:
            category = self._path_category(stamp.relative_path)
            paths = categories.get(category)
            if paths is not None:
                paths.add(self._path_from_probe(world, stamp.relative_path))
        return {
            category: tuple(sorted(paths, key=str))
            for category, paths in categories.items()
        }

    @staticmethod
    def _path_from_probe(world: Path, value: str) -> Path:
        """Resolve a world-relative or external probe path without I/O."""
        path = Path(value)
        return path if path.is_absolute() else world / path

    @staticmethod
    def _select_player_files(
        world: Path,
        paths: tuple[Path, ...],
    ) -> dict[str, Path]:
        """Apply the scanner's 26.1-first duplicate UUID precedence."""
        ordered = WorldIndexBuilder._order_paths_by_directories(
            paths,
            (world / "players" / "data", world / "playerdata"),
        )
        selected: dict[str, Path] = {}
        for path in ordered:
            selected.setdefault(normalize_uuid(path.stem), path)
        return selected

    @staticmethod
    def _select_data_files(
        world: Path,
        paths: tuple[Path, ...],
    ) -> tuple[Path, ...]:
        """Apply the scanner's 26.1-first duplicate filename precedence."""
        ordered = WorldIndexBuilder._order_paths_by_directories(
            paths,
            (world / "data" / "minecraft", world / "data"),
        )
        selected: dict[str, Path] = {}
        for path in ordered:
            selected.setdefault(path.name, path)
        return tuple(selected.values())

    @staticmethod
    def _order_paths_by_directories(
        paths: tuple[Path, ...],
        directories: Iterable[Path],
    ) -> tuple[Path, ...]:
        """Sort paths by configured directory precedence, then by path."""
        ranks = {directory: index for index, directory in enumerate(directories)}
        fallback_rank = len(ranks)
        return tuple(sorted(
            paths,
            key=lambda path: (ranks.get(path.parent, fallback_rank), str(path)),
        ))

    def probe(self, world_path: Path | str) -> WorldIndexProbe:
        """重新枚举相关文件并返回当前失效签名。"""
        world = self._validate_world(world_path)
        return self._current_probe(world)

    def _current_probe(self, world: Path) -> WorldIndexProbe:
        """为已经验证的世界生成当前完整探针。"""
        dimensions = tuple(discover_dimension_region_dirs(world))
        stamps, active_dimensions = self._enumerate_stamped_paths(
            world,
            dimensions,
        )
        return self._probe_from_stamps(world, stamps, active_dimensions)

    def is_cache_guard_current(self, snapshot: WorldIndexSnapshot) -> bool:
        """Return whether index membership can be reused without a full scan.

        File content changes do not invalidate path indexes. Directory metadata
        detects additions, removals, and renames, while ``level.dat`` and the
        parsed user-cache candidates are checked directly.

        Args:
            snapshot: Previously completed world index.

        Returns:
            True when the snapshot still describes the same indexed paths.
        """
        world = self._validate_world(snapshot.world_path)
        return is_world_index_cache_guard_current(
            world,
            snapshot.cache_guard,
        )

    def refresh(
        self,
        previous: WorldIndexSnapshot,
        *,
        current_probe: WorldIndexProbe | None = None,
    ) -> WorldIndexSnapshot:
        """探针未变复用快照，变化时仅重扫受影响的文件类别。

        Args:
            previous: 此前构建的不可变快照。
            current_probe: 调用方已经获取的当前探针，避免重复目录遍历。

        Returns:
            仍有效时返回同一 ``previous`` 实例，否则返回新快照。
        """
        world = self._validate_world(previous.world_path)
        if current_probe is None:
            current_probe = self._current_probe(world)
        if current_probe == previous.probe:
            return previous
        categories = self._changed_categories(previous.probe, current_probe)
        if "unknown" in categories:
            return self.build(world)
        return self._refresh_categories(
            previous,
            current_probe,
            categories,
        )

    def _refresh_categories(
        self,
        previous: WorldIndexSnapshot,
        current_probe: WorldIndexProbe,
        categories: set[str],
    ) -> WorldIndexSnapshot:
        """复用未变化分片，从同一份新探针派生变化类别。"""
        world = previous.world_path
        player_files = previous.player_files
        if "players" in categories:
            player_files = self._player_files_from_probe(world, current_probe)

        region_files = previous.region_files
        dimensions = previous.dimensions
        if "regions" in categories:
            region_files = self._region_files_from_probe(world, current_probe)
            dimensions = self._build_dimensions(
                region_files,
                current_probe.dimensions,
            )

        data_files = previous.data_files
        if "data" in categories:
            data_files = self._data_files_from_probe(world, current_probe)

        stats_files = previous.stats_files
        if "stats" in categories:
            stats_files = self._probe_paths(world, current_probe, "stats")

        advancement_files = previous.advancement_files
        if "advancements" in categories:
            advancement_files = self._probe_paths(
                world,
                current_probe,
                "advancements",
            )

        usercache = previous.usercache
        if categories.intersection({"players", "usercache"}):
            usercache = self._load_usercache(
                world,
                player_files,
                self._probe_paths(world, current_probe, "usercache"),
            )

        return WorldIndexSnapshot(
            world_path=world,
            probe=current_probe,
            cache_guard=self._build_cache_guard(world, current_probe),
            player_files=player_files,
            region_files=region_files,
            data_files=data_files,
            stats_files=stats_files,
            advancement_files=advancement_files,
            usercache=usercache,
            dimensions=dimensions,
        )

    @staticmethod
    def _changed_categories(
        previous: WorldIndexProbe,
        current: WorldIndexProbe,
    ) -> set[str]:
        """根据新增、删除或属性变化的文件推导需重扫的分片。"""
        old_stamps = {stamp.relative_path: stamp for stamp in previous.files}
        new_stamps = {stamp.relative_path: stamp for stamp in current.files}
        changed_paths = {
            path
            for path in old_stamps.keys() | new_stamps.keys()
            if old_stamps.get(path) != new_stamps.get(path)
        }
        categories = {
            WorldIndexBuilder._path_category(path)
            for path in changed_paths
        }
        if previous.dimensions != current.dimensions:
            categories.add("regions")
        return categories

    @staticmethod
    def _path_category(relative_path: str) -> str:
        """把探针路径映射到一个可独立更新的索引分片。"""
        normalized = relative_path.replace("\\", "/").lower()
        parts = tuple(part for part in normalized.split("/") if part)
        name = parts[-1] if parts else normalized
        if name == "usercache.json":
            return "usercache"
        if normalized == "level.dat":
            return "level"
        if name == "region":
            return "regions"
        if name.endswith(".mca") and "region" in parts:
            return "regions"
        if name.endswith(".dat") and (
            "playerdata" in parts
            or WorldIndexBuilder._contains_parts(parts, "players", "data")
        ):
            return "players"
        if name.endswith(".json") and "stats" in parts:
            return "stats"
        if name.endswith(".json") and "advancements" in parts:
            return "advancements"
        if name.endswith(".dat") and "data" in parts:
            return "data"
        return "unknown"

    @staticmethod
    def _contains_parts(
        parts: tuple[str, ...],
        parent: str,
        child: str,
    ) -> bool:
        """判断路径部件中是否出现相邻的 parent/child。"""
        return any(
            left == parent and right == child
            for left, right in zip(parts, parts[1:])
        )

    def _enumerate_stamped_paths(
        self,
        world: Path,
        dimensions: tuple[DimensionRegionDirectory, ...],
    ) -> tuple[tuple[WorldFileStamp, ...], tuple[DimensionRegionDirectory, ...]]:
        """枚举相关文件，并复用安全检查读取的属性生成签名。"""
        metadata_by_path: dict[Path, os.stat_result] = {}
        player_files = self._glob_files(
            find_player_data_dirs(world),
            "*.dat",
            metadata_by_path,
        )
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
        data_files = self._glob_files(
            find_data_dirs(world),
            "*.dat",
            metadata_by_path,
        )
        stats_files = self._glob_files(
            find_stats_dirs(world),
            "*.json",
            metadata_by_path,
        )
        advancement_files = self._glob_files(
            find_advancements_dirs(world),
            "*.json",
            metadata_by_path,
        )
        stamps_by_path = self._stamped_paths(
            world,
            player_files=player_files,
            region_files=region_files,
            data_files=data_files,
            stats_files=stats_files,
            advancement_files=advancement_files,
            metadata_by_path=metadata_by_path,
        )
        safe_paths = set(stamps_by_path)
        active_region_dirs = {
            path.parent for path in region_files if path in safe_paths
        }
        directory_safety: dict[Path, bool] = {}
        for region_dir in active_region_dirs:
            stamp = self._world_content_stamp(
                world,
                region_dir,
                directory_safety,
            )
            if stamp is not None:
                stamps_by_path[region_dir] = stamp
        active_dimensions = tuple(
            dimension
            for dimension in dimensions
            if dimension.region_dir in active_region_dirs
        )
        return tuple(sorted(stamps_by_path.values())), active_dimensions

    def _build_dimensions(
        self,
        region_files: tuple[Path, ...],
        dimensions: tuple[DimensionRegionDirectory, ...],
    ) -> tuple[WorldDimensionIndex, ...]:
        """按同一探针的维度描述和文件分组构造维度索引。"""
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
            for dimension in dimensions
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
        extra_paths: Iterable[Path] = (),
        metadata_by_path: Optional[dict[Path, os.stat_result]] = None,
    ) -> dict[Path, WorldFileStamp]:
        """汇总安全路径，并保留其已读取的文件属性。"""
        world_paths = {
            world / "level.dat",
            *player_files,
            *region_files,
            *data_files,
            *stats_files,
            *advancement_files,
            *extra_paths,
        }
        directory_safety: dict[Path, bool] = {}
        known_metadata = metadata_by_path or {}
        stamps_by_path: dict[Path, WorldFileStamp] = {}
        for path in world_paths:
            stamp = self._world_content_stamp(
                world,
                path,
                directory_safety,
                metadata=known_metadata.get(path),
            )
            if stamp is not None:
                stamps_by_path[path] = stamp
        for candidate in self._usercache_candidates(world):
            if self._is_lexically_within(candidate, world):
                stamp = self._world_content_stamp(
                    world,
                    candidate,
                    directory_safety,
                )
            else:
                stamp = self._external_file_stamp(world, candidate)
            if stamp is not None:
                stamps_by_path[candidate] = stamp
        return stamps_by_path

    @staticmethod
    def _world_content_stamp(
        world: Path,
        path: Path,
        directory_safety: dict[Path, bool],
        *,
        metadata: Optional[os.stat_result] = None,
    ) -> Optional[WorldFileStamp]:
        """Return one stamp after validating a world-contained path once."""
        candidate = path.absolute()
        metadata = WorldIndexBuilder._safe_world_content_metadata(
            world,
            candidate,
            directory_safety,
            metadata=metadata,
        )
        if metadata is None:
            return None
        relative_path = os.path.relpath(candidate, world).replace(os.sep, "/")
        return WorldIndexBuilder._stamp_from_metadata(relative_path, metadata)

    @staticmethod
    def _external_file_stamp(
        world: Path,
        path: Path,
    ) -> Optional[WorldFileStamp]:
        """Return a stamp for an explicit external user-cache candidate."""
        try:
            metadata = path.stat()
        except OSError:
            return None
        if not stat.S_ISREG(metadata.st_mode):
            return None
        return WorldIndexBuilder._stamp_from_metadata(
            WorldIndexBuilder._display_path(world, path),
            metadata,
        )

    @staticmethod
    def _stamp_from_metadata(
        relative_path: str,
        metadata: os.stat_result,
    ) -> WorldFileStamp:
        """Build a deterministic file stamp without another filesystem call."""
        return WorldFileStamp(
            relative_path=relative_path,
            size=metadata.st_size,
            modified_ns=metadata.st_mtime_ns,
        )

    def _build_cache_guard(
        self,
        world: Path,
        probe: WorldIndexProbe,
    ) -> WorldIndexCacheGuard:
        """Capture the directory and mutable-file state for a snapshot."""
        indexed_paths = (
            self._path_from_probe(world, stamp.relative_path)
            for stamp in probe.files
        )
        return build_world_index_cache_guard(
            world,
            indexed_paths,
            (dimension.region_dir for dimension in probe.dimensions),
            (world / "level.dat", *self._usercache_candidates(world)),
        )

    @staticmethod
    def _is_safe_world_content_path(world: Path, path: Path) -> bool:
        """Reject linked or escaped paths discovered inside the world tree."""
        return WorldIndexBuilder._is_safe_world_content_path_cached(
            world,
            path,
            {},
        )

    @staticmethod
    def _is_safe_world_content_path_cached(
        world: Path,
        path: Path,
        directory_safety: dict[Path, bool],
    ) -> bool:
        """Validate each parent chain once, then reject linked leaf files."""
        return WorldIndexBuilder._safe_world_content_metadata(
            world,
            path,
            directory_safety,
        ) is not None

    @staticmethod
    def _safe_world_content_metadata(
        world: Path,
        path: Path,
        directory_safety: dict[Path, bool],
        *,
        metadata: Optional[os.stat_result] = None,
    ) -> Optional[os.stat_result]:
        """Validate one path and return the metadata already read for it."""
        candidate = path.absolute()
        if metadata is None:
            try:
                metadata = candidate.lstat()
            except OSError:
                return None
        file_attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_attribute = getattr(
            stat,
            "FILE_ATTRIBUTE_REPARSE_POINT",
            0x400,
        )
        if stat.S_ISLNK(metadata.st_mode) or file_attributes & reparse_attribute:
            return None
        is_directory = stat.S_ISDIR(metadata.st_mode)
        if not is_directory and not stat.S_ISREG(metadata.st_mode):
            return None
        directory = candidate if is_directory else candidate.parent
        is_safe_directory = directory_safety.get(directory)
        if is_safe_directory is None:
            is_safe_directory = WorldIndexBuilder._is_safe_world_directory(
                world,
                directory,
            )
            directory_safety[directory] = is_safe_directory
        if not is_safe_directory:
            return None
        return metadata

    @staticmethod
    def _is_safe_world_directory(world: Path, directory: Path) -> bool:
        """Validate one content directory and every world-relative ancestor."""
        try:
            relative = directory.relative_to(world)
        except ValueError:
            return False
        current = world
        for part in relative.parts:
            current /= part
            is_junction = getattr(current, "is_junction", lambda: False)
            if current.is_symlink() or bool(is_junction()):
                return False
        try:
            directory.resolve().relative_to(world)
        except (OSError, RuntimeError, ValueError):
            return False
        return True

    @staticmethod
    def _is_lexically_within(path: Path, root: Path) -> bool:
        """Return whether a path is expressed below root without resolving links."""
        try:
            path.absolute().relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _probe_from_stamps(
        world: Path,
        stamps: Iterable[WorldFileStamp],
        dimensions: tuple[DimensionRegionDirectory, ...],
    ) -> WorldIndexProbe:
        """从已读取的文件签名生成确定性探针。"""
        ordered_stamps = tuple(sorted(stamps))
        digest = hashlib.sha256()
        for stamp in ordered_stamps:
            digest.update(
                f"{stamp.relative_path}\0{stamp.size}\0{stamp.modified_ns}\n".encode(
                    "utf-8"
                )
            )
        for dimension in dimensions:
            digest.update(
                (
                    f"{dimension.id}\0{dimension.name}\0"
                    f"{WorldIndexBuilder._display_path(world, dimension.region_dir)}\0"
                    f"{dimension.coordinate_scale}\n"
                ).encode("utf-8")
            )
        return WorldIndexProbe(
            digest.hexdigest(),
            ordered_stamps,
            dimensions,
        )

    @staticmethod
    def _display_path(world: Path, path: Path) -> str:
        """世界内使用相对路径，外部 usercache 使用绝对规范路径。"""
        absolute = path.absolute()
        try:
            return absolute.relative_to(world).as_posix()
        except ValueError:
            pass
        resolved = path.resolve()
        return str(resolved)

    @staticmethod
    def _glob_files(
        directories: Iterable[Path],
        pattern: str,
        metadata_by_path: Optional[dict[Path, os.stat_result]] = None,
    ) -> tuple[Path, ...]:
        """Enumerate direct files and retain their non-following metadata."""
        files: set[Path] = set()
        for directory in directories:
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if not fnmatch(entry.name, pattern):
                            continue
                        try:
                            metadata = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if not stat.S_ISREG(metadata.st_mode):
                            continue
                        path = directory / entry.name
                        files.add(path)
                        if metadata_by_path is not None:
                            metadata_by_path[path] = metadata
            except OSError:
                continue
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
    "WorldIndexBuildCancelledError",
    "WorldIndexBuildPhase",
    "WorldIndexCacheGuard",
    "WorldDimensionIndex",
    "WorldFileStamp",
    "WorldIndexBuilder",
    "WorldIndexCancelCheck",
    "WorldIndexProgressCallback",
    "WorldIndexProgressFrame",
    "WorldIndexProbe",
    "WorldIndexSnapshot",
    "WorldShellMetadata",
]
