from pathlib import Path
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple, TypedDict, Union
import re


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
    """One logical Minecraft dimension and its active region directory."""

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
        path_or_name: Union[Path, str]) -> Optional[Tuple[int, int]]:
    """解析 MCA 区域文件坐标。"""
    name = path_or_name.name if isinstance(
        path_or_name, Path) else str(path_or_name)
    match = REGION_FILE_RE.match(name)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def scan_region_dir(region_dir: Path) -> List[Path]:
    """扫描单个 region 目录中的有效 MCA 文件。"""
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
    """Return whether a directory contains at least one valid MCA file.

    Dimension discovery only needs an existence check; avoid materializing and
    sorting every region path before the caller performs the actual scan.
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
    if not parent.is_dir():
        return []
    try:
        return sorted(
            (path for path in parent.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
    except OSError:
        return []


def discover_dimension_region_dirs(
    world_path: Path,
) -> List[DimensionRegionDirectory]:
    """Discover active dimension directories with modern paths taking priority."""
    dimensions: List[DimensionRegionDirectory] = []
    seen: set[str] = set()

    def add(dim_id: str, name: str, region_dir: Path) -> None:
        if dim_id in seen or not has_region_file(region_dir):
            return
        dimensions.append(
            DimensionRegionDirectory(
                dim_id,
                name,
                region_dir,
                coordinate_scale=_coordinate_scale(dim_id),
            )
        )
        seen.add(dim_id)

    modern_root = world_path / "dimensions" / "minecraft"
    for dimension_dir in _iter_directories(modern_root):
        dimension_name = dimension_dir.name
        dim_id = (
            "overworld"
            if dimension_name == "overworld"
            else f"minecraft:{dimension_name}"
        )
        add(
            dim_id,
            _VANILLA_DIMENSION_NAMES.get(
                dimension_name,
                f"📦 minecraft:{dimension_name}",
            ),
            dimension_dir / "region",
        )

    add("overworld", _VANILLA_DIMENSION_NAMES["overworld"], world_path / "region")

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
        add(dim_id, display_name, dimension_dir / "region")

    dimensions_root = world_path / "dimensions"
    for namespace_dir in _iter_directories(dimensions_root):
        if namespace_dir.name == "minecraft":
            continue
        for dimension_dir in _iter_directories(namespace_dir):
            dim_id = f"{namespace_dir.name}:{dimension_dir.name}"
            add(dim_id, f"📦 {dim_id}", dimension_dir / "region")

    return dimensions


def iter_region_dirs(
    world_path: Path,
    include_dimensions: bool = True,
) -> Iterable[Path]:
    """枚举包含有效 MCA 文件的 region 目录。"""
    if not include_dimensions:
        if scan_region_dir(world_path / "region"):
            yield world_path / "region"
        return
    for dimension in discover_dimension_region_dirs(world_path):
        yield dimension.region_dir


def scan_regions(
        world_path: Path,
        include_dimensions: bool = True) -> List[Path]:
    """扫描世界存档中的有效 MCA 文件。"""
    files: List[Path] = []
    for region_dir in iter_region_dirs(
            world_path, include_dimensions=include_dimensions):
        files.extend(scan_region_dir(region_dir))
    return sorted(files, key=lambda p: str(p))
