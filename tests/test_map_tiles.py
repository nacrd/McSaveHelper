import pytest

from core.mca.map_tiles import (
    HIGH_DETAIL_TILE_LADDER,
    MapTileRequest,
    choose_tile_size,
    plan_visible_requests,
    prioritize_regions,
)


def test_choose_tile_size_uses_cached_lod_ladder() -> None:
    assert choose_tile_size(1) == 16
    assert choose_tile_size(16) == 16
    assert choose_tile_size(17) == 32
    assert choose_tile_size(80) == 128
    assert choose_tile_size(900) == 256


def test_choose_tile_size_normalizes_custom_ladder() -> None:
    assert choose_tile_size(20, (64, 16, 16, 32)) == 32
    assert choose_tile_size(300, HIGH_DETAIL_TILE_LADDER) == 512
    with pytest.raises(ValueError, match="不能为空"):
        choose_tile_size(20, ())


def test_visible_region_priority_is_center_first_and_deduplicated() -> None:
    coords = [(4, 0), (1, 1), (0, 0), (-1, 0), (1, 1)]

    assert prioritize_regions(coords, center=(0, 0)) == [
        (0, 0),
        (-1, 0),
        (1, 1),
        (4, 0),
    ]


def test_visible_request_plan_keeps_one_lod_for_the_frame() -> None:
    requests = plan_visible_requests(
        [(2, 0), (0, 0), (1, 0)],
        screen_tile_pixels=70,
        center=(1, 0),
    )

    assert requests == [
        MapTileRequest((1, 0), 128, 0),
        MapTileRequest((0, 0), 128, 1),
        MapTileRequest((2, 0), 128, 2),
    ]
