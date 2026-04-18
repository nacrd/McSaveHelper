from pathlib import Path
from typing import List


def scan_all_regions(world_path: Path) -> List[Path]:
    """扫描所有区域文件

    Args:
        world_path: 世界存档路径

    Returns:
        区域文件路径列表
    """
    patterns = ["region/*.mca", "DIM*/region/*.mca", "dimensions/**/region/*.mca", "*/region/*.mca"]
    files: List[Path] = []
    for pat in patterns:
        files.extend(world_path.rglob(pat))
    return list(set(files))