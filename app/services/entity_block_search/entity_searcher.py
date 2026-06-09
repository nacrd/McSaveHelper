"""Entity search implementation."""

from pathlib import Path
from typing import Any, Callable, List

from .constants import MAX_RESULTS
from .models import SearchResult, SearchSummary
from .utils import get_dimension_region_files, get_entities, matches_target, tag_to_str, tag_value


class EntitySearcher:
    """Searches entities in region chunks."""

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
            log("anvil-parser2 未安装，无法搜索实体", "ERROR")
        except Exception as e:
            log(f"搜索维度 {dimension} 失败: {e}", "ERROR")

    def search_chunk(self, chunk: Any, target: str, dimension: str) -> None:
        try:
            for entity in get_entities(chunk):
                if self._limit_reached():
                    return
                self._handle_entity(entity, target, dimension)
        except Exception:
            pass

    def _scan_regions(self, region_files: List[Path], dimension: str, target: str, log: Callable[[str, str], None], progress: Callable[[float, str], None]) -> None:
        from anvil import Region
        total = len(region_files)
        for idx, region_file in enumerate(region_files):
            if self._limit_reached():
                return
            progress(idx / total, f"搜索区块文件 {idx + 1}/{total}")
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

    def _handle_entity(self, entity: Any, target: str, dimension: str) -> None:
        try:
            entity_id = tag_to_str(entity.get("id", ""))
            if not matches_target(entity_id, target):
                return
            pos = entity.get("Pos", [])
            if len(pos) < 3:
                return
            result = SearchResult("entity", entity_id, self._entity_pos(pos), dimension, self._entity_info(entity, entity_id))
            self.results.append(result)
        except Exception:
            pass

    @staticmethod
    def _entity_pos(pos: Any) -> tuple:
        return (int(float(tag_value(pos[0]))), int(float(tag_value(pos[1]))), int(float(tag_value(pos[2]))))

    def _entity_info(self, entity: Any, entity_id: str) -> dict:
        extra_info = {}
        if "villager" in entity_id:
            villager_data = entity.get("VillagerData", {})
            if hasattr(villager_data, "get"):
                extra_info["profession"] = tag_to_str(villager_data.get("profession", "unknown"))
        self._add_optional_health(entity, extra_info)
        custom_name = entity.get("CustomName", None)
        if custom_name:
            extra_info["custom_name"] = tag_to_str(custom_name)
        return extra_info

    @staticmethod
    def _add_optional_health(entity: Any, extra_info: dict) -> None:
        health = entity.get("Health", None)
        if health is not None:
            try:
                extra_info["health"] = float(tag_value(health))
            except (ValueError, TypeError):
                pass

    def _limit_reached(self) -> bool:
        return len(self.results) >= MAX_RESULTS
