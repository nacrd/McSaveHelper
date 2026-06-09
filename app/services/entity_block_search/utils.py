"""Shared helpers for NBT-like search data."""

from pathlib import Path
from typing import Any, List, Optional, Tuple

from core.region_utils import scan_region_dir


def tag_value(value: Any) -> Any:
    return getattr(value, "value", value)


def tag_to_str(value: Any) -> str:
    return str(tag_value(value))


def matches_target(name: str, target: str) -> bool:
    return target == "*" or name == target or name.endswith(f":{target}")


def get_block_name(block: Any) -> str:
    try:
        name_attr = getattr(block, "name", "")
        return tag_to_str(name_attr() if callable(name_attr) else name_attr)
    except Exception:
        return ""


def get_section_range(chunk: Any) -> range:
    try:
        from anvil.chunk import _section_height_range
        result = _section_height_range(chunk.version)
        return result if isinstance(result, range) else range(-4, 20)
    except Exception:
        return range(-4, 20)


def get_dimension_path(world_path: Path, dimension: str) -> Optional[Path]:
    if dimension == "overworld":
        return world_path
    paths = _dimension_candidates(world_path, dimension)
    for path in paths:
        if path.exists():
            return path
    return None


def get_dimension_region_files(world_path: Path, dimension: str) -> List[Path]:
    dimension_path = get_dimension_path(world_path, dimension)
    if not dimension_path:
        return []
    return scan_region_dir(dimension_path / "region")


def get_entities(chunk: Any) -> List[Any]:
    data = chunk.data if hasattr(chunk, "data") else chunk
    return _get_child_list(data, ("entities", "Entities"))


def get_block_entities(chunk: Any) -> List[Any]:
    data = chunk.data if hasattr(chunk, "data") else chunk
    return _get_child_list(data, ("block_entities", "BlockEntities", "TileEntities"))


def get_block_entity_position(block_entity: Any) -> Optional[Tuple[int, int, int]]:
    try:
        x = block_entity.get("x", block_entity.get("X"))
        y = block_entity.get("y", block_entity.get("Y"))
        z = block_entity.get("z", block_entity.get("Z"))
        if x is None or y is None or z is None:
            return None
        return (int(tag_value(x)), int(tag_value(y)), int(tag_value(z)))
    except Exception:
        return None


def _dimension_candidates(world_path: Path, dimension: str) -> List[Path]:
    if dimension == "nether":
        return [world_path / "DIM-1", world_path / "dimensions" / "minecraft" / "the_nether"]
    if dimension == "end":
        return [world_path / "DIM1", world_path / "dimensions" / "minecraft" / "the_end"]
    return []


def _get_child_list(data: Any, keys: Tuple[str, ...]) -> List[Any]:
    if not data:
        return []
    for key in keys:
        items = data.get(key, [])
        if items:
            return list(items)
    level = data.get("Level", {})
    if hasattr(level, "get"):
        for key in keys:
            items = level.get(key, [])
            if items:
                return list(items)
    return []
