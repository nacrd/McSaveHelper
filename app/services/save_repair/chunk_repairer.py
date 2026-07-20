"""Chunk Repairer - 区块修复服务

修复损坏的区块，隔离无法读取的区域文件。
"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.scanner import scan_all_regions

from .models import RepairReport
from .validation_utils import count_damaged_chunks, quarantine_file


@dataclass(frozen=True)
class ChunkRepairResult:
    checked_regions: int = 0
    damaged_chunks: int = 0
    quarantined_regions: int = 0


class ChunkRepairer:
    """区块修复器"""

    def __init__(self, cancel_event: threading.Event) -> None:
        self._cancel_event = cancel_event

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def repair_chunks(
        self,
        world_path: Path,
        report: RepairReport,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        """修复区块"""
        region_files = scan_all_regions(world_path)
        total = len(region_files)

        if total == 0:
            log("未找到区块文件", "WARNING")
            return

        log(f"找到 {total} 个区块文件", "INFO")

        max_workers = min(max(1, (len(region_files) + 3) // 4), 8)

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
                try:
                    result = future.result(timeout=120)
                    report.chunks_checked += result.checked_regions
                    report.chunks_damaged += result.damaged_chunks
                    report.chunks_quarantined_regions += (
                        result.quarantined_regions
                    )
                except Exception as e:
                    rf = futures[future]
                    log(f"处理 {rf.name} 异常: {e}", "ERROR")
                completed += 1
                progress(
                    0.10 + (completed / total) * 0.65,
                    f"检查区块文件 {completed}/{total}",
                )

    def _repair_region(
        self,
        region_file: Path,
        log: Callable[[str, str], None],
    ) -> ChunkRepairResult:
        if self.is_cancelled:
            return ChunkRepairResult()
        try:
            damaged, completed = count_damaged_chunks(
                region_file,
                lambda: self.is_cancelled,
            )
            if damaged:
                log(
                    f"区块文件 {region_file.name} 包含 {damaged} 个损坏区块",
                    "WARNING",
                )
            return ChunkRepairResult(1 if completed else 0, damaged, 0)
        except Exception as exc:
            log(f"无法读取区块文件 {region_file.name}: {exc}", "ERROR")
            quarantine_file(region_file, log)
            return ChunkRepairResult(0, 0, 1)
