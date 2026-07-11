"""Chunk Repairer - 区块修复服务

修复损坏的区块，隔离无法读取的区域文件。
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Tuple, Any, List

import nbtlib
from core.mca import NativeRegion as Region

from core.scanner import scan_all_regions

from .models import RepairReport, IssueLevel, RepairIssue
from .validation_utils import validate_chunk


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

        completed = 0
        lock = threading.Lock()

        def process_region(idx: int, region_file: Path) -> Tuple[int, int, int]:
            """处理单个区域文件，返回 (checked, damaged, quarantined_flag)"""
            if self.is_cancelled:
                return 0, 0, 0

            checked = 0
            damaged = 0
            quarantined = 0

            try:
                region = Region.from_file(str(region_file))
                region_damaged = 0

                for chunk_x in range(32):
                    for chunk_z in range(32):
                        if self.is_cancelled:
                            return checked, damaged, quarantined
                        try:
                            chunk = region.get_chunk(chunk_x, chunk_z)
                            if chunk is not None:
                                ok = validate_chunk(chunk)
                                if not ok:
                                    region_damaged += 1
                                    damaged += 1
                        except Exception:
                            region_damaged += 1
                            damaged += 1

                checked = 1

                if region_damaged > 0:
                    log(
                        f"区块文件 {region_file.name} 包含 {region_damaged} 个损坏区块",
                        "WARNING",
                    )

            except Exception as e:
                log(f"无法读取区块文件 {region_file.name}: {e}", "ERROR")
                self._quarantine_file(region_file, log)
                quarantined = 1

            with lock:
                nonlocal completed
                completed += 1
                progress(
                    0.10 + (completed / total) * 0.65,
                    f"检查区块文件 {completed}/{total}",
                )

            return checked, damaged, quarantined

        max_workers = min(max(1, (len(region_files) + 3) // 4), 8)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(process_region, idx, rf): rf
                for idx, rf in enumerate(region_files)
            }
            for future in as_completed(futures):
                if self.is_cancelled:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    c, d, q = future.result(timeout=120)
                    report.chunks_checked += c
                    report.chunks_damaged += d
                    report.chunks_quarantined_regions += q
                except Exception as e:
                    rf = futures[future]
                    log(f"处理 {rf.name} 异常: {e}", "ERROR")

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
