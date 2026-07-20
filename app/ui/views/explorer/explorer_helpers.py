"""Pure helper functions for ExplorerView.

These helpers are kept free of Flet controls and ExplorerView instance state so
large Explorer tabs can be split incrementally without changing behavior.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.models.nbt_edit import NbtChange
from app.services.nbt_value_utils import coerce_like_tag, tag_display_value

# Re-export for existing Explorer imports.
__all__ = [
    "tag_display_value",
    "coerce_like_tag",
    "world_coords_to_region_chunk",
    "format_stage_value",
    "format_diff_value",
    "format_change_summary",
    "extract_chunk_objects",
]


def world_coords_to_region_chunk(
        world_x: int, world_z: int) -> Tuple[int, int, int, int]:
    """世界方块坐标 → 区域坐标与局部区块坐标。

    Args:
        world_x: 方块 X。
        world_z: 方块 Z。

    Returns:
        ``(region_x, region_z, local_chunk_x, local_chunk_z)``。
    """
    chunk_x = world_x // 16
    chunk_z = world_z // 16
    region_x = chunk_x // 32
    region_z = chunk_z // 32
    local_chunk_x = chunk_x % 32
    local_chunk_z = chunk_z % 32
    return region_x, region_z, local_chunk_x, local_chunk_z


def format_stage_value(value: Any) -> str:
    """暂存列表中的短值展示（截断到约 48 字符）。"""
    text = str(getattr(value, "value", value))
    return text if len(text) <= 48 else text[:45] + "…"


def format_diff_value(value: Any) -> str:
    """变更 diff 中的值展示（截断到约 160 字符）。"""
    text = str(getattr(value, "value", value))
    return text if len(text) <= 160 else text[:157] + "…"


def format_change_summary(index: int, change: NbtChange) -> str:
    """将单条 NbtChange 格式化为多行摘要文本。

    Args:
        index: 列表序号（0 起，展示为 #index+1）。
        change: 暂存变更。
    """
    old_text = format_diff_value(change.old_value)
    new_text = format_diff_value(change.new_value)
    kind = {
        "json": "JSON",
        "chunk": "区块",
        "chunk_readonly": "区块",
    }.get(change.format, "NBT")
    return (
        f"#{index + 1} [{kind}] {change.target_label}\n"
        f"  {change.display_path}\n  - {old_text}\n  + {new_text}"
    )


def _tag_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _is_mapping(value: Any) -> bool:
    return isinstance(
        value,
        dict) or (
        hasattr(
            value,
            "keys") and hasattr(
                value,
                "__getitem__") and type(value).__name__ in (
                    "NBTFile",
            "TAG_Compound"))


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
    """从区块 NBT 提取实体/方块实体摘要列表（NBT 页左侧对象列表）。

    Args:
        chunk_data: 区块根 compound 或兼容映射。

    Returns:
        每项含类型、id、位置与索引的字典列表。
    """
    objects: List[Dict[str, Any]] = []

    entities = _get_first_mapping(chunk_data, ["Entities", "entities"])
    if _is_list(entities):
        for index, entity in enumerate(entities):
            entity_id = str(
                _tag_value(
                    _get_value(
                        entity,
                        "id",
                        "unknown"))) if _is_mapping(entity) else "unknown"
            objects.append({
                "icon": "🐾",
                "title": f"实体 #{index + 1}: {entity_id}",
                "subtitle": _format_pos(entity),
                "data": entity,
            })

    block_entities = _get_first_mapping(
        chunk_data, ["block_entities", "BlockEntities", "TileEntities"])
    if _is_list(block_entities):
        for index, block_entity in enumerate(block_entities):
            block_id = str(
                _tag_value(
                    _get_value(
                        block_entity,
                        "id",
                        "unknown"))) if _is_mapping(block_entity) else "unknown"
            objects.append({
                "icon": "📦",
                "title": f"方块实体 #{index + 1}: {block_id}",
                "subtitle": _format_pos(block_entity),
                "data": block_entity,
            })
    return objects
