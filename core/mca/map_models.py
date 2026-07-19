"""地图领域模型.

本模块只包含地图状态和坐标换算, 不执行文件读取或渲染操作.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Literal, Mapping, Optional, Tuple, Union, cast


MapUnit = Literal["block", "chunk", "region"]
MapBounds = Tuple[int, int, int, int]
MapTarget = Union[str, "MapDimension"]

BLOCKS_PER_CHUNK = 16
CHUNKS_PER_REGION = 32
BLOCKS_PER_REGION = BLOCKS_PER_CHUNK * CHUNKS_PER_REGION
SUPPORTED_MAP_STYLES = frozenset({"topview", "terrain"})


def _text(value: Any, field_name: str) -> str:
    """校验并返回非空文本."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _integer(value: Any, field_name: str) -> int:
    """校验整数并拒绝布尔值."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _positive_number(value: Any, field_name: str) -> float:
    """校验有限正数."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return number


def _unit(value: Any) -> MapUnit:
    """校验选择范围单位."""
    if value not in {"block", "chunk", "region"}:
        raise ValueError("unit must be one of: block, chunk, region")
    return cast(MapUnit, value)


@dataclass(frozen=True)
class MapDimension:
    """描述一个 Minecraft 维度及其区域文件位置."""

    id: str
    name: str
    region_dir: Path
    coordinate_scale: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _text(self.id, "id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(self, "region_dir", Path(self.region_dir))
        object.__setattr__(
            self,
            "coordinate_scale",
            _positive_number(self.coordinate_scale, "coordinate_scale"),
        )


@dataclass(frozen=True)
class MapTileKey:
    """标识一个地图瓦片及其层级坐标."""

    world_id: str
    dimension_id: str
    style: str
    lod: int
    region_x: int
    region_z: int
    y_slice: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "world_id", _text(self.world_id, "world_id"))
        object.__setattr__(
            self,
            "dimension_id",
            _text(self.dimension_id, "dimension_id"),
        )
        object.__setattr__(self, "style", _text(self.style, "style"))
        lod = _integer(self.lod, "lod")
        if lod < 0:
            raise ValueError("lod must be greater than or equal to zero")
        object.__setattr__(self, "lod", lod)
        object.__setattr__(self, "region_x", _integer(self.region_x, "region_x"))
        object.__setattr__(self, "region_z", _integer(self.region_z, "region_z"))
        if self.y_slice is not None:
            object.__setattr__(self, "y_slice", _integer(self.y_slice, "y_slice"))

    def parent(self, levels: int = 1) -> "MapTileKey":
        """返回指定层数的父瓦片, 坐标采用 floor division."""
        levels = _integer(levels, "levels")
        if levels < 0:
            raise ValueError("levels must be greater than or equal to zero")
        divisor = 2**levels
        return MapTileKey(
            world_id=self.world_id,
            dimension_id=self.dimension_id,
            style=self.style,
            lod=self.lod + levels,
            region_x=self.region_x // divisor,
            region_z=self.region_z // divisor,
            y_slice=self.y_slice,
        )

    def cache_parts(self) -> Tuple[str, ...]:
        """返回适合作为磁盘缓存路径的稳定分段."""
        parts = (
            self.world_id,
            self.dimension_id,
            self.style,
            f"lod-{self.lod}",
            f"{self.region_x}_{self.region_z}",
        )
        if self.y_slice is None:
            return (*parts, "surface")
        return (*parts, f"y-{self.y_slice}")


