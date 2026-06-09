"""Models for entity/block/container search."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass
class SearchResult:
    """搜索结果"""

    result_type: str
    name: str
    position: Tuple[int, int, int]
    dimension: str
    extra_info: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.extra_info is None:
            self.extra_info = {}

    def __repr__(self) -> str:
        return f"SearchResult({self.result_type}, {self.name}, {self.position}, {self.dimension})"


@dataclass
class SearchSummary:
    """搜索摘要，用于 UI 和日志展示。"""

    scanned_regions: int = 0
    scanned_chunks: int = 0
    skipped_chunks: int = 0
    warnings: List[str] = field(default_factory=list)
