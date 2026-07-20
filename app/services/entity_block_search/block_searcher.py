"""Block search implementation."""

from typing import Any, List

from .base_searcher import BaseSearcher
from .container_searcher import ContainerSearcher
from .models import SearchResult
from .utils import get_block_name, get_section_range, matches_target, tag_to_str


class BlockSearcher(BaseSearcher):
    """搜索区域区块中的方块。"""

    progress_label = "区块文件"

    def __init__(self, results: List[SearchResult], summary: Any) -> None:
        super().__init__(results, summary)
        self.container_helper = ContainerSearcher(results, summary)

    def search_chunk(self, chunk: Any, target: str, dimension: str) -> None:
        try:
            matching_sections = self._matching_sections(chunk, target)
            if not matching_sections:
                return
            for section_y in matching_sections:
                self._scan_section(chunk, target, dimension, section_y)
        except Exception:
            pass

    def _matching_sections(self, chunk: Any, target: str) -> List[int]:
        matches = []
        for section_y in get_section_range(chunk):
            if self._section_palette_matches(chunk, section_y, target):
                matches.append(section_y)
        return matches

    def _section_palette_matches(
        self,
        chunk: Any,
        section_y: int,
        target: str,
    ) -> bool:
        try:
            palette = chunk.get_palette(section_y)
            if palette is None:
                return False
            return any(
                self._block_matches(block, target)
                for block in palette
                if block is not None
            )
        except Exception:
            return False

    def _scan_section(self, chunk: Any, target: str, dimension: str, section_y: int) -> None:
        for x in range(16):
            for z in range(16):
                for y in range(section_y * 16, section_y * 16 + 16):
                    if self._limit_reached():
                        return
                    try:
                        block = chunk.get_block(x, y, z)
                        if block is None or not self._block_matches(block, target):
                            continue
                        world_x, world_z = chunk.x * 16 + x, chunk.z * 16 + z
                        self.results.append(SearchResult(
                            "block",
                            get_block_name(block),
                            (world_x, y, world_z),
                            dimension,
                            self.container_helper.get_container_info_at(
                                chunk, world_x, y, world_z),
                        ))
                    except Exception:
                        continue

    @staticmethod
    def _block_matches(block: Any, target: str) -> bool:
        block_name = get_block_name(block)
        block_id = tag_to_str(getattr(block, "id", ""))
        return matches_target(block_name, target) or matches_target(block_id, target)
