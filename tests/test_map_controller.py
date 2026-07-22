from pathlib import Path

import pytest

from app.controllers.map_controller import MapController
from app.services.map_marker_service import MapMarkerService
from core.mca.map_search import MapSearchError


def _dimensions(tmp_path: Path) -> list[dict[str, object]]:
    return [
        {
            "id": "overworld",
            "name": "主世界",
            "region_dir": tmp_path / "region",
            "coordinate_scale": 1.0,
        },
        {
            "id": "minecraft:the_nether",
            "name": "下界",
            "region_dir": tmp_path / "DIM-1" / "region",
            "coordinate_scale": 8.0,
        },
    ]


def test_map_controller_keeps_independent_dimension_states(tmp_path: Path) -> None:
    controller = MapController(MapMarkerService(tmp_path / "markers"))
    controller.bind_world(tmp_path / "world", _dimensions(tmp_path))
    controller.state.center_x = 800
    controller.state.center_z = -160

    nether = controller.switch_dimension("minecraft:the_nether")

    assert (nether.center_x, nether.center_z) == (100.0, -20.0)
    nether.center_x = 25
    overworld = controller.switch_dimension("overworld")
    assert (overworld.center_x, overworld.center_z) == (800, -160)
    assert controller.switch_dimension("minecraft:the_nether").center_x == 25


def test_map_controller_infers_vanilla_nether_scale_when_metadata_is_legacy(
    tmp_path: Path,
) -> None:
    controller = MapController(MapMarkerService(tmp_path / "markers"))
    controller.bind_world(
        tmp_path / "world",
        [
            {"id": "overworld", "name": "主世界", "region_dir": tmp_path},
            {
                "id": "minecraft:the_nether",
                "name": "下界",
                "region_dir": tmp_path,
            },
        ],
    )
    controller.state.center_x = 800
    assert controller.switch_dimension("minecraft:the_nether").center_x == 100


def test_map_controller_toggles_layers_and_reports_unknown_layer(tmp_path: Path) -> None:
    calls = []
    controller = MapController(
        MapMarkerService(tmp_path / "markers"),
        on_state_changed=lambda state: calls.append(state.generation),
    )

    assert controller.toggle_layer("markers") is False
    assert controller.toggle_layer("markers", True) is True
    assert calls == [1, 2]
    with pytest.raises(KeyError, match="未知"):
        controller.toggle_layer("clouds")


def test_map_controller_callbacks_publish_detached_immutable_snapshots(
    tmp_path: Path,
) -> None:
    snapshots = []
    controller = MapController(
        MapMarkerService(tmp_path / "markers"),
        on_state_changed=snapshots.append,
    )

    controller.toggle_layer("markers", False)
    published = snapshots[-1]
    controller.toggle_layer("markers", True)

    assert published.layers.show_markers is False
    assert snapshots[-1].layers.show_markers is True
    with pytest.raises(AttributeError):
        setattr(published.layers, "show_markers", True)


def test_map_controller_restores_style_and_layers_per_dimension(tmp_path: Path) -> None:
    controller = MapController(MapMarkerService(tmp_path / "markers"))
    controller.bind_world(tmp_path / "world", _dimensions(tmp_path))
    controller.set_style("biome")
    controller.toggle_layer("coordinates", False)

    controller.switch_dimension("minecraft:the_nether")
    controller.set_style("structure")
    controller.toggle_layer("markers", False)

    overworld = controller.switch_dimension("overworld")
    assert overworld.style == "biome"
    assert overworld.layers.show_coordinates is False
    assert overworld.layers.show_markers is True


def test_map_controller_persists_markers_and_searches_current_dimension(
    tmp_path: Path,
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    controller = MapController(MapMarkerService(tmp_path / "markers"))
    controller.bind_world(world, _dimensions(tmp_path))
    marker = controller.upsert_marker("基地", -12, 34, y=70)

    result = controller.search("基地")[0]

    assert result.marker_id == marker.id
    assert (controller.state.center_x, controller.state.center_z) == (-12, 34)
    assert controller.delete_marker(marker.id) is True
    with pytest.raises(MapSearchError, match="未找到"):
        controller.search("基地")


def test_map_controller_does_not_delete_marker_from_another_dimension(
    tmp_path: Path,
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    service = MapMarkerService(tmp_path / "markers")
    controller = MapController(service)
    controller.bind_world(world, _dimensions(tmp_path))
    marker = controller.upsert_marker("主世界基地", 10, 20)

    controller.switch_dimension("minecraft:the_nether")

    assert controller.delete_marker(marker.id) is False
    controller.switch_dimension("overworld")
    assert [item.id for item in controller.markers()] == [marker.id]


def test_map_controller_reads_markers_only_from_memory_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    service = MapMarkerService(tmp_path / "markers")
    controller = MapController(service)
    list_calls = 0
    original_list = service.list

    def list_markers(*args, **kwargs):
        nonlocal list_calls
        list_calls += 1
        return original_list(*args, **kwargs)

    monkeypatch.setattr(service, "list", list_markers)
    controller.bind_world(world, _dimensions(tmp_path))

    controller.markers()
    controller.markers(include_disabled=True)

    assert list_calls == 0
