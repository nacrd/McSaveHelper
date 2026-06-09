"""Container extraction and search helpers."""

from pathlib import Path
from typing import Any, Callable, Dict, List

from .constants import MAX_RESULTS
from .models import SearchResult, SearchSummary
from .utils import (
    get_block_entities,
    get_block_entity_position,
    get_dimension_region_files,
    matches_target,
    tag_to_str,
    tag_value,
)


class ContainerSearcher:
    """Searches container block entities."""

    def __init__(self, results: List[SearchResult], summary: SearchSummary) -> None:
        self.results = results
        self.summary = summary

    def search_dimension(self, world_path: Path, dimension: str, target: str, log: Callable[[str, str], None], progress: Callable[[float, str], None]) -> None:
        try:
            region_files = get_dimension_region_files(world_path, dimension)
            if not region_files:
                log(f"维度 {dimension} 没有区块文件", "WARNING")
                return
            log(f"在 {dimension} 中找到 {len(region_files)} 个区块文件", "INFO")
            self._scan_regions(region_files, dimension, target, log, progress)
        except ImportError:
            log("anvil-parser2 未安装，无法搜索容器", "ERROR")
        except Exception as e:
            log(f"搜索维度 {dimension} 失败: {e}", "ERROR")

    def search_chunk(self, chunk: Any, target: str, dimension: str) -> None:
        try:
            for block_entity in get_block_entities(chunk):
                if self._limit_reached():
                    return
                self._handle_container(block_entity, target, dimension)
        except Exception:
            pass

    def get_container_info_at(self, chunk: Any, x: int, y: int, z: int) -> Dict[str, Any]:
        try:
            for block_entity in get_block_entities(chunk):
                if get_block_entity_position(block_entity) == (x, y, z):
                    return extract_container_info(block_entity)
        except Exception:
            pass
        return {}

    def _scan_regions(self, region_files: List[Path], dimension: str, target: str, log: Callable[[str, str], None], progress: Callable[[float, str], None]) -> None:
        from anvil import Region
        total = len(region_files)
        for idx, region_file in enumerate(region_files):
            if self._limit_reached():
                return
            progress(idx / total, f"搜索容器 {idx + 1}/{total}")
            self.summary.scanned_regions += 1
            try:
                self._scan_region(Region.from_file(str(region_file)), target, dimension)
            except Exception as e:
                log(f"读取区块文件 {region_file.name} 失败: {e}", "WARNING")

    def _scan_region(self, region: Any, target: str, dimension: str) -> None:
        for cx in range(32):
            for cz in range(32):
                if self._limit_reached():
                    return
                try:
                    chunk = region.get_chunk(cx, cz)
                    if chunk is not None:
                        self.summary.scanned_chunks += 1
                        self.search_chunk(chunk, target, dimension)
                except Exception:
                    self.summary.skipped_chunks += 1

    def _handle_container(self, block_entity: Any, target: str, dimension: str) -> None:
        try:
            container_id = tag_to_str(block_entity.get("id", ""))
            if not matches_target(container_id, target):
                return
            position = get_block_entity_position(block_entity)
            if position is None:
                return
            self.results.append(SearchResult("container", container_id, position, dimension, extract_container_info(block_entity)))
        except Exception:
            pass

    def _limit_reached(self) -> bool:
        return len(self.results) >= MAX_RESULTS


def extract_container_info(block_entity: Any) -> Dict[str, Any]:
    parsed_items = []
    for item in block_entity.get("Items", []) if hasattr(block_entity, "get") else []:
        try:
            item_id = tag_to_str(item.get("id", "unknown"))
            count = int(tag_value(item.get("Count", 1)))
            slot = item.get("Slot", None)
            prefix = f"槽位{int(tag_value(slot))}: " if slot is not None else ""
            parsed_items.append(f"{prefix}{item_id} x{count}")
        except Exception:
            pass
    info = {"item_count": len(parsed_items), "items": "; ".join(parsed_items) if parsed_items else "空"}
    custom_name = block_entity.get("CustomName", None) if hasattr(block_entity, "get") else None
    if custom_name:
        info["custom_name"] = tag_to_str(custom_name)
    return info
