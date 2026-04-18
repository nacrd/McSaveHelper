import os
import shutil
from pathlib import Path

from .types import LogCallback
from .constants import MinecraftConstants



def should_clean(p: Path) -> bool:
    name = p.name.lower()
    if name in MinecraftConstants.CLEAN_PATTERNS:
        return True
    # 检查扩展名是否在清理扩展名集合中
    for ext in MinecraftConstants.CLEAN_EXTENSIONS:
        if name.endswith(ext):
            return True
    return False


def clean_world(world_path: Path, log: LogCallback) -> None:
    cleaned = 0
    for root, dirs, files in os.walk(world_path, topdown=False):
        for file in files:
            fp = Path(root) / file
            if should_clean(fp):
                try:
                    fp.unlink()
                    cleaned += 1
                except OSError:
                    pass
        for d in dirs:
            dp = Path(root) / d
            if should_clean(dp):
                try:
                    shutil.rmtree(dp)
                    cleaned += 1
                except OSError:
                    pass
    if cleaned > 0:
        log(f"精简完成，删除了 {cleaned} 项", "CLEAN")