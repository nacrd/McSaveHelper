"""Section palette + bit-packed block state access."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from core.mca.nbt_access import (
    as_int,
    as_str,
    chunk_root_and_version,
    first_key,
    is_mapping,
    is_sequence,
    iter_sequence,
    long_array_values,
    mapping_get,
    tag_value,
)
from core.mca.versions import DATA_VERSION_1_13, DATA_VERSION_1_16, section_y_range

_AIR_NAMES = frozenset(
    {
        "minecraft:air",
        "minecraft:cave_air",
        "minecraft:void_air",
        "air",
        "cave_air",
        "void_air",
    }
)


def is_air_name(name: Optional[str]) -> bool:
    if not name:
        return True
    n = name.lower()
    return n in _AIR_NAMES or n.endswith(":air") or n.endswith("_air")


def _palette_name(entry: Any) -> str:
    if is_mapping(entry):
        name = first_key(entry, "Name", "name")
        return as_str(name) if name is not None else "minecraft:air"
    return as_str(entry) or "minecraft:air"


def _section_y(section: Any) -> Optional[int]:
    return as_int(first_key(section, "Y", "y"))


def _iter_sections(root: Any) -> List[Any]:
    sections = first_key(root, "sections", "Sections")
    if sections is None:
        return []
    return [s for s in iter_sequence(sections) if is_mapping(s)]


def _section_index_map(root: Any) -> Dict[int, Any]:
    out: Dict[int, Any] = {}
    for section in _iter_sections(root):
        y = _section_y(section)
        if y is not None:
            out[y] = section
    return out


def _palette_and_data(section: Any) -> Tuple[List[str], Optional[List[int]]]:
    """Return (palette_names, packed_longs_or_None)."""
    # 1.16+ nested block_states
    block_states = first_key(section, "block_states", "BlockStates")
    if is_mapping(block_states):
        palette_tag = first_key(block_states, "palette", "Palette")
        data_tag = first_key(block_states, "data", "Data")
        palette = [_palette_name(e) for e in iter_sequence(palette_tag)]
        data = long_array_values(data_tag) if data_tag is not None else None
        return palette, data

    # 1.13–1.15 flat Palette + BlockStates on section
    palette_tag = first_key(section, "Palette", "palette")
    if palette_tag is not None:
        palette = [_palette_name(e) for e in iter_sequence(palette_tag)]
        data_tag = first_key(section, "BlockStates", "block_states")
        # If block_states was a mapping we already handled it; here expect array
        data = None
        if data_tag is not None and not is_mapping(data_tag):
            data = long_array_values(data_tag)
        return palette, data

    return [], None


def _bits_per_entry(palette_len: int) -> int:
    if palette_len <= 1:
        return 0
    bits = (palette_len - 1).bit_length()
    return max(4, bits)


def _palette_index(
    data: List[int],
    index: int,
    bits: int,
    stretch: bool,
) -> int:
    if bits <= 0:
        return 0
    mask = (1 << bits) - 1
    if not stretch:
        values_per_long = 64 // bits
        if values_per_long <= 0:
            return 0
        long_index = index // values_per_long
        bit_offset = (index % values_per_long) * bits
        if long_index >= len(data):
            return 0
        word = data[long_index]
        return (word >> bit_offset) & mask

    # Pre-20w17a: values may span two longs
    bit_index = index * bits
    long_index = bit_index // 64
    bit_offset = bit_index % 64
    if long_index >= len(data):
        return 0
    word = data[long_index]
    if bit_offset + bits <= 64:
        return (word >> bit_offset) & mask
    # span
    low_bits = 64 - bit_offset
    if long_index + 1 >= len(data):
        return (word >> bit_offset) & mask
    high = data[long_index + 1]
    low_part = word >> bit_offset
    high_part = high & ((1 << (bits - low_bits)) - 1)
    return (low_part | (high_part << low_bits)) & mask


def block_id_at(chunk_nbt: Any, x: int, y: int, z: int) -> Optional[str]:
    """Return block resource id at chunk-local (x,y,z), e.g. minecraft:stone."""
    if not (0 <= x < 16 and 0 <= z < 16):
        return None
    root, version = chunk_root_and_version(chunk_nbt)
    if root is None:
        return None

    # Python // floors toward -inf: y=-1 → section -1. Correct for MC.
    section_y = y // 16

    sections = _section_index_map(root)
    section = sections.get(section_y)
    if section is None:
        return "minecraft:air"

    # Legacy pre-1.13 Blocks array
    if version is not None and version < DATA_VERSION_1_13:
        blocks = first_key(section, "Blocks")
        if blocks is not None:
            arr = iter_sequence(blocks)
            local_y = y & 15
            index = local_y * 256 + z * 16 + x
            try:
                block_id = int(tag_value(arr[index]))
            except Exception:
                return "minecraft:air"
            # Without full legacy map, expose numeric pseudo-id
            return f"legacy:{block_id}"

    palette, data = _palette_and_data(section)
    if not palette:
        return "minecraft:air"
    if len(palette) == 1 or data is None:
        return palette[0]

    bits = _bits_per_entry(len(palette))
    local_y = y - section_y * 16
    index = local_y * 256 + z * 16 + x
    stretch = version is not None and version < DATA_VERSION_1_16
    # 20w17a is 2529; DATA_VERSION_1_16 constant ~2566 is close enough.
    # Prefer non-stretch when version unknown (modern worlds dominate).
    if version is None:
        stretch = False
    else:
        stretch = version < 2529

    try:
        pi = _palette_index(data, index, bits, stretch=stretch)
    except Exception:
        return palette[0]
    if 0 <= pi < len(palette):
        return palette[pi]
    return "minecraft:air"


def scan_surface_y(chunk_nbt: Any, x: int, z: int) -> Optional[int]:
    """Fallback: walk sections top-down until a non-air block is found."""
    if not (0 <= x < 16 and 0 <= z < 16):
        return None
    root, version = chunk_root_and_version(chunk_nbt)
    if root is None:
        return None
    sections = _section_index_map(root)
    if not sections:
        return None

    for section_y in sorted(sections.keys(), reverse=True):
        section = sections[section_y]
        palette, data = _palette_and_data(section)
        if not palette:
            continue
        if all(is_air_name(n) for n in palette):
            continue
        # If single non-air palette entry fills section, top of section is surface
        # Still need exact column — sample each y.
        y0 = section_y * 16
        for y in range(y0 + 15, y0 - 1, -1):
            name = block_id_at(chunk_nbt, x, y, z)
            if not is_air_name(name):
                return y
    return None


def surface_block_id(chunk_nbt: Any, x: int, z: int) -> Optional[str]:
    """Heightmap-first surface block id for column (x, z)."""
    from core.mca.heightmaps import surface_y_from_heightmap

    y = surface_y_from_heightmap(chunk_nbt, x, z)
    if y is None:
        y = scan_surface_y(chunk_nbt, x, z)
    if y is None:
        return None
    # Heightmap points at top non-air; verify and walk down a few if air
    for dy in range(0, 8):
        name = block_id_at(chunk_nbt, x, y - dy, z)
        if not is_air_name(name):
            return name
    return block_id_at(chunk_nbt, x, y, z)
