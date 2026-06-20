from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union
import re


REGION_FILE_RE = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.mca$")


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


def iter_region_dirs(
        world_path: Path,
        include_dimensions: bool = True) -> Iterable[Path]:
    """枚举世界存档中的 region 目录（兼容 Minecraft 26.1 新版路径）

    新版 (26.1): dimensions/minecraft/the_nether/region/, dimensions/minecraft/the_end/region/
    旧版: DIM-1/region/, DIM1/region/
    当新版路径存在时，跳过对应的旧版路径以避免重复扫描。
    """
    yield world_path / "region"
    if not include_dimensions:
        return

    # 已知的原版维度映射：旧路径名 -> (新版命名空间路径名, ...)
    _OLD_TO_NEW = {
        "DIM-1": ("dimensions", "minecraft", "the_nether"),
        "DIM1": ("dimensions", "minecraft", "the_end"),
    }

    yielded_new_dims: set = set()  # 记录已通过新版路径 yield 的维度

    # 先检查 dimensions/minecraft/ 下的新版路径（26.1+）
    mc_dims_base = world_path / "dimensions" / "minecraft"
    if mc_dims_base.is_dir():
        try:
            for dim_dir in mc_dims_base.iterdir():
                if not dim_dir.is_dir():
                    continue
                region_dir = dim_dir / "region"
                if region_dir.is_dir():
                    yield region_dir
                    yielded_new_dims.add(dim_dir.name)
        except OSError:
            pass

    # 再枚举旧版 DIM* 路径（如果对应的维度尚未通过新版路径处理）
    try:
        for dim_dir in world_path.iterdir():
            if dim_dir.is_dir() and dim_dir.name.startswith("DIM"):
                new_parts = _OLD_TO_NEW.get(dim_dir.name)
                if new_parts:
                    new_dim_name = new_parts[-1]  # e.g. "the_nether"
                    if new_dim_name in yielded_new_dims:
                        continue  # 新版路径已存在，跳过旧版
                yield dim_dir / "region"
    except OSError:
        pass

    # 枚举 dimensions/ 下的非 minecraft 命名空间维度（模组维度）
    dimensions_base = world_path / "dimensions"
    if not dimensions_base.is_dir():
        return
    try:
        for namespace_dir in dimensions_base.iterdir():
            if not namespace_dir.is_dir():
                continue
            # minecraft 命名空间已在上面处理过
            if namespace_dir.name == "minecraft":
                continue
            try:
                for dim_dir in namespace_dir.iterdir():
                    if dim_dir.is_dir():
                        yield dim_dir / "region"
            except OSError:
                pass
    except OSError:
        pass


def scan_regions(
        world_path: Path,
        include_dimensions: bool = True) -> List[Path]:
    """扫描世界存档中的有效 MCA 文件。"""
    files: List[Path] = []
    for region_dir in iter_region_dirs(
            world_path, include_dimensions=include_dimensions):
        files.extend(scan_region_dir(region_dir))
    return sorted(files, key=lambda p: str(p))
