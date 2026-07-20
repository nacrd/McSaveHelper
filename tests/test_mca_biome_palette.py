"""Pure tests for modern 4x4x4 section biome decoding."""
from __future__ import annotations

import core.nbt as nbtlib

from core.mca.biome_palette import (
    ChunkBiomes,
    decode_biome_section,
)


def _pack_compact(values: list[int], bits: int) -> list[int]:
    values_per_long = 64 // bits
    words = [0] * ((len(values) + values_per_long - 1) // values_per_long)
    mask = (1 << bits) - 1
    for index, value in enumerate(values):
        word_index = index // values_per_long
        offset = (index % values_per_long) * bits
        words[word_index] |= (value & mask) << offset
    return [word if word < (1 << 63) else word - (1 << 64) for word in words]


def _pack_stretched(values: list[int], bits: int) -> list[int]:
    words = [0] * ((len(values) * bits + 63) // 64)
    mask = (1 << 64) - 1
    for index, value in enumerate(values):
        bit_index = index * bits
        word_index = bit_index // 64
        offset = bit_index % 64
        words[word_index] |= (value << offset) & mask
        if offset + bits > 64:
            words[word_index + 1] |= value >> (64 - offset)
    return [word if word < (1 << 63) else word - (1 << 64) for word in words]


def _section(palette: list[str], data: list[int] | None = None, y: int = 0):
    biome = nbtlib.Compound({
        "palette": nbtlib.List[nbtlib.String]([nbtlib.String(name) for name in palette]),
    })
    if data is not None:
        biome["data"] = nbtlib.LongArray(data)
    return nbtlib.Compound({"Y": nbtlib.Byte(y), "biomes": biome})


def test_constant_palette_reads_world_y_in_negative_section() -> None:
    chunk = nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "sections": nbtlib.List[nbtlib.Compound]([
            _section(["minecraft:snowy_plains"], y=-4),
        ]),
    })

    view = ChunkBiomes(chunk)

    assert view.biome_at(0, -64, 0) == "minecraft:snowy_plains"
    assert view.biome_at(15, -49, 15) == "minecraft:snowy_plains"


def test_packed_index_follows_xaero_qy_qz_qx_order() -> None:
    values = [0] * 64
    # qx=1, qy=2, qz=3 -> index 45.
    values[(2 << 4) | (3 << 2) | 1] = 1
    data = _pack_compact(values, bits=1)
    section = _section(["minecraft:plains", "minecraft:forest"], data)
    decoded = decode_biome_section(section)
    assert decoded is not None

    assert decoded.biome_at(4, 8, 12) == "minecraft:forest"
    assert decoded.biome_at(0, 0, 0) == "minecraft:plains"


def test_three_bit_palette_uses_compact_storage_and_signed_longs() -> None:
    values = [0] * 64
    values[21] = 4
    values[63] = 3
    data = _pack_compact(values, bits=3)
    decoded = decode_biome_section(
        _section(
            [
                "minecraft:plains",
                "minecraft:forest",
                "minecraft:desert",
                "minecraft:taiga",
                "minecraft:jungle",
            ],
            data,
        )
    )
    assert decoded is not None
    assert decoded.biome_at(4, 4, 4) == "minecraft:jungle"
    assert decoded.biome_at(12, 12, 12) == "minecraft:taiga"


def test_stretched_compatibility_layout_is_accepted() -> None:
    values = [0] * 64
    values[21] = 4
    decoded = decode_biome_section(
        _section(
            [
                "minecraft:plains",
                "minecraft:forest",
                "minecraft:desert",
                "minecraft:taiga",
                "minecraft:jungle",
            ],
            _pack_stretched(values, bits=3),
        )
    )
    assert decoded is not None
    assert decoded.biome_at(4, 4, 4) == "minecraft:jungle"


def test_legacy_string_column_biomes_remain_readable() -> None:
    values = [nbtlib.String("minecraft:plains")] * 256
    values[7 * 16 + 3] = nbtlib.String("minecraft:desert")
    chunk = nbtlib.File({"Biomes": nbtlib.List[nbtlib.String](values)})

    assert ChunkBiomes(chunk).biome_at(3, 70, 7) == "minecraft:desert"


def test_invalid_palette_index_falls_back_to_first_entry() -> None:
    values = [3] + [0] * 63
    decoded = decode_biome_section(
        _section(
            ["minecraft:plains", "minecraft:forest", "minecraft:desert"],
            _pack_compact(values, bits=2),
        )
    )
    assert decoded is not None
    assert decoded.biome_at(0, 0, 0) == "minecraft:plains"
