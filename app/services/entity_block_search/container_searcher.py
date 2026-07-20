"""Container extraction and search helpers."""
from __future__ import annotations

from typing import Any, Dict

from .base_searcher import BaseSearcher
from .models import SearchResult
from .utils import (
    get_block_entities,
    get_block_entity_position,
    matches_target,
    tag_to_str,
    tag_value,
)


class ContainerSearcher(BaseSearcher):
    """搜索区块中的容器方块实体。"""

    progress_label = "容器"

    def search_chunk(self, chunk: Any, target: str, dimension: str) -> None:
        try:
            for block_entity in get_block_entities(chunk):
                if self._limit_reached():
                    return
                self._handle_container(block_entity, target, dimension)
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

    def get_container_info_at(
        self,
        chunk: Any,
        x: int,
        y: int,
        z: int,
    ) -> Dict[str, Any]:
        """Return inventory summary for a container at world coords."""
        try:
            for block_entity in get_block_entities(chunk):
                if get_block_entity_position(block_entity) == (x, y, z):
                    return extract_container_info(block_entity)
        except (
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
            KeyError,
            AttributeError,
        ):
            pass
        except Exception:
            pass
        return {}

    def _handle_container(
        self,
        block_entity: Any,
        target: str,
        dimension: str,
    ) -> None:
        try:
            container_id = tag_to_str(block_entity.get("id", ""))
            if not matches_target(container_id, target):
                return
            position = get_block_entity_position(block_entity)
            if position is None:
                return
            self.results.append(SearchResult(
                "container",
                container_id,
                position,
                dimension,
                extract_container_info(block_entity),
            ))
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


def extract_container_info(block_entity: Any) -> Dict[str, Any]:
    """Parse Items[] from a container block entity into display fields."""
    parsed_items: list[str] = []
    items = (
        block_entity.get("Items", [])
        if hasattr(block_entity, "get")
        else []
    )
    for item in items:
        try:
            item_id = tag_to_str(item.get("id", "unknown"))
            count = int(tag_value(item.get("Count", 1)))
            slot = item.get("Slot", None)
            prefix = (
                f"槽位{int(tag_value(slot))}: "
                if slot is not None
                else ""
            )
            parsed_items.append(f"{prefix}{item_id} x{count}")
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
        except Exception:
            continue
    info: Dict[str, Any] = {
        "item_count": len(parsed_items),
        "items": "; ".join(parsed_items) if parsed_items else "空",
    }
    custom_name = (
        block_entity.get("CustomName", None)
        if hasattr(block_entity, "get")
        else None
    )
    if custom_name:
        info["custom_name"] = tag_to_str(custom_name)
    return info
