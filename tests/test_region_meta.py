from collections import Counter

from core.mca.region_meta import (
    collect_biomes,
    collect_structures,
    extract_structure_position,
)


def test_collect_biomes_from_modern_and_legacy_chunk_data() -> None:
    counter: Counter[str] = Counter()
    collect_biomes(
        {
            "sections": [
                {"biomes": {"palette": ["minecraft:plains", "minecraft:forest"]}},
            ],
            "Biomes": ["minecraft:river"],
        },
        counter,
    )

    assert counter["minecraft:plains"] == 1
    assert counter["minecraft:forest"] == 1
    assert counter["minecraft:river"] == 1


def test_collect_structures_and_bb_positions() -> None:
    counter: Counter[str] = Counter()
    positions: list[dict] = []
    collect_structures(
        {
            "structures": {
                "starts": {
                    "minecraft:village": {
                        "BB": [16, 64, -32, 48, 80, 0],
                    }
                },
                "References": {
                    "minecraft:mineshaft": [1, 2],
                },
            }
        },
        counter,
        positions,
    )

    assert counter["minecraft:village"] == 1
    assert counter["minecraft:mineshaft"] == 1
    assert positions[0]["block_x"] == 16
    assert positions[0]["source"] == "bb"


def test_extract_structure_position_from_chunk_coords() -> None:
    pos = extract_structure_position(
        "minecraft:fortress",
        {"ChunkX": 3, "ChunkZ": -2},
    )

    assert pos == {
        "name": "minecraft:fortress",
        "block_x": 48,
        "block_z": -32,
        "source": "chunk",
    }
