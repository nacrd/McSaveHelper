"""Tests for section palette block_id_at."""
from __future__ import annotations

import nbtlib

from core.mca.block_palette import block_id_at, is_air_name, surface_block_id


def _single_block_section(section_y: int, name: str) -> nbtlib.Compound:
    return nbtlib.Compound({
        "Y": nbtlib.Byte(section_y),
        "block_states": nbtlib.Compound({
            "palette": nbtlib.List[nbtlib.Compound]([
                nbtlib.Compound({"Name": nbtlib.String(name)}),
            ]),
            # no data → entire section is palette[0]
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
            _single_block_section(4, "minecraft:stone"),  # y 64..79
        ]),
        "Heightmaps": nbtlib.Compound({
            # value 65 → surface y 64
            "WORLD_SURFACE": nbtlib.LongArray(
                _pack_heightmap([65] * 256)
            ),
        }),
    })
    assert block_id_at(chunk, 0, 64, 0) == "minecraft:stone"
    assert block_id_at(chunk, 0, 0, 0) == "minecraft:air"  # missing section
    assert surface_block_id(chunk, 0, 0) == "minecraft:stone"


def _pack_heightmap(values: list[int], bits: int = 9) -> list[int]:
    values_per_long = 64 // bits
    remaining = list(values)
    packed: list[int] = []
    while remaining:
        word = 0
        for i in range(min(values_per_long, len(remaining))):
            word |= (remaining.pop(0) & ((1 << bits) - 1)) << (i * bits)
        packed.append(word)
    return packed


def test_block_id_multi_palette_compact() -> None:
    # 2-entry palette needs 4 bits min; non-stretch packing
    palette = nbtlib.List[nbtlib.Compound]([
        nbtlib.Compound({"Name": nbtlib.String("minecraft:air")}),
        nbtlib.Compound({"Name": nbtlib.String("minecraft:dirt")}),
    ])
    # index for (x=0,y_local=0,z=0) = 0 → air
    # index for (x=1,y_local=0,z=0) = 1 → dirt
    # bits=4, values_per_long=16
    # pack: low nibble 0, next nibble 1
    word = 0 | (1 << 4)
    section = nbtlib.Compound({
        "Y": nbtlib.Byte(0),
        "block_states": nbtlib.Compound({
            "palette": palette,
            "data": nbtlib.LongArray([word] + [0] * 15),  # 16 longs for 4096*4/64
        }),
    })
    # Actually 4096 entries * 4 bits = 16384 bits = 256 longs for non-stretch? 
    # values_per_long=16, 4096/16=256 longs. Provide enough zeros.
    data = [0] * 256
    data[0] = word
    section["block_states"]["data"] = nbtlib.LongArray(data)

    chunk = nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "sections": nbtlib.List[nbtlib.Compound]([section]),
    })
    assert block_id_at(chunk, 0, 0, 0) == "minecraft:air"
    assert block_id_at(chunk, 1, 0, 0) == "minecraft:dirt"
