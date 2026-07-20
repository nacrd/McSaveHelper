"""Chunk Repairer - 区块修复服务

扫描世界中的区域文件，统计损坏区块，并将无法读取的区域隔离。
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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

    通过线程池并行检查 region 文件；取消时停止接受新任务。
    当前实现以检测与隔离为主，不重写损坏区块内容。
    """

    def __init__(self, cancel_event: threading.Event) -> None:
        """初始化修复器。

        Args:
            cancel_event: 协作式取消事件。
        """
        self._cancel_event = cancel_event

    @property
    def is_cancelled(self) -> bool:
        """当前修复是否已被请求取消。"""
        return self._cancel_event.is_set()

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

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._repair_region, region_file, log): region_file
                for region_file in region_files
            }
            completed = 0
            for future in as_completed(futures):
                if self.is_cancelled:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                region_file = futures[future]
                try:
                    result = future.result(timeout=120)
                except TimeoutError as exc:
                    log(f"处理 {region_file.name} 超时: {exc}", "ERROR")
                except (OSError, ValueError, RuntimeError) as exc:
                    log(f"处理 {region_file.name} 异常: {exc}", "ERROR")
                except Exception as exc:
                    # 线程入口边界：保留失败语义，继续其余区域。
                    log(f"处理 {region_file.name} 异常: {exc}", "ERROR")
                else:
                    report.chunks_checked += result.checked_regions
                    report.chunks_damaged += result.damaged_chunks
                    report.chunks_quarantined_regions += (
                        result.quarantined_regions
                    )
                completed += 1
                progress(
                    0.10 + (completed / total) * 0.65,
                    f"检查区块文件 {completed}/{total}",
                )

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
