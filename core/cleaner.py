"""存档清理模块

提供 Minecraft 存档目录的清理功能，删除临时文件、日志文件等不需要的内容。
"""

import os
import shutil
from pathlib import Path

from .types import LogCallback
from .constants import MinecraftConstants


def should_clean(path: Path) -> bool:
    """判断文件或目录是否需要清理

    根据文件名或扩展名判断是否在清理列表中。

    Args:
        path: 要检查的文件或目录路径

    Returns:
        如果需要清理返回 True，否则返回 False
    """
    name_lower: str = path.name.lower()

    if name_lower in MinecraftConstants.CLEAN_PATTERNS:
        return True

    for ext in MinecraftConstants.CLEAN_EXTENSIONS:
        if name_lower.endswith(ext):
            return True

    return False


def clean_world(world_path: Path, log: LogCallback) -> None:
    """清理世界存档目录中的临时文件和日志

    递归遍历目录，删除符合清理模式的文件和目录。
    清理失败时会静默跳过，不会中断清理过程。

    Args:
        world_path: 世界存档目录路径
        log: 日志回调函数，接受 (消息, 级别) 两个参数
    """
    cleaned_count: int = 0

    for root, dirs, files in os.walk(world_path, topdown=False):
        root_path = Path(root)

        for file_name in files:
            file_path = root_path / file_name
            if should_clean(file_path):
                try:
                    file_path.unlink()
                    cleaned_count += 1
                except OSError:
                    pass

        for dir_name in dirs:
            dir_path = root_path / dir_name
            if should_clean(dir_path):
                try:
                    shutil.rmtree(dir_path)
                    cleaned_count += 1
                except OSError:
                    pass

    if cleaned_count > 0:
        log(f"精简完成，删除了 {cleaned_count} 项", "CLEAN")
