"""Block search implementation."""
from __future__ import annotations

from typing import Any, List, Optional

from core.mca.block_palette import ChunkBlocks

from .base_searcher import BaseSearcher
from .container_searcher import ContainerSearcher
from .models import SearchResult
from .utils import get_section_range, matches_target


class BlockSearcher(BaseSearcher):
    """搜索区域区块中的方块。"""

    progress_label = "区块文件"

    def __init__(self, results: List[SearchResult], summary: Any) -> None:
        """初始化方块搜索器并复用容器辅助扫描。

        Args:
            results: 搜索结果聚合列表。
            summary: 扫描摘要对象。
        """
        super().__init__(results, summary)
        self.container_helper = ContainerSearcher(results, summary)

    def search_chunk(self, chunk: Any, target: str, dimension: str) -> None:
        """在单个区块中按目标 ID 扫描方块。

        Args:
            chunk: MCA/NBT 区块对象。
            target: 目标方块 ID 或匹配模式。
            dimension: 维度标识（写入结果）。
        """
        try:
            blocks = self._chunk_blocks(chunk)
            if blocks is None:
                return
            matching_sections = self._matching_sections(chunk, blocks, target)
            if not matching_sections:
                return
            containers = self.container_helper.container_lookup(chunk)
            for section_y in matching_sections:
                self._scan_section(
                    chunk,
                    blocks,
                    target,
                    dimension,
                    section_y,
                    containers,
                )
        except (
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
            KeyError,
            AttributeError,
            IndexError,
        ):
            return

    def _matching_sections(
        self,
        chunk: Any,
        blocks: ChunkBlocks,
        target: str,
    ) -> List[int]:
        section_ys = list(reversed(blocks.section_ys_desc)) or list(
            get_section_range(chunk)
        )
        return [
            section_y
            for section_y in section_ys
            if self._section_may_contain(blocks, section_y, target)
        ]

    def _section_may_contain(
        self,
        blocks: ChunkBlocks,
        section_y: int,
        target: str,
    ) -> bool:
        names = blocks.get_palette_names(section_y)
        if names:
            return any(self._name_matches(name, target) for name in names)
        # Legacy or palette-less sections: let the iterator filter cells.
        return True

    def _scan_section(
        self,
        chunk: Any,
        blocks: ChunkBlocks,
        target: str,
        dimension: str,
        section_y: int,
        containers: dict[tuple[int, int, int], dict[str, Any]],
    ) -> None:
        chunk_x = int(getattr(chunk, "x", 0) or 0)
        chunk_z = int(getattr(chunk, "z", 0) or 0)
        for x, y, z, block_id in blocks.iter_matching_blocks(
            section_y,
            lambda name: self._name_matches(name, target),
        ):
            if self._limit_reached():
                return
            world_x = chunk_x * 16 + x
            world_z = chunk_z * 16 + z
            self.results.append(SearchResult(
                "block",
                block_id,
                (world_x, y, world_z),
                dimension,
                containers.get((world_x, y, world_z), {}),
            ))

    @staticmethod
    def _chunk_blocks(chunk: Any) -> Optional[ChunkBlocks]:
        blocks = getattr(chunk, "blocks", None)
        if isinstance(blocks, ChunkBlocks):
            return blocks
        data = getattr(chunk, "data", None)
        if not data:
            return None
        return ChunkBlocks(data)

    @staticmethod
    def _name_matches(name: str, target: str) -> bool:
        return matches_target(name, target)
