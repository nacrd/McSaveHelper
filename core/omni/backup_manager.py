"""
BackupManager - 备份和恢复管理器
负责创建、恢复和列出存档备份
"""
import shutil
import datetime
from pathlib import Path
from typing import List, Optional, Callable


class BackupManager:
    """备份和恢复管理器"""

    def __init__(self, world_path: Path, log_callback: Optional[Callable] = None):
        self.world_path = world_path
        self._log = log_callback or (lambda msg, lvl="INFO": None)

    def create_backup(self, backup_name: Optional[str] = None) -> Optional[Path]:
        """创建当前存档的备份

        Args:
            backup_name: 备份名称，若为 None 则使用时间戳

        Returns:
            备份文件夹路径，失败返回 None
        """
        try:
            if backup_name is None:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = f"{self.world_path.name}_backup_{timestamp}"

            backup_dir = self.world_path.parent / backup_name

            if backup_dir.exists():
                # 清理旧备份
                try:
                    shutil.rmtree(backup_dir)
                except Exception as e:
                    self._log(f"清理旧备份失败: {e}", "WARNING")
                    # 尝试使用带后缀的名称
                    i = 1
                    while (self.world_path.parent / f"{backup_name}_{i}").exists():
                        i += 1
                    backup_dir = self.world_path.parent / f"{backup_name}_{i}"

            shutil.copytree(self.world_path, backup_dir)
            self._log(f"已创建备份: {backup_dir}", "BACKUP")
            return backup_dir

        except Exception as e:
            self._log(f"创建备份失败: {e}", "ERROR")
            return None

    def restore_backup(self, backup_path: Path, replace_current: bool = False) -> bool:
        """从备份恢复存档

        Args:
            backup_path: 备份文件夹路径
            replace_current: 是否替换当前存档（危险操作）

        Returns:
            是否成功
        """
        try:
            if not backup_path.exists() or not backup_path.is_dir():
                self._log(f"备份不存在或不是目录: {backup_path}", "ERROR")
                return False

            if replace_current:
                # 先备份当前存档
                current_backup = self.create_backup(f"{self.world_path.name}_pre_restore")
                if current_backup is None:
                    self._log("无法在恢复前备份当前存档，取消恢复", "ERROR")
                    return False

                # 删除当前存档
                shutil.rmtree(self.world_path)

                # 从备份复制
                shutil.copytree(backup_path, self.world_path)
                self._log(f"已从备份恢复存档: {backup_path}", "RESTORE")
                return True
            else:
                # 创建副本而不替换当前存档
                dest_name = f"{self.world_path.name}_restored"
                dest_path = self.world_path.parent / dest_name
                i = 1
                while dest_path.exists():
                    dest_path = self.world_path.parent / f"{dest_name}_{i}"
                    i += 1

                shutil.copytree(backup_path, dest_path)
                self._log(f"已将备份恢复到: {dest_path}", "RESTORE")
                return True

        except Exception as e:
            self._log(f"恢复备份失败: {e}", "ERROR")
            return False

    def list_backups(self) -> List[Path]:
        """列出当前存档的所有备份

        Returns:
            备份文件夹路径列表（按修改时间排序，最新的在前）
        """
        backups = []
        try:
            parent_dir = self.world_path.parent
            world_name = self.world_path.name

            for item in parent_dir.iterdir():
                if item.is_dir() and item.name.startswith(world_name) and \
                   ("backup" in item.name or "restored" in item.name):
                    backups.append(item)

            # 按修改时间排序，最新的在前
            backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        except Exception as e:
            self._log(f"列出备份失败: {e}", "ERROR")

        return backups
