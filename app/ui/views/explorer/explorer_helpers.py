"""Pure helper functions for ExplorerView.

These helpers are kept free of Flet controls and ExplorerView instance state so
large Explorer tabs can be split incrementally without changing behavior.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import nbtlib


def tag_display_value(value: Any) -> str:
    if hasattr(value, "unpack"):
        value = value.unpack()
    elif hasattr(value, "value"):
        value = value.value
    return str(value)


def coerce_like_tag(raw: str, original: Any) -> Any:
    tag_type = type(original)
    text = raw.strip()
    if "(" in text and text.endswith(")"):
        text = text[text.find("(") + 1:-1]
    if isinstance(original, (nbtlib.Float, nbtlib.Double)):
        return tag_type(float(text))
    if isinstance(original, (nbtlib.Byte, nbtlib.Short, nbtlib.Int, nbtlib.Long)):
        return tag_type(int(float(text)))
    try:
        return tag_type(text)
    except Exception:
        return text


def world_coords_to_region_chunk(world_x: int, world_z: int) -> Tuple[int, int, int, int]:
    chunk_x = world_x // 16
    chunk_z = world_z // 16
    region_x = chunk_x // 32
    region_z = chunk_z // 32
    local_chunk_x = chunk_x % 32
    local_chunk_z = chunk_z % 32
    return region_x, region_z, local_chunk_x, local_chunk_z


def format_stage_value(value: Any) -> str:
    text = str(getattr(value, "value", value))
    return text if len(text) <= 48 else text[:45] + "…"


def format_diff_value(value: Any) -> str:
    text = str(getattr(value, "value", value))
    return text if len(text) <= 160 else text[:157] + "…"


def format_change_summary(index: int, change: Dict[str, Any]) -> str:
    old_text = format_diff_value(change["old_value"])
    new_text = format_diff_value(change["new_value"])
    target = change.get("target_label", "未知目标")
    kind = "JSON" if change.get("format") == "json" else "NBT"
    return f"#{index + 1} [{kind}] {target}\n  {change['display_path']}\n  - {old_text}\n  + {new_text}"


def _tag_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _is_mapping(value: Any) -> bool:
    return isinstance(value, dict) or (
        hasattr(value, "keys") and hasattr(value, "__getitem__") and type(value).__name__ in ("NBTFile", "TAG_Compound")
    )


def _is_list(value: Any) -> bool:
    return isinstance(value, list) or type(value).__name__ == "TAG_List"


def _get_value(data: Any, key: str, default: Any = None) -> Any:
    if isinstance(data, dict):
        return data.get(key, default)
    if _is_mapping(data):
        try:
            return data[key] if key in data.keys() else default
        except Exception:
            return default
    return default


def _get_first_mapping(data: Any, keys: List[str]) -> Any:
    if not _is_mapping(data):
        return None
    for key in keys:
        value = _get_value(data, key)
        if value is not None:
            return value
    level = _get_value(data, "Level")
    if _is_mapping(level):
        for key in keys:
            value = _get_value(level, key)
            if value is not None:
                return value
    return None


def _format_pos(data: Any) -> str:
    if not _is_mapping(data):
        return "未知位置"
    pos = _get_value(data, "Pos")
    if _is_list(pos) and len(pos) >= 3:
        return f"({_tag_value(pos[0])}, {_tag_value(pos[1])}, {_tag_value(pos[2])})"
    xyz = [_get_value(data, "x"), _get_value(data, "y"), _get_value(data, "z")]
    if all(item is not None for item in xyz):
        return f"({_tag_value(xyz[0])}, {_tag_value(xyz[1])}, {_tag_value(xyz[2])})"
    return "未知位置"


def extract_chunk_objects(chunk_data: Any) -> List[Dict[str, Any]]:
    objects: List[Dict[str, Any]] = []

    entities = _get_first_mapping(chunk_data, ["Entities", "entities"])
    if _is_list(entities):
        for index, entity in enumerate(entities):
            entity_id = str(_tag_value(_get_value(entity, "id", "unknown"))) if _is_mapping(entity) else "unknown"
            objects.append({
                "icon": "🐾",
                "title": f"实体 #{index + 1}: {entity_id}",
                "subtitle": _format_pos(entity),
                "data": entity,
            })

    block_entities = _get_first_mapping(chunk_data, ["block_entities", "BlockEntities", "TileEntities"])
    if _is_list(block_entities):
        for index, block_entity in enumerate(block_entities):
            block_id = str(_tag_value(_get_value(block_entity, "id", "unknown"))) if _is_mapping(block_entity) else "unknown"
            objects.append({
                "icon": "📦",
                "title": f"方块实体 #{index + 1}: {block_id}",
                "subtitle": _format_pos(block_entity),
                "data": block_entity,
            })
    return objects
