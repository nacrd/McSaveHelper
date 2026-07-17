from types import SimpleNamespace

from app.services.world_stats_service import WorldStatsService


def test_analyze_chunk_counts_palette_and_entity_types() -> None:
    chunk = SimpleNamespace(data={
        "sections": [
            {
                "block_states": {
                    "palette": [
                        {"Name": "minecraft:stone"},
                        {"Name": "minecraft:air"},
                    ],
                },
            },
            {
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

    assert blocks == {"minecraft:stone": 2, "minecraft:dirt": 1}
    assert entities == {"minecraft:pig": 2, "block:minecraft:chest": 1}


def test_analyze_chunk_handles_missing_data() -> None:
    blocks, entities = WorldStatsService()._analyze_chunk(SimpleNamespace())

    assert blocks == {}
    assert entities == {}
