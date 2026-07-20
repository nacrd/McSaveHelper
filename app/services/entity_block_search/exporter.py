"""Result export for entity/block/container search."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, TextIO

from core.logger import logger

from .models import SearchResult, SearchSummary


def export_results_to_text(
    output_path: Path,
    summary: SearchSummary,
    stored_results: List[SearchResult],
    results: Optional[List[SearchResult]] = None,
) -> None:
    """将搜索结果导出为文本文件。

    Args:
        output_path: 目标文本路径。
        summary: 扫描统计。
        stored_results: 服务内部缓存结果。
        results: 可选覆盖导出列表。
    """
    try:
        export_results = results if results is not None else stored_results
        with open(output_path, "w", encoding="utf-8") as handle:
            _write_header(handle, summary, len(export_results))
            for idx, result in enumerate(export_results, 1):
                _write_result(handle, idx, result)
    except OSError as exc:
        logger.error(f"导出结果失败: {exc}", module="EntityBlockSearch")


def _write_header(handle: TextIO, summary: SearchSummary, total: int) -> None:
    handle.write(f"搜索结果 - 共 {total} 个\n")
    handle.write(f"扫描区域: {summary.scanned_regions}\n")
    handle.write(f"扫描区块: {summary.scanned_chunks}\n")
    handle.write(f"跳过区块: {summary.skipped_chunks}\n")
    handle.write("=" * 80 + "\n\n")


def _write_result(handle: TextIO, idx: int, result: SearchResult) -> None:
    handle.write(f"{idx}. {result.name}\n")
    handle.write(f"   类型: {result.result_type}\n")
    handle.write(f"   位置: X={result.x}, Y={result.y}, Z={result.z}\n")
    handle.write(f"   维度: {result.dimension}\n")
    if result.extra_info:
        handle.write("   额外信息:\n")
        for key, value in result.extra_info.items():
            handle.write(f"      {key}: {value}\n")
    handle.write("\n")
