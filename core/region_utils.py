from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union
import re


REGION_FILE_RE = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.mca$")


def parse_region_coords(path_or_name: Union[Path, str]) -> Optional[Tuple[int, int]]:
    """解析 MCA 区域文件坐标。"""
    name = path_or_name.name if isinstance(path_or_name, Path) else str(path_or_name)
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


def iter_region_dirs(world_path: Path, include_dimensions: bool = True) -> Iterable[Path]:
    """枚举世界存档中的 region 目录。"""
    yield world_path / "region"
    if not include_dimensions:
        return

    try:
        for dim_dir in world_path.iterdir():
            if dim_dir.is_dir() and dim_dir.name.startswith("DIM"):
                yield dim_dir / "region"
    except OSError:
        pass

    dimensions_base = world_path / "dimensions"
    if not dimensions_base.is_dir():
        return
    try:
        for namespace_dir in dimensions_base.iterdir():
            if not namespace_dir.is_dir():
                continue
            try:
                for dim_dir in namespace_dir.iterdir():
                    if dim_dir.is_dir():
                        yield dim_dir / "region"
            except OSError:
                pass
    except OSError:
        pass


def scan_regions(world_path: Path, include_dimensions: bool = True) -> List[Path]:
    """扫描世界存档中的有效 MCA 文件。"""
    files: List[Path] = []
    for region_dir in iter_region_dirs(world_path, include_dimensions=include_dimensions):
        files.extend(scan_region_dir(region_dir))
    return sorted(files, key=lambda p: str(p))
