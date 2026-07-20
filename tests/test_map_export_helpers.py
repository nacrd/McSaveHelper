"""Helpers for the map-export renderer that reuses map topview tiles."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from core.mca.map_export_renderer import MapExportRenderer, MapRenderCancelled
from core.mca.topview_renderer import LEAF_TILE_SIZE


def test_map_image_spec_calculates_dimensions_and_memory() -> None:
    spec = MapExportRenderer.calculate_image_spec(
        {"min_x": 0, "max_x": 1, "min_z": -1, "max_z": 0},
        scale=2,
    )

    assert (spec.width, spec.height) == (512, 512)
    assert spec.estimated_mb == pytest.approx(0.75)


def test_map_image_spec_rejects_oversized_dimensions() -> None:
    with pytest.raises(ValueError, match="图像尺寸过大"):
        MapExportRenderer.calculate_image_spec(
            {"min_x": 0, "max_x": 100, "min_z": 0, "max_z": 0},
            scale=1,
        )


def _solid_tile_png(color: tuple[int, int, int] = (34, 139, 34)) -> bytes:
    image = Image.new("RGB", (LEAF_TILE_SIZE, LEAF_TILE_SIZE), color)
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    image.close()
    return buffer.getvalue()


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
