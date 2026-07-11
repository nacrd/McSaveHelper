"""Heightmap decoding for surface Y lookup.

Prefers WORLD_SURFACE, then MOTION_BLOCKING, then MOTION_BLOCKING_NO_LEAVES.
Modern (post-20w17a) heightmaps use compact bit packing that does not span
across long boundaries.
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

from core.mca.nbt_access import (
    as_int,
    chunk_root_and_version,
    first_key,
    is_mapping,
    long_array_values,
    mapping_get,
)
from core.mca.versions import DATA_VERSION_1_16, DATA_VERSION_1_18

# Preferred heightmap names (Java Edition).
_HEIGHTMAP_NAMES = (
    "WORLD_SURFACE",
    "WORLD_SURFACE_WG",
    "MOTION_BLOCKING",
    "MOTION_BLOCKING_NO_LEAVES",
)


def _bits_for_version(data_version: Optional[int]) -> int:
    # Height range needs enough bits for (max_build_height + 1).
    # 1.18+: -64..320 → span 384 → values 0..384 → 9 bits
    # pre-1.18: 0..255 → values 0..256 → 9 bits
    return 9


def unpack_heightmap_values(
    longs: Sequence[int],
    bits: int = 9,
    count: int = 256,
) -> List[int]:
    """Unpack compact (non-spanning) heightmap longs into `count` integers."""
    if bits <= 0 or bits > 64:
        return []
    values_per_long = 64 // bits
    if values_per_long <= 0:
        return []
    mask = (1 << bits) - 1
    out: List[int] = []
    for word in longs:
        w = int(word)
        if w < 0:
            w &= (1 << 64) - 1
        for i in range(values_per_long):
            out.append((w >> (i * bits)) & mask)
            if len(out) >= count:
                return out[:count]
    return out


def _heightmap_array(chunk_nbt: Any) -> Optional[List[int]]:
    root, version = chunk_root_and_version(chunk_nbt)
    if root is None:
        return None
    heightmaps = first_key(root, "Heightmaps", "heightmaps")
    if not is_mapping(heightmaps):
        return None

    raw = None
    for name in _HEIGHTMAP_NAMES:
        raw = mapping_get(heightmaps, name)
        if raw is not None:
            break
    if raw is None:
        # Some tools store only one unnamed-style entry; try first long-array-ish value
        try:
            for _, value in getattr(heightmaps, "items", lambda: [])():
                raw = value
                break
        except Exception:
            raw = None
    if raw is None:
        return None

    longs = long_array_values(raw)
    if not longs:
        return None

    bits = _bits_for_version(version)
    values = unpack_heightmap_values(longs, bits=bits, count=256)
    if len(values) < 256:
        return None
    return values


def surface_y_from_heightmap(
    chunk_nbt: Any, local_x: int, local_z: int
) -> Optional[int]:
    """Return surface block Y for column (local_x, local_z), or None.

    Heightmap entries store the Y coordinate *above* the highest matching
    block (Minecraft convention), so we return value - 1.
    """
    if not (0 <= local_x < 16 and 0 <= local_z < 16):
        return None
    values = _heightmap_array(chunk_nbt)
    if not values:
        return None
    index = local_z * 16 + local_x
    try:
        value = int(values[index])
    except Exception:
        return None
    # 0 often means "no surface" / void column in some generators
    if value <= 0:
        return None
    return value - 1


def has_heightmap(chunk_nbt: Any) -> bool:
    return _heightmap_array(chunk_nbt) is not None
