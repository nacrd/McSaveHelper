from pathlib import Path
from typing import List
import re


_REGION_FILE_RE = re.compile(r"^r\.-?\d+\.-?\d+\.mca$")


def scan_all_regions(world_path: Path) -> List[Path]:
    """扫描所有区域文件

    Args:
        world_path: 世界存档路径

    Returns:
        区域文件路径列表
    """
    # 使用单一 glob 递归模式覆盖所有 region 子目录，避免重复扫描
    files: List[Path] = []
    for file in world_path.rglob("*.mca"):
        if file.is_file() and file.parent.name == "region" and _REGION_FILE_RE.match(file.name):
            files.append(file)
    return sorted(set(files))
