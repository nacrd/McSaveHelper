"""Result export for entity/block/container search."""
from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import List, Optional, TextIO

from core.io_atomic import atomic_write_text

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
    export_results = results if results is not None else stored_results
    buffer = StringIO()
    _write_header(buffer, summary, len(export_results))
    for idx, result in enumerate(export_results, 1):
        _write_result(buffer, idx, result)
    atomic_write_text(output_path, buffer.getvalue())


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
