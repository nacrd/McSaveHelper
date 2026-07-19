from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

from PIL import Image
import pytest

from core.mca import texture_palette as texture_palette_module
from core.mca.tile_cache import cache_path_for
from core.mca.texture_palette import (
    average_block_texture,
    set_texture_jar,
    texture_jar_path,
)


def _png(color: tuple[int, int, int, int]) -> bytes:
    output = BytesIO()
    with Image.new("RGBA", (4, 4), color) as image:
        image.save(output, format="PNG")
    return output.getvalue()


def test_texture_palette_reads_top_texture_and_ignores_transparent_pixels(
    tmp_path: Path,
) -> None:
    jar_path = tmp_path / "client.jar"
    with zipfile.ZipFile(jar_path, "w") as archive:
        archive.writestr(
            "assets/minecraft/textures/block/test_block.png",
            _png((10, 20, 30, 255)),
        )
        archive.writestr(
            "assets/minecraft/textures/block/layered_top.png",
            _png((90, 120, 150, 255)),
        )

    set_texture_jar(jar_path)
    try:
        assert average_block_texture("minecraft:test_block") == (10, 20, 30)
        assert average_block_texture("minecraft:layered") == (90, 120, 150)
        assert texture_jar_path() == jar_path
    finally:
        set_texture_jar(None)


def test_texture_palette_returns_none_for_missing_asset(tmp_path: Path) -> None:
    jar_path = tmp_path / "client.jar"
    with zipfile.ZipFile(jar_path, "w"):
        pass

    set_texture_jar(jar_path)
    try:
        assert average_block_texture("minecraft:not_present") is None
    finally:
        set_texture_jar(None)


def test_tile_cache_key_changes_with_texture_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    region_path = tmp_path / "r.0.0.mca"
    region_path.write_bytes(b"region")
    jar_path = tmp_path / "client.jar"
    with zipfile.ZipFile(jar_path, "w"):
        pass
    monkeypatch.setattr(texture_palette_module, "_discover_jar", lambda: None)

    set_texture_jar(None)
    fallback_path = cache_path_for(region_path, 64)
    set_texture_jar(jar_path)
    try:
        jar_path_key = cache_path_for(region_path, 64)
    finally:
        set_texture_jar(None)

    assert jar_path_key != fallback_path
