import core.nbt as nbtlib
from typing import List, Optional, Tuple, Any

from .types import UUIDMapping

_UUID_STRING_KEYS = {
    "owner",
    "uuid",
    "trusted",
    "target",
    "id",
    "owneruuid",
    "playeruuid",
}


def _replace_int_array(tag: Any, mappings: List[UUIDMapping]) -> Optional[Tuple[Any, int]]:
    if not isinstance(tag, nbtlib.tag.IntArray):
        return None
    current = list(tag)
    for mapping in mappings:
        if current == mapping[0]:
            return nbtlib.tag.IntArray(mapping[1]), 1
    return None


def _replace_string(
    tag: Any,
    mappings: List[UUIDMapping],
    key_name: Optional[str],
) -> Optional[Tuple[Any, int]]:
    if not isinstance(tag, nbtlib.tag.String):
        return None
    if not key_name or key_name.lower() not in _UUID_STRING_KEYS:
        return None
    current = str(tag)
    for mapping in mappings:
        if current == mapping[2]:
            return nbtlib.tag.String(mapping[3]), 1
    return None


def _replace_compound_pairs(tag: dict, mappings: List[UUIDMapping]) -> int:
    changes = 0
    for mapping in mappings:
        old_most, old_least = mapping[4]
        new_most, new_least = mapping[5]
        for key in list(tag.keys()):
            if "Most" not in key:
                continue
            least_key = f"{key.replace('Most', '')}Least"
            if least_key not in tag:
                continue
            try:
                matches = int(tag[key]) == old_most and int(tag[least_key]) == old_least
            except (ValueError, TypeError, KeyError):
                matches = False
            if matches:
                tag[key] = nbtlib.tag.Long(new_most)
                tag[least_key] = nbtlib.tag.Long(new_least)
                changes += 1
    return changes


def patch_nbt(
    tag: Any,
    mappings: List[UUIDMapping],
    key_name: Optional[str] = None
) -> Tuple[Any, int]:
    """递归遍历 NBT，将旧 UUID 替换为新 UUID，返回 (修改后的tag, 修改次数)

    Args:
        tag: NBT 标签对象
        mappings: UUID 映射列表
        key_name: 当前键名（用于上下文）

    Returns:
        (修改后的 tag, 修改次数)
    """
    replacement = _replace_int_array(tag, mappings)
    if replacement is not None:
        return replacement
    replacement = _replace_string(tag, mappings, key_name)
    if replacement is not None:
        return replacement

    if isinstance(tag, dict):
        changes = _replace_compound_pairs(tag, mappings)
        for k in tag:
            tag[k], c = patch_nbt(tag[k], mappings, k)
            changes += c
        return tag, changes

    if isinstance(tag, list):
        changes = 0
        for i in range(len(tag)):
            tag[i], c = patch_nbt(tag[i], mappings, key_name)
            changes += c
        return tag, changes

    return tag, 0
