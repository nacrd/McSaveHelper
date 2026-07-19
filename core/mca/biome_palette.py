"""Modern Minecraft section-biome palette decoding.

Minecraft stores biomes in a paletted container with four-block resolution in
each axis.  A section therefore contains 4 * 4 * 4 entries, packed in the
same low-bit-first layout used by ``SimpleBitStorage``.  This module keeps the
decoder independent from block-state palettes so callers can use it without
changing the established block parsing rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.mca.nbt_access import (
    as_int,
    as_str,
    chunk_root_and_version,
    first_key,
    is_mapping,
    iter_sequence,
    long_array_values,
)

_BIOME_EDGE = 4
_BIOME_ENTRY_COUNT = _BIOME_EDGE ** 3


def _palette_name(entry: Any) -> str:
    """Read a biome resource id from a palette entry.

    Vanilla writes strings, while a few converters and older tools emit a
    compound containing ``Name``/``name``.  Preserve the resource id as-is
    apart from surrounding whitespace; matching code can then handle modded
    namespaces without losing information.
    """
    if is_mapping(entry):
        value = first_key(entry, "Name", "name", "Id", "id", "biome")
        return as_str(value).strip() if value is not None else ""
    return as_str(entry).strip()


def _section_y(section: Any) -> Optional[int]:
    value = as_int(first_key(section, "Y", "y"))
    if value is None:
        return None
    # NBT Byte tags are normally already signed, but plain JSON-like test
    # trees may carry the equivalent unsigned byte.
    return value - 256 if value > 127 else value


def _biome_container(section_or_container: Any) -> Any:
    """Return a section's biome compound, accepting the compound itself."""
    if not is_mapping(section_or_container):
        return None
    if first_key(section_or_container, "palette", "Palette") is not None:
        return section_or_container
    return first_key(section_or_container, "biomes", "Biomes")


def _bits_for_palette(palette_size: int) -> int:
    if palette_size <= 1:
        return 0
    return max(1, (palette_size - 1).bit_length())


def _compact_word_count(bits: int) -> int:
    if bits <= 0:
        return 0
    values_per_long = 64 // bits
    if values_per_long <= 0:
        return 0
    return ceil(_BIOME_ENTRY_COUNT / values_per_long)


def _stretched_word_count(bits: int) -> int:
    if bits <= 0:
        return 0
    return ceil(_BIOME_ENTRY_COUNT * bits / 64)


def _read_packed_index(
    words: Sequence[int],
    index: int,
    bits: int,
    *,
    stretched: bool,
) -> int:
    """Read one low-bit-first palette index.

    Vanilla's biome storage uses the compact layout.  The stretched variant
    is accepted as a compatibility path for hand-authored NBT and older
    converters whose packed values are allowed to cross a long boundary.
    """
    if bits <= 0 or index < 0 or index >= _BIOME_ENTRY_COUNT:
        return 0
    mask = (1 << bits) - 1
    if not stretched:
        values_per_long = 64 // bits
        if values_per_long <= 0:
            return 0
        word_index = index // values_per_long
        if word_index >= len(words):
            return 0
        offset = (index % values_per_long) * bits
        return (int(words[word_index]) >> offset) & mask

    bit_index = index * bits
    word_index = bit_index // 64
    offset = bit_index % 64
    if word_index >= len(words):
        return 0
    word = int(words[word_index])
    if offset + bits <= 64:
        return (word >> offset) & mask
    low_bits = 64 - offset
    value = word >> offset
    if word_index + 1 >= len(words):
        return value & mask
    high = int(words[word_index + 1])
    value |= (high & ((1 << (bits - low_bits)) - 1)) << low_bits
    return value & mask


@dataclass(frozen=True)
class BiomeSection:
    """One section's 4x4x4 biome palette and packed storage."""

    palette: Tuple[str, ...]
    data: Optional[Tuple[int, ...]] = None
    bits: int = 0
    stretched: bool = False

    def biome_at(self, local_x: int, local_y: int, local_z: int) -> Optional[str]:
        """Return the biome at section-local block coordinates."""
        if not (0 <= local_x < 16 and 0 <= local_y < 16 and 0 <= local_z < 16):
            return None
        if not self.palette:
            return None
        if len(self.palette) == 1 or not self.data or self.bits <= 0:
            return self.palette[0]

        quad_x = local_x >> 2
        quad_y = local_y >> 2
        quad_z = local_z >> 2
        index = (quad_y << 4) | (quad_z << 2) | quad_x
        palette_index = _read_packed_index(
            self.data,
            index,
            self.bits,
            stretched=self.stretched,
        )
        if 0 <= palette_index < len(self.palette):
            return self.palette[palette_index] or None
        # Xaero falls back to the first palette entry for malformed storage.
        return self.palette[0] or None

    def get(self, quad_x: int, section_quad_y: int, quad_z: int) -> Optional[str]:
        """Xaero-compatible lookup using 4x4x4 coordinates."""
        if not (
            0 <= quad_x < 4
            and 0 <= section_quad_y < 4
            and 0 <= quad_z < 4
        ):
            return None
        return self.biome_at(quad_x << 2, section_quad_y << 2, quad_z << 2)


