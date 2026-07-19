"""Tests for section palette block_id_at."""
from __future__ import annotations

from collections import Counter

import nbtlib

from core.mca.block_palette import (
    ChunkBlocks,
    block_id_at,
    get_world_surface_chunk_blocks,
    is_air_name,
    surface_block_id,
)


def _pack_heightmap(values, bits=9):
    values_per_long = 64 // bits
    remaining = list(values)
    packed = []
    while remaining:
        word = 0
        for i in range(min(values_per_long, len(remaining))):
            word |= (remaining.pop(0) & ((1 << bits) - 1)) << (i * bits)
        packed.append(word)
    return packed


def _single_block_section(section_y, name):
    return nbtlib.Compound({
        "Y": nbtlib.Byte(section_y),
        "block_states": nbtlib.Compound({
            "palette": nbtlib.List[nbtlib.Compound]([
                nbtlib.Compound({"Name": nbtlib.String(name)}),
            ]),
        }),
    })


def _palette_section(section_y, names, data=None):
    palette = nbtlib.List[nbtlib.Compound]([
        nbtlib.Compound({"Name": nbtlib.String(name)})
        for name in names
    ])
    if data is None:
        block_states = nbtlib.Compound({"palette": palette})
    else:
        block_states = nbtlib.Compound({
            "palette": palette,
            "data": nbtlib.LongArray(data),
        })
    return nbtlib.Compound({
        "Y": nbtlib.Byte(section_y),
        "block_states": block_states,
    })


def _pack_indices(indices, bits, stretch):
    """Pack palette indices using the two layouts supported by block_palette."""
    words = [0] * (
        (4096 + (64 // bits) - 1) // (64 // bits)
        if not stretch
        else (4096 * bits + 63) // 64
    )
    mask = (1 << bits) - 1
    for index, value in enumerate(indices):
        value &= mask
        if not stretch:
            values_per_long = 64 // bits
            long_index = index // values_per_long
            bit_offset = (index % values_per_long) * bits
            words[long_index] |= value << bit_offset
            continue
        bit_index = index * bits
        long_index = bit_index // 64
        bit_offset = bit_index % 64
        words[long_index] |= (value << bit_offset) & ((1 << 64) - 1)
        if bit_offset + bits > 64:
            words[long_index + 1] |= value >> (64 - bit_offset)

    # nbtlib LongArray stores signed 64-bit values; the reader normalizes
    # negative entries back to their unsigned representation.
    return [word if word < (1 << 63) else word - (1 << 64) for word in words]


def _point_counts(blocks: ChunkBlocks) -> Counter[str]:
    expected: Counter[str] = Counter()
    for section_y in blocks.section_ys_desc:
        y_base = section_y * 16
        for local_y in range(16):
            for z in range(16):
                for x in range(16):
                    block_id = blocks.block_id_at(x, y_base + local_y, z)
                    if block_id is not None:
                        expected[block_id] += 1
    return expected


def test_is_air_name() -> None:
    assert is_air_name("minecraft:air")
    assert is_air_name("minecraft:cave_air")
    assert not is_air_name("minecraft:stone")


def test_block_id_single_palette() -> None:
    chunk = nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "xPos": nbtlib.Int(0),
        "zPos": nbtlib.Int(0),
        "sections": nbtlib.List[nbtlib.Compound]([
            _single_block_section(4, "minecraft:stone"),
        ]),
        "Heightmaps": nbtlib.Compound({
            "MOTION_BLOCKING": nbtlib.LongArray(_pack_heightmap([129] * 256)),
        }),
    })
    assert block_id_at(chunk, 0, 64, 0) == "minecraft:stone"
    assert block_id_at(chunk, 0, 0, 0) == "minecraft:air"
    assert surface_block_id(chunk, 0, 0) == "minecraft:stone"


