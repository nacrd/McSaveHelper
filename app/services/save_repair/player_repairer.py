"""Player Repairer - 玩家数据修复服务

修复玩家数据文件，补充缺失字段，隔离无法修复的文件。
"""
import threading
from pathlib import Path
from typing import Callable, List, Dict, Any

import nbtlib
from nbtlib import Compound, String, Float, Int, List as NbtList, Double

from .models import RepairReport, IssueLevel, RepairIssue
from .validation_utils import quarantine_file
from core.utils import list_player_dat_files


# 玩家数据必需字段列表
PLAYER_REQUIRED_FIELDS = [
    "Pos",
    "Rotation",
    "Health",
    "foodLevel",
    "foodSaturationLevel",
    "XpLevel",
    "XpP",
    "Inventory",
    "Dimension",
    "playerGameType",
]


def get_player_defaults() -> Dict[str, Any]:
    """获取玩家数据默认值（工厂函数，避免跨文件共享可变对象）"""
    return {
        "Pos": NbtList[Double]([0.0, 64.0, 0.0]),
        "Rotation": NbtList[Float]([0.0, 0.0]),
        "Health": Float(20.0),
        "foodLevel": Int(20),
        "foodSaturationLevel": Float(5.0),
        "XpLevel": Int(0),
        "XpP": Float(0.0),
        "Inventory": NbtList[Compound]([]),
        "Dimension": String("minecraft:overworld"),
        "playerGameType": Int(0),
    }


class PlayerRepairer:
    """玩家数据修复器"""

    def __init__(self, cancel_event: threading.Event) -> None:
        self._cancel_event = cancel_event

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def repair_players(
        self,
        world_path: Path,
        report: RepairReport,
        log: Callable[[str, str], None],
    ) -> None:
        """修复玩家数据（兼容 Minecraft 26.1 新旧路径）"""
        player_files = list_player_dat_files(world_path)

        if not player_files:
            log("玩家数据目录不存在", "WARNING")
            return

        log(f"找到 {len(player_files)} 个玩家数据文件", "INFO")

        for player_file in player_files:
            if self.is_cancelled:
                break

            try:
                nbt_data = nbtlib.load(str(player_file))
                report.players_checked += 1

                missing = self._find_missing_fields(nbt_data)
                if missing:
                    repaired = self._repair_fields(nbt_data, missing)
                    if repaired:
                        # 保存修复后的数据
                        nbt_data.save(player_file)
                        report.players_fixed += 1
                        log(
                            f"玩家数据 {player_file.name} 已修复缺失字段: {', '.join(repaired)}",
                            "SUCCESS",
                        )
                        report.issues.append(RepairIssue(
                            level=IssueLevel.FIXED,
                            category="player",
                            message=f"{player_file.name}: 修复 {', '.join(repaired)}",
                            file_path=str(player_file),
                        ))
                    else:
                        log(f"玩家数据 {player_file.name} 字段完整", "INFO")

            except Exception as e:
                log(f"无法读取玩家数据 {player_file.name}: {e}", "ERROR")
                quarantine_file(player_file, log)
                report.players_quarantined += 1
                report.issues.append(RepairIssue(
                    level=IssueLevel.ERROR,
                    category="player",
                    message=f"{player_file.name}: 已隔离 ({e})",
                    file_path=str(player_file),
                ))

    def _find_missing_fields(self, nbt_data: Any) -> List[str]:
        """查找玩家数据中缺失的必需字段"""
        missing: List[str] = []
        for field_name in PLAYER_REQUIRED_FIELDS:
            if field_name not in nbt_data:
                missing.append(field_name)
        return missing

    def _repair_fields(
        self,
        nbt_data: Any,
        missing: List[str],
    ) -> List[str]:
        """尝试用默认值填充缺失字段，返回实际修复的字段列表"""
        defaults = get_player_defaults()
        repaired: List[str] = []
        for field_name in missing:
            default = defaults.get(field_name)
            if default is None:
                continue
            try:
                nbt_data[field_name] = default
                repaired.append(field_name)
            except Exception:
                pass
        return repaired

