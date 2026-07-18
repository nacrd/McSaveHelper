from types import SimpleNamespace

from app.services.world_stats_service import WorldStatsService


def test_analyze_chunk_counts_palette_and_entity_types() -> None:
    chunk = SimpleNamespace(data={
        "sections": [
            {
                "Y": 0,
                "block_states": {
                    "palette": [
                        {"Name": "minecraft:stone"},
                        {"Name": "minecraft:air"},
                    ],
                },
            },
            {
                "Y": 1,
                "block_states": {
                    "palette": [
                        {"Name": "minecraft:stone"},
                        {"Name": "minecraft:dirt"},
                    ],
                },
            },
        ],
        "entities": [
            {"id": "minecraft:pig"},
            {"id": "minecraft:pig"},
            {"id": ""},
        ],
        "block_entities": [
            {"id": "minecraft:chest"},
        ],
    })

    blocks, entities = WorldStatsService()._analyze_chunk(chunk)

    assert blocks == {"minecraft:stone": 8192}
    assert entities == {"minecraft:pig": 2, "block:minecraft:chest": 1}


def test_analyze_chunk_handles_missing_data() -> None:
    blocks, entities = WorldStatsService()._analyze_chunk(SimpleNamespace())

    assert blocks == {}
    assert entities == {}


def test_analyze_chunk_counts_packed_palette_indices() -> None:
    data = [0] * 256
    data[0] = 1  # first block uses palette index 1; remaining 4095 use index 0
    chunk = SimpleNamespace(data={
        "DataVersion": 3463,
        "sections": [{
            "Y": 0,
            "block_states": {
                "palette": [
                    {"Name": "minecraft:stone"},
                    {"Name": "minecraft:dirt"},
                ],
                "data": data,
            },
        }],
    })

    blocks, _entities = WorldStatsService()._analyze_chunk(chunk)

    assert blocks == {"minecraft:stone": 4095, "minecraft:dirt": 1}
