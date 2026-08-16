"""Base class for region-based searchers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Collection, List

from core.mca import McaError, NativeRegion
from core.mca.chunk_view import BLOCK_SEARCH_ROOT_FIELDS

from .constants import MAX_RESULTS
from .models import SearchResult, SearchSummary
from .utils import get_dimension_region_files

LogFn = Callable[[str, str], None]
ProgressFn = Callable[[float, str], None]


class BaseSearcher(ABC):
    """提供共享的区域扫描逻辑；子类实现 ``search_chunk``。"""

    progress_label: str = "区块文件"
    chunk_root_fields: Collection[str] = BLOCK_SEARCH_ROOT_FIELDS

    def __init__(
        self,
        results: List[SearchResult],
        summary: SearchSummary,
    ) -> None:
        """绑定共享的结果列表与扫描摘要。

        Args:
            results: 搜索结果聚合列表（就地追加）。
            summary: 扫描进度与命中统计摘要。
        """
        self.results = results
        self.summary = summary

    def search_dimension(
        self,
        world_path: Path,
        dimension: str,
        target: str,
        log: LogFn,
        progress: ProgressFn,
    ) -> None:
        """扫描一个维度的 region 文件。"""
        try:
            region_files = get_dimension_region_files(world_path, dimension)
            if not region_files:
                log(f"维度 {dimension} 没有区块文件", "WARNING")
                return
            log(
                f"在 {dimension} 中找到 {len(region_files)} 个区块文件",
                "INFO",
            )
            self._scan_regions(region_files, dimension, target, log, progress)
        except ImportError:
            log(
                f"MCA 读取模块不可用，无法搜索{self.progress_label}",
                "ERROR",
            )
        except (OSError, ValueError, TypeError, RuntimeError, McaError) as exc:
            log(f"搜索维度 {dimension} 失败: {exc}", "ERROR")

    @abstractmethod
    def search_chunk(self, chunk: Any, target: str, dimension: str) -> None:
        """处理单个区块。由子类实现。"""

    def _scan_regions(
        self,
        region_files: List[Path],
        dimension: str,
        target: str,
        log: LogFn,
        progress: ProgressFn,
    ) -> None:
        total = len(region_files)
        for idx, region_file in enumerate(region_files):
            if self._limit_reached():
                return
            progress(
                idx / total,
                f"搜索{self.progress_label} {idx + 1}/{total}",
            )
            self.summary.scanned_regions += 1
            try:
                with NativeRegion.from_file(region_file) as region:
                    self._scan_region(region, target, dimension)
            except (OSError, ValueError, TypeError, RuntimeError, KeyError, McaError) as exc:
                log(f"读取区块文件 {region_file.name} 失败: {exc}", "WARNING")

    def _scan_region(self, region: Any, target: str, dimension: str) -> None:
        try:
            # Sort by (x, z) to preserve previous search/result order even
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
                chunk = self._read_chunk(region, cx, cz)
                if chunk is not None:
                    self.summary.scanned_chunks += 1
                    self.search_chunk(chunk, target, dimension)
            except (
                OSError,
                ValueError,
                TypeError,
                RuntimeError,
                KeyError,
                AttributeError,
                McaError,
            ):
                self.summary.skipped_chunks += 1

    def _read_chunk(self, region: Any, cx: int, cz: int) -> Any:
        reader = getattr(region, "read_chunk_fields", None)
        if callable(reader):
            return reader(cx, cz, self.chunk_root_fields)
        return region.get_chunk(cx, cz)

    def _limit_reached(self) -> bool:
        return len(self.results) >= MAX_RESULTS
