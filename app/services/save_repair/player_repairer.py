"""Player Repairer - 玩家数据修复服务

修复玩家数据文件，补充缺失字段，隔离无法修复的文件。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping

import core.nbt as nbtlib
from core.nbt import Compound, Double, Float, Int, List as NbtList, String

from core.utils import list_player_dat_files

from .models import IssueLevel, RepairIssue, RepairReport
from .validation_utils import quarantine_file

LogFn = Callable[[str, str], None]

# 玩家数据必需字段列表
PLAYER_REQUIRED_FIELDS: tuple[str, ...] = (
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
)


def get_player_defaults() -> Dict[str, Any]:
    """构造玩家数据默认值。

    每次调用返回新的 NBT 标签实例，避免跨文件共享可变对象。

    Returns:
        Dict[str, Any]: 字段名到 NBT 默认标签的映射。
    """
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


def find_missing_player_fields(
    nbt_data: Mapping[str, Any],
    required_fields: tuple[str, ...] = PLAYER_REQUIRED_FIELDS,
) -> List[str]:
    """查找玩家 NBT 中缺失的必需字段。

    Args:
        nbt_data: 玩家数据根标签（可映射访问）。
        required_fields: 需要检查的字段名序列。

    Returns:
        List[str]: 缺失字段名列表，保持 ``required_fields`` 顺序。
    """
    return [name for name in required_fields if name not in nbt_data]


def apply_player_field_defaults(
    nbt_data: MutableMapping[str, Any],
    missing: List[str],
    defaults: Mapping[str, Any] | None = None,
) -> List[str]:
    """用默认值填充缺失字段。

    Args:
        nbt_data: 可写的玩家数据根标签。
        missing: 需要填充的字段名列表。
        defaults: 可选默认值映射；``None`` 时调用
            :func:`get_player_defaults`。

    Returns:
        List[str]: 实际写入成功的字段名列表。
    """
    values = defaults if defaults is not None else get_player_defaults()
    repaired: List[str] = []
    for field_name in missing:
        default = values.get(field_name)
        if default is None:
            continue
        try:
            nbt_data[field_name] = default
        except (TypeError, ValueError, KeyError):
            # NBT 标签类型不兼容时跳过该字段，继续修复其余项。
            continue
        repaired.append(field_name)
    return repaired


class PlayerRepairer:
    """玩家数据修复器。

    在世界路径下扫描玩家 ``.dat`` 文件，补齐缺失的必需字段；
    无法读取的文件会被隔离并记入报告。
    """

    def __init__(self, cancel_event: threading.Event) -> None:
        """初始化修复器。

        Args:
            cancel_event: 协作式取消事件；置位后停止后续文件处理。
        """
        self._cancel_event = cancel_event

    @property
    def is_cancelled(self) -> bool:
        """当前修复是否已被请求取消。"""
        return self._cancel_event.is_set()

    def repair_players(
        self,
        world_path: Path,
        report: RepairReport,
        log: LogFn,
    ) -> None:
        """修复世界中的玩家数据文件。

        兼容 Minecraft 26.1 新旧玩家目录布局。

        Args:
            world_path: 世界根目录（含 ``level.dat``）。
            report: 可变修复报告，用于累计检查/修复/隔离计数。
            log: 日志回调 ``(message, level)``。

        Raises:
            本方法不向外抛出单文件 I/O 错误；无法处理的文件会隔离并记入
            ``report``。取消仅停止后续文件，不回滚已写入内容。
        """
        player_files = list_player_dat_files(world_path)
        if not player_files:
            log("玩家数据目录不存在", "WARNING")
            return

        log(f"找到 {len(player_files)} 个玩家数据文件", "INFO")
        for player_file in player_files:
            if self.is_cancelled:
                break
            self._repair_one_player(player_file, report, log)

    def _repair_one_player(
        self,
        player_file: Path,
        report: RepairReport,
        log: LogFn,
    ) -> None:
        """修复单个玩家数据文件。

        Args:
            player_file: 玩家 ``.dat`` 路径。
            report: 可变修复报告。
            log: 日志回调。
        """
        try:
            nbt_data = nbtlib.load(str(player_file))
            report.players_checked += 1
            missing = find_missing_player_fields(nbt_data)
            if not missing:
                return

            repaired = apply_player_field_defaults(nbt_data, missing)
            if not repaired:
                log(f"玩家数据 {player_file.name} 字段完整", "INFO")
                return

            nbt_data.save(player_file)
            report.players_fixed += 1
            joined = ", ".join(repaired)
            log(
                f"玩家数据 {player_file.name} 已修复缺失字段: {joined}",
                "SUCCESS",
            )
            report.issues.append(RepairIssue(
                level=IssueLevel.FIXED,
                category="player",
                message=f"{player_file.name}: 修复 {joined}",
                file_path=str(player_file),
            ))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self._quarantine_player(player_file, report, log, exc)
        except Exception as exc:
            # NBT 解析可能抛出库专属错误；隔离后继续处理其余玩家。
            self._quarantine_player(player_file, report, log, exc)

    def _quarantine_player(
        self,
        player_file: Path,
        report: RepairReport,
        log: LogFn,
        exc: BaseException,
    ) -> None:
        """隔离无法读取/修复的玩家文件并记入报告。"""
        log(f"无法读取玩家数据 {player_file.name}: {exc}", "ERROR")
        quarantine_file(player_file, log)
        report.players_quarantined += 1
        report.issues.append(RepairIssue(
            level=IssueLevel.ERROR,
            category="player",
            message=f"{player_file.name}: 已隔离 ({exc})",
            file_path=str(player_file),
        ))
