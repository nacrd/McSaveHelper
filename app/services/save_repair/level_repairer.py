"""Level Repairer - level.dat 修复服务

修复 level.dat 文件，补充缺失字段，修正范围异常。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import nbtlib

from .models import RepairReport

LogFn = Callable[[str, str], None]

# level.dat 中 Data 下的必需字段及其默认值工厂
LEVEL_DAT_REQUIRED_FIELDS: Dict[str, Callable[[], Any]] = {
    "DataVersion": lambda: nbtlib.Int(0),
    "LevelName": lambda: nbtlib.String("World"),
    "generatorName": lambda: nbtlib.String("default"),
    "SpawnX": lambda: nbtlib.Int(0),
    "SpawnY": lambda: nbtlib.Int(64),
    "SpawnZ": lambda: nbtlib.Int(0),
    "RandomSeed": lambda: nbtlib.Long(0),
    "Time": lambda: nbtlib.Long(0),
    "DayTime": lambda: nbtlib.Long(0),
    "GameType": lambda: nbtlib.Int(0),
    "Difficulty": lambda: nbtlib.Byte(2),
    "DifficultyLocked": lambda: nbtlib.Byte(0),
    "allowCommands": lambda: nbtlib.Byte(1),
    "initialized": lambda: nbtlib.Byte(1),
}

# 合理 SpawnY 范围（现代高度限制的保守区间）
_SPAWN_Y_MIN = -64
_SPAWN_Y_MAX = 320
_SPAWN_Y_DEFAULT = 64
_DIFFICULTY_MIN = 0
_DIFFICULTY_MAX = 3
_DIFFICULTY_DEFAULT = 2


def add_missing_level_fields(
    data: Any,
    *,
    log: LogFn | None = None,
    required_fields: Dict[str, Callable[[], Any]] | None = None,
) -> List[str]:
    """用默认值补充 Data 中缺失的必需字段。

    Args:
        data: ``level.dat`` 的 ``Data`` Compound（可写映射）。
        log: 可选日志回调 ``(message, level)``。
        required_fields: 字段名到默认值工厂的映射；默认使用
            :data:`LEVEL_DAT_REQUIRED_FIELDS`。

    Returns:
        list[str]: 实际写入成功的字段名列表。
    """
    fields = required_fields if required_fields is not None else LEVEL_DAT_REQUIRED_FIELDS
    repaired: List[str] = []
    for field_name, default_factory in fields.items():
        if field_name in data:
            continue
        try:
            data[field_name] = default_factory()
        except (TypeError, ValueError, KeyError):
            # nbtlib 标签类型不兼容时跳过该字段。
            continue
        repaired.append(field_name)
        if log is not None:
            log(f"level.dat 补充缺失字段: {field_name}", "WARNING")
    return repaired


def repair_spawn_y_if_out_of_range(data: Any) -> Optional[str]:
    """当 ``SpawnY`` 越界时重置为默认高度。

    Args:
        data: ``level.dat`` 的 ``Data`` Compound。

    Returns:
        str | None: 修复描述（如 ``SpawnY(范围修正)``）；无需修复时为 None。
    """
    if "SpawnY" not in data:
        return None
    try:
        value = int(data["SpawnY"])
    except (ValueError, TypeError):
        return None
    if _SPAWN_Y_MIN <= value <= _SPAWN_Y_MAX:
        return None
    data["SpawnY"] = nbtlib.Int(_SPAWN_Y_DEFAULT)
    return "SpawnY(范围修正)"


def repair_difficulty_if_out_of_range(data: Any) -> Optional[str]:
    """当 ``Difficulty`` 不在 0–3 时重置为普通难度。

    Args:
        data: ``level.dat`` 的 ``Data`` Compound。

    Returns:
        str | None: 修复描述；无需修复时为 None。
    """
    if "Difficulty" not in data:
        return None
    try:
        value = int(data["Difficulty"])
    except (ValueError, TypeError):
        return None
    if _DIFFICULTY_MIN <= value <= _DIFFICULTY_MAX:
        return None
    data["Difficulty"] = nbtlib.Byte(_DIFFICULTY_DEFAULT)
    return "Difficulty(范围修正)"


def collect_level_field_repairs(
    data: Any,
    *,
    log: LogFn | None = None,
) -> List[str]:
    """执行字段级修复并返回修复项描述列表。

    Args:
        data: ``level.dat`` 的 ``Data`` Compound。
        log: 可选日志回调。

    Returns:
        list[str]: 修复项名称/描述列表。
    """
    repaired = add_missing_level_fields(data, log=log)
    spawn_fix = repair_spawn_y_if_out_of_range(data)
    if spawn_fix is not None:
        repaired.append(spawn_fix)
    difficulty_fix = repair_difficulty_if_out_of_range(data)
    if difficulty_fix is not None:
        repaired.append(difficulty_fix)
    return repaired


class LevelRepairer:
    """level.dat 修复器。

    在世界路径下校验并修复 ``level.dat``；主文件损坏时尝试从
    ``level.dat_old`` 原子恢复。
    """

    def __init__(self, cancel_event: threading.Event) -> None:
        """初始化修复器。

        Args:
            cancel_event: 协作式取消事件（当前 level 修复为单文件，保留以对齐接口）。
        """
        self._cancel_event = cancel_event

    @property
    def is_cancelled(self) -> bool:
        """当前修复是否已被请求取消。"""
        return self._cancel_event.is_set()

    def repair_level_dat(
        self,
        world_path: Path,
        report: RepairReport,
        log: LogFn,
    ) -> None:
        """修复世界中的 ``level.dat``。

        Args:
            world_path: 世界根目录（含 ``level.dat``）。
            report: 可变修复报告。
            log: 日志回调 ``(message, level)``。
        """
        if self.is_cancelled:
            return

        level_dat = world_path / "level.dat"
        level_dat_old = world_path / "level.dat_old"

        if not level_dat.exists():
            if level_dat_old.exists():
                log("level.dat 不存在，尝试从 level.dat_old 恢复", "WARNING")
                self._restore_from_backup(level_dat, level_dat_old, report, log)
            else:
                log("level.dat 和 level.dat_old 都不存在", "ERROR")
            return

        try:
            nbt_data = nbtlib.load(str(level_dat))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            log(f"level.dat 无法解析: {exc}", "ERROR")
            self._restore_from_backup(level_dat, level_dat_old, report, log)
            return
        except Exception as exc:
            # nbtlib 可能抛出库专属错误。
            log(f"level.dat 无法解析: {exc}", "ERROR")
            self._restore_from_backup(level_dat, level_dat_old, report, log)
            return

        if "Data" not in nbt_data:
            log("level.dat 缺少 Data 字段", "ERROR")
            self._restore_from_backup(level_dat, level_dat_old, report, log)
            return

        data = nbt_data["Data"]
        if not isinstance(data, nbtlib.tag.Compound):
            log("level.dat 的 Data 字段类型错误", "ERROR")
            self._restore_from_backup(level_dat, level_dat_old, report, log)
            return

        repaired_fields = collect_level_field_repairs(data, log=log)
        if not repaired_fields:
            log("level.dat 验证通过", "INFO")
            return

        try:
            self._save_atomically(nbt_data, level_dat)
        except OSError as exc:
            log(f"保存 level.dat 失败: {exc}", "ERROR")
            return
        except Exception as exc:
            log(f"保存 level.dat 失败: {exc}", "ERROR")
            return

        report.level_dat_fixed = True
        report.level_dat_repaired_fields = repaired_fields
        log(
            f"level.dat 已保存修复 ({', '.join(repaired_fields)})",
            "SUCCESS",
        )

    def _restore_from_backup(
        self,
        level_dat: Path,
        level_dat_old: Path,
        report: RepairReport,
        log: LogFn,
    ) -> None:
        """从 ``level.dat_old`` 原子恢复主文件。"""
        if not level_dat_old.exists():
            log("level.dat_old 不存在，无法恢复", "ERROR")
            return

        log("尝试从 level.dat_old 恢复", "WARNING")
        try:
            nbtlib.load(str(level_dat_old))
            self._copy_atomically(level_dat_old, level_dat)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            log(f"level.dat_old 无法恢复: {exc}", "ERROR")
            return
        except Exception as exc:
            log(f"level.dat_old 无法恢复: {exc}", "ERROR")
            return

        report.level_dat_fixed = True
        log("已从 level.dat_old 恢复", "SUCCESS")

    @staticmethod
    def _temp_path(target: Path) -> Path:
        """在目标同目录创建临时文件路径。"""
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        os.close(fd)
        return Path(temp_name)

    @classmethod
    def _save_atomically(cls, nbt_data: Any, target: Path) -> None:
        """先写临时文件再 ``os.replace`` 发布 NBT。"""
        temp_path = cls._temp_path(target)
        try:
            nbt_data.save(temp_path)
            os.replace(temp_path, target)
        finally:
            temp_path.unlink(missing_ok=True)

    @classmethod
    def _copy_atomically(cls, source: Path, target: Path) -> None:
        """原子复制文件到目标路径。"""
        temp_path = cls._temp_path(target)
        try:
            shutil.copy2(source, temp_path)
            os.replace(temp_path, target)
        finally:
            temp_path.unlink(missing_ok=True)