def test_world_surface_chunk_view_uses_world_surface_without_changing_default() -> None:
    chunk = nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "sections": nbtlib.List[nbtlib.Compound]([
            _single_block_section(4, "minecraft:stone"),
            _single_block_section(5, "minecraft:oak_leaves"),
        ]),
        "Heightmaps": nbtlib.Compound({
            "MOTION_BLOCKING": nbtlib.LongArray(_pack_heightmap([129] * 256)),
            "WORLD_SURFACE": nbtlib.LongArray(_pack_heightmap([145] * 256)),
        }),
    })

    assert ChunkBlocks(chunk).surface_sample(0, 0) == ("minecraft:stone", 64)
    assert get_world_surface_chunk_blocks(chunk).surface_sample(0, 0) == (
        "minecraft:oak_leaves",
        80,
    )


def test_block_id_multi_palette_compact() -> None:
    palette = nbtlib.List[nbtlib.Compound]([
        nbtlib.Compound({"Name": nbtlib.String("minecraft:air")}),
        nbtlib.Compound({"Name": nbtlib.String("minecraft:dirt")}),
    ])
    word = 0 | (1 << 4)
    data = [0] * 256
    data[0] = word
    section = nbtlib.Compound({
        "Y": nbtlib.Byte(0),
        "block_states": nbtlib.Compound({
            "palette": palette,
            "data": nbtlib.LongArray(data),
        }),
    })
    chunk = nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "sections": nbtlib.List[nbtlib.Compound]([section]),
    })
    assert block_id_at(chunk, 0, 0, 0) == "minecraft:air"
    assert block_id_at(chunk, 1, 0, 0) == "minecraft:dirt"


def test_count_block_ids_matches_point_reads_for_single_and_compact_palette() -> None:
    data = [0] * 256
    data[0] = 1 | (2 << 4)
    chunk = nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "sections": nbtlib.List[nbtlib.Compound]([
            _single_block_section(1, "minecraft:stone"),
            _palette_section(0, ["minecraft:air", "minecraft:dirt", "minecraft:gold_block"], data),
        ]),
    })

    blocks = ChunkBlocks(chunk)

    assert blocks.count_block_ids() == _point_counts(blocks)
    assert blocks.count_block_ids()["minecraft:stone"] == 4096


def test_count_block_ids_matches_stretch_packed_values_across_long_boundary() -> None:
    # Seventeen entries require five bits.  Index 12 starts at bit 60 and
    # therefore crosses a long boundary in the stretch layout.
    indices = [0] * 4096
    indices[12] = 1
    indices[13] = 2
    names = [f"minecraft:test_{index}" for index in range(17)]
    chunk = nbtlib.File({
        "DataVersion": nbtlib.Int(2200),
        "sections": nbtlib.List[nbtlib.Compound]([
            _palette_section(0, names, _pack_indices(indices, bits=5, stretch=True)),
        ]),
    })

    blocks = ChunkBlocks(chunk)

    assert blocks.count_block_ids() == _point_counts(blocks)
    assert blocks.count_block_ids()[names[1]] == 1
    assert blocks.count_block_ids()[names[2]] == 1


def test_count_block_ids_preserves_legacy_and_missing_data_fallbacks() -> None:
    legacy = nbtlib.Compound({
        "Y": nbtlib.Byte(0),
        "Blocks": nbtlib.ByteArray([1, 2]),
    })
    missing_data = _palette_section(
        1,
        ["minecraft:stone", "minecraft:dirt"],
    )
    chunk = nbtlib.File({
        "DataVersion": nbtlib.Int(1343),
        "sections": nbtlib.List[nbtlib.Compound]([legacy, missing_data]),
    })

    blocks = ChunkBlocks(chunk)
    counts = blocks.count_block_ids()

    assert counts == _point_counts(blocks)
    assert counts["legacy:1"] == 1
    assert counts["legacy:2"] == 1
    assert counts["minecraft:stone"] == 4096
    assert counts["minecraft:air"] == 4094


def test_count_block_ids_treats_out_of_range_packed_indices_as_air() -> None:
    # Palette size two uses four bits; 0xF is outside the palette.
    data = [-1] + [0] * 255
    chunk = nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "sections": nbtlib.List[nbtlib.Compound]([
            _palette_section(0, ["minecraft:stone", "minecraft:dirt"], data),
        ]),
    })

    blocks = ChunkBlocks(chunk)
    counts = blocks.count_block_ids()

    assert counts == _point_counts(blocks)
    assert counts["minecraft:air"] == 16
    assert counts["minecraft:stone"] == 4080
