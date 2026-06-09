"""Save Repair Service (Refactored) - 存档修复服务

重构后的主服务，使用门面模式协调各个修复器。
保持向后兼容的 API。
"""
import time
import threading
from pathlib import Path
from typing import Optional, Callable

from core.logger import logger

from .save_repair.models import (
    IssueLevel,
    RepairIssue,
    RepairReport,
    DetectReport,
)
from .save_repair.detector import WorldDetector
from .save_repair.chunk_repairer import ChunkRepairer
from .save_repair.player_repairer import PlayerRepairer
from .save_repair.level_repairer import LevelRepairer
from .save_repair.backup_helper import BackupHelper


class SaveRepairService:
    """存档修复服务（重构版）

    门面模式，协调各个修复器，保持原有 API 不变。
    """

    def __init__(self) -> None:
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """请求取消正在进行的修复操作"""
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    # ── 存档检测（只读）────────────────────────────────────

    def detect_world(
        self,
        world_path: Path,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> DetectReport:
        """检测存档状态（只读，不修改任何文件）

        Args:
            world_path: 存档路径
            progress_callback: 进度回调
            log_callback: 日志回调

        Returns:
            DetectReport 检测报告
        """
        self._cancel_event.clear()
        report = DetectReport()
        start_time = time.monotonic()

        def log(msg: str, level: str = "INFO") -> None:
            getattr(logger, level.lower(), logger.info)(msg, module="SaveDetect")
            if log_callback:
                log_callback(msg, level)
            issue_level = {
                "INFO": IssueLevel.INFO,
                "WARNING": IssueLevel.WARNING,
                "ERROR": IssueLevel.ERROR,
                "SUCCESS": IssueLevel.FIXED,
            }.get(level.upper(), IssueLevel.INFO)
            report.issues.append(RepairIssue(
                level=issue_level,
                category="detect",
                message=msg,
            ))

        def progress(value: float, msg: str) -> None:
            if progress_callback:
                progress_callback(min(value, 1.0), msg)

        try:
            if not world_path.exists():
                raise FileNotFoundError(f"存档路径不存在: {world_path}")

            log(f"开始检测存档: {world_path}")

            # 使用 WorldDetector 进行检测
            detector = WorldDetector(self._cancel_event)
            detector.detect_world(world_path, report, log, progress)

            if self.is_cancelled:
                report.cancelled = True
                log("检测操作已取消", "WARNING")

            progress(1.0, "检测完成")
            if report.has_problems:
                log(f"检测完成，发现 {len(report.issues)} 个问题", "WARNING")
            else:
                log("检测完成，存档状态良好", "SUCCESS")

        except Exception as e:
            log(f"检测失败: {e}", "ERROR")
            logger.error(str(e), module="SaveDetect")

        report.elapsed_seconds = time.monotonic() - start_time
        return report

    # ── 修复接口 ──────────────────────────────────────────

    def repair_world(
        self,
        world_path: Path,
        fix_chunks: bool = True,
        fix_players: bool = True,
        fix_level_dat: bool = True,
        backup: bool = True,
        max_workers: int = 4,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> RepairReport:
        """修复世界存档

        Args:
            world_path: 存档路径
            fix_chunks: 是否修复区块
            fix_players: 是否修复玩家数据
            fix_level_dat: 是否修复 level.dat
            backup: 是否备份
            max_workers: 并发处理区域文件的最大线程数（保留参数以兼容）
            progress_callback: 进度回调 (0.0~1.0, 描述)
            log_callback: 日志回调 (消息, 级别)

        Returns:
            RepairReport 修复报告
        """
        self._cancel_event.clear()
        report = RepairReport()
        start_time = time.monotonic()

        def log(msg: str, level: str = "INFO") -> None:
            getattr(logger, level.lower(), logger.info)(msg, module="SaveRepair")
            if log_callback:
                log_callback(msg, level)
            issue_level = {
                "INFO": IssueLevel.INFO,
                "WARNING": IssueLevel.WARNING,
                "ERROR": IssueLevel.ERROR,
                "SUCCESS": IssueLevel.FIXED,
            }.get(level.upper(), IssueLevel.INFO)
            report.issues.append(RepairIssue(
                level=issue_level,
                category="general",
                message=msg,
            ))

        def progress(value: float, msg: str) -> None:
            if progress_callback:
                progress_callback(min(value, 1.0), msg)

        try:
            if not world_path.exists():
                raise FileNotFoundError(f"存档路径不存在: {world_path}")

            log(f"开始修复存档: {world_path}")

            # 备份
            if backup and not self.is_cancelled:
                progress(0.02, "创建备份...")
                try:
                    backup_helper = BackupHelper(self._cancel_event)
                    backup_path = backup_helper.create_backup(world_path, progress)
                    report.backup_path = str(backup_path)
                    log(f"已创建备份: {backup_path}", "SUCCESS")
                except Exception as e:
                    log(f"备份失败: {e}", "ERROR")
                    report.backup_path = ""

            # 修复区块
            if fix_chunks and not self.is_cancelled:
                progress(0.10, "扫描区块文件...")
                chunk_repairer = ChunkRepairer(self._cancel_event)
                chunk_repairer.repair_chunks(world_path, report, log, progress)

            # 修复玩家数据
            if fix_players and not self.is_cancelled:
                progress(0.75, "修复玩家数据...")
                player_repairer = PlayerRepairer(self._cancel_event)
                player_repairer.repair_players(world_path, report, log)

            # 修复 level.dat
            if fix_level_dat and not self.is_cancelled:
                progress(0.90, "修复 level.dat...")
                level_repairer = LevelRepairer(self._cancel_event)
                level_repairer.repair_level_dat(world_path, report, log)

            if self.is_cancelled:
                report.cancelled = True
                log("修复操作已取消", "WARNING")

            progress(1.0, "修复完成")
            log(
                f"修复完成 - 区块: {report.chunks_checked} 检查/{report.chunks_damaged} 损坏, "
                f"玩家: {report.players_checked} 检查/{report.players_fixed} 修复",
                "SUCCESS",
            )

        except Exception as e:
            log(f"修复失败: {e}", "ERROR")
            logger.error(str(e), module="SaveRepair")

        report.elapsed_seconds = time.monotonic() - start_time
        return report