@dataclass(frozen=True)
class MapSelection:
    """描述一个在方块, 区块或区域单位上的 inclusive 矩形."""

    start_x: int
    start_z: int
    end_x: int
    end_z: int
    unit: MapUnit = "block"

    def __post_init__(self) -> None:
        object.__setattr__(self, "start_x", _integer(self.start_x, "start_x"))
        object.__setattr__(self, "start_z", _integer(self.start_z, "start_z"))
        object.__setattr__(self, "end_x", _integer(self.end_x, "end_x"))
        object.__setattr__(self, "end_z", _integer(self.end_z, "end_z"))
        object.__setattr__(self, "unit", _unit(self.unit))

    @property
    def normalized(self) -> "MapSelection":
        """返回起止坐标按 X 和 Z 分别排序后的选择."""
        start_x = min(self.start_x, self.end_x)
        end_x = max(self.start_x, self.end_x)
        start_z = min(self.start_z, self.end_z)
        end_z = max(self.start_z, self.end_z)
        if (
            start_x == self.start_x
            and start_z == self.start_z
            and end_x == self.end_x
            and end_z == self.end_z
        ):
            return self
        return MapSelection(start_x, start_z, end_x, end_z, self.unit)

    @property
    def block_bounds(self) -> MapBounds:
        """返回 inclusive 方块边界, 顺序为 min_x, min_z, max_x, max_z."""
        selection = self.normalized
        if selection.unit == "block":
            return (
                selection.start_x,
                selection.start_z,
                selection.end_x,
                selection.end_z,
            )
        unit_size = (
            BLOCKS_PER_CHUNK
            if selection.unit == "chunk"
            else BLOCKS_PER_REGION
        )
        return (
            selection.start_x * unit_size,
            selection.start_z * unit_size,
            selection.end_x * unit_size + unit_size - 1,
            selection.end_z * unit_size + unit_size - 1,
        )

    @property
    def chunk_bounds(self) -> MapBounds:
        """返回 inclusive 区块边界, 负坐标使用 floor division."""
        selection = self.normalized
        if selection.unit == "chunk":
            return (
                selection.start_x,
                selection.start_z,
                selection.end_x,
                selection.end_z,
            )
        if selection.unit == "region":
            return (
                selection.start_x * CHUNKS_PER_REGION,
                selection.start_z * CHUNKS_PER_REGION,
                selection.end_x * CHUNKS_PER_REGION + CHUNKS_PER_REGION - 1,
                selection.end_z * CHUNKS_PER_REGION + CHUNKS_PER_REGION - 1,
            )
        min_x, min_z, max_x, max_z = selection.block_bounds
        return (
            min_x // BLOCKS_PER_CHUNK,
            min_z // BLOCKS_PER_CHUNK,
            max_x // BLOCKS_PER_CHUNK,
            max_z // BLOCKS_PER_CHUNK,
        )

    @property
    def region_bounds(self) -> MapBounds:
        """返回 inclusive 区域边界, 负坐标使用 floor division."""
        selection = self.normalized
        if selection.unit == "region":
            return (
                selection.start_x,
                selection.start_z,
                selection.end_x,
                selection.end_z,
            )
        if selection.unit == "chunk":
            min_x, min_z, max_x, max_z = selection.chunk_bounds
            return (
                min_x // CHUNKS_PER_REGION,
                min_z // CHUNKS_PER_REGION,
                max_x // CHUNKS_PER_REGION,
                max_z // CHUNKS_PER_REGION,
            )
        min_x, min_z, max_x, max_z = selection.block_bounds
        return (
            min_x // BLOCKS_PER_REGION,
            min_z // BLOCKS_PER_REGION,
            max_x // BLOCKS_PER_REGION,
            max_z // BLOCKS_PER_REGION,
        )

    def contains_block(self, x: int, z: int) -> bool:
        """判断一个方块坐标是否位于选择范围内."""
        x = _integer(x, "x")
        z = _integer(z, "z")
        min_x, min_z, max_x, max_z = self.block_bounds
        return min_x <= x <= max_x and min_z <= z <= max_z

    @classmethod
    def from_region(
        cls,
        start_x: int,
        start_z: int,
        end_x: Optional[int] = None,
        end_z: Optional[int] = None,
    ) -> "MapSelection":
        """从一个区域坐标或区域坐标矩形创建选择."""
        if (end_x is None) != (end_z is None):
            raise ValueError("end_x and end_z must be provided together")
        return cls(
            start_x,
            start_z,
            start_x if end_x is None else end_x,
            start_z if end_z is None else end_z,
            "region",
        )

    @classmethod
    def from_chunk(
        cls,
        start_x: int,
        start_z: int,
        end_x: Optional[int] = None,
        end_z: Optional[int] = None,
    ) -> "MapSelection":
        """从一个区块坐标或区块坐标矩形创建选择."""
        if (end_x is None) != (end_z is None):
            raise ValueError("end_x and end_z must be provided together")
        return cls(
            start_x,
            start_z,
            start_x if end_x is None else end_x,
            start_z if end_z is None else end_z,
            "chunk",
        )


