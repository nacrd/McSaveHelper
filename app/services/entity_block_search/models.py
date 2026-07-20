"""实体/方块/容器搜索的数据模型。"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple


@dataclass
class SearchResult:
    """单条搜索命中结果。

    Attributes:
        result_type: 结果类别（实体/方块/容器等）。
        name: 目标 ID 或显示名。
        position: 世界坐标 ``(x, y, z)``。
        dimension: 维度键。
        extra_info: 可选附加字段（NBT 摘要等）。
    """

    result_type: str
    name: str
    position: Tuple[int, int, int]
    dimension: str
    extra_info: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """保证 extra_info 永不为 None。"""
        if self.extra_info is None:
            self.extra_info = {}

    @property
    def x(self) -> int:
        """方块/实体 X 坐标。"""
        return self.position[0]

    @property
    def y(self) -> int:
        """Y 坐标。"""
        return self.position[1]

    @property
    def z(self) -> int:
        """Z 坐标。"""
        return self.position[2]

    @property
    def target_id(self) -> str:
        """目标 ID，与 ``name`` 相同，供视图层统一访问。"""
        return self.name

    @property
    def position_str(self) -> str:
        """``(x, y, z)`` 展示字符串。"""
        return f"({self.x}, {self.y}, {self.z})"

    def __repr__(self) -> str:
        return (
            f"SearchResult({self.result_type}, {self.name}, "
            f"{self.position}, {self.dimension})"
        )


@dataclass
class SearchCondition:
    """搜索条件，封装一次搜索请求的所有参数。

    Attributes:
        search_type: 搜索类型（见 VALID_SEARCH_TYPES）。
        target: 目标 ID/名称关键字。
        dimensions: 要扫描的维度列表（可能被 validate 过滤）。
        world_path: 世界根目录。
    """

    search_type: str
    target: str
    dimensions: List[str]
    world_path: Path

    def validate(self) -> List[str]:
        """校验条件合法性，返回错误消息列表（空表示合法）。

        副作用：将 ``dimensions`` 过滤为仅含合法维度。

        Returns:
            错误文案列表；空列表表示可执行搜索。
        """
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
    """搜索摘要，用于 UI 和日志展示。

    Attributes:
        scanned_regions: 已扫描 region 数。
        scanned_chunks: 已扫描区块数。
        skipped_chunks: 跳过（损坏/不可读）区块数。
        warnings: 扫描过程中的警告文案。
    """

    scanned_regions: int = 0
    scanned_chunks: int = 0
    skipped_chunks: int = 0
    warnings: List[str] = field(default_factory=list)
