"""Block search implementation."""

from pathlib import Path
from typing import Any, Callable, List

from .constants import MAX_RESULTS
from .container_searcher import ContainerSearcher
from .models import SearchResult, SearchSummary
from .utils import get_block_name, get_dimension_region_files, get_section_range, matches_target, tag_to_str


class BlockSearcher:
    """Searches blocks in region chunks."""

    def __init__(self, results: List[SearchResult], summary: SearchSummary) -> None:
        self.results = results
        self.summary = summary
        self.container_helper = ContainerSearcher(results, summary)

    def search_dimension(self, world_path: Path, dimension: str, target: str, log: Callable[[str, str], None], progress: Callable[[float, str], None]) -> None:
        try:
            region_files = get_dimension_region_files(world_path, dimension)
            if not region_files:
                log(f"维度 {dimension} 没有区块文件", "WARNING")
                return
            log(f"在 {dimension} 中找到 {len(region_files)} 个区块文件", "INFO")
            self._scan_regions(region_files, dimension, target, log, progress)
        except ImportError:
            log("anvil-parser2 未安装，无法搜索方块", "ERROR")
        except Exception as e:
            log(f"搜索维度 {dimension} 失败: {e}", "ERROR")

    def search_chunk(self, chunk: Any, target: str, dimension: str) -> None:
        try:
            matching_sections = self._matching_sections(chunk, target)
            if not matching_sections:
                return
            for section_y in matching_sections:
                self._scan_section(chunk, target, dimension, section_y)
        except Exception:
            pass

    def _scan_regions(self, region_files: List[Path], dimension: str, target: str, log: Callable[[str, str], None], progress: Callable[[float, str], None]) -> None:
        from anvil import Region
        total = len(region_files)
        for idx, region_file in enumerate(region_files):
            if self._limit_reached():
                return
            progress(idx / total, f"搜索区块文件 {idx + 1}/{total}")
            self.summary.scanned_regions += 1
            try:
                self._scan_region(Region.from_file(str(region_file)), target, dimension)
            except Exception as e:
                log(f"读取区块文件 {region_file.name} 失败: {e}", "WARNING")

    def _scan_region(self, region: Any, target: str, dimension: str) -> None:
        for cx in range(32):
            for cz in range(32):
                if self._limit_reached():
                    return
                try:
                    chunk = region.get_chunk(cx, cz)
                    if chunk is not None:
                        self.summary.scanned_chunks += 1
                        self.search_chunk(chunk, target, dimension)
                except Exception:
                    self.summary.skipped_chunks += 1

    def _matching_sections(self, chunk: Any, target: str) -> List[int]:
        target_block = self._target_block(target)
        matches = []
        for section_y in get_section_range(chunk):
            if self._section_palette_matches(chunk, section_y, target, target_block):
                matches.append(section_y)
        return matches

    def _section_palette_matches(self, chunk: Any, section_y: int, target: str, target_block: Any) -> bool:
        try:
            palette = chunk.get_palette(section_y)
            if palette is None:
                return False
            return any(self._block_matches(block, target, target_block) for block in palette if block is not None)
        except Exception:
            return False

    def _scan_section(self, chunk: Any, target: str, dimension: str, section_y: int) -> None:
        for x in range(16):
            for z in range(16):
                for y in range(section_y * 16, section_y * 16 + 16):
                    if self._limit_reached():
                        return
                    self._check_block_at(chunk, target, dimension, x, y, z)

    def _check_block_at(self, chunk: Any, target: str, dimension: str, x: int, y: int, z: int) -> None:
        try:
            block = chunk.get_block(x, y, z)
            if block is None or not self._block_matches(block, target, None):
                return
            world_x, world_z = chunk.x * 16 + x, chunk.z * 16 + z
            self.results.append(SearchResult("block", get_block_name(block), (world_x, y, world_z), dimension, self.container_helper.get_container_info_at(chunk, world_x, y, world_z)))
        except Exception:
            pass

    @staticmethod
    def _target_block(target: str) -> Any:
        if ":" not in target:
            return None
        try:
            from anvil import Block
            return Block.from_name(target)
        except Exception:
            return None

    @staticmethod
    def _block_matches(block: Any, target: str, target_block: Any) -> bool:
        if target_block is not None and block == target_block:
            return True
        block_name = get_block_name(block)
        block_id = tag_to_str(getattr(block, "id", ""))
        return matches_target(block_name, target) or matches_target(block_id, target)

    def _limit_reached(self) -> bool:
        return len(self.results) >= MAX_RESULTS
