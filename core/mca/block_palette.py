"""Section palette + bit-packed block state access with lazy section parse."""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.mca.heightmaps import (
    DEFAULT_HEIGHTMAP_NAMES,
    WORLD_SURFACE_HEIGHTMAP_NAMES,
    decode_heightmap_raw,
    heightmap_value_to_block_y,
)
from core.mca.biome_palette import ChunkBiomes
from core.mca.nbt_access import (
    as_str,
    chunk_root_and_version,
    first_key,
    is_mapping,
    iter_sequence,
    long_array_values,
    section_y as _section_y,
    tag_value,
)
from core.mca.versions import DATA_VERSION_1_13

_AIR_NAMES = frozenset({
    "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
    "air", "cave_air", "void_air",
})
_AIR_BLOCK_ID = "minecraft:air"
_SECTION_BLOCK_COUNT = 16 * 16 * 16

_TRANSPARENT_SURFACE_EXACT = frozenset(
    {
        "grass",
        "short_grass",
        "tall_grass",
        "fern",
        "large_fern",
        "dead_bush",
        "vine",
        "lily_pad",
        "seagrass",
        "tall_seagrass",
        "kelp",
        "kelp_plant",
        "bamboo",
        "bamboo_sapling",
        "moss_carpet",
        "snow",
        "leaf_litter",
        "sugar_cane",
        "sweet_berry_bush",
        "allium",
        "azure_bluet",
        "blue_orchid",
        "closed_eyeblossom",
        "cornflower",
        "dandelion",
        "flowering_azalea",
        "lilac",
        "lily_of_the_valley",
        "open_eyeblossom",
        "orange_tulip",
        "oxeye_daisy",
        "peony",
        "pink_petals",
        "pink_tulip",
        "poppy",
        "red_tulip",
        "rose_bush",
        "sunflower",
        "torchflower",
        "white_tulip",
        "wither_rose",
        "wildflowers",
        "firefly_bush",
        "bush",
        "wheat",
        "carrots",
        "potatoes",
        "beetroots",
    }
)


@lru_cache(maxsize=512)
def is_transparent_surface_name(name: Optional[str]) -> bool:
    """Return whether a top block should reveal an underlying surface.

    This is intentionally a conservative material classifier rather than a
    full block-model implementation.  It covers common foliage/decorations
    that otherwise make ``WORLD_SURFACE`` maps look like isolated noise while
    leaving fluids, glass and ice as visible primary map materials.
    """
    if not name:
        return False
    path = name.strip().lower().rsplit(":", 1)[-1]
    if path in _TRANSPARENT_SURFACE_EXACT:
        return True
    if "leaves" in path or path.endswith("_leaf"):
        return True
    if path.endswith("_flower") or path.endswith("_flowers"):
        return True
    if path.endswith("_sapling") or path.endswith("_plant"):
        return True
    return path in {
        "cave_vines",
        "twisting_vines",
        "weeping_vines",
        "nether_sprouts",
        "warped_roots",
        "crimson_roots",
    }


@lru_cache(maxsize=512)
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


def _count_legacy_blocks(legacy_blocks: List[int]) -> Counter[str]:
    """Count one legacy section, padding a short Blocks array with air."""
    counter: Counter[str] = Counter()
    try:
        valid_count = min(len(legacy_blocks), _SECTION_BLOCK_COUNT)
    except Exception:
        valid_count = 0
    for index in range(valid_count):
        try:
            block_id = f"legacy:{legacy_blocks[index]}"
        except Exception:
            block_id = _AIR_BLOCK_ID
        counter[block_id] += 1
    missing_count = _SECTION_BLOCK_COUNT - valid_count
    if missing_count:
        counter[_AIR_BLOCK_ID] += missing_count
    return counter


def _count_compact_palette_indices(
    words: List[int],
    bits: int,
    palette_len: int,
) -> Tuple[List[int], int]:
    counts = [0] * palette_len
    invalid = 0
    decoded = 0
    mask = (1 << bits) - 1
    values_per_long = 64 // bits
    if values_per_long <= 0:
        counts[0] = _SECTION_BLOCK_COUNT
        return counts, invalid
    for word in words:
        take = min(values_per_long, _SECTION_BLOCK_COUNT - decoded)
        for _ in range(take):
            palette_index = word & mask
            if palette_index < palette_len:
                counts[palette_index] += 1
            else:
                invalid += 1
            word >>= bits
        decoded += take
        if decoded >= _SECTION_BLOCK_COUNT:
            break
    counts[0] += _SECTION_BLOCK_COUNT - decoded
    return counts, invalid


