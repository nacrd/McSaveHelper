"""Facade service for entity/block/container search."""

from pathlib import Path
from typing import Callable, List, Optional
import traceback

from core.logger import logger
from .entity_block_search.base_searcher import BaseSearcher
from .entity_block_search.block_searcher import BlockSearcher
from .entity_block_search.constants import (
    COMMON_BLOCKS,
    COMMON_CONTAINERS,
    COMMON_ENTITIES,
    MAX_RESULTS,
    VALID_DIMENSIONS,
    VALID_SEARCH_TYPES,
)
from .entity_block_search.container_searcher import ContainerSearcher
from .entity_block_search.entity_searcher import EntitySearcher
from .entity_block_search.exporter import export_results_to_text as export_text
from .entity_block_search.models import SearchResult, SearchCondition, SearchSummary


class EntityBlockSearchService:
    """实体/方块/容器搜索服务。"""

    COMMON_ENTITIES = COMMON_ENTITIES
    COMMON_BLOCKS = COMMON_BLOCKS
    COMMON_CONTAINERS = COMMON_CONTAINERS
    MAX_RESULTS = MAX_RESULTS

    def __init__(self) -> None:
        """初始化空结果列表与扫描摘要。"""
        self.results: List[SearchResult] = []
        self.summary = SearchSummary()

    def search(
        self,
        world_path: Path,
        search_type: str,
        target: str,
        dimensions: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> List[SearchResult]:
        """搜索实体、方块或容器。

        Args:
            world_path: 世界根目录。
            search_type: ``entity`` / ``block`` / ``container`` 等合法类型。
            target: 目标 ID 或名称片段。
            dimensions: 可选维度过滤列表。
            progress_callback: 进度回调。
            log_callback: 日志回调。

        Returns:
            list[SearchResult]: 本次搜索结果（失败时可能为空，错误写入日志）。
        """
        self.results = []
        self.summary = SearchSummary()
        log = self._make_logger(log_callback)
        progress = self._make_progress(progress_callback)
        try:
            dimensions = self._validate_request(
                world_path, search_type, target, dimensions
            )
            self._run_search(
                world_path, search_type, target, dimensions, log, progress
            )
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            log(f"搜索失败: {exc}", "ERROR")
            logger.error(traceback.format_exc(), module="EntityBlockSearch")
        except Exception as exc:
            # MCA/NBT 遍历边界：保留结果列表，错误记入日志。
            log(f"搜索失败: {exc}", "ERROR")
            logger.error(traceback.format_exc(), module="EntityBlockSearch")
        return self.results

    def search_condition(
        self,
        condition: SearchCondition,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> List[SearchResult]:
        """使用 SearchCondition 对象执行搜索。"""
        errors = condition.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return self.search(
            world_path=condition.world_path,
            search_type=condition.search_type,
            target=condition.target,
            dimensions=condition.dimensions,
            progress_callback=progress_callback,
            log_callback=log_callback,
        )

    def export_results_to_text(
        self,
        output_path: Path,
        results: Optional[List[SearchResult]] = None,
    ) -> None:
        """将搜索结果导出为文本文件。"""
        export_text(output_path, self.summary, self.results, results)

    def export_results(self, results: List[SearchResult], output_path: Path) -> None:
        """导出搜索结果（匹配视图调用签名）。"""
        self.export_results_to_text(output_path, results)

    def _run_search(
        self,
        world_path: Path,
        search_type: str,
        target: str,
        dimensions: List[str],
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        from core.performance import get_tracker
        tracker = get_tracker()
        metadata = {
            "world": world_path.name,
            "type": search_type,
            "target": target,
        }
        with tracker.track("实体方块搜索", metadata):
            log(f"开始搜索 {search_type}: {target}", "INFO")
            log(f"搜索维度: {', '.join(dimensions)}", "INFO")
            self._search_dimensions(world_path, search_type, target, dimensions, log, progress)
            progress(1.0, f"搜索完成，找到 {len(self.results)} 个结果")
            log(f"搜索完成，共找到 {len(self.results)} 个 {target}", "INFO")
            tracker.add_metadata("results", len(self.results))
            tracker.add_metadata("regions", self.summary.scanned_regions)
            tracker.add_metadata("chunks", self.summary.scanned_chunks)

    def _search_dimensions(
        self,
        world_path: Path,
        search_type: str,
        target: str,
        dimensions: List[str],
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        step = 1.0 / len(dimensions)
        total_progress = 0.0
        for dimension in dimensions:
            progress(total_progress, f"搜索维度: {dimension}")
            searcher = self._create_searcher(search_type)
            base_progress = total_progress

            def update_dimension_progress(value: float, message: str) -> None:
                progress(base_progress + value * step, message)

            searcher.search_dimension(
                world_path,
                dimension,
                target,
                log,
                update_dimension_progress,
            )
            if self._is_result_limit_reached():
                log(f"结果数量达到上限 {self.MAX_RESULTS}，已停止继续扫描", "WARNING")
                break
            total_progress += step

    def _create_searcher(self, search_type: str) -> BaseSearcher:
        if search_type == "entity":
            return EntitySearcher(self.results, self.summary)
        if search_type == "block":
            return BlockSearcher(self.results, self.summary)
        return ContainerSearcher(self.results, self.summary)

    def _validate_request(
        self,
        world_path: Path,
        search_type: str,
        target: str,
        dimensions: Optional[List[str]],
    ) -> List[str]:
        if not world_path.exists():
            raise FileNotFoundError(f"存档路径不存在: {world_path}")
        if search_type not in VALID_SEARCH_TYPES:
            raise ValueError(f"不支持的搜索类型: {search_type}")
        if not target:
            raise ValueError("搜索目标不能为空")
        selected_dimensions = dimensions or ["overworld", "nether", "end"]
        valid_dimensions = [
            dimension
            for dimension in selected_dimensions
            if dimension in VALID_DIMENSIONS
        ]
        if not valid_dimensions:
            raise ValueError("未选择有效维度")
        return valid_dimensions

    def _make_logger(
        self,
        callback: Optional[Callable[[str, str], None]],
    ) -> Callable[[str, str], None]:
        def log(msg: str, level: str = "INFO") -> None:
            logger.info(msg, module="EntityBlockSearch")
            if callback:
                callback(msg, level)
        return log

    @staticmethod
    def _make_progress(
        callback: Optional[Callable[[float, str], None]],
    ) -> Callable[[float, str], None]:
        def progress(value: float, msg: str) -> None:
            if callback:
                callback(value, msg)
        return progress

    def _is_result_limit_reached(self) -> bool:
        return len(self.results) >= self.MAX_RESULTS


__all__ = ["EntityBlockSearchService", "SearchResult", "SearchCondition", "SearchSummary"]
