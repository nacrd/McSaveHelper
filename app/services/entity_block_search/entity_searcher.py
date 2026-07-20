"""Entity search implementation."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from .base_searcher import BaseSearcher
from .models import SearchResult
from .utils import (
    get_dimension_entity_files,
    get_dimension_region_files,
    get_entities,
    matches_target,
    tag_to_str,
    tag_value,
)

LogFn = Callable[[str, str], None]
ProgressFn = Callable[[float, str], None]


class EntitySearcher(BaseSearcher):
    """搜索区域区块中的实体。"""

    progress_label = "区块文件"

    def search_dimension(
        self,
        world_path: Path,
        dimension: str,
        target: str,
        log: LogFn,
        progress: ProgressFn,
    ) -> None:
        """Scan modern entity regions and legacy chunk-embedded entities."""
        entity_files = get_dimension_entity_files(world_path, dimension)
        chunk_files = get_dimension_region_files(world_path, dimension)
        region_files = entity_files + chunk_files
        if not region_files:
            log(f"维度 {dimension} 没有实体或区块文件", "WARNING")
            return
        log(
            f"在 {dimension} 中找到 {len(entity_files)} 个实体文件、"
            f"{len(chunk_files)} 个区块文件",
            "INFO",
        )
        self._scan_regions(region_files, dimension, target, log, progress)

    def search_chunk(self, chunk: Any, target: str, dimension: str) -> None:
        """在单个区块中扫描匹配的实体。

        Args:
            chunk: MCA/NBT 区块对象。
            target: 目标实体 ID 或匹配模式。
            dimension: 维度标识（写入结果）。
        """
        try:
            for entity in get_entities(chunk):
                if self._limit_reached():
                    return
                self._handle_entity(entity, target, dimension)
        except (
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
            KeyError,
            AttributeError,
        ):
            return
        except Exception:
            return

    def _handle_entity(
        self,
        entity: Any,
        target: str,
        dimension: str,
    ) -> None:
        try:
            entity_id = tag_to_str(entity.get("id", ""))
            if not matches_target(entity_id, target):
                return
            pos = entity.get("Pos", [])
            if len(pos) < 3:
                return
            result = SearchResult(
                "entity",
                entity_id,
                self._entity_pos(pos),
                dimension,
                self._entity_info(entity, entity_id),
            )
            self.results.append(result)
        except (
            TypeError,
            ValueError,
            KeyError,
            AttributeError,
            IndexError,
        ):
            return
        except Exception:
            return

    @staticmethod
    def _entity_pos(pos: Any) -> tuple[int, int, int]:
        values = [int(float(tag_value(value))) for value in pos[:3]]
        return values[0], values[1], values[2]

    def _entity_info(self, entity: Any, entity_id: str) -> Dict[str, Any]:
        extra_info: Dict[str, Any] = {}
        if "villager" in entity_id:
            villager_data = entity.get("VillagerData", {})
            if hasattr(villager_data, "get"):
                extra_info["profession"] = tag_to_str(
                    villager_data.get("profession", "unknown")
                )
        self._add_optional_health(entity, extra_info)
        custom_name = entity.get("CustomName", None)
        if custom_name:
            extra_info["custom_name"] = tag_to_str(custom_name)
        return extra_info

    @staticmethod
    def _add_optional_health(entity: Any, extra_info: Dict[str, Any]) -> None:
        health = entity.get("Health", None)
        if health is None:
            return
        try:
            extra_info["health"] = float(tag_value(health))
        except (ValueError, TypeError):
            pass
