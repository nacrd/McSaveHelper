import json
from types import SimpleNamespace
from typing import Any

import core.mca
import pytest
from app.services import world_stats_service as world_stats_module
from app.services.world_stats_service import (
    PLAYER_SORT_DEATHS,
    PLAYER_SORT_MINED,
    PLAYER_SORT_MOB_KILLS,
    PLAYER_SORT_NAME,
    PLAYER_SORT_PLAY_TIME,
    WorldStatsCancelledError,
    WorldStatsService,
    DimensionSizeStats,
    PlayerPlaytimeStats,
)
from core.world_index import WorldIndexBuilder


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
    region_path = tmp_path / "region" / "r.0.0.mca"
    region_path.parent.mkdir(parents=True)
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
    assert stats.region_sizes == {"region/r.0.0.mca": 6}


def test_collect_dimension_sizes_by_dimension(tmp_path) -> None:
    overworld = tmp_path / "region" / "r.0.0.mca"
    nether = tmp_path / "DIM-1" / "region" / "r.0.0.mca"
    end = tmp_path / "DIM1" / "region" / "r.1.1.mca"
    for path, payload in (
        (overworld, b"a" * 100),
        (nether, b"b" * 250),
        (end, b"c" * 50),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    stats = WorldStatsService().collect_dimension_sizes(tmp_path)

    by_id = {item.dimension_id: item for item in stats}
    assert by_id["overworld"].region_count == 1
    assert by_id["overworld"].total_bytes == 100
    assert by_id["minecraft:the_nether"].total_bytes == 250
    assert by_id["minecraft:the_end"].total_bytes == 50
    # Sorted by total_bytes descending.
    assert stats[0].dimension_id == "minecraft:the_nether"


def test_collect_player_playtimes_reads_legacy_and_modern_paths(tmp_path) -> None:
    legacy_uuid = "156897ff-7fa6-4150-9db1-33ae6337bca8"
    modern_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    legacy_dir = tmp_path / "stats"
    modern_dir = tmp_path / "players" / "stats"
    legacy_dir.mkdir(parents=True)
    modern_dir.mkdir(parents=True)

    (legacy_dir / f"{legacy_uuid}.json").write_text(
        json.dumps({
            "stats": {
                "minecraft:custom": {
                    "minecraft:play_time": 72000,
                    "minecraft:total_world_time": 80000,
                    "minecraft:deaths": 2,
                    "minecraft:mob_kills": 5,
                    "minecraft:player_kills": 1,
                    "minecraft:jump": 10,
                    "minecraft:damage_dealt": 40,
                    "minecraft:walk_one_cm": 1000,
                    "minecraft:sprint_one_cm": 500,
                },
                "minecraft:mined": {
                    "minecraft:stone": 12,
                    "minecraft:dirt": 3,
                },
                "minecraft:used": {
                    "minecraft:oak_planks": 4,
                },
            }
        }),
        encoding="utf-8",
    )
    (modern_dir / f"{modern_uuid}.json").write_text(
        json.dumps({
            "stats": {
                "minecraft:custom": {
                    "minecraft:play_one_minute": 144000,
                    "minecraft:total_world_time": 150000,
                    "minecraft:deaths": 0,
                    "minecraft:mob_kills": 1,
                }
            }
        }),
        encoding="utf-8",
    )
    (tmp_path / "usercache.json").write_text(
        json.dumps([
            {"uuid": modern_uuid, "name": "Steve"},
            {"uuid": legacy_uuid, "name": "Alex"},
        ]),
        encoding="utf-8",
    )

    players = WorldStatsService().collect_player_playtimes(tmp_path)

    assert len(players) == 2
    assert players[0].name == "Steve"
    assert players[0].play_time_ticks == 144000
    assert players[1].name == "Alex"
    assert players[1].play_time_ticks == 72000
    assert players[1].deaths == 2
    assert players[1].mob_kills == 5
    assert players[1].player_kills == 1
    assert players[1].mined == 15
    assert players[1].placed == 4
    assert players[1].jumps == 10
    assert players[1].damage_dealt == 40
    assert players[1].distance_cm == 1500

    by_deaths = WorldStatsService().collect_player_playtimes(
        tmp_path,
        sort_by=PLAYER_SORT_DEATHS,
    )
    assert by_deaths[0].name == "Alex"
    assert by_deaths[0].deaths == 2

    by_mined = WorldStatsService.sort_player_stats(
        players,
        PLAYER_SORT_MINED,
    )
    assert by_mined[0].mined == 15
    assert by_mined[0].name == "Alex"

    # Session-style name_map overrides/supplements usercache.
    renamed = WorldStatsService().collect_player_playtimes(
        tmp_path,
        name_map={
            modern_uuid: "Herobrine",
            legacy_uuid: None,
        },
    )
    by_name = {player.uuid: player.name for player in renamed}
    assert by_name[modern_uuid.replace("-", "").lower()] == "Herobrine"
    assert by_name[legacy_uuid.replace("-", "").lower()] == "Alex"


def test_collect_player_playtimes_uses_shared_index_without_rescanning(
    tmp_path,
    monkeypatch: Any,
) -> None:
    player_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    stats_dir = tmp_path / "stats"
    player_dir = tmp_path / "playerdata"
    stats_dir.mkdir()
    player_dir.mkdir()
    (tmp_path / "level.dat").write_bytes(b"level")
    (player_dir / f"{player_uuid}.dat").write_bytes(b"player")
    (stats_dir / f"{player_uuid}.json").write_text(
        json.dumps({
            "stats": {
                "minecraft:custom": {
                    "minecraft:play_time": 2400,
                },
            },
        }),
        encoding="utf-8",
    )
    (tmp_path / "usercache.json").write_text(
        json.dumps([{"uuid": player_uuid, "name": "IndexedPlayer"}]),
        encoding="utf-8",
    )
    snapshot = WorldIndexBuilder().build(tmp_path)

    def fail_scan(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("共享索引路径不应重新扫描目录")

    monkeypatch.setattr(world_stats_module, "find_stats_dirs", fail_scan)
    monkeypatch.setattr(world_stats_module, "WorldScanner", fail_scan)

    players = WorldStatsService().collect_player_playtimes(
        tmp_path,
        index_snapshot=snapshot,
    )

    assert len(players) == 1
    assert players[0].name == "IndexedPlayer"
    assert players[0].play_time_ticks == 2400


def test_with_player_names_fills_missing_display_names() -> None:
    players = [
        PlayerPlaytimeStats(
            uuid="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            name=None,
            play_time_ticks=1,
            total_world_time_ticks=1,
            deaths=0,
            mob_kills=0,
        ),
        PlayerPlaytimeStats(
            uuid="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            name="KeepMe",
            play_time_ticks=2,
            total_world_time_ticks=2,
            deaths=0,
            mob_kills=0,
        ),
    ]
    named = WorldStatsService().with_player_names(
        players,
        {
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa": "FromSession",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb": "Ignored",
        },
    )
    assert named[0].name == "FromSession"
    assert named[1].name == "KeepMe"


def test_sort_player_stats_supports_name_and_kills() -> None:
    players = [
        PlayerPlaytimeStats(
            uuid="a",
            name="Zed",
            play_time_ticks=10,
            total_world_time_ticks=10,
            deaths=0,
            mob_kills=3,
            mined=1,
        ),
        PlayerPlaytimeStats(
            uuid="b",
            name="Ann",
            play_time_ticks=20,
            total_world_time_ticks=20,
            deaths=1,
            mob_kills=9,
            mined=0,
        ),
    ]

    by_name = WorldStatsService.sort_player_stats(players, PLAYER_SORT_NAME)
    assert [item.name for item in by_name] == ["Ann", "Zed"]

    by_kills = WorldStatsService.sort_player_stats(
        players,
        PLAYER_SORT_MOB_KILLS,
    )
    assert by_kills[0].name == "Ann"
    assert WorldStatsService.player_metric_value(
        by_kills[0],
        PLAYER_SORT_MOB_KILLS,
    ) == 9
    assert WorldStatsService.player_metric_value(
        by_kills[0],
        PLAYER_SORT_PLAY_TIME,
    ) == 20


def test_collect_player_playtimes_prefers_modern_path(tmp_path) -> None:
    uuid = "11111111-2222-3333-4444-555555555555"
    legacy = tmp_path / "stats"
    modern = tmp_path / "players" / "stats"
    legacy.mkdir()
    modern.mkdir(parents=True)
    (legacy / f"{uuid}.json").write_text(
        json.dumps({
            "stats": {"minecraft:custom": {"minecraft:play_time": 10}}
        }),
        encoding="utf-8",
    )
    (modern / f"{uuid}.json").write_text(
        json.dumps({
            "stats": {"minecraft:custom": {"minecraft:play_time": 99}}
        }),
        encoding="utf-8",
    )

    players = WorldStatsService().collect_player_playtimes(tmp_path)

    assert len(players) == 1
    assert players[0].play_time_ticks == 99


def test_format_ticks_as_duration() -> None:
    assert WorldStatsService.format_ticks_as_duration(0) == "0s"
    assert WorldStatsService.format_ticks_as_duration(40) == "2s"
    assert WorldStatsService.format_ticks_as_duration(72000) == "1h 0m 0s"
    assert WorldStatsService.format_ticks_as_duration(1_728_000) == "1d 0h 0m"


def test_analyze_world_includes_dimension_and_player_summaries(
    tmp_path,
    monkeypatch: Any,
) -> None:
    region_path = tmp_path / "region" / "r.0.0.mca"
    region_path.parent.mkdir(parents=True)
    region_path.write_bytes(b"x" * 20)
    stats_dir = tmp_path / "stats"
    stats_dir.mkdir()
    uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    (stats_dir / f"{uuid}.json").write_text(
        json.dumps({
            "stats": {
                "minecraft:custom": {
                    "minecraft:play_time": 200,
                    "minecraft:total_world_time": 300,
                }
            }
        }),
        encoding="utf-8",
    )

    class Region:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def iter_present_chunks():
            return iter([])

        @staticmethod
        def get_chunk(_x, _z):
            return None

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

    assert isinstance(stats.dimension_stats[0], DimensionSizeStats)
    assert stats.dimension_stats[0].region_count == 1
    assert stats.dimension_stats[0].total_bytes == 20
    assert isinstance(stats.player_stats[0], PlayerPlaytimeStats)
    assert stats.player_stats[0].play_time_ticks == 200


def test_analyze_world_reports_phased_progress(
    tmp_path,
    monkeypatch: Any,
) -> None:
    region_a = tmp_path / "region" / "r.0.0.mca"
    region_b = tmp_path / "region" / "r.0.1.mca"
    region_a.parent.mkdir(parents=True)
    region_a.write_bytes(b"a")
    region_b.write_bytes(b"b")
    events: list[tuple[float, str]] = []

    class Region:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def iter_present_chunks():
            return iter([])

        @staticmethod
        def get_chunk(_x, _z):
            return None

    monkeypatch.setattr(
        world_stats_module,
        "scan_all_regions",
        lambda _world: [region_a, region_b],
    )
    monkeypatch.setattr(
        core.mca,
        "NativeRegion",
        SimpleNamespace(from_file=lambda _path: Region()),
    )

    def on_progress(value: float, stage: str) -> None:
        events.append((value, stage))

    WorldStatsService().analyze_world(tmp_path, progress_callback=on_progress)

    stages = [stage for _value, stage in events]
    assert stages[0] == "dimensions"
    assert "players" in stages
    assert "scanning" in stages
    assert "regions:1:2" in stages
    assert "regions:2:2" in stages
    assert stages[-2] == "finalizing"
    assert stages[-1] == "done"
    values = [value for value, _stage in events]
    assert values[0] < values[-1]
    assert values[-1] == 1.0
    assert all(0.0 <= value <= 1.0 for value in values)
    # Progress is non-decreasing for a successful run.
    assert values == sorted(values)


def test_analyze_world_progress_handles_empty_regions(
    tmp_path,
    monkeypatch: Any,
) -> None:
    events: list[tuple[float, str]] = []
    monkeypatch.setattr(
        world_stats_module,
        "scan_all_regions",
        lambda _world: [],
    )

    WorldStatsService().analyze_world(
        tmp_path,
        progress_callback=lambda value, stage: events.append((value, stage)),
    )

    stages = [stage for _value, stage in events]
    assert "dimensions" in stages
    assert "finalizing" in stages
    assert stages[-1] == "done"
    assert events[-1][0] == 1.0


def test_analyze_world_stops_between_region_files(
    tmp_path,
    monkeypatch: Any,
) -> None:
    region_paths = [
        tmp_path / "region" / "r.0.0.mca",
        tmp_path / "region" / "r.0.1.mca",
    ]
    analyzed = []
    service = WorldStatsService()
    monkeypatch.setattr(
        world_stats_module,
        "scan_all_regions",
        lambda _world: region_paths,
    )
    monkeypatch.setattr(
        service,
        "_analyze_one_region",
        lambda *args: analyzed.append(args[1]),
    )

    with pytest.raises(WorldStatsCancelledError, match="统计已取消"):
        service.analyze_world(
            tmp_path,
            cancel_check=lambda: bool(analyzed),
        )

    assert analyzed == [region_paths[0]]
