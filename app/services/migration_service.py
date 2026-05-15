"""迁移服务 —— 封装快速/完整模式和批量处理逻辑"""
import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from core.fast_mode import run_fast
from core.full_mode import run_full
from core.batch_processor import BatchProcessor, scan_worlds_directory
from core.config import config_manager
from core.logger import logger, LogLevel
from core.types import LogCallback, ProgressCallback
from core.i18n import t
from app.services.config_service import ConfigService


class MigrationService:
    """存档迁移服务

    职责：
      - 执行单存档迁移（快速/完整模式）
      - 执行批量迁移
      - 扫描批量目录
      - 管理进度回调
    """

    def __init__(self, config: ConfigService) -> None:
        self._config = config
        self._batch_processor: Optional[BatchProcessor] = None
        self._batch_worlds: List[Path] = []
        self._scan_result: str = ""

    @property
    def batch_worlds(self) -> List[Path]:
        return self._batch_worlds

    @property
    def scan_result(self) -> str:
        return self._scan_result

    def scan_batch_dir(self, directory: str) -> List[Path]:
        """扫描批量目录，返回世界存档列表"""
        bp = Path(directory)
        if not bp.exists():
            return []
        worlds = scan_worlds_directory(bp)
        self._batch_worlds = worlds
        if worlds:
            names = ", ".join([w.name for w in worlds[:3]])
            if len(worlds) > 3:
                names += "..."
            self._scan_result = t(
                "messages.scanned_worlds",
                "扫描到 {count} 个世界存档: {names}",
                count=len(worlds), names=names,
            )
        else:
            self._scan_result = t(
                "messages.no_valid_worlds",
                "未找到有效的世界存档（需要包含level.dat）",
            )
        return worlds

    def run_single(
        self,
        src: str,
        dest: str,
        world_name: str,
        mode: str,
        offline: bool,
        clean: bool,
        pure_clean: bool,
        manual_names_str: str,
        log_cb: LogCallback,
        progress_cb: ProgressCallback,
    ) -> str:
        """执行单存档迁移，返回输出路径"""
        src_path = Path(src)
        dest_path = Path(dest)
        manual = [n.strip() for n in manual_names_str.split(",") if n.strip()]

        if mode == "fast":
            run_fast(src_path, dest_path, world_name, offline, clean, pure_clean, manual, log_cb)
        else:
            run_full(src_path, dest_path, world_name, offline, clean, pure_clean, manual, log_cb, progress_cb)

        return str(dest_path / world_name)

    def run_batch(
        self,
        dest_dir: str,
        mode: str,
        offline: bool,
        clean: bool,
        pure_clean: bool,
        manual_names_str: str,
        max_concurrent: int,
        log_cb: LogCallback,
        progress_cb: ProgressCallback,
    ) -> Dict[str, Any]:
        """执行批量迁移，返回处理结果字典"""
        dest_path = Path(dest_dir)
        manual = [n.strip() for n in manual_names_str.split(",") if n.strip()]
        world_names = [f"world_{i+1}" for i in range(len(self._batch_worlds))]

        self._batch_processor = BatchProcessor(max_concurrent)
        results = self._batch_processor.process_batch(
            self._batch_worlds, dest_path, world_names, mode,
            offline, clean, pure_clean, manual, log_cb, progress_cb,
        )
        return results

    @staticmethod
    def open_folder(path: str) -> None:
        """在系统文件管理器中打开目录"""
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass
