"""Result export for entity/block/container search."""

from pathlib import Path
from typing import List, Optional

from core.logger import logger
from .models import SearchResult, SearchSummary


def export_results_to_text(output_path: Path, summary: SearchSummary, stored_results: List[SearchResult], results: Optional[List[SearchResult]] = None) -> None:
    """将搜索结果导出为文本文件。"""
    try:
        export_results = results if results is not None else stored_results
        with open(output_path, "w", encoding="utf-8") as f:
            _write_header(f, summary, len(export_results))
            for idx, result in enumerate(export_results, 1):
                _write_result(f, idx, result)
    except Exception as e:
        logger.error(f"导出结果失败: {e}", module="EntityBlockSearch")


def _write_header(f, summary: SearchSummary, total: int) -> None:
    f.write(f"搜索结果 - 共 {total} 个\n")
    f.write(f"扫描区域: {summary.scanned_regions}\n")
    f.write(f"扫描区块: {summary.scanned_chunks}\n")
    f.write(f"跳过区块: {summary.skipped_chunks}\n")
    f.write("=" * 80 + "\n\n")


def _write_result(f, idx: int, result: SearchResult) -> None:
    f.write(f"{idx}. {result.name}\n")
    f.write(f"   类型: {result.result_type}\n")
    f.write(f"   位置: X={result.position[0]}, Y={result.position[1]}, Z={result.position[2]}\n")
    f.write(f"   维度: {result.dimension}\n")
    if result.extra_info:
        f.write("   额外信息:\n")
        for key, value in result.extra_info.items():
            f.write(f"      {key}: {value}\n")
    f.write("\n")
