"""地图标记持久化和统一搜索解析测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.map_marker_service import (
    MapMarkerService,
    MapMarkerServiceError,
)
from core.mca.map_models import MapMarker
from core.mca.map_search import MapSearchError, MapSearchResult, parse_map_query


OVERWORLD = "minecraft:overworld"
NETHER = "minecraft:the_nether"


def _world(tmp_path: Path) -> Path:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"test")
    return world


def _marker(
    marker_id: str,
    name: str,
    *,
    x: int = 0,
    y: int = 64,
    z: int = 0,
    dimension_id: str = OVERWORLD,
    group: str = "default",
    enabled: bool = True,
    metadata: dict | None = None,
) -> MapMarker:
    return MapMarker(
        id=marker_id,
        name=name,
        x=x,
        y=y,
        z=z,
        dimension_id=dimension_id,
        group=group,
        enabled=enabled,
        metadata=metadata or {},
    )


def test_marker_service_persists_replaces_sorts_and_returns_copies(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    root = tmp_path / "marker-store"
    service = MapMarkerService(root)
    original = _marker(
        "same",
        "旧名称",
        group="beta",
        metadata={"nested": {"value": 1}},
    )

    saved = service.upsert(world, original)
    service.upsert(world, _marker("z", "矿井", group="beta"))
    service.upsert(world, _marker("b", "村庄", group="alpha"))
    service.upsert(world, _marker("a", "村庄", group="alpha"))
    replacement = _marker(
        "same",
        "基地",
        group="alpha",
        metadata={"nested": {"value": 1}},
    )
    service.upsert(world, replacement)

    original.metadata["nested"]["value"] = 2
    saved.metadata["nested"]["value"] = 3
    reloaded = MapMarkerService(root).list(world, include_disabled=True)

    assert [marker.id for marker in reloaded] == ["same", "a", "b", "z"]
    assert reloaded[0].name == "基地"
    assert reloaded[0].metadata == {"nested": {"value": 1}}
    reloaded[0].metadata["nested"]["value"] = 9
    assert service.list(world, include_disabled=True)[0].metadata == {
        "nested": {"value": 1}
    }

    path = service.storage_path(world)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert [item["id"] for item in payload["markers"]] == [
        "same",
        "a",
        "b",
        "z",
    ]
    assert not list(root.glob(".*.tmp"))
    assert list(world.iterdir()) == [world / "level.dat"]


def test_marker_service_filters_dimensions_and_disabled_records(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    service = MapMarkerService(tmp_path / "marker-store")
    service.upsert(world, _marker("home", "家", dimension_id=OVERWORLD))
    service.upsert(world, _marker("portal", "下界门", dimension_id=NETHER))
    service.upsert(world, _marker("hidden", "隐藏", enabled=False))

    assert [marker.id for marker in service.list(world)] == ["portal", "home"]
    assert [marker.id for marker in service.list(world, OVERWORLD)] == ["home"]
    assert [
        marker.id
        for marker in service.list(world, OVERWORLD, include_disabled=True)
    ] == ["home", "hidden"]

    assert service.clear(world, NETHER) == 1
    assert service.delete(world, "missing") is False
    assert service.delete(world, "home") is True
    assert service.clear(world) == 1
    assert service.list(world, include_disabled=True) == []


def test_marker_service_quarantines_broken_json(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = MapMarkerService(tmp_path / "marker-store")
    path = service.storage_path(world)
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    assert service.list(world, include_disabled=True) == []
    assert not path.exists()
    assert path.with_suffix(".broken").read_text(encoding="utf-8") == "{not-json"


def test_marker_service_never_writes_inside_world(tmp_path: Path) -> None:
    world = _world(tmp_path)
    service = MapMarkerService(world / "application-data")

    with pytest.raises(MapMarkerServiceError, match="不能位于"):
        service.upsert(world, _marker("home", "家"))

    assert not (world / "application-data").exists()


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (" -12, 34 ", MapSearchResult(kind="block", x=-12, z=34)),
        ("-1 -64 -17", MapSearchResult(kind="block", x=-1, y=-64, z=-17)),
        ("r.-1.-2", MapSearchResult(kind="region", x=-256, z=-768)),
        ("C.-1.-2", MapSearchResult(kind="chunk", x=-8, z=-24)),
    ],
)
def test_parse_map_query_supports_negative_coordinates(
    query: str,
    expected: MapSearchResult,
) -> None:
    assert parse_map_query(query) == [expected]


def test_parse_map_query_prioritizes_exact_marker_and_sorts_stably() -> None:
    markers = [
        _marker("base-far", "Home Base", x=100, z=100),
        _marker("exact-far", "HOME", x=80, z=80),
        _marker("other-dimension", "home", dimension_id=NETHER),
        _marker("base-near", "home base", x=1, z=1),
        _marker("exact-near", "home", x=-2, z=0),
        _marker("old", "Old Home", x=0, z=0),
    ]

    results = parse_map_query("HoMe", markers, OVERWORLD)

    assert [result.marker_id for result in results] == [
        "exact-near",
        "exact-far",
        "base-near",
        "base-far",
        "old",
    ]
    assert results[0] == MapSearchResult(
        kind="marker",
        x=-2,
        y=64,
        z=0,
        label="home",
        marker_id="exact-near",
    )


def test_parse_map_query_reports_clear_chinese_errors() -> None:
    with pytest.raises(MapSearchError, match="不能为空") as empty:
        parse_map_query("  ")
    assert empty.value.code == "empty"
    with pytest.raises(MapSearchError, match="坐标格式无效") as invalid:
        parse_map_query("r.-.2")
    assert invalid.value.code == "invalid_format"
    with pytest.raises(MapSearchError, match="未找到") as missing:
        parse_map_query("不存在")
    assert missing.value.code == "not_found"
