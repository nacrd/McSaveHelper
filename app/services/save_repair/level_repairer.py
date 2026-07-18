"""Level Repairer - level.dat 修复服务

修复 level.dat 文件，补充缺失字段，修正范围异常。
"""
import os
import shutil
import threading
import tempfile
from pathlib import Path
from typing import Callable, List, Any, Dict

import nbtlib

from .models import RepairReport


# level.dat 中 Data 下的必需字段及其默认值
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
                self._restore_from_backup(level_dat, level_dat_old, report, log)
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
            try:
                self._save_atomically(nbt_data, level_dat)
                report.level_dat_fixed = True
                report.level_dat_repaired_fields = repaired_fields
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
        try:
            nbtlib.load(str(level_dat_old))
            self._copy_atomically(level_dat_old, level_dat)
            report.level_dat_fixed = True
            log("已从 level.dat_old 恢复", "SUCCESS")
        except Exception as exc:
            log(f"level.dat_old 无法恢复: {exc}", "ERROR")

    @staticmethod
    def _save_atomically(nbt_data: Any, target: Path) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temp_path = Path(temp_name)
        os.close(fd)
        try:
            nbt_data.save(temp_path)
            os.replace(temp_path, target)
        finally:
            temp_path.unlink(missing_ok=True)

    @staticmethod
    def _copy_atomically(source: Path, target: Path) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temp_path = Path(temp_name)
        os.close(fd)
        try:
            shutil.copy2(source, temp_path)
            os.replace(temp_path, target)
        finally:
            temp_path.unlink(missing_ok=True)

    def _repair_fields(
        self,
        data: Any,
        log: Callable[[str, str], None],
    ) -> List[str]:
        """验证并修复 level.dat Data 中的字段，返回修复的字段名列表"""
        repaired: List[str] = []

        # 补充缺失字段
        for field_name, default_factory in LEVEL_DAT_REQUIRED_FIELDS.items():
            if field_name not in data:
                try:
                    data[field_name] = default_factory()
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
                        data[spawn_field] = nbtlib.Int(64)
                        repaired.append(f"{spawn_field}(范围修正)")
                except (ValueError, TypeError):
                    pass

        # 修复 Difficulty 在合理范围
        if "Difficulty" in data:
            try:
                val = int(data["Difficulty"])
                if val < 0 or val > 3:
                    data["Difficulty"] = nbtlib.Byte(2)
                    repaired.append("Difficulty(范围修正)")
            except (ValueError, TypeError):
                pass

        return repaired
