"""Backup Helper - 备份与文件隔离服务

创建存档备份，带进度的文件复制。
"""
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Callable, List, Optional


class BackupHelper:
    """备份助手"""

    def __init__(self, cancel_event: threading.Event) -> None:
        self._cancel_event = cancel_event

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def create_backup(
        self,
        world_path: Path,
        progress: Callable[[float, str], None],
    ) -> Path:
        """创建存档备份

        Args:
            world_path: 存档路径
            progress: 进度回调

        Returns:
            备份路径

        Raises:
            RuntimeError: 备份失败
        """
        backup_name = f"{world_path.name}_backup"
        backup_path = world_path.parent / backup_name

        counter = 1
        while backup_path.exists():
            backup_path = world_path.parent / f"{backup_name}_{counter}"
            counter += 1

        temp_backup_dir: Optional[Path] = None
        try:
            temp_backup_dir = Path(tempfile.mkdtemp(prefix="mcsavehelper_backup_"))
            dest = temp_backup_dir / world_path.name

            # 带进度的复制
            self._copytree_with_progress(world_path, dest, progress)

            shutil.move(str(dest), str(backup_path))
            return backup_path

        except Exception as e:
            if temp_backup_dir and temp_backup_dir.exists():
                shutil.rmtree(temp_backup_dir, ignore_errors=True)
            raise RuntimeError(f"备份失败: {e}")

    def _copytree_with_progress(
        self,
        src: Path,
        dst: Path,
        progress: Callable[[float, str], None],
    ) -> None:
        """带进度回调的目录复制"""
        # 先统计总文件数（缓存文件大小，避免三次 stat 调用）
        file_sizes: List[tuple] = []
        for f in src.rglob("*"):
            try:
                st = f.stat()
                if st.st_mode & 0o170000 == 0o100000:
                    file_sizes.append((f, st.st_size))
            except OSError:
                pass
        total_size = sum(s for _, s in file_sizes)
        file_count = len(file_sizes)

        dst.mkdir(parents=True, exist_ok=True)
        copied_size = 0

        for idx, (src_file, file_size) in enumerate(file_sizes):
            if self.is_cancelled:
                raise RuntimeError("备份已取消")

            rel = src_file.relative_to(src)
            dst_file = dst / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)

            copied_size += file_size
            if total_size > 0:
                pct = copied_size / total_size
                progress(0.02 + pct * 0.08, f"备份中... {idx + 1}/{file_count}")
