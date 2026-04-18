import nbtlib
from typing import List, Optional, Tuple, Any

from .types import UUIDMapping


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
    changes = 0

    # IntArray (1.16+)
    if isinstance(tag, nbtlib.tag.IntArray):
        curr = list(tag)
        for m in mappings:
            if curr == m[0]:
                return nbtlib.tag.IntArray(m[1]), 1

    # String (白名单内)
    if isinstance(tag, nbtlib.tag.String):
        if key_name and key_name.lower() in {'owner', 'uuid', 'trusted', 'target', 'id', 'owneruuid', 'playeruuid'}:
            curr = str(tag)
            for m in mappings:
                if curr == m[2]:
                    return nbtlib.tag.String(m[3]), 1

    # Compound (Most/Least)
    if isinstance(tag, dict):
        for m in mappings:
            old_m, old_l = m[4]
            new_m, new_l = m[5]
            for k in list(tag.keys()):
                if 'Most' in k:
                    suffix = k.replace('Most', '')
                    least_k = f"{suffix}Least"
                    if least_k in tag:
                        try:
                            if int(tag[k]) == old_m and int(tag[least_k]) == old_l:
                                tag[k] = nbtlib.tag.Long(new_m)
                                tag[least_k] = nbtlib.tag.Long(new_l)
                                changes += 1
                        except (ValueError, TypeError, KeyError):
                            pass
        for k in tag:
            tag[k], c = patch_nbt(tag[k], mappings, k)
            changes += c

    # List
    elif isinstance(tag, list):
        for i in range(len(tag)):
            tag[i], c = patch_nbt(tag[i], mappings, key_name)
            changes += c

    return tag, changes