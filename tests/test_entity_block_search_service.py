from app.services.entity_block_search_service import EntityBlockSearchService


class MockChunk:
    def __init__(self, data):
        self.data = data


def test_search_containers_in_chunk_extracts_items():
    service = EntityBlockSearchService()
    chunk = MockChunk({
        "block_entities": [
            {
                "id": "minecraft:chest",
                "x": 10,
                "y": 64,
                "z": -3,
                "Items": [
                    {"Slot": 0, "id": "minecraft:diamond", "Count": 5},
                    {"Slot": 1, "id": "minecraft:apple", "Count": 2},
                ],
            },
            {
                "id": "minecraft:furnace",
                "x": 11,
                "y": 64,
                "z": -3,
                "Items": [],
            },
        ],
    })

    service._search_containers_in_chunk(chunk, "minecraft:chest", "overworld")

    assert len(service.results) == 1
    result = service.results[0]
    assert result.result_type == "container"
    assert result.name == "minecraft:chest"
    assert result.position == (10, 64, -3)
    assert result.extra_info["item_count"] == 2
    assert "minecraft:diamond x5" in result.extra_info["items"]
    assert "minecraft:apple x2" in result.extra_info["items"]


def test_search_containers_supports_all_target_and_legacy_keys():
    service = EntityBlockSearchService()
    chunk = MockChunk({
        "Level": {
            "TileEntities": [
                {"id": "minecraft:barrel", "x": 1, "y": 2, "z": 3, "Items": []},
                {"id": "minecraft:hopper", "x": 4, "y": 5, "z": 6, "Items": []},
            ],
        },
    })

    service._search_containers_in_chunk(chunk, "*", "overworld")

    assert [result.name for result in service.results] == [
        "minecraft:barrel",
        "minecraft:hopper",
    ]
    assert service.results[0].extra_info["items"] == "空"


def test_get_container_info_at_returns_matching_block_entity_items():
    service = EntityBlockSearchService()
    chunk = MockChunk({
        "BlockEntities": [
            {
                "id": "minecraft:barrel",
                "x": 7,
                "y": 70,
                "z": 8,
                "Items": [{"id": "minecraft:iron_ingot", "Count": 16}],
            }
        ],
    })

    info = service._get_container_info_at(chunk, 7, 70, 8)

    assert info["item_count"] == 1
    assert info["items"] == "minecraft:iron_ingot x16"
    assert service._get_container_info_at(chunk, 0, 70, 8) == {}


def test_search_entities_reads_modern_and_legacy_keys():
    service = EntityBlockSearchService()
    modern_chunk = MockChunk({
        "entities": [{"id": "minecraft:zombie", "Pos": [1.5, 64.0, -2.5]}],
    })
    legacy_chunk = MockChunk({
        "Level": {
            "Entities": [{"id": "minecraft:pig", "Pos": [3.0, 65.0, 4.0]}],
        },
    })

    service._search_entities_in_chunk(modern_chunk, "zombie", "overworld")
    service._search_entities_in_chunk(
        legacy_chunk, "minecraft:pig", "overworld")

    assert [result.name for result in service.results] == [
        "minecraft:zombie",
        "minecraft:pig",
    ]
    assert service.results[0].position == (1, 64, -2)
    assert service.results[1].position == (3, 65, 4)


def test_dimension_region_files_do_not_scan_other_dimensions(tmp_path):
    world = tmp_path / "world"
    overworld_region = world / "region"
    nether_region = world / "DIM-1" / "region"
    end_region = world / "DIM1" / "region"
    overworld_region.mkdir(parents=True)
    nether_region.mkdir(parents=True)
    end_region.mkdir(parents=True)
    (overworld_region / "r.0.0.mca").write_bytes(b"")
    (nether_region / "r.1.0.mca").write_bytes(b"")
    (end_region / "r.2.0.mca").write_bytes(b"")

    service = EntityBlockSearchService()

    assert service._get_dimension_region_files(world, "overworld") == [
        overworld_region / "r.0.0.mca"]
    assert service._get_dimension_region_files(world, "nether") == [
        nether_region / "r.1.0.mca"]
    assert service._get_dimension_region_files(
        world, "end") == [end_region / "r.2.0.mca"]


def test_result_limit_helper_stops_at_max_results():
    service = EntityBlockSearchService()
    service.MAX_RESULTS = 1
    chunk = MockChunk({
        "block_entities": [
            {"id": "minecraft:barrel", "x": 1, "y": 2, "z": 3, "Items": []},
            {"id": "minecraft:hopper", "x": 4, "y": 5, "z": 6, "Items": []},
        ],
    })

    service._search_containers_in_chunk(chunk, "*", "overworld")

    assert len(service.results) == 1
    assert service._is_result_limit_reached() is True
