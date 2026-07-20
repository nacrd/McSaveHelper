"""存档统计服务 - 收集和分析存档统计数据"""
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.scanner import scan_all_regions
from core.region_utils import parse_region_coords
from core.types import LogCallback


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


@dataclass
class WorldStatistics:
    """存档完整统计数据"""
    total_regions: int = 0
    total_chunks: int = 0
    total_blocks: int = 0
    total_entities: int = 0
    block_stats: Optional[BlockStats] = None
    entity_stats: Optional[EntityStats] = None
    region_sizes: Dict[Tuple[int, int], int] = field(default_factory=dict)
    loaded_chunks: int = 0
    empty_chunks: int = 0


@dataclass(frozen=True)
class _RegionChunkStats:
    total_chunks: int
    empty_chunks: int
    block_counts: Counter[str]
    entity_counts: Counter[str]


StatsProgressCallback = Callable[[int, int], None]


class WorldStatsService:
    """存档统计服务"""

    AIR_BLOCKS = {
        "minecraft:air",
        "minecraft:cave_air",
        "minecraft:void_air",
        "air",
        "cave_air",
        "void_air"}

    def __init__(self, log: Optional[LogCallback] = None) -> None:
        self.log: LogCallback = log or _default_log

    def _log(self, message: str, level: str = "INFO") -> None:
        self.log(message, level)

    def analyze_world(
            self,
            world_path: Path,
            progress_callback: Optional[StatsProgressCallback] = None,
    ) -> WorldStatistics:
        """分析存档并返回统计数据"""
        from core.performance import get_tracker
        tracker = get_tracker()

        with tracker.track("存档统计分析", {"world": world_path.name}):
            stats = WorldStatistics()

            region_files = scan_all_regions(world_path)
            stats.total_regions = len(region_files)
            tracker.increment_files(len(region_files))

            block_counter: Counter[str] = Counter()
            entity_counter: Counter[str] = Counter()

            for idx, region_path in enumerate(region_files):
                try:
                    coords = self._require_region_coords(region_path)
                    stats.region_sizes[coords] = region_path.stat().st_size
                    region_stats = self._analyze_region_chunks(region_path)
                    self._merge_region_stats(
                        stats,
                        region_stats,
                        block_counter,
                        entity_counter,
                    )
                    if progress_callback:
                        progress_callback(idx + 1, len(region_files))
                except Exception as exc:
                    self._log(
                        f"分析区域 {region_path.name} 失败: {exc}",
                        "WARNING",
                    )
                    tracker.increment_errors(1)

            self._finalize_statistics(stats, block_counter, entity_counter)
            self._log_statistics(stats)

        return stats

    @staticmethod
    def _require_region_coords(region_path: Path) -> Tuple[int, int]:
        coords = parse_region_coords(region_path)
        if coords is None:
            raise ValueError(f"无效的区域文件名: {region_path.name}")
        return coords

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
        total_chunks = 0
        empty_chunks = max(0, 1024 - len(present)) if present is not None else 0
        coordinates = present if present is not None else self._all_chunk_coordinates()
        for x, z in coordinates:
            try:
                chunk = region.get_chunk(x, z)
                if chunk is not None:
                    total_chunks += 1
                    chunk_blocks, chunk_entities = self._analyze_chunk(chunk)
                    block_counts.update(chunk_blocks)
                    entity_counts.update(chunk_entities)
                elif present is None:
                    empty_chunks += 1
            except Exception:
                if present is None:
                    empty_chunks += 1
        return _RegionChunkStats(
            total_chunks=total_chunks,
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
        stats.total_chunks += region_stats.total_chunks
        # loaded_chunks tracks the same non-empty chunks as total_chunks.
        stats.loaded_chunks += region_stats.total_chunks
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
        self._log(
            f"存档分析完成: {stats.total_regions} 区域, "
            f"{stats.total_chunks} 区块, {stats.total_blocks} 方块, "
            f"{stats.total_entities} 实体",
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
        except Exception:
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


def get_world_stats_service(
        log: Optional[LogCallback] = None) -> WorldStatsService:
    """Return a statistics service scoped to one analysis operation."""
    return WorldStatsService(log=log)
