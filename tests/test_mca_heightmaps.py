"""Tests for heightmap unpacking."""
from __future__ import annotations

import nbtlib

from core.mca.heightmaps import (
    surface_y_from_heightmap,
    unpack_heightmap_values,
)


def test_unpack_compact_9bit() -> None:
    # values_per_long = 64 // 9 = 7
    # pack first value 100 into low bits of one long
    bits = 9
    value = 100
    word = value  # at offset 0
    out = unpack_heightmap_values([word], bits=bits, count=7)
    assert out[0] == 100
    assert all(v == 0 for v in out[1:])


def test_surface_y_from_synthetic_chunk() -> None:
    # Build 256 heightmap values: all 65 → surface block y = 64
    bits = 9
    values_per_long = 64 // bits
    packed = []
    # fill 256 entries of 65
    remaining = [65] * 256
    while remaining:
        word = 0
        for i in range(min(values_per_long, len(remaining))):
            word |= (remaining.pop(0) & ((1 << bits) - 1)) << (i * bits)
        packed.append(word)

    chunk = nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "xPos": nbtlib.Int(0),
        "zPos": nbtlib.Int(0),
        "Heightmaps": nbtlib.Compound({
            "WORLD_SURFACE": nbtlib.LongArray(packed),
        }),
    })
    y = surface_y_from_heightmap(chunk, 0, 0)
    assert y == 64
    y2 = surface_y_from_heightmap(chunk, 15, 15)
    assert y2 == 64
