"""Save Repair Service - 存档修复服务

将存档修复服务拆分为多个模块，按职责划分：

- ``models``: 报告与问题数据结构
- ``detector``: 只读检测
- ``chunk_repairer`` / ``player_repairer`` / ``level_repairer``: 修复实现
"""
from __future__ import annotations

from .chunk_repairer import ChunkRepairer
from .detector import WorldDetector
from .level_repairer import LevelRepairer
from .models import (
    DetectReport,
    IssueLevel,
    RepairIssue,
    RepairReport,
    WorldInfo,
)
from .player_repairer import PlayerRepairer

__all__ = [
    "IssueLevel",
    "RepairIssue",
    "RepairReport",
    "DetectReport",
    "WorldInfo",
    "WorldDetector",
    "ChunkRepairer",
    "PlayerRepairer",
    "LevelRepairer",
]