def _count_stretched_palette_indices(
    words: List[int],
    bits: int,
    palette_len: int,
) -> Tuple[List[int], int]:
    counts = [0] * palette_len
    invalid = 0
    decoded = 0
    mask = (1 << bits) - 1
    buffer = 0
    available = 0
    for word in words:
        buffer |= word << available
        available += 64
        while available >= bits and decoded < _SECTION_BLOCK_COUNT:
            palette_index = buffer & mask
            if palette_index < palette_len:
                counts[palette_index] += 1
            else:
                invalid += 1
            buffer >>= bits
            available -= bits
            decoded += 1
        if decoded >= _SECTION_BLOCK_COUNT:
            break
    # The point reader preserves low bits when a stretched value crosses past
    # a truncated final long, treating only the missing high bits as zero.
    if decoded < _SECTION_BLOCK_COUNT and available > 0:
        palette_index = buffer & mask
        if palette_index < palette_len:
            counts[palette_index] += 1
        else:
            invalid += 1
        decoded += 1
    counts[0] += _SECTION_BLOCK_COUNT - decoded
    return counts, invalid


def _count_packed_blocks(section: _SectionData) -> Counter[str]:
    """Count packed entries while retaining point-read fallback behavior."""
    data = section.data
    assert data is not None
    palette = section.palette
    palette_len = len(palette)
    try:
        words = [int(word) & ((1 << 64) - 1) for word in data]
    except Exception:
        words = []

    if not words or section.bits <= 0:
        counts = [_SECTION_BLOCK_COUNT] + [0] * (palette_len - 1)
        invalid = 0
    elif section.stretch:
        counts, invalid = _count_stretched_palette_indices(
            words,
            section.bits,
            palette_len,
        )
    else:
        counts, invalid = _count_compact_palette_indices(
            words,
            section.bits,
            palette_len,
        )

    counter: Counter[str] = Counter()
    for palette_index, count in enumerate(counts):
        if count:
            counter[palette[palette_index]] += count
    if invalid:
        counter[_AIR_BLOCK_ID] += invalid
    return counter


def _count_section_block_ids(section: _SectionData) -> Counter[str]:
    """Count one parsed section using ``block_id_at``'s established rules."""
    if section.legacy_blocks is not None:
        return _count_legacy_blocks(section.legacy_blocks)

    palette = section.palette
    if not palette:
        return Counter({_AIR_BLOCK_ID: _SECTION_BLOCK_COUNT})
    if len(palette) == 1 or section.data is None:
        return Counter({palette[0]: _SECTION_BLOCK_COUNT})
    return _count_packed_blocks(section)


