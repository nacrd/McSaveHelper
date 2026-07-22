"""Explorer map controls mirror dimension-specific controller state."""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import flet as ft

from app.controllers.map_controller import MapController
from app.services.map_marker_service import MapMarkerService
from app.ui.feature_context import FeatureContext
from app.ui.views.explorer.region_tab import RegionTabMixin
from core.mca.map_models import MapLayerState, MapViewState


class _App:
    @staticmethod
    def translate(key: str, default: str = "", **kwargs: object) -> str:
        del key
        return default.format(**kwargs)


class _MapView:
    def __init__(self) -> None:
        self.style = "topview"
        self.layers = MapLayerState()
        self.markers: list[object] = []

    def set_display_mode(self, style: str) -> None:
        self.style = style

    def apply_layer_state(self, layers: MapLayerState) -> None:
        self.layers = layers

    def set_markers(self, markers: list[object]) -> None:
        self.markers = markers


def _host() -> RegionTabMixin:
    host = RegionTabMixin()
    host.app = cast(FeatureContext, _App())
    host._map_view = cast(Any, _MapView())
    host._region_display_mode_dropdown = ft.Dropdown()
    host._map_coord_btn = ft.IconButton()
    host._map_empty_btn = ft.IconButton()
    host._map_marker_btn = ft.IconButton()
    return host


def test_apply_map_state_updates_view_dropdown_and_layer_buttons() -> None:
    host = _host()
    state = MapViewState(
        style="biome",
        layers=MapLayerState(
            show_coordinates=False,
            show_markers=False,
            show_empty_regions=True,
        ),
    )

    host._apply_map_state(state)

    map_view = cast(_MapView, host._map_view)
    assert map_view.style == "biome"
    assert map_view.layers is state.layers
    assert host._region_display_mode_dropdown.value == "biome"
    assert host._map_coord_btn.selected is False
    assert host._map_empty_btn.selected is True
    assert host._map_marker_btn.selected is False


def test_refresh_markers_clears_selection_from_previous_dimension(
    tmp_path: Path,
) -> None:
    host = _host()
    world = tmp_path / "world"
    world.mkdir()
    controller = MapController(MapMarkerService(tmp_path / "markers"))
    controller.bind_world(
        world,
        [
            {"id": "overworld", "name": "主世界", "region_dir": tmp_path},
            {"id": "nether", "name": "下界", "region_dir": tmp_path},
        ],
    )
    marker = controller.upsert_marker("基地", 0, 0)
    controller.switch_dimension("nether")
    host._map_controller = controller
    host._selected_marker_id = marker.id
    host._map_delete_marker_btn = ft.IconButton(disabled=False)
    host._map_marker_list = ft.ListView()
    host._map_marker_count_text = ft.Text()

    host._refresh_map_markers()

    assert host._selected_marker_id is None
    assert host._map_delete_marker_btn.disabled is True