def decode_biome_section(section_or_container: Any) -> Optional[BiomeSection]:
    """Decode a section or biome compound into :class:`BiomeSection`.

    Empty/malformed containers return ``None``.  A palette with no data is a
    valid constant section and is represented with ``data=None``.
    """
    container = _biome_container(section_or_container)
    if not is_mapping(container):
        return None
    palette_tag = first_key(container, "palette", "Palette")
    palette = tuple(_palette_name(item) for item in iter_sequence(palette_tag))
    if not palette or not any(palette):
        return None

    data_tag = first_key(container, "data", "Data")
    data_values = tuple(long_array_values(data_tag)) if data_tag is not None else None
    bits = _bits_for_palette(len(palette))
    if bits <= 0 or not data_values:
        return BiomeSection(palette=palette)

    # SimpleBitStorage (the format used by current Minecraft) packs complete
    # values into each long.  Accept the crossing-boundary representation when
    # the supplied word count proves that it is the intended layout.
    compact_count = _compact_word_count(bits)
    stretched_count = _stretched_word_count(bits)
    stretched = (
        len(data_values) == stretched_count
        and stretched_count < compact_count
    )
    return BiomeSection(
        palette=palette,
        data=data_values,
        bits=bits,
        stretched=stretched,
    )


# Descriptive alias used by callers that think in terms of parsing rather
# than decoding; keeping both names also makes the pure API easy to discover.
parse_biome_section = decode_biome_section


class ChunkBiomes:
    """Lazy section lookup for a chunk's modern biome containers."""

    __slots__ = (
        "root",
        "version",
        "_section_raw",
        "_sections",
        "_legacy_values",
    )

    def __init__(self, chunk_nbt: Any) -> None:
        self.root, self.version = chunk_root_and_version(chunk_nbt)
        self._section_raw: Dict[int, Any] = {}
        self._sections: Dict[int, Optional[BiomeSection]] = {}
        self._legacy_values: Optional[List[Any]] = None
        if self.root is None:
            return

        sections = first_key(self.root, "sections", "Sections")
        for section in iter_sequence(sections):
            if not is_mapping(section):
                continue
            section_y = _section_y(section)
            if section_y is not None:
                self._section_raw[section_y] = section

        # Pre-1.18 chunks may carry one biome id per x/z column.  Numeric
        # registry ids cannot be resolved without a version-specific registry,
        # but string lists emitted by converters remain useful.
        legacy = first_key(self.root, "Biomes", "biomes")
        if legacy is not None:
            values = iter_sequence(legacy)
            if values:
                self._legacy_values = values

    def _section(self, section_y: int) -> Optional[BiomeSection]:
        if section_y not in self._sections:
            raw = self._section_raw.get(section_y)
            self._sections[section_y] = decode_biome_section(raw)
        return self._sections[section_y]

    def biome_at(self, local_x: int, world_y: int, local_z: int) -> Optional[str]:
        """Return a biome resource id at chunk-local x/z and world y."""
        if not (0 <= local_x < 16 and 0 <= local_z < 16):
            return None
        section_y = world_y // 16
        section = self._section(section_y)
        if section is not None:
            section_local_y = world_y - section_y * 16
            return section.biome_at(local_x, section_local_y, local_z)
        return self._legacy_biome_at(local_x, local_z)

    def get(self, local_x: int, world_y: int, local_z: int) -> Optional[str]:
        """Alias matching the point-reader style used by map renderers."""
        return self.biome_at(local_x, world_y, local_z)

    def _legacy_biome_at(self, local_x: int, local_z: int) -> Optional[str]:
        values = self._legacy_values
        if not values:
            return None
        index = local_z * 16 + local_x
        if index >= len(values):
            return None
        name = _palette_name(values[index])
        return name or None


def get_chunk_biomes(chunk_nbt: Any) -> ChunkBiomes:
    """Create a lazy biome view for a decoded chunk NBT tree."""
    return ChunkBiomes(chunk_nbt)


def biome_at(chunk_nbt: Any, local_x: int, world_y: int, local_z: int) -> Optional[str]:
    """Convenience point lookup for callers that do not need a view object."""
    return ChunkBiomes(chunk_nbt).biome_at(local_x, world_y, local_z)


__all__ = [
    "BiomeSection",
    "ChunkBiomes",
    "biome_at",
    "decode_biome_section",
    "get_chunk_biomes",
    "parse_biome_section",
]
