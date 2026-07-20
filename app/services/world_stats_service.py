"""存档统计服务 - 收集和分析存档统计数据"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.omni.player_manager import PlayerManager
from core.omni.world_scanner import WorldScanner
from core.region_utils import (
    discover_dimension_region_dirs,
    parse_region_coords,
    scan_region_dir,
)
from core.scanner import scan_all_regions
from core.types import LogCallback
from core.utils import find_stats_dirs


def _default_log(msg: str, lvl: str = "INFO") -> None:
    pass


@dataclass
class BlockStats:
    """方块统计信息"""
    total_count: int = 0
    block_types: Dict[str, int] = field(default_factory=dict)
    top_blocks: List[Tuple[str, int]] = field(default_factory=list)


@dataclass
class EntityStats:
    """实体统计信息"""
    total_count: int = 0
    entity_types: Dict[str, int] = field(default_factory=dict)
    top_entities: List[Tuple[str, int]] = field(default_factory=list)


@dataclass(frozen=True)
class DimensionSizeStats:
    """单个维度的区域文件规模。"""

    dimension_id: str
    display_name: str
    region_count: int
    total_bytes: int


@dataclass(frozen=True)
class PlayerPlaytimeStats:
    """单个玩家的 stats JSON 摘要。"""

    uuid: str
    name: Optional[str]
    play_time_ticks: int
    total_world_time_ticks: int
    deaths: int
    mob_kills: int
    player_kills: int = 0
    mined: int = 0
    placed: int = 0
    jumps: int = 0
    damage_dealt: int = 0
    distance_cm: int = 0


# Sort keys used by the Explorer stats UI and pure sort helper.
PLAYER_SORT_PLAY_TIME = "play_time"
PLAYER_SORT_WORLD_TIME = "world_time"
PLAYER_SORT_DEATHS = "deaths"
PLAYER_SORT_MOB_KILLS = "mob_kills"
PLAYER_SORT_PLAYER_KILLS = "player_kills"
PLAYER_SORT_MINED = "mined"
PLAYER_SORT_PLACED = "placed"
PLAYER_SORT_JUMPS = "jumps"
PLAYER_SORT_DAMAGE = "damage_dealt"
PLAYER_SORT_DISTANCE = "distance"
PLAYER_SORT_NAME = "name"

PLAYER_SORT_OPTIONS: tuple[str, ...] = (
    PLAYER_SORT_PLAY_TIME,
    PLAYER_SORT_WORLD_TIME,
    PLAYER_SORT_DEATHS,
    PLAYER_SORT_MOB_KILLS,
    PLAYER_SORT_PLAYER_KILLS,
    PLAYER_SORT_MINED,
    PLAYER_SORT_PLACED,
    PLAYER_SORT_JUMPS,
    PLAYER_SORT_DAMAGE,
    PLAYER_SORT_DISTANCE,
    PLAYER_SORT_NAME,
)

_DISTANCE_CUSTOM_KEYS = (
    "minecraft:walk_one_cm",
    "minecraft:sprint_one_cm",
    "minecraft:crouch_one_cm",
    "minecraft:fly_one_cm",
    "minecraft:swim_one_cm",
    "minecraft:walk_on_water_one_cm",
    "minecraft:walk_under_water_one_cm",
    "minecraft:boat_one_cm",
    "minecraft:horse_one_cm",
    "minecraft:minecart_one_cm",
    "minecraft:pig_one_cm",
    "minecraft:strider_one_cm",
    "minecraft:climb_one_cm",
    "minecraft:fall_one_cm",
    "minecraft:aviate_one_cm",
)


@dataclass
class WorldStatistics:
    """存档完整统计数据"""
    total_regions: int = 0
    total_blocks: int = 0
    total_entities: int = 0
    block_stats: Optional[BlockStats] = None
    entity_stats: Optional[EntityStats] = None
    # Keys are world-relative region paths so multi-dimension coords do not collide.
    region_sizes: Dict[str, int] = field(default_factory=dict)
    loaded_chunks: int = 0
    empty_chunks: int = 0
    dimension_stats: List[DimensionSizeStats] = field(default_factory=list)
    player_stats: List[PlayerPlaytimeStats] = field(default_factory=list)


@dataclass(frozen=True)
class _RegionChunkStats:
    loaded_chunks: int
    empty_chunks: int
    block_counts: Counter[str]
    entity_counts: Counter[str]


# value in [0.0, 1.0], human-readable stage message
StatsProgressCallback = Callable[[float, str], None]


class WorldStatsService:
    """存档统计服务。

    先收集维度规模与玩家 stats，再扫描区域文件汇总方块/实体计数。
    单个区域失败不会中止整次分析。
    """

    AIR_BLOCKS = {
        "minecraft:air",
        "minecraft:cave_air",
        "minecraft:void_air",
        "air",
        "cave_air",
        "void_air",
    }

    # Region analysis spans most of the bar after lightweight prep stages.
    _REGION_START = 0.15
    _REGION_SPAN = 0.82
    _FINALIZE_VALUE = 0.98

    def __init__(self, log: Optional[LogCallback] = None) -> None:
        """初始化统计服务。

        Args:
            log: 可选日志回调；默认空操作。
        """
        self.log: LogCallback = log or _default_log

    def analyze_world(
        self,
        world_path: Path,
        progress_callback: Optional[StatsProgressCallback] = None,
        name_map: Optional[Dict[str, Optional[str]]] = None,
    ) -> WorldStatistics:
        """分析存档并返回完整统计。

        Args:
            world_path: 世界根目录。
            progress_callback: 可选进度回调 ``(0..1, stage)``。
            name_map: 可选 UUID→玩家名映射，优先于 usercache。

        Returns:
            WorldStatistics: 维度、玩家与区域汇总结果。
        """
        from core.performance import get_tracker
        tracker = get_tracker()

        with tracker.track("存档统计分析", {"world": world_path.name}):
            stats = WorldStatistics()
            self._report_progress(progress_callback, 0.02, "dimensions")
            stats.dimension_stats = self.collect_dimension_sizes(world_path)
            self._report_progress(progress_callback, 0.08, "players")
            stats.player_stats = self.collect_player_playtimes(
                world_path,
                name_map=name_map,
            )
            self._report_progress(progress_callback, 0.12, "scanning")

            region_files = scan_all_regions(world_path)
            stats.total_regions = len(region_files)
            tracker.increment_files(len(region_files))
            block_counter, entity_counter = self._analyze_all_regions(
                world_path,
                region_files,
                stats,
                progress_callback,
                tracker,
            )
            self._report_progress(
                progress_callback,
                self._FINALIZE_VALUE,
                "finalizing",
            )
            self._finalize_statistics(stats, block_counter, entity_counter)
            self._log_statistics(stats)
            self._report_progress(progress_callback, 1.0, "done")

        return stats

    def _analyze_all_regions(
        self,
        world_path: Path,
        region_files: List[Path],
        stats: WorldStatistics,
        progress_callback: Optional[StatsProgressCallback],
        tracker: Any,
    ) -> Tuple[Counter[str], Counter[str]]:
        """Scan every region file and merge block/entity counters."""
        block_counter: Counter[str] = Counter()
        entity_counter: Counter[str] = Counter()
        total_regions = len(region_files)
        if total_regions == 0:
            self._report_progress(
                progress_callback,
                self._FINALIZE_VALUE,
                "finalizing",
            )
            return block_counter, entity_counter

        self._report_progress(
            progress_callback,
            self._REGION_START,
            f"regions:0:{total_regions}",
        )
        for idx, region_path in enumerate(region_files):
            self._analyze_one_region(
                world_path,
                region_path,
                stats,
                block_counter,
                entity_counter,
                tracker,
            )
            done = idx + 1
            fraction = done / total_regions
            value = self._REGION_START + self._REGION_SPAN * fraction
            self._report_progress(
                progress_callback,
                value,
                f"regions:{done}:{total_regions}",
            )
        return block_counter, entity_counter

    def _analyze_one_region(
        self,
        world_path: Path,
        region_path: Path,
        stats: WorldStatistics,
        block_counter: Counter[str],
        entity_counter: Counter[str],
        tracker: Any,
    ) -> None:
        """Analyze a single region file; log and continue on failure."""
        try:
            rel_key = self._region_size_key(world_path, region_path)
            stats.region_sizes[rel_key] = region_path.stat().st_size
            region_stats = self._analyze_region_chunks(region_path)
            self._merge_region_stats(
                stats,
                region_stats,
                block_counter,
                entity_counter,
            )
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.log(
                f"分析区域 {region_path.name} 失败: {exc}",
                "WARNING",
            )
            tracker.increment_errors(1)
        except Exception as exc:
            # 区域解析库可能抛出非标准错误；跳过该文件继续。
            self.log(
                f"分析区域 {region_path.name} 失败: {exc}",
                "WARNING",
            )
            tracker.increment_errors(1)

    @staticmethod
    def _report_progress(
        progress_callback: Optional[StatsProgressCallback],
        value: float,
        message: str,
    ) -> None:
        if progress_callback is None:
            return
        clamped = max(0.0, min(1.0, value))
        progress_callback(clamped, message)

    def collect_dimension_sizes(
        self,
        world_path: Path,
    ) -> List[DimensionSizeStats]:
        """按维度汇总区域文件数与字节数（轻量，不读区块内容）。"""
        results: List[DimensionSizeStats] = []
        for dimension in discover_dimension_region_dirs(world_path):
            region_files = scan_region_dir(dimension.region_dir)
            total_bytes = 0
            for region_path in region_files:
                try:
                    total_bytes += region_path.stat().st_size
                except OSError:
                    continue
            results.append(
                DimensionSizeStats(
                    dimension_id=dimension.id,
                    display_name=dimension.name,
                    region_count=len(region_files),
                    total_bytes=total_bytes,
                )
            )
        results.sort(key=lambda item: (-item.total_bytes, item.dimension_id))
        return results

    def collect_player_playtimes(
        self,
        world_path: Path,
        *,
        sort_by: str = PLAYER_SORT_PLAY_TIME,
        name_map: Optional[Dict[str, Optional[str]]] = None,
    ) -> List[PlayerPlaytimeStats]:
        """读取玩家 stats JSON，汇总游玩时间与关键自定义计数。

        玩家显示名优先使用传入的 ``name_map``（通常来自
        :meth:`WorldSession.get_player_names`），否则复用
        :class:`PlayerManager` + :class:`WorldScanner` 的 usercache 解析。
        """
        names = self._resolve_player_names(world_path, name_map)
        by_uuid: Dict[str, PlayerPlaytimeStats] = {}
        for stats_dir in find_stats_dirs(world_path):
            if not stats_dir.is_dir():
                continue
            for stats_path in sorted(stats_dir.glob("*.json")):
                uuid = PlayerManager.normalize_uuid(stats_path.stem)
                if not uuid or uuid in by_uuid:
                    continue
                player = self._parse_player_stats_file(
                    stats_path,
                    uuid=uuid,
                    name=names.get(uuid),
                )
                if player is None:
                    continue
                by_uuid[uuid] = player
        return self.sort_player_stats(list(by_uuid.values()), sort_by)

    def with_player_names(
        self,
        players: List[PlayerPlaytimeStats],
        name_map: Optional[Dict[str, Optional[str]]],
    ) -> List[PlayerPlaytimeStats]:
        """Attach display names from a WorldSession-style name map."""
        if not name_map:
            return list(players)
        resolved = {
            PlayerManager.normalize_uuid(uuid): name
            for uuid, name in name_map.items()
            if uuid and name
        }
        updated: List[PlayerPlaytimeStats] = []
        for player in players:
            name = player.name or resolved.get(player.uuid)
            if name == player.name:
                updated.append(player)
            else:
                updated.append(
                    PlayerPlaytimeStats(
                        uuid=player.uuid,
                        name=name,
                        play_time_ticks=player.play_time_ticks,
                        total_world_time_ticks=player.total_world_time_ticks,
                        deaths=player.deaths,
                        mob_kills=player.mob_kills,
                        player_kills=player.player_kills,
                        mined=player.mined,
                        placed=player.placed,
                        jumps=player.jumps,
                        damage_dealt=player.damage_dealt,
                        distance_cm=player.distance_cm,
                    )
                )
        return updated

    @classmethod
    def sort_player_stats(
        cls,
        players: List[PlayerPlaytimeStats],
        sort_by: str = PLAYER_SORT_PLAY_TIME,
    ) -> List[PlayerPlaytimeStats]:
        """Return a new list sorted by the selected player metric."""
        key = sort_by if sort_by in PLAYER_SORT_OPTIONS else PLAYER_SORT_PLAY_TIME
        if key == PLAYER_SORT_NAME:
            return sorted(
                players,
                key=lambda item: (
                    (item.name or "").casefold(),
                    item.uuid,
                ),
            )
        metric = {
            PLAYER_SORT_PLAY_TIME: lambda item: item.play_time_ticks,
            PLAYER_SORT_WORLD_TIME: lambda item: item.total_world_time_ticks,
            PLAYER_SORT_DEATHS: lambda item: item.deaths,
            PLAYER_SORT_MOB_KILLS: lambda item: item.mob_kills,
            PLAYER_SORT_PLAYER_KILLS: lambda item: item.player_kills,
            PLAYER_SORT_MINED: lambda item: item.mined,
            PLAYER_SORT_PLACED: lambda item: item.placed,
            PLAYER_SORT_JUMPS: lambda item: item.jumps,
            PLAYER_SORT_DAMAGE: lambda item: item.damage_dealt,
            PLAYER_SORT_DISTANCE: lambda item: item.distance_cm,
        }[key]
        return sorted(
            players,
            key=lambda item: (
                -metric(item),
                (item.name or "").casefold(),
                item.uuid,
            ),
        )

    @staticmethod
    def player_metric_value(
        player: PlayerPlaytimeStats,
        sort_by: str,
    ) -> int:
        """Numeric metric used for ranking bars and sort keys."""
        mapping = {
            PLAYER_SORT_PLAY_TIME: player.play_time_ticks,
            PLAYER_SORT_WORLD_TIME: player.total_world_time_ticks,
            PLAYER_SORT_DEATHS: player.deaths,
            PLAYER_SORT_MOB_KILLS: player.mob_kills,
            PLAYER_SORT_PLAYER_KILLS: player.player_kills,
            PLAYER_SORT_MINED: player.mined,
            PLAYER_SORT_PLACED: player.placed,
            PLAYER_SORT_JUMPS: player.jumps,
            PLAYER_SORT_DAMAGE: player.damage_dealt,
            PLAYER_SORT_DISTANCE: player.distance_cm,
        }
        if sort_by == PLAYER_SORT_NAME:
            return 0
        return mapping.get(sort_by, player.play_time_ticks)

    @staticmethod
    def format_ticks_as_duration(ticks: int) -> str:
        """将 Minecraft 统计刻数格式化为可读时长。"""
        if ticks < 0:
            ticks = 0
        total_seconds = ticks // 20
        days, rem = divmod(total_seconds, 86_400)
        hours, rem = divmod(rem, 3_600)
        minutes, seconds = divmod(rem, 60)
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    @staticmethod
    def _region_size_key(world_path: Path, region_path: Path) -> str:
        try:
            return region_path.resolve().relative_to(world_path.resolve()).as_posix()
        except ValueError:
            coords = parse_region_coords(region_path)
            if coords is None:
                return region_path.name
            return f"{coords[0]}.{coords[1]}/{region_path.name}"

    def _analyze_region_chunks(self, region_path: Path) -> _RegionChunkStats:
        from core.mca import NativeRegion

        with NativeRegion.from_file(region_path) as region:
            present = self._present_chunk_coordinates(region)
            return self._collect_region_chunk_stats(region, present)

    @staticmethod
    def _present_chunk_coordinates(
        region: Any,
    ) -> Optional[List[Tuple[int, int]]]:
        try:
            return list(region.iter_present_chunks())
        except AttributeError:
            # Older adapters and lightweight test doubles only expose get_chunk().
            return None

    def _collect_region_chunk_stats(
        self,
        region: Any,
        present: Optional[List[Tuple[int, int]]],
    ) -> _RegionChunkStats:
        block_counts: Counter[str] = Counter()
        entity_counts: Counter[str] = Counter()
        loaded_chunks = 0
        empty_chunks = max(0, 1024 - len(present)) if present is not None else 0
        coordinates = present if present is not None else self._all_chunk_coordinates()
        for x, z in coordinates:
            try:
                chunk = region.get_chunk(x, z)
                if chunk is not None:
                    loaded_chunks += 1
                    chunk_blocks, chunk_entities = self._analyze_chunk(chunk)
                    block_counts.update(chunk_blocks)
                    entity_counts.update(chunk_entities)
                elif present is None:
                    empty_chunks += 1
            except (OSError, ValueError, TypeError, RuntimeError, KeyError, AttributeError):
                if present is None:
                    empty_chunks += 1
            except Exception:
                # Region adapters may raise package-specific errors.
                if present is None:
                    empty_chunks += 1
        return _RegionChunkStats(
            loaded_chunks=loaded_chunks,
            empty_chunks=empty_chunks,
            block_counts=block_counts,
            entity_counts=entity_counts,
        )

    @staticmethod
    def _all_chunk_coordinates() -> List[Tuple[int, int]]:
        return [(x, z) for x in range(32) for z in range(32)]

    @staticmethod
    def _merge_region_stats(
        stats: WorldStatistics,
        region_stats: _RegionChunkStats,
        block_counter: Counter[str],
        entity_counter: Counter[str],
    ) -> None:
        stats.loaded_chunks += region_stats.loaded_chunks
        stats.empty_chunks += region_stats.empty_chunks
        block_counter.update(region_stats.block_counts)
        entity_counter.update(region_stats.entity_counts)

    @staticmethod
    def _finalize_statistics(
        stats: WorldStatistics,
        block_counter: Counter[str],
        entity_counter: Counter[str],
    ) -> None:
        stats.block_stats = BlockStats(
            total_count=sum(block_counter.values()),
            block_types=dict(block_counter),
            top_blocks=block_counter.most_common(20),
        )
        stats.total_blocks = stats.block_stats.total_count
        stats.entity_stats = EntityStats(
            total_count=sum(entity_counter.values()),
            entity_types=dict(entity_counter),
            top_entities=entity_counter.most_common(20),
        )
        stats.total_entities = stats.entity_stats.total_count

    def _log_statistics(self, stats: WorldStatistics) -> None:
        self.log(
            f"存档分析完成: {stats.total_regions} 区域, "
            f"{stats.loaded_chunks} 区块, {stats.total_blocks} 方块, "
            f"{stats.total_entities} 实体, "
            f"{len(stats.dimension_stats)} 维度, "
            f"{len(stats.player_stats)} 玩家统计",
            "INFO",
        )

    def get_region_size_distribution(
            self, stats: WorldStatistics) -> Dict[str, int]:
        """获取区域文件大小分布"""
        distribution = {
            "< 1KB": 0,
            "1KB - 100KB": 0,
            "100KB - 1MB": 0,
            "1MB - 5MB": 0,
            "> 5MB": 0
        }

        for size in stats.region_sizes.values():
            kb = size / 1024
            mb = kb / 1024

            if mb > 5:
                distribution["> 5MB"] += 1
            elif mb > 1:
                distribution["1MB - 5MB"] += 1
            elif kb > 100:
                distribution["100KB - 1MB"] += 1
            elif kb > 1:
                distribution["1KB - 100KB"] += 1
            else:
                distribution["< 1KB"] += 1

        return distribution

    def _analyze_chunk(self, chunk: Any) -> Tuple[Counter[str], Counter[str]]:
        """分析单个区块的方块和实体"""
        block_counter: Counter[str] = Counter()
        entity_counter: Counter[str] = Counter()
        try:
            data = getattr(chunk, 'data', None)
            if not data:
                return block_counter, entity_counter
            block_counter.update(self._count_palette_blocks(data))
            entity_counter.update(self._count_entities(data, 'entities'))
            entity_counter.update(self._count_entities(
                data,
                'block_entities',
                prefix='block:',
            ))
        except (OSError, ValueError, TypeError, RuntimeError, KeyError, AttributeError):
            pass
        except Exception:
            # Corrupted chunk payloads should not abort region analysis.
            pass
        return block_counter, entity_counter

    def _count_palette_blocks(self, data: Any) -> Counter[str]:
        from core.mca.block_palette import ChunkBlocks

        counter: Counter[str] = Counter()
        blocks = ChunkBlocks(data)
        for block_id, count in blocks.count_block_ids().items():
            if block_id and block_id not in self.AIR_BLOCKS:
                counter[block_id] += count
        return counter

    @staticmethod
    def _count_entities(
        data: Any,
        key: str,
        *,
        prefix: str = '',
    ) -> Counter[str]:
        counter: Counter[str] = Counter()
        for entity in data.get(key, []):
            entity_id = str(entity.get('id', ''))
            if entity_id:
                counter[f"{prefix}{entity_id}"] += 1
        return counter

    def _resolve_player_names(
        self,
        world_path: Path,
        name_map: Optional[Dict[str, Optional[str]]] = None,
    ) -> Dict[str, str]:
        """Resolve UUID -> name via PlayerManager, optionally seeded by session."""
        manager = PlayerManager(log_callback=self.log)
        uuids: set[str] = set()
        try:
            scanner = WorldScanner(world_path, log_callback=self.log)
            # Public scan helpers (playerdata + usercache only).
            player_files = scanner.scan_player_files()
            usercache = scanner.scan_usercache(set(player_files.keys()))
            manager.initialize_names(player_files, usercache)
            uuids.update(player_files.keys())
            uuids.update(usercache.keys())
        except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
            self.log(f"加载玩家名称失败: {exc}", "WARNING")
        except Exception as exc:
            self.log(f"加载玩家名称失败: {exc}", "WARNING")
        if name_map:
            manager.seed_names(name_map)
            uuids.update(
                PlayerManager.normalize_uuid(uuid)
                for uuid in name_map
                if uuid
            )
        resolved: Dict[str, str] = {}
        for uuid, name in manager.get_player_names(sorted(uuids)).items():
            if name:
                resolved[uuid] = name
        return resolved

    def _parse_player_stats_file(
        self,
        stats_path: Path,
        *,
        uuid: str,
        name: Optional[str],
    ) -> Optional[PlayerPlaytimeStats]:
        try:
            with stats_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.log(f"读取玩家统计失败 {stats_path.name}: {exc}", "WARNING")
            return None
        if not isinstance(payload, dict):
            return None
        stats_root = payload.get("stats")
        if not isinstance(stats_root, dict):
            return None
        custom = stats_root.get("minecraft:custom")
        if not isinstance(custom, dict):
            custom = {}
        mined_map = stats_root.get("minecraft:mined")
        used_map = stats_root.get("minecraft:used")
        play_ticks = self._read_custom_int(
            custom,
            "minecraft:play_time",
            "minecraft:play_one_minute",
        )
        world_ticks = self._read_custom_int(
            custom,
            "minecraft:total_world_time",
        )
        return PlayerPlaytimeStats(
            uuid=uuid,
            name=name,
            play_time_ticks=play_ticks,
            total_world_time_ticks=world_ticks,
            deaths=self._read_custom_int(custom, "minecraft:deaths"),
            mob_kills=self._read_custom_int(custom, "minecraft:mob_kills"),
            player_kills=self._read_custom_int(
                custom,
                "minecraft:player_kills",
            ),
            mined=self._sum_category_counts(mined_map),
            placed=self._sum_category_counts(used_map),
            jumps=self._read_custom_int(custom, "minecraft:jump"),
            damage_dealt=self._read_custom_int(
                custom,
                "minecraft:damage_dealt",
            ),
            distance_cm=self._sum_custom_keys(custom, _DISTANCE_CUSTOM_KEYS),
        )

    @staticmethod
    def _sum_category_counts(values: Any) -> int:
        if not isinstance(values, dict):
            return 0
        total = 0
        for value in values.values():
            try:
                total += max(0, int(value))
            except (TypeError, ValueError):
                continue
        return total

    @classmethod
    def _sum_custom_keys(
        cls,
        custom: Dict[str, Any],
        keys: tuple[str, ...],
    ) -> int:
        return sum(cls._read_custom_int(custom, key) for key in keys)

    @staticmethod
    def _read_custom_int(custom: Dict[str, Any], *keys: str) -> int:
        for key in keys:
            value = custom.get(key)
            if value is None:
                continue
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
        return 0


def get_world_stats_service(
        log: Optional[LogCallback] = None) -> WorldStatsService:
    """Return a statistics service scoped to one analysis operation."""
    return WorldStatsService(log=log)
