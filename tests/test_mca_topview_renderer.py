"""Top-view cache completeness tests."""
from pathlib import Path
from typing import Any

import pytest

from core.mca import topview_renderer


def test_partial_mod_tile_is_returned_but_not_persisted(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    region_path = tmp_path / "r.0.0.mca"
    region_path.write_bytes(b"placeholder")
    stored = []

    def partial_grid(_path, tile_size, **kwargs):
        kwargs["status_out"].append(False)
        return [[(30, 40, 50)] * tile_size for _ in range(tile_size)]

    monkeypatch.setattr(topview_renderer, "_load_cached_tile", lambda *_args: None)
    monkeypatch.setattr(topview_renderer, "_sample_surface_grid", partial_grid)
    monkeypatch.setattr(
        topview_renderer,
        "_store_cached_tile",
        lambda *args: stored.append(args),
    )

    status = []
    png = topview_renderer.render_region_topview(
        region_path,
        tile_size=32,
        status_out=status,
    )

    assert png is not None
    assert status == [False]
    assert stored == []


@pytest.mark.parametrize(
    "block_name",
    (
        "minecraft:oak_stairs",
        "minecraft:oak_slab",
        "minecraft:oak_wall",
        "minecraft:oak_fence",
        "minecraft:oak_trapdoor",
        "minecraft:oak_door",
        "minecraft:oak_fence_gate",
    ),
)
def test_wood_structural_variants_share_a_stable_material_color(
    block_name: str,
) -> None:
    color = topview_renderer._color_for_block_name(block_name)

    assert color == topview_renderer._color_for_block_name("minecraft:oak_planks")
    assert color != topview_renderer._color_for_block_name("minecraft:unknown_block")


@pytest.mark.parametrize(
    ("block_name", "expected_name"),
    (
        ("minecraft:dirt_path", "minecraft:dirt"),
        ("minecraft:grass_path", "minecraft:dirt"),
        ("modded:WATER", "minecraft:water"),
        ("modded:GRASS_BLOCK", "minecraft:grass_block"),
        ("modded:OAK_LEAVES", "minecraft:oak_leaves"),
    ),
)
def test_surface_material_aliases_keep_water_grass_leaf_and_path_colors(
    block_name: str,
    expected_name: str,
) -> None:
    assert topview_renderer._color_for_block_name(block_name) == (
        topview_renderer._color_for_block_name(expected_name)
    )


@pytest.mark.parametrize(
    ("block_name", "expected_name"),
    (
        ("minecraft:cobblestone_wall", "minecraft:cobblestone"),
        ("minecraft:mossy_cobblestone_wall", "minecraft:mossy_cobblestone"),
        ("minecraft:red_sandstone_stairs", "minecraft:red_sandstone"),
        ("minecraft:deepslate_wall", "minecraft:deepslate"),
    ),
)
def test_stone_structural_variants_use_their_base_material(
    block_name: str,
    expected_name: str,
) -> None:
    assert topview_renderer._color_for_block_name(block_name) == (
        topview_renderer._color_for_block_name(expected_name)
    )


def test_stone_pressure_plate_does_not_inherit_wood_variant_color() -> None:
    assert topview_renderer._color_for_block_name("minecraft:stone_pressure_plate") != (
        topview_renderer._color_for_block_name("minecraft:oak_planks")
    )


@pytest.mark.parametrize(
    "block_name",
    (
        "minecraft:vine",
        "minecraft:short_grass",
        "minecraft:fern",
        "minecraft:leaf_litter",
        "minecraft:dandelion",
        "minecraft:sweet_berry_bush",
        "minecraft:lily_pad",
        "minecraft:seagrass",
        "minecraft:tall_seagrass",
        "minecraft:kelp",
        "minecraft:sugar_cane",
    ),
)
def test_natural_surface_blocks_never_use_hashed_fallback(
    block_name: str,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(topview_renderer, "average_block_texture", lambda _name: None)

    color = topview_renderer._color_for_block_name(block_name)

    assert max(color) - min(color) < 90
    assert color != topview_renderer._color_for_block_name("minecraft:unknown_block")


def test_biome_tint_changes_grass_leaves_and_water_but_not_stone(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(topview_renderer, "average_block_texture", lambda _name: None)

    for block_name in (
        "minecraft:grass_block",
        "minecraft:oak_leaves",
        "minecraft:water",
    ):
        base = topview_renderer._color_for_block_name(block_name)
        forest = topview_renderer._color_for_surface_sample(
            block_name,
            "minecraft:forest",
        )
        assert forest != base

    stone = topview_renderer._color_for_block_name("minecraft:stone")
    assert topview_renderer._color_for_surface_sample(
        "minecraft:stone",
        "minecraft:forest",
    ) == stone


def test_gray_tint_mask_texture_falls_back_before_biome_tint(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        topview_renderer,
        "average_block_texture",
        lambda _name: (120, 120, 120),
    )

    base = topview_renderer._color_for_block_name("minecraft:grass_block")
    tinted = topview_renderer._color_for_surface_sample(
        "minecraft:grass_block",
        "minecraft:swamp",
    )

    assert base == topview_renderer.BLOCK_COLORS["minecraft:grass_block"]
    assert tinted != (120, 120, 120)


def test_colored_local_texture_is_used_for_non_tinted_material(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        topview_renderer,
        "average_block_texture",
        lambda _name: (90, 110, 130),
    )

    assert topview_renderer._color_for_block_name("minecraft:stone") == (
        90,
        110,
        130,
    )
