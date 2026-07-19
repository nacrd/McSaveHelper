"""Base class for region-based searchers."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, List

from .constants import MAX_RESULTS
from .models import SearchResult, SearchSummary
from .utils import get_dimension_region_files


class BaseSearcher(ABC):
    """提供共享的区域扫描逻辑；子类实现 search_chunk。"""

    progress_label: str = "区块文件"

    def __init__(self, results: List[SearchResult], summary: SearchSummary) -> None:
        self.results = results
        self.summary = summary

    def search_dimension(
        self,
        world_path: Path,
        dimension: str,
        target: str,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        try:
            region_files = get_dimension_region_files(world_path, dimension)
            if not region_files:
                log(f"维度 {dimension} 没有区块文件", "WARNING")
                return
            log(f"在 {dimension} 中找到 {len(region_files)} 个区块文件", "INFO")
            self._scan_regions(region_files, dimension, target, log, progress)
        except ImportError:
            log(f"MCA 读取模块不可用，无法搜索{self.progress_label}", "ERROR")
        except Exception as e:
            log(f"搜索维度 {dimension} 失败: {e}", "ERROR")

    @abstractmethod
    def search_chunk(self, chunk: Any, target: str, dimension: str) -> None:
        """处理单个区块。由子类实现。"""
        ...

    def _scan_regions(
        self,
        region_files: List[Path],
        dimension: str,
        target: str,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        from core.mca import NativeRegion
        total = len(region_files)
        for idx, region_file in enumerate(region_files):
            if self._limit_reached():
                return
            progress(idx / total, f"搜索{self.progress_label} {idx + 1}/{total}")
            self.summary.scanned_regions += 1
            try:
                with NativeRegion.from_file(region_file) as region:
                    self._scan_region(region, target, dimension)
            except Exception as e:
                log(f"读取区块文件 {region_file.name} 失败: {e}", "WARNING")

    def _scan_region(self, region: Any, target: str, dimension: str) -> None:
        try:
            # Sort by (x, z) to preserve the previous search/result order even
            # though the MCA location table itself is stored z-major.
            coordinates = sorted(region.iter_present_chunks())
        except AttributeError:
            coordinates = [
                (cx, cz)
                for cx in range(32)
                for cz in range(32)
            ]
        for cx, cz in coordinates:
            if self._limit_reached():
                return
            try:
                chunk = region.get_chunk(cx, cz)
                if chunk is not None:
                    self.summary.scanned_chunks += 1
                    self.search_chunk(chunk, target, dimension)
            except Exception:
                self.summary.skipped_chunks += 1

    def _limit_reached(self) -> bool:
        return len(self.results) >= MAX_RESULTS
