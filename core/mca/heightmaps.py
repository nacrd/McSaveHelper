"""Heightmap decoding for surface Y lookup.

Modern post-1.18 heightmap entries are relative to world min_y (-64):
stored value is (absolute_y + 1 - min_y), packed as compact 9-bit ints.
Pre-1.18 values are absolute (min_y = 0).
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from core.mca.nbt_access import (
    chunk_root_and_version,
    first_key,
    is_mapping,
    long_array_values,
    mapping_get,
)
from core.mca.versions import DATA_VERSION_1_18

# Keep the historical default for callers that use the heightmap for collision
# or statistics decisions.  The map renderer opts into WORLD_SURFACE below.
DEFAULT_HEIGHTMAP_NAMES: Tuple[str, ...] = (
    "MOTION_BLOCKING",
    "MOTION_BLOCKING_NO_LEAVES",
    "WORLD_SURFACE",
    "WORLD_SURFACE_WG",
)

# WORLD_SURFACE follows the highest non-air column, which is the height a
# top-down map needs for foliage, water and terrain silhouettes.  Keep motion
# maps as fallbacks for older or partially written chunks.
WORLD_SURFACE_HEIGHTMAP_NAMES: Tuple[str, ...] = (
    "WORLD_SURFACE",
    "WORLD_SURFACE_WG",
    "MOTION_BLOCKING",
    "MOTION_BLOCKING_NO_LEAVES",
)


def world_min_y(data_version: Optional[int]) -> int:
    if data_version is not None and data_version >= DATA_VERSION_1_18:
        return -64
    return 0


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
        w = int(word) & ((1 << 64) - 1)
        for i in range(values_per_long):
            out.append((w >> (i * bits)) & mask)
            if len(out) >= count:
                return out[:count]
    return out


def decode_heightmap_raw(
    chunk_nbt: Any,
    *,
    heightmap_names: Sequence[str] = DEFAULT_HEIGHTMAP_NAMES,
) -> Tuple[Optional[List[int]], Optional[int]]:
    """Return packed height values using an explicit heightmap preference.

    ``MOTION_BLOCKING`` remains the default for compatibility.  Renderers that
    need the visible world silhouette should pass
    :data:`WORLD_SURFACE_HEIGHTMAP_NAMES` explicitly.
    """
    root, version = chunk_root_and_version(chunk_nbt)
    if root is None:
        return None, version
    heightmaps = first_key(root, "Heightmaps", "heightmaps")
    if not is_mapping(heightmaps):
        return None, version

    raw = _preferred_heightmap(heightmaps, heightmap_names)
    if raw is None:
        return None, version

    longs = long_array_values(raw)
    if not longs:
        return None, version

    values = unpack_heightmap_values(longs, bits=9, count=256)
    if len(values) < 256:
        return None, version
    return values, version


def _preferred_heightmap(
    heightmaps: Any, heightmap_names: Sequence[str]
) -> Any:
    for name in heightmap_names:
        raw = mapping_get(heightmaps, name)
        if raw is not None:
            return raw
    try:
        items = list(heightmaps.items())
    except Exception:
        return None
    return items[0][1] if items else None


def heightmap_value_to_block_y(
    value: int, data_version: Optional[int]
) -> Optional[int]:
    """Convert one heightmap entry to the Y of the top matching block."""
    if value <= 0:
        return None
    min_y = world_min_y(data_version)
    # Stored value = (block_y + 1) - min_y  =>  block_y = value + min_y - 1
    block_y = int(value) + min_y - 1
    max_y = 319 if min_y < 0 else 255
    if block_y < min_y - 1 or block_y > max_y + 1:
        return None
    return block_y


def surface_y_from_heightmap(
    chunk_nbt: Any,
    local_x: int,
    local_z: int,
    *,
    heightmap_names: Sequence[str] = DEFAULT_HEIGHTMAP_NAMES,
) -> Optional[int]:
    """Return a selected heightmap's block Y for one local column."""
    if not (0 <= local_x < 16 and 0 <= local_z < 16):
        return None
    values, version = decode_heightmap_raw(
        chunk_nbt,
        heightmap_names=heightmap_names,
    )
    if not values:
        return None
    index = local_z * 16 + local_x
    try:
        value = int(values[index])
    except Exception:
        return None
    return heightmap_value_to_block_y(value, version)
