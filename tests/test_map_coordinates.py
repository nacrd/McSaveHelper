from core.mca.map_coordinates import (
    chunk_block_bounds,
    format_chunk_block_range,
    format_region_block_range,
    format_region_coordinate_label,
    region_block_bounds,
)


def test_region_and_chunk_bounds_support_negative_coordinates() -> None:
    region = region_block_bounds((-2, 3))
    chunk = chunk_block_bounds((-1, -2))
    assert (region.min_x, region.max_x, region.min_z, region.max_z) == (
        -1024,
        -513,
        1536,
        2047,
    )
    assert (chunk.min_x, chunk.max_x, chunk.min_z, chunk.max_z) == (
        -16,
        -1,
        -32,
        -17,
    )


def test_block_range_formatting_is_inclusive() -> None:
    assert format_region_block_range((0, 0)) == "X 0~511, Z 0~511"
    assert format_chunk_block_range((2, -1)) == "X 32~47, Z -16~-1"


def test_region_coordinate_labels_progress_with_zoom() -> None:
    coord = (-1, 2)

    assert format_region_coordinate_label(
        coord,
        view_level="world",
        scale=1.0,
        cell_size=32,
    ) == "-1,2"
    assert format_region_coordinate_label(
        coord,
        view_level="region",
        scale=2.4,
        cell_size=80,
    ) == "-512~-1"
    assert format_region_coordinate_label(
        coord,
        view_level="region",
        scale=3.0,
        cell_size=100,
    ) == "X-512~-1\nZ1024~1535"
    assert format_region_coordinate_label(
        coord,
        view_level="chunk",
        scale=3.0,
        cell_size=100,
    ) == "-256, 1280"
