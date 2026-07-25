"""Helpers for the map-export renderer that reuses map topview tiles."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from core.mca.format import HEADER_SIZE
from core.mca.map_export_bounds import analyze_loaded_map_content
from core.mca.map_export_renderer import (
    MapExportRenderer,
    MapRenderCancelled,
)
from core.mca.region_file import local_chunk_index
from core.mca.topview_renderer import LEAF_TILE_SIZE


def test_map_image_spec_calculates_dimensions_and_memory() -> None:
    spec = MapExportRenderer.calculate_image_spec(
        {"min_x": 0, "max_x": 1, "min_z": -1, "max_z": 0},
        scale=2,
    )

    assert (spec.width, spec.height) == (512, 512)
    assert spec.estimated_mb == pytest.approx(0.75)


def test_map_image_spec_allows_dimensions_that_require_streaming() -> None:
    bounds = {"min_x": 0, "max_x": 209, "min_z": 0, "max_z": 214}

    spec = MapExportRenderer.calculate_image_spec(bounds, scale=1)

    assert (spec.width, spec.height) == (107520, 110080)
    assert spec.estimated_mb > 32_000


def _solid_tile_png(color: tuple[int, int, int] = (34, 139, 34)) -> bytes:
    image = Image.new("RGB", (LEAF_TILE_SIZE, LEAF_TILE_SIZE), color)
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    image.close()
    return buffer.getvalue()


def _region_header_with_chunks(*chunks: tuple[int, int]) -> bytes:
    header = bytearray(HEADER_SIZE)
    for local_x, local_z in chunks:
        offset = local_chunk_index(local_x, local_z) * 4
        header[offset:offset + 3] = (2).to_bytes(3, "big")
        header[offset + 3] = 1
    return bytes(header)


def test_loaded_content_bounds_ignore_empty_region_padding(tmp_path: Path) -> None:
    first = tmp_path / "r.0.0.mca"
    distant = tmp_path / "r.3.-2.mca"
    empty = tmp_path / "r.10.10.mca"
    first.write_bytes(_region_header_with_chunks((10, 12)))
    distant.write_bytes(_region_header_with_chunks((1, 2)))
    empty.write_bytes(_region_header_with_chunks())

    content = analyze_loaded_map_content([first, distant, empty])

    assert content.region_files == (first, distant)
    assert content.block_bounds == (160, -992, 1567, 207)
    assert content.chunk_count == 2


def test_create_map_image_uses_topview_renderer(tmp_path: Path) -> None:
    region = tmp_path / "r.0.0.mca"
    region.write_bytes(b"\x00" * 16)
    renderer = MapExportRenderer()
    logs: list[str] = []

    with patch(
        "core.mca.map_export_renderer.render_region_topview",
        return_value=_solid_tile_png(),
    ) as render:
        image = renderer.create_map_image(
            [region],
            {"min_x": 0, "max_x": 0, "min_z": 0, "max_z": 0},
            "topview",
            scale=16,
            log=lambda message, _level: logs.append(message),
            progress=lambda *_args: None,
        )
        try:
            assert image.size == (32, 32)
            assert image.getpixel((0, 0)) == (34, 139, 34)
            assert renderer.last_rendered_chunks == 32 * 32
            render.assert_called_once()
            assert render.call_args.kwargs["tile_size"] == LEAF_TILE_SIZE
            assert any("地图俯视渲染" in message for message in logs)
        finally:
            image.close()


def test_create_map_image_composes_directly_at_export_scale(tmp_path: Path) -> None:
    first_region = tmp_path / "r.0.0.mca"
    second_region = tmp_path / "r.1.0.mca"
    first_region.write_bytes(b"\x00" * 16)
    second_region.write_bytes(b"\x00" * 16)
    renderer = MapExportRenderer()
    red_tile = _solid_tile_png((255, 0, 0))
    blue_tile = _solid_tile_png((0, 0, 255))

    def render_tile(region_file: Path, **_kwargs: object) -> bytes:
        return red_tile if region_file == first_region else blue_tile

    with patch(
        "core.mca.map_export_renderer.Image.new",
        wraps=Image.new,
    ) as create_image, patch(
        "core.mca.map_export_renderer.render_region_topview",
        side_effect=render_tile,
    ):
        image = renderer.create_map_image(
            [first_region, second_region],
            {"min_x": 0, "max_x": 1, "min_z": 0, "max_z": 0},
            "topview",
            scale=4,
            log=lambda *_args: None,
            progress=lambda *_args: None,
        )
    try:
        assert image.size == (256, 128)
        assert image.getpixel((0, 0)) == (255, 0, 0)
        assert image.getpixel((128, 0)) == (0, 0, 255)
        assert create_image.call_args_list[0].args[1] == (256, 128)
    finally:
        image.close()


def test_save_map_image_streams_full_resolution_png(tmp_path: Path) -> None:
    region = tmp_path / "r.0.0.mca"
    region.write_bytes(b"\x00" * 16)
    output = tmp_path / "streamed.png"
    renderer = MapExportRenderer()

    with patch.object(
        MapExportRenderer,
        "MAX_IMAGE_DIMENSION",
        8,
    ), patch(
        "core.mca.map_export_renderer.render_region_topview",
        return_value=_solid_tile_png((12, 34, 56)),
    ):
        spec = renderer.save_map_image(
            output,
            [region],
            {"min_x": 0, "max_x": 0, "min_z": 0, "max_z": 0},
            "topview",
            scale=1,
            log=lambda *_args: None,
            progress=lambda *_args: None,
            block_bounds=(0, 0, 15, 15),
        )

    with Image.open(output) as image:
        assert spec.width == 16
        assert spec.height == 16
        assert image.size == (16, 16)
        assert image.getpixel((15, 15)) == (12, 34, 56)


def test_save_full_map_crops_to_loaded_chunk_bounds(tmp_path: Path) -> None:
    region = tmp_path / "r.0.0.mca"
    region.write_bytes(_region_header_with_chunks((5, 6)))
    output = tmp_path / "cropped.png"
    logs: list[str] = []
    renderer = MapExportRenderer()

    with patch(
        "core.mca.map_export_renderer.render_region_topview",
        return_value=_solid_tile_png((45, 67, 89)),
    ):
        spec = renderer.save_map_image(
            output,
            [region],
            {"min_x": 0, "max_x": 0, "min_z": 0, "max_z": 0},
            "topview",
            scale=1,
            log=lambda message, _level: logs.append(message),
            progress=lambda *_args: None,
        )

    with Image.open(output) as image:
        assert (spec.width, spec.height) == (16, 16)
        assert image.size == (16, 16)
        assert image.getpixel((15, 15)) == (45, 67, 89)
    assert any("512x512 裁剪为 16x16" in message for message in logs)


def test_streaming_png_preserves_pixels_across_region_boundaries(
    tmp_path: Path,
) -> None:
    colors = {
        (0, 0): (255, 0, 0),
        (1, 0): (0, 255, 0),
        (0, 1): (0, 0, 255),
        (1, 1): (255, 255, 0),
    }
    regions: list[Path] = []
    tile_pngs: dict[Path, bytes] = {}
    for (region_x, region_z), color in colors.items():
        region = tmp_path / f"r.{region_x}.{region_z}.mca"
        region.write_bytes(b"\x00" * 16)
        regions.append(region)
        tile_pngs[region] = _solid_tile_png(color)

    output = tmp_path / "boundary.png"
    renderer = MapExportRenderer()
    with patch.object(
        MapExportRenderer,
        "MAX_IMAGE_DIMENSION",
        1,
    ), patch(
        "core.mca.map_export_renderer.render_region_topview",
        side_effect=lambda path, **_kwargs: tile_pngs[path],
    ):
        renderer.save_map_image(
            output,
            regions,
            {"min_x": 0, "max_x": 1, "min_z": 0, "max_z": 1},
            "topview",
            scale=1,
            log=lambda *_args: None,
            progress=lambda *_args: None,
            block_bounds=(510, 510, 513, 513),
        )

    with Image.open(output) as image:
        assert image.size == (4, 4)
        assert image.getpixel((0, 0)) == colors[(0, 0)]
        assert image.getpixel((3, 0)) == colors[(1, 0)]
        assert image.getpixel((0, 3)) == colors[(0, 1)]
        assert image.getpixel((3, 3)) == colors[(1, 1)]


def test_create_map_image_honours_cancellation(tmp_path: Path) -> None:
    import threading

    region = tmp_path / "r.0.0.mca"
    region.write_bytes(b"\x00" * 16)
    cancel = threading.Event()
    cancel.set()
    renderer = MapExportRenderer()

    with pytest.raises(MapRenderCancelled):
        renderer.create_map_image(
            [region],
            {"min_x": 0, "max_x": 0, "min_z": 0, "max_z": 0},
            "topview",
            scale=16,
            log=lambda *_args: None,
            progress=lambda *_args: None,
            cancel_event=cancel,
        )


def test_create_map_image_crops_block_selection(tmp_path: Path) -> None:
    region = tmp_path / "r.0.0.mca"
    region.write_bytes(b"\x00" * 16)
    renderer = MapExportRenderer()

    with patch(
        "core.mca.map_export_renderer.render_region_topview",
        return_value=_solid_tile_png((10, 20, 30)),
    ):
        image = renderer.create_map_image(
            [region],
            {"min_x": 0, "max_x": 0, "min_z": 0, "max_z": 0},
            "topview",
            scale=1,
            log=lambda *_args: None,
            progress=lambda *_args: None,
            block_bounds=(0, 0, 15, 15),
        )
        try:
            assert image.size == (16, 16)
            assert image.getpixel((0, 0)) == (10, 20, 30)
        finally:
            image.close()


def test_unreadable_regions_raise_when_nothing_renders(tmp_path: Path) -> None:
    region = tmp_path / "r.0.0.mca"
    region.write_bytes(b"\x00" * 16)
    renderer = MapExportRenderer()

    with patch(
        "core.mca.map_export_renderer.render_region_topview",
        return_value=None,
    ):
        with pytest.raises(ValueError, match="均不可读"):
            renderer.create_map_image(
                [region],
                {"min_x": 0, "max_x": 0, "min_z": 0, "max_z": 0},
                "topview",
                scale=16,
                log=lambda *_args: None,
                progress=lambda *_args: None,
            )
