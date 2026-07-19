from pathlib import Path

import pytest

from core.mca import (
    MapDimension,
    MapExportSpec,
    MapLayerState,
    MapMarker,
    MapSelection,
    MapTileKey,
    MapViewState,
)


def test_map_dimension_requires_a_positive_coordinate_scale(tmp_path: Path) -> None:
    dimension = MapDimension("overworld", "主世界", tmp_path / "region", 1)

    assert dimension.region_dir == tmp_path / "region"
    assert dimension.coordinate_scale == 1.0
    with pytest.raises(ValueError, match="coordinate_scale"):
        MapDimension("nether", "下界", tmp_path, 0)


def test_map_tile_parent_uses_floor_division_for_negative_coordinates() -> None:
    tile = MapTileKey(
        world_id="save-1",
        dimension_id="overworld",
        style="topview",
        lod=2,
        region_x=-5,
        region_z=6,
        y_slice=32,
    )

    parent = tile.parent(2)

    assert parent == MapTileKey(
        world_id="save-1",
        dimension_id="overworld",
        style="topview",
        lod=4,
        region_x=-2,
        region_z=1,
        y_slice=32,
    )
    assert tile.cache_parts() == (
        "save-1",
        "overworld",
        "topview",
        "lod-2",
        "-5_6",
        "y-32",
    )


@pytest.mark.parametrize(
    ("world_id", "dimension_id", "style", "field"),
    [
        ("  ", "overworld", "topview", "world_id"),
        ("save-1", "  ", "topview", "dimension_id"),
        ("save-1", "overworld", "  ", "style"),
    ],
)
def test_map_tile_key_rejects_empty_identity_fields(
    world_id: str,
    dimension_id: str,
    style: str,
    field: str,
) -> None:
    with pytest.raises(ValueError, match=field):
        MapTileKey(world_id, dimension_id, style, lod=0, region_x=0, region_z=0)


def test_map_tile_key_rejects_negative_lod() -> None:
    with pytest.raises(ValueError, match="lod"):
        MapTileKey("save-1", "overworld", "topview", -1, 0, 0)


def test_block_selection_normalizes_and_floors_negative_coordinates() -> None:
    selection = MapSelection(15, 32, -17, -1)

    assert selection.normalized == MapSelection(-17, -1, 15, 32)
    assert selection.block_bounds == (-17, -1, 15, 32)
    assert selection.chunk_bounds == (-2, -1, 0, 2)
    assert selection.region_bounds == (-1, -1, 0, 0)
    assert selection.contains_block(-17, -1)
    assert selection.contains_block(15, 32)
    assert not selection.contains_block(-18, 0)


def test_selection_factories_expand_to_inclusive_bounds() -> None:
    region = MapSelection.from_region(-2, 1)
    chunk = MapSelection.from_chunk(-2, -1)

    assert region.region_bounds == (-2, 1, -2, 1)
    assert region.chunk_bounds == (-64, 32, -33, 63)
    assert region.block_bounds == (-1024, 512, -513, 1023)
    assert chunk.chunk_bounds == (-2, -1, -2, -1)
    assert chunk.block_bounds == (-32, -16, -17, -1)
    assert chunk.region_bounds == (-1, -1, -1, -1)


def test_marker_serialization_does_not_share_metadata() -> None:
    source_metadata = {"tags": ["home"], "extra": {"owner": "Alex"}}
    marker = MapMarker(
        id="home",
        name="家",
        x=-12,
        y=64,
        z=30,
        dimension_id="overworld",
        metadata=source_metadata,
    )
    source_metadata["tags"].append("changed")

    payload = marker.to_dict()
    restored = MapMarker.from_dict(payload)
    payload["metadata"]["extra"]["owner"] = "Steve"

    assert marker.metadata == {"tags": ["home"], "extra": {"owner": "Alex"}}
    assert restored == marker
    assert restored.metadata is not marker.metadata
    assert restored.metadata["extra"] is not marker.metadata["extra"]


def test_layer_defaults_are_not_shared_between_view_states() -> None:
    first = MapViewState()
    second = MapViewState()

    first.layers.show_grid = True

    assert first.layers == MapLayerState(
        show_grid=True,
        show_coordinates=False,
        show_markers=True,
        show_empty_regions=False,
    )
    assert second.layers.show_grid is False


def test_dimension_switch_preserves_scaled_anchor_and_invalidates_selection(
    tmp_path: Path,
) -> None:
    layers = MapLayerState(show_empty_regions=True)
    state = MapViewState(
        dimension_id="overworld",
        style="topview",
        center_x=800,
        center_z=-160,
        scale=2,
        layers=layers,
        selection=MapSelection.from_region(1, 2),
        generation=7,
    )
    nether = MapDimension("nether", "下界", tmp_path / "DIM-1" / "region", 8)

    returned = state.switch_dimension(nether, coordinate_scale_ratio=1 / 8)

    assert returned is state
    assert state.dimension_id == "nether"
    assert (state.center_x, state.center_z) == (100.0, -20.0)
    assert state.scale == 2.0
    assert state.style == "topview"
    assert state.layers is layers
    assert state.selection is None
    assert state.generation == 8


def test_set_style_only_increments_generation_when_style_changes() -> None:
    state = MapViewState(generation=3)

    assert state.set_style("topview") is state
    assert state.generation == 3
    state.set_style("terrain")

    assert state.style == "terrain"
    assert state.generation == 4


def test_map_export_spec_validates_style_and_scale() -> None:
    assert MapExportSpec() == MapExportSpec(
        dimension_id="overworld",
        style="topview",
        scale=1,
        selection=None,
    )
    assert MapExportSpec(style="terrain", scale=4).scale == 4

    with pytest.raises(ValueError, match="style"):
        MapExportSpec(style="unknown")
    with pytest.raises(ValueError, match="scale"):
        MapExportSpec(scale=0)
