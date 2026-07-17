"""Entity search implementation."""

from typing import Any

from .base_searcher import BaseSearcher
from .utils import get_entities, matches_target, tag_to_str, tag_value


class EntitySearcher(BaseSearcher):
    """搜索区域区块中的实体。"""

    progress_label = "区块文件"

    def search_chunk(self, chunk: Any, target: str, dimension: str) -> None:
        try:
            for entity in get_entities(chunk):
                if self._limit_reached():
                    return
                self._handle_entity(entity, target, dimension)
        except Exception:
            pass

    def _handle_entity(self, entity: Any, target: str, dimension: str) -> None:
        try:
            entity_id = tag_to_str(entity.get("id", ""))
            if not matches_target(entity_id, target):
                return
            pos = entity.get("Pos", [])
            if len(pos) < 3:
                return
            from .models import SearchResult
            result = SearchResult(
                "entity",
                entity_id,
                self._entity_pos(pos),
                dimension,
                self._entity_info(entity, entity_id),
            )
            self.results.append(result)
        except Exception:
            pass

    @staticmethod
    def _entity_pos(pos: Any) -> tuple:
        return tuple(int(float(tag_value(value))) for value in pos[:3])

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
