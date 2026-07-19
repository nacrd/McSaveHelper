from types import SimpleNamespace
from typing import Any

import core.mca
from app.services import world_stats_service as world_stats_module
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


def test_analyze_chunk_filters_air_from_bulk_palette_counts() -> None:
    data = [0] * 256
    data[0] = 1  # The first block is void air; remaining blocks are stone.
    chunk = SimpleNamespace(data={
        "DataVersion": 3463,
        "sections": [
            {
                "Y": 0,
                "block_states": {
                    "palette": [
                        {"Name": "minecraft:stone"},
                        {"Name": "minecraft:void_air"},
                    ],
                    "data": data,
                },
            },
            {
                "Y": 1,
                "block_states": {
                    "palette": [{"Name": "minecraft:cave_air"}],
                },
            },
        ],
    })

    blocks, _entities = WorldStatsService()._analyze_chunk(chunk)

    assert blocks == {"minecraft:stone": 4095}


def test_analyze_world_reads_only_present_region_slots(
    tmp_path,
    monkeypatch: Any,
) -> None:
    region_path = tmp_path / "r.0.0.mca"
    region_path.write_bytes(b"region")
    calls = []

    class Region:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def iter_present_chunks():
            return iter([(2, 3)])

        @staticmethod
        def get_chunk(x, z):
            calls.append((x, z))
            return SimpleNamespace(data={})

    monkeypatch.setattr(
        world_stats_module,
        "scan_all_regions",
        lambda _world: [region_path],
    )
    monkeypatch.setattr(
        core.mca,
        "NativeRegion",
        SimpleNamespace(from_file=lambda _path: Region()),
    )

    stats = WorldStatsService().analyze_world(tmp_path)

    assert calls == [(2, 3)]
    assert stats.loaded_chunks == 1
    assert stats.empty_chunks == 1023
