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
    if data_version is None or data_version < DATA_VERSION_1_18:
        return range(0, 16)
    return range(-4, 20)


def has_modern_heightmaps(data_version: Optional[int]) -> bool:
    return data_version is not None and data_version >= DATA_VERSION_1_13
