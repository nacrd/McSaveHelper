"""Tests for heightmap unpacking."""
from __future__ import annotations

import nbtlib

from core.mca.heightmaps import (
    WORLD_SURFACE_HEIGHTMAP_NAMES,
    heightmap_value_to_block_y,
    surface_y_from_heightmap,
    unpack_heightmap_values,
    world_min_y,
)
from core.mca.versions import DATA_VERSION_1_18


def test_unpack_compact_9bit() -> None:
    bits = 9
    value = 100
    word = value
    out = unpack_heightmap_values([word], bits=bits, count=7)
    assert out[0] == 100
    assert all(v == 0 for v in out[1:])


def test_world_min_y() -> None:
    assert world_min_y(DATA_VERSION_1_18) == -64
    assert world_min_y(DATA_VERSION_1_18 - 1) == 0
    assert world_min_y(None) == 0


def test_heightmap_value_to_block_y_modern() -> None:
    # block_y=64, min_y=-64 => stored = 64+1-(-64) = 129
    assert heightmap_value_to_block_y(129, 3463) == 64
    # block_y=-64 => stored = -64+1-(-64) = 1
    assert heightmap_value_to_block_y(1, 3463) == -64


def test_heightmap_value_to_block_y_legacy() -> None:
    # pre-1.18 absolute: stored = block_y + 1
    assert heightmap_value_to_block_y(65, 1500) == 64


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


def test_surface_y_from_synthetic_chunk_modern() -> None:
    packed = _pack_heightmap([129] * 256)
    chunk = nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "xPos": nbtlib.Int(0),
        "zPos": nbtlib.Int(0),
        "Heightmaps": nbtlib.Compound({
            "MOTION_BLOCKING": nbtlib.LongArray(packed),
        }),
    })
    assert surface_y_from_heightmap(chunk, 0, 0) == 64
    assert surface_y_from_heightmap(chunk, 15, 15) == 64


def test_surface_heightmap_priority_is_explicit_and_default_stays_motion_blocking() -> None:
    chunk = nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "Heightmaps": nbtlib.Compound({
            "MOTION_BLOCKING": nbtlib.LongArray(_pack_heightmap([129] * 256)),
            "WORLD_SURFACE": nbtlib.LongArray(_pack_heightmap([145] * 256)),
        }),
    })

    assert surface_y_from_heightmap(chunk, 0, 0) == 64
    assert surface_y_from_heightmap(
        chunk,
        0,
        0,
        heightmap_names=WORLD_SURFACE_HEIGHTMAP_NAMES,
    ) == 80
