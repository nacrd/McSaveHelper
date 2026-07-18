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

    @property
    def total_fixes(self) -> int:
        return (
            self.chunks_damaged
            + self.chunks_quarantined_regions * 1024
            + self.players_fixed
            + self.players_quarantined
            + (1 if self.level_dat_fixed else 0)
        )

    def summary_text(self) -> str:
        lines = [
            f"区块检查: {self.chunks_checked}",
            f"区块损坏: {self.chunks_damaged}",
            f"区域文件隔离: {self.chunks_quarantined_regions}",
            f"玩家检查: {self.players_checked}",
            f"玩家修复: {self.players_fixed}",
            f"玩家隔离: {self.players_quarantined}",
            f"level.dat: {'已修复' if self.level_dat_fixed else '正常'}",
        ]
        if self.level_dat_repaired_fields:
            lines.append(f"  修复字段: {', '.join(self.level_dat_repaired_fields)}")
        if self.backup_path:
            lines.append(f"备份位置: {self.backup_path}")
        lines.append(f"耗时: {self.elapsed_seconds:.1f}s")
        if self.cancelled:
            lines.append("(操作已取消)")
        return "\n".join(lines)


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
    has_level_dat_old: bool = False
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

    def summary_text(self) -> str:
        lines: List[str] = []
        info = self.world_info

        lines.append("── 世界信息 ──")
        if info.world_name:
            lines.append(f"名称: {info.world_name}")
        if info.version_name:
            lines.append(f"版本: {info.version_name} (DataVersion {info.data_version})")
        if info.game_type_name:
            lines.append(f"模式: {info.game_type_name}")
        lines.append(f"难度: {info.difficulty_name}")
        lines.append(f"种子: {info.seed}")
        lines.append(f"出生点: {info.spawn_pos}")
        if info.play_time_ticks > 0:
            hours = info.play_time_ticks / 72000
            lines.append(f"游戏时间: {hours:.1f} 小时")
        lines.append(f"存档大小: {info.world_size_mb:.1f} MB")
        lines.append(f"维度: {', '.join(info.dimensions) if info.dimensions else '无'}")
        lines.append(f"区域文件: {info.region_count}, 区块: {info.total_chunks}")
        lines.append(f"玩家: {info.player_count}")

        lines.append("")
        lines.append("── 检测结果 ──")
        lines.append(f"区块检查: {self.chunks_checked}, 损坏: {self.chunks_damaged}")
        if self.unreadable_regions:
            lines.append(f"无法读取的区域文件: {len(self.unreadable_regions)}")
            for name in self.unreadable_regions[:10]:
                lines.append(f"  - {name}")
            if len(self.unreadable_regions) > 10:
                lines.append(f"  ... 共 {len(self.unreadable_regions)} 个")
        lines.append(f"玩家检查: {self.players_checked}, 有问题: {self.players_with_issues}")
        if self.player_issues:
            for pname, pissues in list(self.player_issues.items())[:5]:
                lines.append(f"  {pname}: {', '.join(pissues)}")
        lines.append(f"level.dat: {'正常' if self.level_dat_ok else '异常'}")
        if self.level_dat_issues:
            for issue in self.level_dat_issues:
                lines.append(f"  - {issue}")

        lines.append(f"\n耗时: {self.elapsed_seconds:.1f}s")
        if self.cancelled:
            lines.append("(操作已取消)")

        if not self.has_problems:
            lines.append("\n存档状态良好，未发现问题。")
        else:
            lines.append(f"\n发现 {len(self.issues)} 个问题，建议执行修复。")

        return "\n".join(lines)