@dataclass(frozen=True)
class MapMarker:
    """描述地图上的一个标记点."""

    id: str
    name: str
    x: int
    y: int
    z: int
    dimension_id: str
    color: str = "#FFD54F"
    group: str = "default"
    icon: str = "pin"
    enabled: bool = True
    show_label: bool = True
    source: str = "user"
    metadata: Dict[str, Any] = field(default_factory=dict, compare=True, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _text(self.id, "id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(self, "x", _integer(self.x, "x"))
        object.__setattr__(self, "y", _integer(self.y, "y"))
        object.__setattr__(self, "z", _integer(self.z, "z"))
        object.__setattr__(
            self,
            "dimension_id",
            _text(self.dimension_id, "dimension_id"),
        )
        object.__setattr__(self, "color", _text(self.color, "color"))
        object.__setattr__(self, "group", _text(self.group, "group"))
        object.__setattr__(self, "icon", _text(self.icon, "icon"))
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")
        if not isinstance(self.show_label, bool):
            raise TypeError("show_label must be a boolean")
        object.__setattr__(self, "source", _text(self.source, "source"))
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", copy.deepcopy(dict(self.metadata)))

    def to_dict(self) -> Dict[str, Any]:
        """序列化标记并返回独立的 metadata 副本."""
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "dimension_id": self.dimension_id,
            "color": self.color,
            "group": self.group,
            "icon": self.icon,
            "enabled": self.enabled,
            "show_label": self.show_label,
            "source": self.source,
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MapMarker":
        """从字典恢复标记, 并复制输入 metadata."""
        if not isinstance(data, Mapping):
            raise TypeError("data must be a mapping")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        return cls(
            id=data["id"],
            name=data["name"],
            x=data["x"],
            y=data["y"],
            z=data["z"],
            dimension_id=data["dimension_id"],
            color=data.get("color", "#FFD54F"),
            group=data.get("group", "default"),
            icon=data.get("icon", "pin"),
            enabled=data.get("enabled", True),
            show_label=data.get("show_label", True),
            source=data.get("source", "user"),
            metadata=copy.deepcopy(dict(metadata)),
        )


@dataclass
class MapLayerState:
    """描述地图图层的显示开关."""

    show_grid: bool = False
    show_coordinates: bool = False
    show_markers: bool = True
    show_empty_regions: bool = False


@dataclass
class MapViewState:
    """描述地图视图并管理维度和样式切换."""

    dimension_id: str = "overworld"
    style: str = "topview"
    center_x: float = 0.0
    center_z: float = 0.0
    scale: float = 1.0
    layers: MapLayerState = field(default_factory=MapLayerState)
    selection: Optional[MapSelection] = None
    generation: int = 0

    def __post_init__(self) -> None:
        self.dimension_id = _text(self.dimension_id, "dimension_id")
        self.style = _text(self.style, "style")
        self.center_x = self._finite_coordinate(self.center_x, "center_x")
        self.center_z = self._finite_coordinate(self.center_z, "center_z")
        self.scale = _positive_number(self.scale, "scale")
        self.generation = _integer(self.generation, "generation")
        if self.generation < 0:
            raise ValueError("generation must be greater than or equal to zero")
        if not isinstance(self.layers, MapLayerState):
            raise TypeError("layers must be a MapLayerState")
        if self.selection is not None and not isinstance(self.selection, MapSelection):
            raise TypeError("selection must be a MapSelection or None")

    @staticmethod
    def _finite_coordinate(value: Any, field_name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{field_name} must be a number")
        coordinate = float(value)
        if not math.isfinite(coordinate):
            raise ValueError(f"{field_name} must be finite")
        return coordinate

    def switch_dimension(
        self,
        target: MapTarget,
        coordinate_scale_ratio: float = 1.0,
    ) -> "MapViewState":
        """切换维度并按比例移动中心锚点."""
        if isinstance(target, MapDimension):
            target_id = target.id
        else:
            target_id = _text(target, "target")
        ratio = _positive_number(coordinate_scale_ratio, "coordinate_scale_ratio")
        self.dimension_id = target_id
        self.center_x *= ratio
        self.center_z *= ratio
        self.selection = None
        self.generation += 1
        return self

    def set_style(self, style: str) -> "MapViewState":
        """设置地图样式并使视图代次递增."""
        style = _text(style, "style")
        if style != self.style:
            self.style = style
            self.generation += 1
        return self


@dataclass(frozen=True)
class MapExportSpec:
    """描述一次地图导出的参数."""

    dimension_id: str = "overworld"
    style: str = "topview"
    scale: int = 1
    selection: Optional[MapSelection] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimension_id", _text(self.dimension_id, "dimension_id"))
        style = _text(self.style, "style")
        if style not in SUPPORTED_MAP_STYLES:
            supported = ", ".join(sorted(SUPPORTED_MAP_STYLES))
            raise ValueError(f"style must be one of: {supported}")
        object.__setattr__(self, "style", style)
        scale = _integer(self.scale, "scale")
        if scale <= 0:
            raise ValueError("scale must be greater than zero")
        object.__setattr__(self, "scale", scale)
        if self.selection is not None and not isinstance(self.selection, MapSelection):
            raise TypeError("selection must be a MapSelection or None")


__all__ = [
    "BLOCKS_PER_CHUNK",
    "BLOCKS_PER_REGION",
    "CHUNKS_PER_REGION",
    "MapBounds",
    "MapDimension",
    "MapExportSpec",
    "MapLayerState",
    "MapMarker",
    "MapSelection",
    "MapTileKey",
    "MapUnit",
    "MapViewState",
    "SUPPORTED_MAP_STYLES",
]
