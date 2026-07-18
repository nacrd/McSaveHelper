from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from core.mca.map_export_renderer import MapExportRenderer


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


def test_highest_block_uses_native_surface_fast_path() -> None:
    chunk = SimpleNamespace(
        _blocks=SimpleNamespace(surface_y=lambda _x, _z: 72),
    )

    assert MapExportRenderer().highest_block_y(chunk, 1, 2) == 72


def test_highest_block_falls_back_when_native_surface_is_missing(
    monkeypatch: Any,
) -> None:
    class Chunk:
        _blocks = SimpleNamespace(surface_y=lambda _x, _z: None)

        @staticmethod
        def get_block(_x: int, y: int, _z: int) -> Any:
            block_id = "minecraft:stone" if y == 20 else "minecraft:air"
            return SimpleNamespace(id=block_id)

    renderer = MapExportRenderer()
    monkeypatch.setattr(
        renderer,
        "_get_non_air_sections",
        lambda _chunk: [1],
    )

    assert renderer.highest_block_y(Chunk(), 0, 0) == 20


def test_fallback_grid_supports_scales_larger_than_chunk_width() -> None:
    image = Image.new("RGB", (4, 4))
    try:
        MapExportRenderer.draw_fallback_grid(image, scale=32)
        assert image.getpixel((0, 0)) == (200, 200, 200)
    finally:
        image.close()
