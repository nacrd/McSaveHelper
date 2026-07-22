"""Chunk Repairer - 区块修复服务

扫描世界中的区域文件，统计损坏区块，并将无法读取的区域隔离。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
    TaskPriority,
)
from app.services.runtime_map import map_items
from core.scanner import scan_all_regions

from .models import RepairReport
from .validation_utils import count_damaged_chunks, quarantine_file

LogFn = Callable[[str, str], None]
ProgressFn = Callable[[float, str], None]


@dataclass(frozen=True)
class ChunkRepairResult:
    """单个区域文件的修复/检查结果。

    Attributes:
        checked_regions: 是否完成检查（1 或 0）。
        damaged_chunks: 发现的损坏区块数。
        quarantined_regions: 是否因无法读取而被隔离（1 或 0）。
    """

    checked_regions: int = 0
    damaged_chunks: int = 0
    quarantined_regions: int = 0


class ChunkRepairer:
    """区块修复器。

    通过统一执行运行时并行检查 region 文件；取消时停止新任务。
    当前实现以检测与隔离为主，不重写损坏区块内容。
    """

    def __init__(
        self,
        cancel_event: threading.Event,
        execution_runtime: Optional[ExecutionRuntime] = None,
    ) -> None:
        """初始化修复器。

        Args:
            cancel_event: 协作式取消事件。
            execution_runtime: 可选共享运行时；缺省创建本地有界运行时。
        """
        self._cancel_event = cancel_event
        self._execution_runtime = execution_runtime or ExecutionRuntime()
        self._owns_execution_runtime = execution_runtime is None

    @property
    def is_cancelled(self) -> bool:
        """当前修复是否已被请求取消。"""
        return self._cancel_event.is_set()

    def close(self) -> None:
        """释放本地拥有的运行时；可重复调用。"""
        if self._owns_execution_runtime:
            self._execution_runtime.shutdown(wait=False)
            self._owns_execution_runtime = False

    def repair_chunks(
        self,
        world_path: Path,
        report: RepairReport,
        log: LogFn,
        progress: ProgressFn,
    ) -> None:
        """扫描并检查世界中的区域文件。

        Args:
            world_path: 世界根目录。
            report: 可变修复报告。
            log: 日志回调 ``(message, level)``。
            progress: 进度回调 ``(fraction, label)``，fraction 约在 0.10–0.75。
        """
        region_files = scan_all_regions(world_path)
        total = len(region_files)
        if total == 0:
            log("未找到区块文件", "WARNING")
            return

        log(f"找到 {total} 个区块文件", "INFO")
        max_workers = min(max(1, (total + 3) // 4), 8)
        completed = 0

        def on_item_done(_index: int, value: object) -> None:
            nonlocal completed
            completed += 1
            if isinstance(value, ChunkRepairResult):
                report.chunks_checked += value.checked_regions
                report.chunks_damaged += value.damaged_chunks
                report.chunks_quarantined_regions += value.quarantined_regions
            elif isinstance(value, BaseException):
                log(f"处理区域文件异常: {value}", "ERROR")
            progress(
                0.10 + (completed / total) * 0.65,
                f"检查区块文件 {completed}/{total}",
            )

        def worker(
            token: CancellationToken,
            region_file: Path,
        ) -> ChunkRepairResult:
            del token
            return self._repair_region(region_file, log)

        try:
            map_items(
                self._execution_runtime,
                "repair_region",
                region_files,
                worker,
                lane=ExecutionLane.CPU,
                priority=TaskPriority.BACKGROUND,
                cancel_check=lambda: self.is_cancelled,
                on_item_done=on_item_done,
                max_in_flight=max_workers,
            )
        except OperationCancelledError:
            log("区块检查已取消", "WARNING")

    def _repair_region(
        self,
        region_file: Path,
        log: LogFn,
    ) -> ChunkRepairResult:
        """检查单个区域文件并在无法读取时隔离。

        Args:
            region_file: ``.mca`` 区域路径。
            log: 日志回调。

        Returns:
            ChunkRepairResult: 检查/隔离结果。
        """
        if self.is_cancelled:
            return ChunkRepairResult()
        try:
            damaged, completed = count_damaged_chunks(
                region_file,
                lambda: self.is_cancelled,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            log(f"无法读取区块文件 {region_file.name}: {exc}", "ERROR")
            quarantine_file(region_file, log)
            return ChunkRepairResult(0, 0, 1)
        except Exception as exc:
            log(f"无法读取区块文件 {region_file.name}: {exc}", "ERROR")
            quarantine_file(region_file, log)
            return ChunkRepairResult(0, 0, 1)

        if damaged:
            log(
                f"区块文件 {region_file.name} 包含 {damaged} 个损坏区块",
                "WARNING",
            )
        return ChunkRepairResult(1 if completed else 0, damaged, 0)
