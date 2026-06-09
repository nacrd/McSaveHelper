"""Level Repairer - level.dat 修复服务

修复 level.dat 文件，补充缺失字段，修正范围异常。
"""
import shutil
import threading
from pathlib import Path
from typing import Callable, List, Any, Dict

import nbtlib

from .models import RepairReport


# level.dat 中 Data 下的必需字段及其默认值
LEVEL_DAT_REQUIRED_FIELDS: Dict[str, Any] = {
    "DataVersion": 0,
    "version": None,
    "LevelName": "World",
    "generatorName": "default",
    "SpawnX": 0,
    "SpawnY": 64,
    "SpawnZ": 0,
    "RandomSeed": 0,
    "Time": 0,
    "DayTime": 0,
    "GameType": 0,
    "Difficulty": 2,
    "DifficultyLocked": 0,
    "allowCommands": 1,
    "initialized": 1,
    "WorldGenSettings": None,
}


class LevelRepairer:
    """level.dat 修复器"""

    def __init__(self, cancel_event: threading.Event) -> None:
        self._cancel_event = cancel_event

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def repair_level_dat(
        self,
        world_path: Path,
        report: RepairReport,
        log: Callable[[str, str], None],
    ) -> None:
        """修复 level.dat"""
        level_dat = world_path / "level.dat"
        level_dat_old = world_path / "level.dat_old"

        if not level_dat.exists():
            if level_dat_old.exists():
                log("level.dat 不存在，尝试从 level.dat_old 恢复", "WARNING")
                shutil.copy2(level_dat_old, level_dat)
                report.level_dat_fixed = True
                log("已从 level.dat_old 恢复", "SUCCESS")
            else:
                log("level.dat 和 level.dat_old 都不存在", "ERROR")
            return

        # 尝试加载并验证
        try:
            nbt_data = nbtlib.load(str(level_dat))
        except Exception as e:
            log(f"level.dat 无法解析: {e}", "ERROR")
            self._restore_from_backup(level_dat, level_dat_old, report, log)
            return

        # 检查 Data 字段
        if "Data" not in nbt_data:
            log("level.dat 缺少 Data 字段", "ERROR")
            self._restore_from_backup(level_dat, level_dat_old, report, log)
            return

        data = nbt_data["Data"]
        if not isinstance(data, nbtlib.tag.Compound):
            log("level.dat 的 Data 字段类型错误", "ERROR")
            self._restore_from_backup(level_dat, level_dat_old, report, log)
            return

        # 字段级修复
        repaired_fields = self._repair_fields(data, log)
        if repaired_fields:
            report.level_dat_fixed = True
            report.level_dat_repaired_fields = repaired_fields
            # 保存修复后的 level.dat
            try:
                nbt_data.save(level_dat)
                log(f"level.dat 已保存修复 ({', '.join(repaired_fields)})", "SUCCESS")
            except Exception as e:
                log(f"保存 level.dat 失败: {e}", "ERROR")
        else:
            log("level.dat 验证通过", "INFO")

    def _restore_from_backup(
        self,
        level_dat: Path,
        level_dat_old: Path,
        report: RepairReport,
        log: Callable[[str, str], None],
    ) -> None:
        """从 level.dat_old 恢复"""
        if not level_dat_old.exists():
            log("level.dat_old 不存在，无法恢复", "ERROR")
            return

        log("尝试从 level.dat_old 恢复", "WARNING")
        shutil.copy2(level_dat_old, level_dat)

        try:
            nbtlib.load(str(level_dat))
            report.level_dat_fixed = True
            log("已从 level.dat_old 恢复", "SUCCESS")
        except Exception:
            log("level.dat_old 也已损坏", "ERROR")

    def _repair_fields(
        self,
        data: Any,
        log: Callable[[str, str], None],
    ) -> List[str]:
        """验证并修复 level.dat Data 中的字段，返回修复的字段名列表"""
        repaired: List[str] = []

        # 补充缺失字段
        for field_name, default_value in LEVEL_DAT_REQUIRED_FIELDS.items():
            if field_name not in data:
                if default_value is None:
                    continue
                try:
                    data[field_name] = default_value
                    repaired.append(field_name)
                    log(f"level.dat 补充缺失字段: {field_name}", "WARNING")
                except Exception:
                    pass

        # 修复 SpawnX/Y/Z 为合理范围
        for spawn_field in ("SpawnX", "SpawnY", "SpawnZ"):
            if spawn_field in data:
                try:
                    val = int(data[spawn_field])
                    if spawn_field == "SpawnY" and (val < -64 or val > 320):
                        data[spawn_field] = 64
                        repaired.append(f"{spawn_field}(范围修正)")
                except (ValueError, TypeError):
                    pass

        # 修复 Difficulty 在合理范围
        if "Difficulty" in data:
            try:
                val = int(data["Difficulty"])
                if val < 0 or val > 3:
                    data["Difficulty"] = 2
                    repaired.append("Difficulty(范围修正)")
            except (ValueError, TypeError):
                pass

        return repaired
