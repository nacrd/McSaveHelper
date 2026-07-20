"""DataVersion helpers for future section / heightmap branches."""
from __future__ import annotations

from typing import Optional

DATA_VERSION_1_13 = 1519
DATA_VERSION_1_15 = 2200
DATA_VERSION_1_16 = 2566
DATA_VERSION_1_18 = 2844
DATA_VERSION_1_20 = 3463
DATA_VERSION_1_21 = 3953


def section_y_range(data_version: Optional[int]) -> range:
    """按 DataVersion 返回 section Y 索引范围。

    1.18+ 为 ``range(-4, 20)``，更早为 ``range(0, 16)``。

    Args:
        data_version: 世界 DataVersion；None 按旧版处理。
    """
    if data_version is None or data_version < DATA_VERSION_1_18:
        return range(0, 16)
    return range(-4, 20)


def has_modern_heightmaps(data_version: Optional[int]) -> bool:
    """是否使用 1.13+ 复合高度图结构。"""
    return data_version is not None and data_version >= DATA_VERSION_1_13
