import os
import shutil
from pathlib import Path
from typing import Callable

CLEAN_PATTERNS = {
    "logs", "crash-reports", "session.lock", ".ds_store", "thumbs.db",
    "server-resource-packs", "downloads", "journeymap", "xaero", "voxelmap"
}

def should_clean(p: Path) -> bool:
    name = p.name.lower()
    if name in CLEAN_PATTERNS:
        return True
    if name.endswith(".clientcache") or name.endswith(".log"):
        return True
    return False

def clean_world(world_path: Path, log: Callable[[str, str], None]) -> None:
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