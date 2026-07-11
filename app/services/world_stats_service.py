"""存档统计服务 - 收集和分析存档统计数据"""
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from collections import Counter
from dataclasses import dataclass, field

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
            progress_callback: Optional[Any] = None) -> WorldStatistics:
        """分析存档并返回统计数据"""
        from core.performance import get_tracker
        tracker = get_tracker()

        with tracker.track("存档统计分析", {"world": world_path.name}):
            stats = WorldStatistics()

            region_files = scan_all_regions(world_path)
            stats.total_regions = len(region_files)
            tracker.increment_files(len(region_files))

            block_counter: Counter = Counter()
            entity_counter: Counter = Counter()

            for idx, region_path in enumerate(region_files):
                try:
                    coords = parse_region_coords(region_path)
                    if coords is None:
                        raise ValueError(f"无效的区域文件名: {region_path.name}")
                    stats.region_sizes[coords] = region_path.stat().st_size

                    from core.mca import NativeRegion
                    with NativeRegion.from_file(region_path) as region:
                        for x in range(32):
                            for z in range(32):
                                try:
                                    chunk = region.get_chunk(x, z)
                                    if chunk is not None:
                                        stats.total_chunks += 1
                                        stats.loaded_chunks += 1

                                        chunk_blocks, chunk_entities = self._analyze_chunk(
                                            chunk)
                                        block_counter.update(chunk_blocks)
                                        entity_counter.update(chunk_entities)
                                    else:
                                        stats.empty_chunks += 1
                                except Exception:
                                    stats.empty_chunks += 1

                    if progress_callback:
                        progress_callback(idx + 1, len(region_files))

                except Exception as e:
                    self._log(f"分析区域 {region_path.name} 失败: {e}", "WARNING")
                    tracker.increment_errors(1)

            stats.block_stats = BlockStats(
                total_count=sum(block_counter.values()),
                block_types=dict(block_counter),
                top_blocks=block_counter.most_common(20)
            )
            stats.total_blocks = stats.block_stats.total_count

            stats.entity_stats = EntityStats(
                total_count=sum(entity_counter.values()),
                entity_types=dict(entity_counter),
                top_entities=entity_counter.most_common(20)
            )
            stats.total_entities = stats.entity_stats.total_count

            self._log(
                f"存档分析完成: {
                    stats.total_regions} 区域, {
                    stats.total_chunks} 区块, {
                    stats.total_blocks} 方块, {
                    stats.total_entities} 实体",
                "INFO")

        return stats

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
            if hasattr(chunk, 'data') and chunk.data:
                data = chunk.data

                sections = data.get('sections', [])
                if sections:
                    for section in sections:
                        if section is None:
                            continue
                        block_states = section.get('block_states', {})
                        if block_states:
                            palette = block_states.get('palette', [])
                            for block in palette:
                                block_id = str(block.get('Name', ''))
                                if block_id and block_id not in self.AIR_BLOCKS:
                                    block_counter[block_id] += 1

                entities = data.get('entities', [])
                if entities:
                    for entity in entities:
                        entity_id = str(entity.get('id', ''))
                        if entity_id:
                            entity_counter[entity_id] += 1

                block_entities = data.get('block_entities', [])
                if block_entities:
                    for be in block_entities:
                        be_id = str(be.get('id', ''))
                        if be_id:
                            entity_counter[f"block:{be_id}"] += 1

        except Exception:
            pass

        return block_counter, entity_counter


_world_stats_service: Optional[WorldStatsService] = None
_world_stats_service_lock = threading.Lock()


def get_world_stats_service(
        log: Optional[LogCallback] = None) -> WorldStatsService:
    """获取存档统计服务单例（线程安全）"""
    global _world_stats_service
    with _world_stats_service_lock:
        if _world_stats_service is None:
            _world_stats_service = WorldStatsService(log=log)
        elif log is not None:
            _world_stats_service.log = log
    return _world_stats_service
