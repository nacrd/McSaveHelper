"""Tests for section palette block_id_at."""
from __future__ import annotations

import nbtlib

from core.mca.block_palette import block_id_at, is_air_name, surface_block_id


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
