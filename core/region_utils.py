"""Region / dimension path helpers for Minecraft Java worlds.

Discovers active dimension region directories (modern and legacy layouts),
parses ``r.x.z.mca`` names, and scans MCA files without loading chunk data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, TypedDict, Union

REGION_FILE_RE = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.mca$")

_VANILLA_DIMENSION_NAMES = {
    "overworld": "🌍 主世界",
    "the_nether": "🔥 下界",
    "the_end": "🌌 末地",
}
_LEGACY_DIMENSION_IDS = {
    "DIM-1": "minecraft:the_nether",
    "DIM1": "minecraft:the_end",
}


@dataclass(frozen=True)
class DimensionRegionDirectory:
    """One logical Minecraft dimension and its active region directory.

    Attributes:
        id: Dimension id such as ``overworld`` or ``minecraft:the_nether``.
        name: UI display name.
        region_dir: Directory containing ``r.*.*.mca`` files.
        coordinate_scale: Vanilla portal scale relative to overworld.
    """

    id: str
    name: str
    region_dir: Path
    coordinate_scale: float = 1.0


class DimensionInfo(TypedDict):
    """Serialized dimension metadata shared by the session and map UI."""

    id: str
    name: str
    region_dir: str
    coordinate_scale: float


def _coordinate_scale(dimension_id: str) -> float:
    """Return the vanilla portal coordinate scale for a dimension id."""
    if dimension_id in {"minecraft:the_nether", "the_nether", "DIM-1"}:
        return 8.0
    return 1.0


def parse_region_coords(
    path_or_name: Union[Path, str],
) -> Optional[Tuple[int, int]]:
    """解析 MCA 区域文件名中的区域坐标。

    Args:
        path_or_name: 文件路径或文件名 ``r.X.Z.mca``。

    Returns:
        tuple[int, int] | None: ``(region_x, region_z)``；名不合法时为 None。
    """
    name = (
        path_or_name.name
        if isinstance(path_or_name, Path)
        else str(path_or_name)
    )
    match = REGION_FILE_RE.match(name)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def scan_region_dir(region_dir: Path) -> List[Path]:
    """扫描单个 region 目录中的有效 MCA 文件。

    Args:
        region_dir: 区域目录路径。

    Returns:
        list[Path]: 按路径排序的 MCA 文件列表。
    """
    if not region_dir.is_dir():
        return []
    files: List[Path] = []
    try:
        for path in region_dir.iterdir():
            if path.is_file() and parse_region_coords(path) is not None:
                files.append(path)
    except OSError:
        return []
    return sorted(files)


def has_region_file(region_dir: Path) -> bool:
    """判断目录是否至少包含一个有效 MCA 文件。

    维度发现只需存在性检查，避免在调用方真正扫描前物化并排序全部路径。

    Args:
        region_dir: 区域目录。

    Returns:
        bool: 存在有效区域文件时为 True。
    """
    if not region_dir.is_dir():
        return False
    try:
        return any(
            path.is_file() and parse_region_coords(path) is not None
            for path in region_dir.iterdir()
        )
    except OSError:
        return False


def _iter_directories(parent: Path) -> List[Path]:
    """列出子目录（按名称排序）；不可读时返回空列表。"""
    if not parent.is_dir():
        return []
    try:
        return sorted(
            (path for path in parent.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
    except OSError:
        return []


class _DimensionCollector:
    """Collect unique dimensions that currently have region files."""

    def __init__(self) -> None:
        self.dimensions: List[DimensionRegionDirectory] = []
        self._seen: set[str] = set()

    def add(self, dim_id: str, name: str, region_dir: Path) -> None:
        """Register a dimension if not seen and region files exist."""
        if dim_id in self._seen or not has_region_file(region_dir):
            return
        self.dimensions.append(
            DimensionRegionDirectory(
                dim_id,
                name,
                region_dir,
                coordinate_scale=_coordinate_scale(dim_id),
            )
        )
        self._seen.add(dim_id)


def discover_dimension_region_dirs(
    world_path: Path,
) -> List[DimensionRegionDirectory]:
    """发现当前有区域文件的维度目录。

    优先级：现代 ``dimensions/minecraft/*`` → 根 ``region`` / 旧版
    ``DIM*`` → 其他命名空间自定义维度。已见 ID 不会被低优先级布局覆盖。

    Args:
        world_path: 世界根目录。

    Returns:
        list[DimensionRegionDirectory]: 有序维度列表。
    """
    collector = _DimensionCollector()
    _collect_modern_vanilla_dimensions(collector, world_path)
    _collect_legacy_and_custom_dimensions(collector, world_path)
    return collector.dimensions


def _collect_modern_vanilla_dimensions(
    collector: _DimensionCollector,
    world_path: Path,
) -> None:
    modern_root = world_path / "dimensions" / "minecraft"
    for dimension_dir in _iter_directories(modern_root):
        dimension_name = dimension_dir.name
        dim_id = (
            "overworld"
            if dimension_name == "overworld"
            else f"minecraft:{dimension_name}"
        )
        collector.add(
            dim_id,
            _VANILLA_DIMENSION_NAMES.get(
                dimension_name,
                f"📦 minecraft:{dimension_name}",
            ),
            dimension_dir / "region",
        )
    collector.add(
        "overworld",
        _VANILLA_DIMENSION_NAMES["overworld"],
        world_path / "region",
    )


def _collect_legacy_and_custom_dimensions(
    collector: _DimensionCollector,
    world_path: Path,
) -> None:
    for dimension_dir in _iter_directories(world_path):
        if not dimension_dir.name.startswith("DIM"):
            continue
        dim_id = _LEGACY_DIMENSION_IDS.get(
            dimension_dir.name,
            dimension_dir.name.lower(),
        )
        display_name = {
            "DIM-1": _VANILLA_DIMENSION_NAMES["the_nether"],
            "DIM1": _VANILLA_DIMENSION_NAMES["the_end"],
        }.get(dimension_dir.name, f"📦 {dimension_dir.name}")
        collector.add(dim_id, display_name, dimension_dir / "region")

    dimensions_root = world_path / "dimensions"
    for namespace_dir in _iter_directories(dimensions_root):
        if namespace_dir.name == "minecraft":
            continue
        for dimension_dir in _iter_directories(namespace_dir):
            dim_id = f"{namespace_dir.name}:{dimension_dir.name}"
            collector.add(
                dim_id,
                f"📦 {dim_id}",
                dimension_dir / "region",
            )


def iter_region_dirs(
    world_path: Path,
    include_dimensions: bool = True,
) -> Iterable[Path]:
    """枚举包含有效 MCA 文件的 region 目录。

    Args:
        world_path: 世界根目录。
        include_dimensions: False 时仅主世界 ``region``。

    Yields:
        Path: 区域目录路径。
    """
    if not include_dimensions:
        region_dir = world_path / "region"
        if has_region_file(region_dir):
            yield region_dir
        return
    for dimension in discover_dimension_region_dirs(world_path):
        yield dimension.region_dir


def scan_regions(
    world_path: Path,
    include_dimensions: bool = True,
) -> List[Path]:
    """扫描世界存档中的有效 MCA 文件。

    Args:
        world_path: 世界根目录。
        include_dimensions: 是否包含其他维度。

    Returns:
        list[Path]: 按路径字符串排序的 MCA 文件列表。
    """
    files: List[Path] = []
    for region_dir in iter_region_dirs(
        world_path,
        include_dimensions=include_dimensions,
    ):
        files.extend(scan_region_dir(region_dir))
    return sorted(files, key=lambda path: str(path))
