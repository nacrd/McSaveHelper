"""Section palette + bit-packed block state access with lazy section parse."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from core.mca.heightmaps import (
    decode_heightmap_raw,
    heightmap_value_to_block_y,
)
from core.mca.nbt_access import (
    as_int,
    as_str,
    chunk_root_and_version,
    first_key,
    is_mapping,
    iter_sequence,
    long_array_values,
    tag_value,
)
from core.mca.versions import DATA_VERSION_1_13

_AIR_NAMES = frozenset({
    "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
    "air", "cave_air", "void_air",
})


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
    y = as_int(first_key(section, "Y", "y"))
    if y is None:
        return None
    if y > 127:
        y -= 256
    return y


def _palette_and_data(section: Any) -> Tuple[List[str], Optional[List[int]]]:
    block_states = first_key(section, "block_states", "BlockStates")
    if is_mapping(block_states):
        palette_tag = first_key(block_states, "palette", "Palette")
        data_tag = first_key(block_states, "data", "Data")
        palette = [_palette_name(e) for e in iter_sequence(palette_tag)]
        data = long_array_values(data_tag) if data_tag is not None else None
        return palette, data

    palette_tag = first_key(section, "Palette", "palette")
    if palette_tag is not None:
        palette = [_palette_name(e) for e in iter_sequence(palette_tag)]
        data_tag = first_key(section, "BlockStates", "block_states")
        data = None
        if data_tag is not None and not is_mapping(data_tag):
            data = long_array_values(data_tag)
        return palette, data
    return [], None


def _bits_per_entry(palette_len: int) -> int:
    if palette_len <= 1:
        return 0
    return max(4, (palette_len - 1).bit_length())


def _palette_index(data: List[int], index: int, bits: int, stretch: bool) -> int:
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
        word = data[long_index] & ((1 << 64) - 1)
        return (word >> bit_offset) & mask

    bit_index = index * bits
    long_index = bit_index // 64
    bit_offset = bit_index % 64
    if long_index >= len(data):
        return 0
    word = data[long_index] & ((1 << 64) - 1)
    if bit_offset + bits <= 64:
        return (word >> bit_offset) & mask
    low_bits = 64 - bit_offset
    if long_index + 1 >= len(data):
        return (word >> bit_offset) & mask
    high = data[long_index + 1] & ((1 << 64) - 1)
    low_part = word >> bit_offset
    high_part = high & ((1 << (bits - low_bits)) - 1)
    return (low_part | (high_part << low_bits)) & mask


class _SectionData:
    __slots__ = ("palette", "data", "bits", "stretch", "legacy_blocks")

    def __init__(
        self,
        palette: List[str],
        data: Optional[List[int]],
        stretch: bool,
        legacy_blocks: Optional[List[int]] = None,
    ) -> None:
        self.palette = palette
        self.data = data
        self.bits = _bits_per_entry(len(palette)) if palette else 0
        self.stretch = stretch
        self.legacy_blocks = legacy_blocks


class ChunkBlocks:
    """Parsed chunk view with lazy section decoding for topview speed."""

    __slots__ = (
        "root", "version", "sections", "heightmap", "section_ys_desc",
        "_section_raw", "_stretch", "_legacy",
    )

    def __init__(self, chunk_nbt: Any) -> None:
        self.root, self.version = chunk_root_and_version(chunk_nbt)
        self.sections: Dict[int, _SectionData] = {}
        self.heightmap: Optional[List[int]] = None
        self.section_ys_desc: List[int] = []
        self._section_raw: Dict[int, Any] = {}
        self._stretch = False
        self._legacy = False
        if self.root is None:
            return

        hm, ver = decode_heightmap_raw(chunk_nbt)
        if ver is not None:
            self.version = ver
        self.heightmap = hm
        self._stretch = self.version is not None and self.version < 2529
        self._legacy = self.version is not None and self.version < DATA_VERSION_1_13

        sections_tag = first_key(self.root, "sections", "Sections")
        for section in iter_sequence(sections_tag):
            if not is_mapping(section):
                continue
            sy = _section_y(section)
            if sy is None:
                continue
            self._section_raw[sy] = section

        self.section_ys_desc = sorted(self._section_raw.keys(), reverse=True)

    def _ensure_section(self, section_y: int) -> Optional[_SectionData]:
        if section_y in self.sections:
            return self.sections[section_y]
        section = self._section_raw.get(section_y)
        if section is None:
            return None
        legacy = None
        if self._legacy:
            blocks = first_key(section, "Blocks")
            if blocks is not None:
                try:
                    legacy = [int(tag_value(b)) for b in iter_sequence(blocks)]
                except Exception:
                    legacy = None
        palette, data = _palette_and_data(section)
        sec = _SectionData(palette, data, self._stretch, legacy)
        self.sections[section_y] = sec
        return sec

    def block_id_at(self, x: int, y: int, z: int) -> Optional[str]:
        if not (0 <= x < 16 and 0 <= z < 16):
            return None
        section_y = y // 16
        sec = self._ensure_section(section_y)
        if sec is None:
            return "minecraft:air"

        if sec.legacy_blocks is not None:
            local_y = y - section_y * 16
            index = local_y * 256 + z * 16 + x
            try:
                return f"legacy:{sec.legacy_blocks[index]}"
            except Exception:
                return "minecraft:air"

        if not sec.palette:
            return "minecraft:air"
        if len(sec.palette) == 1 or sec.data is None:
            return sec.palette[0]

        local_y = y - section_y * 16
        index = local_y * 256 + z * 16 + x
        try:
            pi = _palette_index(sec.data, index, sec.bits, stretch=sec.stretch)
        except Exception:
            return sec.palette[0]
        if 0 <= pi < len(sec.palette):
            return sec.palette[pi]
        return "minecraft:air"

    def get_palette_names(self, section_y: int) -> Optional[List[str]]:
        sec = self._ensure_section(int(section_y))
        if sec is None or not sec.palette:
            return None
        return list(sec.palette)

    def surface_y(self, x: int, z: int) -> Optional[int]:
        if self.heightmap is not None:
            index = z * 16 + x
            try:
                value = int(self.heightmap[index])
            except Exception:
                value = 0
            y = heightmap_value_to_block_y(value, self.version)
            if y is not None:
                return y
        return self.scan_surface_y(x, z)

    def scan_surface_y(self, x: int, z: int) -> Optional[int]:
        for section_y in self.section_ys_desc:
            sec = self._ensure_section(section_y)
            if sec is None:
                continue
            if not sec.palette and sec.legacy_blocks is None:
                continue
            if sec.palette and all(is_air_name(n) for n in sec.palette):
                continue
            y0 = section_y * 16
            for y in range(y0 + 15, y0 - 1, -1):
                name = self.block_id_at(x, y, z)
                if not is_air_name(name):
                    return y
        return None

    def surface_block_id(self, x: int, z: int) -> Optional[str]:
        y = self.surface_y(x, z)
        if y is None:
            return None
        for dy in range(0, 4):
            name = self.block_id_at(x, y - dy, z)
            if not is_air_name(name):
                return name
        return self.block_id_at(x, y, z)


def get_chunk_blocks(chunk_nbt: Any) -> ChunkBlocks:
    # NBT objects are mutable; an id-based cache can return stale block states
    # after an editor changes palette/data in place.
    return ChunkBlocks(chunk_nbt)


def block_id_at(chunk_nbt: Any, x: int, y: int, z: int) -> Optional[str]:
    return get_chunk_blocks(chunk_nbt).block_id_at(x, y, z)


def scan_surface_y(chunk_nbt: Any, x: int, z: int) -> Optional[int]:
    return get_chunk_blocks(chunk_nbt).scan_surface_y(x, z)


def surface_block_id(chunk_nbt: Any, x: int, z: int) -> Optional[str]:
    return get_chunk_blocks(chunk_nbt).surface_block_id(x, z)
