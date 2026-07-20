from io import BytesIO
from typing import cast

import pytest
from PIL import Image

from app.ui.views.explorer.map.surface_renderer import (
    MapSurfaceRenderer,
    MapSurfaceSpec,
)


def _png(color: tuple[int, int, int], size: int = 8) -> bytes:
    output = BytesIO()
    with Image.new("RGB", (size, size), color) as image:
        image.save(output, format="PNG")
    return output.getvalue()


def _checker_png(size: int = 4) -> bytes:
    output = BytesIO()
    with Image.new("RGB", (size, size)) as image:
        image.putdata(
            [
                (255, 255, 255) if (x + y) % 2 else (0, 0, 0)
                for y in range(size)
                for x in range(size)
            ]
        )
        image.save(output, format="PNG")
    return output.getvalue()


def test_surface_tiles_share_one_exact_pixel_boundary() -> None:
    renderer = MapSurfaceRenderer()
    spec = MapSurfaceSpec(0, 1, 0, 0, pixels_per_region=4)

    frame = renderer.compose(
        spec,
        {(0, 0): 1, (1, 0): 1},
        {(0, 0): _png((220, 20, 20)), (1, 0): _png((20, 80, 220))},
        {(0, 0): 1, (1, 0): 1},
        {(0, 0): (0, 0, 0), (1, 0): (0, 0, 0)},
    )

    image = Image.frombytes("RGBA", (frame.width, frame.height), frame.pixels)
    assert image.getpixel((3, 1)) == (220, 20, 20, 255)
    assert image.getpixel((4, 1)) == (20, 80, 220, 255)
    assert image.getchannel("A").getextrema() == (255, 255)


def test_missing_tile_uses_opaque_region_color_without_a_seam() -> None:
    renderer = MapSurfaceRenderer()
    spec = MapSurfaceSpec(-1, 0, 0, 0, pixels_per_region=3)

    frame = renderer.compose(
        spec,
        {(-1, 0): 1, (0, 0): 1},
        {(-1, 0): _png((1, 2, 3))},
        {(-1, 0): 1, (0, 0): 0},
        {(-1, 0): (9, 9, 9), (0, 0): (40, 90, 50)},
    )

    image = Image.frombytes("RGBA", (frame.width, frame.height), frame.pixels)
    assert image.getpixel((2, 1)) == (1, 2, 3, 255)
    assert image.getpixel((3, 1)) == (40, 90, 50, 255)


def test_surface_downsampling_preserves_mixed_terrain_coverage() -> None:
    renderer = MapSurfaceRenderer()
    spec = MapSurfaceSpec(0, 0, 0, 0, pixels_per_region=1)

    frame = renderer.compose(
        spec,
        {(0, 0): 1},
        {(0, 0): _checker_png()},
        {(0, 0): 1},
        {(0, 0): (0, 0, 0)},
    )

    image = Image.frombytes("RGBA", (frame.width, frame.height), frame.pixels)
    red, green, blue, alpha = cast(
        tuple[int, int, int, int],
        image.getpixel((0, 0)),
    )
    assert 110 <= red <= 145
    assert (green, blue, alpha) == (red, red, 255)


def test_surface_spec_rejects_more_than_sixteen_megapixels() -> None:
    with pytest.raises(ValueError, match="16 megapixel"):
        MapSurfaceSpec(0, 99, 0, 99, pixels_per_region=41)
