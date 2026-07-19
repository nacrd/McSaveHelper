"""Tests for entity/block/container search service."""

from pathlib import Path

from app.services.entity_block_search.container_searcher import (
    ContainerSearcher,
    extract_container_info,
)
from app.services.entity_block_search.entity_searcher import EntitySearcher
from app.services.entity_block_search.models import SearchCondition, SearchResult, SearchSummary
from app.services.entity_block_search.utils import (
    get_dimension_entity_files,
    get_dimension_region_files,
    matches_target,
)


class MockChunk:
    def __init__(self, data):
        self.data = data


# ==================== matches_target 测试 ====================

def test_matches_target_wildcard():
    assert matches_target("minecraft:villager", "*")
    assert matches_target("anything", "*")


def test_matches_target_exact():
    assert matches_target("minecraft:villager", "minecraft:villager")
    assert not matches_target("minecraft:zombie", "minecraft:villager")


def test_matches_target_suffix():
    assert matches_target("minecraft:villager", "villager")
    assert not matches_target("minecraft:zombie", "villager")


def test_matches_target_comma_separated():
    assert matches_target("minecraft:villager", "villager,cow")
    assert matches_target("minecraft:cow", "villager,cow")
    assert not matches_target("minecraft:pig", "villager,cow")


def test_matches_target_glob():
    assert matches_target("minecraft:white_shulker_box", "*shulker*")
    assert matches_target("minecraft:chest", "*chest*")
    assert not matches_target("minecraft:chest", "*shulker*")
    assert matches_target("minecraft:diamond_ore", "minecraft:*_ore")


# ==================== 实体搜索测试 ====================

def test_entity_search_chunk_modern_key():
    results = []
    summary = SearchSummary()
    searcher = EntitySearcher(results, summary)
    chunk = MockChunk({
        "entities": [{"id": "minecraft:zombie", "Pos": [1.5, 64.0, -2.5]}],
    })
    searcher.search_chunk(chunk, "zombie", "overworld")
    assert len(results) == 1
    assert results[0].name == "minecraft:zombie"
    assert results[0].position == (1, 64, -2)
    assert results[0].x == 1
    assert results[0].y == 64
    assert results[0].z == -2
    assert results[0].target_id == "minecraft:zombie"


def test_entity_search_chunk_legacy_key():
    results = []
    summary = SearchSummary()
    searcher = EntitySearcher(results, summary)
    chunk = MockChunk({
        "Level": {
            "Entities": [{"id": "minecraft:pig", "Pos": [3.0, 65.0, 4.0]}],
        },
    })
    searcher.search_chunk(chunk, "minecraft:pig", "overworld")
    assert len(results) == 1
    assert results[0].name == "minecraft:pig"
    assert results[0].position == (3, 65, 4)


def test_entity_search_multi_target():
    results = []
    summary = SearchSummary()
    searcher = EntitySearcher(results, summary)
    chunk = MockChunk({
        "entities": [
            {"id": "minecraft:zombie", "Pos": [1.0, 64.0, 2.0]},
            {"id": "minecraft:cow", "Pos": [3.0, 64.0, 4.0]},
            {"id": "minecraft:pig", "Pos": [5.0, 64.0, 6.0]},
        ],
    })
    searcher.search_chunk(chunk, "zombie,cow", "overworld")
    assert len(results) == 2
    assert results[0].name == "minecraft:zombie"
    assert results[1].name == "minecraft:cow"


def test_region_search_reads_only_present_chunks_in_stable_order():
    results = []
    summary = SearchSummary()
    searcher = EntitySearcher(results, summary)
    calls = []

    class Region:
        @staticmethod
        def iter_present_chunks():
            return iter([(1, 0), (0, 2)])

        @staticmethod
        def get_chunk(cx, cz):
            calls.append((cx, cz))
            return MockChunk({})

    searcher._scan_region(Region(), "*", "overworld")

    assert calls == [(0, 2), (1, 0)]
    assert summary.scanned_chunks == 2


# ==================== 容器搜索测试 ====================

def test_container_search_chunk_extracts_items():
    results = []
    summary = SearchSummary()
    searcher = ContainerSearcher(results, summary)
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
    searcher.search_chunk(chunk, "minecraft:chest", "overworld")
    assert len(results) == 1
    result = results[0]
    assert result.result_type == "container"
    assert result.name == "minecraft:chest"
    assert result.position == (10, 64, -3)
    assert result.extra_info["item_count"] == 2
    assert "minecraft:diamond x5" in result.extra_info["items"]
    assert "minecraft:apple x2" in result.extra_info["items"]


