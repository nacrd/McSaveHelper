from pathlib import Path
from typing import List
import re


_REGION_FILE_RE = re.compile(r"^r\.-?\d+\.-?\d+\.mca$")


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
        region_dirs: List[Path] = []

        # 主世界 region
        region_dirs.append(world_path / "region")

        # DIM* 格式（旧版 / 模组维度，含 DIM-1、DIM1）
        try:
            for dim_dir in world_path.iterdir():
                if dim_dir.is_dir() and dim_dir.name.startswith("DIM"):
                    region_dirs.append(dim_dir / "region")
        except OSError:
            pass

        # dimensions/namespace/name 格式（1.16+ 模组维度）
        dimensions_base = world_path / "dimensions"
        if dimensions_base.is_dir():
            try:
                for namespace_dir in dimensions_base.iterdir():
                    if not namespace_dir.is_dir():
                        continue
                    try:
                        for dim_dir in namespace_dir.iterdir():
                            if dim_dir.is_dir():
                                region_dirs.append(dim_dir / "region")
                    except OSError:
                        pass
            except OSError:
                pass

        total_bytes = 0
        for region_dir in region_dirs:
            if not region_dir.is_dir():
                continue
            try:
                for f in region_dir.iterdir():
                    if f.is_file() and _REGION_FILE_RE.match(f.name):
                        files.append(f)
                        try:
                            total_bytes += f.stat().st_size
                        except OSError:
                            pass
            except OSError:
                pass

        files.sort(key=lambda p: p.name)
        tracker.increment_files(len(files))
        tracker.increment_bytes(total_bytes)

    return files
