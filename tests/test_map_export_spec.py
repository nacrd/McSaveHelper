"""地图导出领域规格测试。"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from PIL import Image

from app.services.map_export_service import MapExportService
from core.mca.map_export_renderer import MapExportRenderer, MapRenderCancelled
from core.mca.map_models import MapExportSpec, MapSelection


class _FakeRenderer(MapExportRenderer):
    def __init__(self) -> None:
        super().__init__()
        self.last_rendered_chunks = 1
        self.calls: list[dict[str, Any]] = []

    def create_map_image(self, *args: Any, **kwargs: Any) -> Image.Image:
        self.calls.append({"args": args, "kwargs": kwargs})
        block_bounds = kwargs.get("block_bounds")
        if block_bounds is None:
            size = (32 * 16, 32 * 16)
        else:
            min_x, min_z, max_x, max_z = block_bounds
            scale = int(args[3])
            size = (
                (max_x - min_x + 1 + scale - 1) // scale,
                (max_z - min_z + 1 + scale - 1) // scale,
            )
        return Image.new("RGB", size, (1, 2, 3))


def _region(path: Path, *coords: tuple[int, int]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for x, z in coords:
        (path / f"r.{x}.{z}.mca").touch()
    return path


def test_export_resolves_dimension_and_explicit_region_priority(tmp_path: Path) -> None:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").touch()
    custom = _region(world / "dimensions" / "mod" / "custom" / "region", (3, 4))
    explicit = _region(tmp_path / "explicit-region", (8, 9))

    service = MapExportService()
    fake = _FakeRenderer()
    service._renderer = fake
    result = service.export_map(
        world,
        tmp_path / "custom.png",
        spec=MapExportSpec(dimension_id="mod:custom", scale=2),
    )
    assert result["success"] is True
    assert fake.calls[0]["args"][0] == [custom / "r.3.4.mca"]
    result = service.export_map(
        world,
        tmp_path / "explicit.png",
        spec=MapExportSpec(dimension_id="missing:dimension"),
        region_dir=explicit,
    )
    assert result["success"] is True
    assert fake.calls[1]["args"][0] == [explicit / "r.8.9.mca"]


def test_export_filters_regions_and_crops_negative_selection(tmp_path: Path) -> None:
    world = tmp_path / "world"
    region_dir = _region(
        world / "region",
        (-2, -2),
        (-1, -1),
        (0, 0),
    )
    (world / "level.dat").touch()
    selection = MapSelection(-513, -513, -1, -1)
    service = MapExportService()
    fake = _FakeRenderer()
    service._renderer = fake

    result = service.export_map(
        world,
        tmp_path / "selection.png",
        spec=MapExportSpec(selection=selection, scale=16),
    )

    assert result["success"] is True
    assert result["selection_bounds"] == (-513, -513, -1, -1)
    assert result["dimensions"] == (33, 33)
    image_spec = MapExportRenderer.calculate_image_spec(
        result["region_bounds"],
        scale=16,
        block_bounds=selection.block_bounds,
    )
    assert (image_spec.width, image_spec.height) == (33, 33)
    scanned = fake.calls[0]["args"][0]
    assert scanned == [region_dir / "r.-1.-1.mca", region_dir / "r.-2.-2.mca"]


def test_renderer_uses_negative_selection_as_image_origin() -> None:
    class FixedHeightRenderer(MapExportRenderer):
        def highest_block_y(self, chunk: Any, x: int, z: int) -> int:
            return 64

    renderer = FixedHeightRenderer()

    class Chunk:
        @staticmethod
        def get_block(_x: int, _y: int, _z: int) -> Any:
            return type("Block", (), {"name": lambda self: "minecraft:stone"})()

    image = Image.new("RGB", (1, 1), (0, 0, 0))
    try:
        renderer._render_chunk(
            image,
            Chunk(),
            -1,
            -1,
            31,
            31,
            {"min_x": -1, "max_x": -1, "min_z": -1, "max_z": -1},
            "topview",
            1,
            block_bounds=(-1, -1, -1, -1),
        )
        assert image.getpixel((0, 0)) == (128, 128, 128)
    finally:
        image.close()


def test_export_cancellation_removes_output(tmp_path: Path) -> None:
    world = tmp_path / "world"
    _region(world / "region", (0, 0))
    (world / "level.dat").touch()
    output = tmp_path / "cancelled.png"
    cancel_event = threading.Event()
    cancel_event.set()

    service = MapExportService()
    fake = _FakeRenderer()
    service._renderer = fake
    result = service.export_map(world, output, cancel_event=cancel_event)

    assert result["success"] is False
    assert result["cancelled"] is True
    assert result["output_path"] is None
    assert not output.exists()
    assert fake.calls == []


def test_renderer_cancellation_does_not_leave_file(tmp_path: Path) -> None:
    world = tmp_path / "world"
    _region(world / "region", (0, 0))
    (world / "level.dat").touch()
    output = tmp_path / "cancelled-render.png"
    cancel_event = threading.Event()

    class CancellingRenderer(_FakeRenderer):
        def create_map_image(self, *args: Any, **kwargs: Any) -> Image.Image:
            cancel_event.set()
            raise MapRenderCancelled("cancelled")

    service = MapExportService()
    service._renderer = CancellingRenderer()
    result = service.export_map(world, output, cancel_event=cancel_event)

    assert result["cancelled"] is True
    assert not output.exists()