class ChunkBlocks:
    """Parsed chunk view with lazy section decoding for topview speed."""

    __slots__ = (
        "root", "version", "sections", "heightmap", "section_ys_desc",
        "_section_raw", "_stretch", "_legacy", "_biomes",
    )

    def __init__(
        self,
        chunk_nbt: Any,
        *,
        heightmap_names: Sequence[str] = DEFAULT_HEIGHTMAP_NAMES,
    ) -> None:
        self.root, self.version = chunk_root_and_version(chunk_nbt)
        self.sections: Dict[int, _SectionData] = {}
        self.heightmap: Optional[List[int]] = None
        self.section_ys_desc: List[int] = []
        self._section_raw: Dict[int, Any] = {}
        self._stretch = False
        self._legacy = False
        self._biomes: Optional[ChunkBiomes] = None
        if self.root is None:
            return

        hm, ver = decode_heightmap_raw(
            chunk_nbt,
            heightmap_names=heightmap_names,
        )
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
        if not _is_local_column(x, z):
            return None
        section_y = y // 16
        sec = self._ensure_section(section_y)
        if sec is None:
            return "minecraft:air"
        if sec.legacy_blocks is not None:
            return _legacy_block_id(sec.legacy_blocks, x, y, z, section_y)
        return _palette_block_id(sec, x, y, z, section_y)

    def count_block_ids(self) -> Counter[str]:
        """Count block IDs in every stored section.

        The result intentionally includes air entries.  Callers that report
        placed blocks can filter them afterwards, while this method remains
        equivalent to querying ``block_id_at`` for all 4096 positions in each
        section.  Packed data is decoded through the same helper as point
        reads so truncated or out-of-range values retain their established
        fallback behavior.
        """
        counter: Counter[str] = Counter()
        for section_y in self.section_ys_desc:
            sec = self._ensure_section(section_y)
            if sec is None:
                continue
            counter.update(_count_section_block_ids(sec))
        return counter

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
        name, _y = self.surface_sample(x, z)
        return name

    def biome_at(self, x: int, y: int, z: int) -> Optional[str]:
        """Return the modern 4x4x4 biome sample at one block position."""
        if self._biomes is None:
            self._biomes = ChunkBiomes(self.root)
        return self._biomes.biome_at(x, y, z)

    def surface_strata(
        self,
        x: int,
        z: int,
        max_depth: int = 8,
    ) -> Tuple[Tuple[str, int], ...]:
        """Return transparent top layers followed by the visible base.

        The first entry is the heightmap surface.  Scanning stops after the
        first material that should not be alpha-composited, so callers retain
        leaves/plants without letting them replace the terrain underneath.
        """
        y = self.surface_y(x, z)
        if y is None:
            return ()
        strata: List[Tuple[str, int]] = []
        for depth in range(max(0, int(max_depth)) + 1):
            sample_y = y - depth
            name = self.block_id_at(x, sample_y, z)
            if is_air_name(name):
                continue
            assert name is not None
            strata.append((name, sample_y))
            if not is_transparent_surface_name(name):
                break
        return tuple(strata)

    def surface_sample(
        self,
        x: int,
        z: int,
    ) -> Tuple[Optional[str], Optional[int]]:
        """Return the top non-air surface block and its world height.

        Reuses :meth:`surface_strata` for the non-air walk.  All-air columns
        still report the heightmap top (matching the previous scan fallback).
        """
        strata = self.surface_strata(x, z)
        if strata:
            return strata[0]
        y = self.surface_y(x, z)
        if y is None:
            return None, None
        return self.block_id_at(x, y, z), y


def _is_local_column(x: int, z: int) -> bool:
    return 0 <= x < 16 and 0 <= z < 16


def _block_index(x: int, y: int, z: int, section_y: int) -> int:
    return (y - section_y * 16) * 256 + z * 16 + x


def _legacy_block_id(
    legacy_blocks: List[int], x: int, y: int, z: int, section_y: int
) -> str:
    try:
        return f"legacy:{legacy_blocks[_block_index(x, y, z, section_y)]}"
    except (IndexError, TypeError):
        return _AIR_BLOCK_ID


def _palette_block_id(
    section: _SectionData, x: int, y: int, z: int, section_y: int
) -> str:
    if not section.palette:
        return _AIR_BLOCK_ID
    if len(section.palette) == 1 or section.data is None:
        return section.palette[0]
    palette_index = _read_palette_index(section, x, y, z, section_y)
    if palette_index is None:
        return section.palette[0]
    if 0 <= palette_index < len(section.palette):
        return section.palette[palette_index]
    return _AIR_BLOCK_ID


def _read_palette_index(
    section: _SectionData, x: int, y: int, z: int, section_y: int
) -> Optional[int]:
    data = section.data
    if data is None:
        return None
    try:
        return _palette_index(
            data,
            _block_index(x, y, z, section_y),
            section.bits,
            stretch=section.stretch,
        )
    except (IndexError, TypeError, ValueError, OverflowError):
        return None


def get_chunk_blocks(
    chunk_nbt: Any,
    *,
    heightmap_names: Sequence[str] = DEFAULT_HEIGHTMAP_NAMES,
) -> ChunkBlocks:
    # NBT objects are mutable; an id-based cache can return stale block states
    # after an editor changes palette/data in place.
    return ChunkBlocks(chunk_nbt, heightmap_names=heightmap_names)


def get_world_surface_chunk_blocks(chunk_nbt: Any) -> ChunkBlocks:
    """Build a chunk view using the visible-world heightmap for map tiles."""
    return get_chunk_blocks(
        chunk_nbt,
        heightmap_names=WORLD_SURFACE_HEIGHTMAP_NAMES,
    )


def block_id_at(chunk_nbt: Any, x: int, y: int, z: int) -> Optional[str]:
    return get_chunk_blocks(chunk_nbt).block_id_at(x, y, z)


def surface_block_id(chunk_nbt: Any, x: int, z: int) -> Optional[str]:
    return get_chunk_blocks(chunk_nbt).surface_block_id(x, z)
