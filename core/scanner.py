from pathlib import Path
from typing import List

from core.region_utils import iter_region_dirs, scan_region_dir


def scan_all_regions(world_path: Path) -> List[Path]:
    """扫描所有区域文件

    直接枚举已知的 region/ 目录，而非递归搜索整个存档树。
    这比 rglob 快得多，尤其对拥有大量模组维度的存档。

    Args:
        world_path: 世界存档路径

    Returns:
        区域文件路径列表
    """
    from core.performance import get_tracker
    tracker = get_tracker()

    with tracker.track("区域文件扫描", {"world": str(world_path)}):
        files: List[Path] = []
        total_bytes = 0
        for region_dir in iter_region_dirs(world_path):
            for f in scan_region_dir(region_dir):
                files.append(f)
                try:
                    total_bytes += f.stat().st_size
                except OSError:
                    pass

        files.sort(key=lambda p: str(p))
        tracker.increment_files(len(files))
        tracker.increment_bytes(total_bytes)

    return files


def scan_all_entity_regions(world_path: Path) -> List[Path]:
    """Scan entity-region siblings for every discovered dimension."""
    files: List[Path] = []
    candidates = [world_path / "entities"]
    if world_path.is_dir():
        candidates.extend(
            path / "entities"
            for path in world_path.iterdir()
            if path.is_dir() and path.name.startswith("DIM")
        )
    dimensions_root = world_path / "dimensions"
    if dimensions_root.is_dir():
        for namespace in dimensions_root.iterdir():
            if not namespace.is_dir():
                continue
            candidates.extend(
                dimension / "entities"
                for dimension in namespace.iterdir()
                if dimension.is_dir()
            )
    for entity_dir in candidates:
        files.extend(scan_region_dir(entity_dir))
    return sorted(set(files), key=lambda path: str(path))
