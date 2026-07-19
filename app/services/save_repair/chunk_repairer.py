"""Chunk Repairer - 区块修复服务

修复损坏的区块，隔离无法读取的区域文件。
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.mca import NativeRegion as Region

from core.scanner import scan_all_regions

from .models import RepairReport
from .validation_utils import validate_chunk


@dataclass(frozen=True)
class ChunkRepairResult:
    checked_regions: int = 0
    damaged_chunks: int = 0
    quarantined_regions: int = 0


class ChunkRepairer:
    """区块修复器"""

    CHUNKS_PER_REGION = 1024

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
            damaged, completed = self._count_damaged_chunks(region_file)
            if damaged:
                log(
                    f"区块文件 {region_file.name} 包含 {damaged} 个损坏区块",
                    "WARNING",
                )
            return ChunkRepairResult(1 if completed else 0, damaged, 0)
        except Exception as exc:
            log(f"无法读取区块文件 {region_file.name}: {exc}", "ERROR")
            self._quarantine_file(region_file, log)
            return ChunkRepairResult(0, 0, 1)

    def _count_damaged_chunks(self, region_file: Path) -> tuple[int, bool]:
        damaged = 0
        with Region.from_file(str(region_file)) as region:
            try:
                coordinates = region.iter_present_chunks()
            except AttributeError:
                coordinates = (
                    (chunk_x, chunk_z)
                    for chunk_x in range(32)
                    for chunk_z in range(32)
                )
            for chunk_x, chunk_z in coordinates:
                if self.is_cancelled:
                    return damaged, False
                try:
                    chunk = region.get_chunk(chunk_x, chunk_z)
                    if chunk is not None and not validate_chunk(chunk):
                        damaged += 1
                except Exception:
                    damaged += 1
        return damaged, True

    def _quarantine_file(
        self,
        file_path: Path,
        log: Callable[[str, str], None],
    ) -> None:
        """隔离损坏的文件"""
        try:
            new_path = file_path.with_suffix(file_path.suffix + ".corrupted")
            if new_path.exists():
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                new_path = file_path.with_suffix(f"{file_path.suffix}.corrupted_{timestamp}")
                log(f"已有隔离文件存在，使用新名称: {new_path.name}", "WARNING")

            file_path.rename(new_path)
            log(f"已隔离损坏文件: {file_path.name} -> {new_path.name}", "WARNING")
        except Exception as e:
            log(f"无法隔离文件 {file_path.name}: {e}", "ERROR")