def test_container_search_wildcard_and_legacy_key():
    results = []
    summary = SearchSummary()
    searcher = ContainerSearcher(results, summary)
    chunk = MockChunk({
        "Level": {
            "TileEntities": [
                {"id": "minecraft:barrel", "x": 1, "y": 2, "z": 3, "Items": []},
                {"id": "minecraft:hopper", "x": 4, "y": 5, "z": 6, "Items": []},
            ],
        },
    })
    searcher.search_chunk(chunk, "*", "overworld")
    assert [r.name for r in results] == ["minecraft:barrel", "minecraft:hopper"]
    assert results[0].extra_info["items"] == "空"


def test_container_search_glob_pattern():
    results = []
    summary = SearchSummary()
    searcher = ContainerSearcher(results, summary)
    chunk = MockChunk({
        "block_entities": [
            {"id": "minecraft:white_shulker_box", "x": 0, "y": 0, "z": 0, "Items": []},
            {"id": "minecraft:chest", "x": 1, "y": 0, "z": 0, "Items": []},
            {"id": "minecraft:orange_shulker_box", "x": 2, "y": 0, "z": 0, "Items": []},
        ],
    })
    searcher.search_chunk(chunk, "*shulker*", "overworld")
    assert len(results) == 2
    assert results[0].name == "minecraft:white_shulker_box"
    assert results[1].name == "minecraft:orange_shulker_box"


def test_container_info_at_returns_matching_items():
    results = []
    summary = SearchSummary()
    searcher = ContainerSearcher(results, summary)
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
    info = searcher.get_container_info_at(chunk, 7, 70, 8)
    assert info["item_count"] == 1
    assert info["items"] == "minecraft:iron_ingot x16"
    assert searcher.get_container_info_at(chunk, 0, 70, 8) == {}


# ==================== 维度路径测试 ====================

def test_dimension_region_files_do_not_cross_dimensions(tmp_path):
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

    assert get_dimension_region_files(world, "overworld") == [
        overworld_region / "r.0.0.mca"]
    assert get_dimension_region_files(world, "nether") == [
        nether_region / "r.1.0.mca"]
    assert get_dimension_region_files(world, "end") == [
        end_region / "r.2.0.mca"]


def test_dimension_entity_files_scan_modern_storage(tmp_path):
    world = tmp_path / "world"
    overworld_entities = world / "entities"
    nether_entities = world / "DIM-1" / "entities"
    overworld_entities.mkdir(parents=True)
    nether_entities.mkdir(parents=True)
    (overworld_entities / "r.0.0.mca").write_bytes(b"")
    (nether_entities / "r.1.0.mca").write_bytes(b"")

    assert get_dimension_entity_files(world, "overworld") == [
        overworld_entities / "r.0.0.mca"
    ]
    assert get_dimension_entity_files(world, "nether") == [
        nether_entities / "r.1.0.mca"
    ]


# ==================== SearchCondition 测试 ====================

def test_search_condition_validate_valid(tmp_path):
    (tmp_path / "region").mkdir()
    condition = SearchCondition(
        search_type="entity",
        target="zombie",
        dimensions=["overworld", "nether"],
        world_path=tmp_path,
    )
    errors = condition.validate()
    assert errors == []
    assert condition.dimensions == ["overworld", "nether"]


def test_search_condition_validate_invalid_type(tmp_path):
    (tmp_path / "region").mkdir()
    condition = SearchCondition(
        search_type="invalid",
        target="zombie",
        dimensions=["overworld"],
        world_path=tmp_path,
    )
    errors = condition.validate()
    assert any("搜索类型" in e for e in errors)


def test_search_condition_validate_no_dimensions(tmp_path):
    (tmp_path / "region").mkdir()
    condition = SearchCondition(
        search_type="entity",
        target="zombie",
        dimensions=[],
        world_path=tmp_path,
    )
    errors = condition.validate()
    assert any("维度" in e for e in errors)


def test_search_condition_validate_nonexistent_path():
    condition = SearchCondition(
        search_type="entity",
        target="zombie",
        dimensions=["overworld"],
        world_path=Path("/nonexistent/path"),
    )
    errors = condition.validate()
    assert any("不存在" in e for e in errors)


# ==================== SearchResult 属性测试 ====================

def test_search_result_properties():
    result = SearchResult("entity", "minecraft:zombie", (10, 64, -20), "overworld")
    assert result.x == 10
    assert result.y == 64
    assert result.z == -20
    assert result.target_id == "minecraft:zombie"
    assert result.position_str == "(10, 64, -20)"


def test_extract_container_info_empty():
    info = extract_container_info({"Items": []})
    assert info["item_count"] == 0
    assert info["items"] == "空"


def test_extract_container_info_with_custom_name():
    entity = {
        "Items": [{"id": "minecraft:diamond", "Count": 1}],
        "CustomName": '{"text":"My Chest"}',
    }
    info = extract_container_info(entity)
    assert info["item_count"] == 1
    assert "custom_name" in info
