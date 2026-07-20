"""Data Models for Save Repair Service

定义存档修复服务使用的所有数据模型。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Tuple


class IssueLevel(Enum):
    """问题严重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FIXED = "fixed"


@dataclass
class RepairIssue:
    """单条修复问题记录"""
    level: IssueLevel
    category: str
    message: str
    file_path: str = ""


@dataclass
class RepairReport:
    """修复报告"""
    success: bool = False
    chunks_checked: int = 0
    chunks_damaged: int = 0
    chunks_quarantined_regions: int = 0
    players_checked: int = 0
    players_fixed: int = 0
    players_quarantined: int = 0
    level_dat_fixed: bool = False
    level_dat_repaired_fields: List[str] = field(default_factory=list)
    backup_path: str = ""
    elapsed_seconds: float = 0.0
    cancelled: bool = False
    issues: List[RepairIssue] = field(default_factory=list)


@dataclass
class WorldInfo:
    """世界基本信息"""
    world_name: str = ""
    data_version: int = 0
    version_name: str = ""
    game_type: int = 0
    game_type_name: str = ""
    difficulty: int = 2
    difficulty_name: str = ""
    seed: int = 0
    spawn_pos: Tuple[int, int, int] = (0, 64, 0)
    world_size_mb: float = 0.0
    total_files: int = 0
    dimensions: List[str] = field(default_factory=list)
    region_count: int = 0
    total_chunks: int = 0
    player_count: int = 0
    has_level_dat: bool = False
    play_time_ticks: int = 0


@dataclass
class DetectReport:
    """存档检测报告（只读，不修改任何文件）"""
    world_info: WorldInfo = field(default_factory=WorldInfo)
    chunks_checked: int = 0
    chunks_damaged: int = 0
    unreadable_regions: List[str] = field(default_factory=list)
    players_checked: int = 0
    players_with_issues: int = 0
    player_issues: Dict[str, List[str]] = field(default_factory=dict)
    level_dat_ok: bool = False
    level_dat_issues: List[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    cancelled: bool = False
    issues: List[RepairIssue] = field(default_factory=list)

    @property
    def has_problems(self) -> bool:
        return (
            self.chunks_damaged > 0
            or len(self.unreadable_regions) > 0
            or self.players_with_issues > 0
            or not self.level_dat_ok
        )
