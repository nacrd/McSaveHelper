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
        self._config: ConfigService = config
        self._batch_processor: Optional[BatchProcessor] = None
        self._batch_worlds: List[Path] = []
        self._scan_result: str = ""

    @property
    def batch_worlds(self) -> List[Path]:
        """批量处理的世界存档列表
        
        Returns:
            List[Path]: 世界存档路径列表
        """
        return self._batch_worlds

    @property
    def scan_result(self) -> str:
        """扫描结果信息
        
        Returns:
            str: 扫描结果描述
        """
        return self._scan_result

    def scan_batch_dir(self, directory: str) -> List[Path]:
        """扫描批量目录，返回世界存档列表
        
        Args:
            directory: 要扫描的目录路径
            
        Returns:
            List[Path]: 找到的世界存档路径列表
        """
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
        target_platform: str,
        target_version: str,
        manual_names_str: str,
        log_cb: LogCallback,
        progress_cb: ProgressCallback,
    ) -> str:
        """执行单存档迁移，返回输出路径
        
        Args:
            src: 源存档目录路径
            dest: 目标输出目录路径
            world_name: 世界存档名称
            mode: 迁移模式，"fast" 或 "full"
            offline: 是否启用离线模式
            clean: 是否启用清理模式
            pure_clean: 是否启用纯清理模式
            manual_names_str: 逗号分隔的手动指定玩家名称
            log_cb: 日志回调函数
            progress_cb: 进度回调函数
            
        Returns:
            str: 输出目录路径
        """
        src_path = Path(src)
        dest_path = Path(dest)
        manual = [n.strip() for n in manual_names_str.split(",") if n.strip()]

        from core.performance import get_tracker
        tracker = get_tracker()
        with tracker.track("存档迁移", {"name": world_name, "mode": mode}):
            if mode == "fast":
                run_fast(src_path, dest_path, world_name, offline, clean, pure_clean, manual, log_cb)
            else:
                custom_mappings = self._config.custom_uuid_mappings if self._config.use_custom_mapping else None
                run_full(
                    src_path,
                    dest_path,
                    world_name,
                    offline,
                    clean,
                    pure_clean,
                    manual,
                    log_cb,
                    progress_cb,
                    custom_mappings,
                )

            output_path = dest_path / world_name
            self._apply_version_conversion(output_path, target_platform, target_version, log_cb)
        return str(output_path)

    def run_batch(
        self,
        dest_dir: str,
        mode: str,
        offline: bool,
        clean: bool,
        pure_clean: bool,
        target_platform: str,
        target_version: str,
        manual_names_str: str,
        max_concurrent: int,
        log_cb: LogCallback,
        progress_cb: ProgressCallback,
    ) -> Dict[str, Any]:
        """执行批量迁移，返回处理结果字典
        
        Args:
            dest_dir: 目标输出目录路径
            mode: 迁移模式，"fast" 或 "full"
            offline: 是否启用离线模式
            clean: 是否启用清理模式
            pure_clean: 是否启用纯清理模式
            manual_names_str: 逗号分隔的手动指定玩家名称
            max_concurrent: 最大并发处理数量
            log_cb: 日志回调函数
            progress_cb: 进度回调函数
            
        Returns:
            Dict[str, Any]: 处理结果字典
        """
        dest_path = Path(dest_dir)
        manual = [n.strip() for n in manual_names_str.split(",") if n.strip()]
        world_names = [f"world_{i+1}" for i in range(len(self._batch_worlds))]

        self._batch_processor = BatchProcessor(
            max_concurrent,
            version_detector=self._config.detect_minecraft_version,
            custom_mappings=self._config.custom_uuid_mappings if self._config.use_custom_mapping else None,
        )
        results = self._batch_processor.process_batch(
            self._batch_worlds, dest_path, world_names, mode,
            offline, clean, pure_clean, manual, log_cb, progress_cb,
        )
        for result in results.values():
            if result.get("success"):
                output_name = result.get("world_name")
                if output_name:
                    self._apply_version_conversion(dest_path / output_name, target_platform, target_version, log_cb)
        return results

    def _apply_version_conversion(
        self,
        world_path: Path,
        target_platform: str,
        target_version: str,
        log_cb: LogCallback,
    ) -> None:
        version_value = None
        if target_version.strip():
            try:
                version_value = int(target_version.strip())
            except ValueError:
                log_cb(f"目标版本 ID 无效，已跳过版本降级: {target_version}", "WARNING")
                return

        if target_platform == "java" and version_value is None:
            return

        from core.converter import convert_world

        log_cb(f"开始应用版本/平台转换: platform={target_platform}, version={version_value or 'keep'}", "CONVERT")
        convert_world(world_path, world_path, target_platform=target_platform, target_version=version_value)
        log_cb("版本/平台转换完成", "CONVERT")

    @staticmethod
    def open_folder(path: str) -> None:
        """在系统文件管理器中打开目录
        
        Args:
            path: 要打开的目录路径
        """
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass
