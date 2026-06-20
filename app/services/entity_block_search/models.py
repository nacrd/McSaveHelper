"""Models for entity/block/container search."""

from dataclasses import dataclass, field
from pathlib import Path
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

    @property
    def x(self) -> int:
        return self.position[0]

    @property
    def y(self) -> int:
        return self.position[1]

    @property
    def z(self) -> int:
        return self.position[2]

    @property
    def target_id(self) -> str:
        """Alias for name, matches view usage."""
        return self.name

    @property
    def position_str(self) -> str:
        return f"({self.x}, {self.y}, {self.z})"

    def __repr__(self) -> str:
        return f"SearchResult({self.result_type}, {self.name}, {self.position}, {self.dimension})"


@dataclass
class SearchCondition:
    """搜索条件，封装一次搜索请求的所有参数。"""

    search_type: str
    target: str
    dimensions: List[str]
    world_path: Path

    def validate(self) -> List[str]:
        """校验条件合法性，返回错误消息列表（空表示合法）。"""
        from .constants import VALID_DIMENSIONS, VALID_SEARCH_TYPES
        errors: List[str] = []
        if not self.world_path or not self.world_path.exists():
            errors.append(f"存档路径不存在: {self.world_path}")
        if self.search_type not in VALID_SEARCH_TYPES:
            errors.append(f"不支持的搜索类型: {self.search_type}")
        if not self.target:
            errors.append("搜索目标不能为空")
        valid_dims = [d for d in self.dimensions if d in VALID_DIMENSIONS]
        if not valid_dims:
            errors.append("未选择有效维度")
        self.dimensions = valid_dims
        return errors


@dataclass
class SearchSummary:
    """搜索摘要，用于 UI 和日志展示。"""

    scanned_regions: int = 0
    scanned_chunks: int = 0
    skipped_chunks: int = 0
    warnings: List[str] = field(default_factory=list)
