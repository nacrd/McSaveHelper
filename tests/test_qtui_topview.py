"""Qt 俯视瓦片首批测试。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray
from PySide6.QtGui import QPixmap

from app.qtui.views.region_map_canvas import QtRegionMapCanvas
from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.region_map import RegionMapService
from core.mca import WritableRegion
import core.nbt as nbtlib


def test_canvas_display_mode_and_tile_paint(qt_app: object) -> None:
    del qt_app
    canvas = QtRegionMapCanvas(lambda *_args: None)
    canvas.resize(400, 300)
    canvas.set_regions({(0, 0): 1024, (1, 0): 2048})
    assert canvas.display_mode == "activity"
    canvas.set_display_mode("topview")
    assert canvas.display_mode == "topview"
    pix = QPixmap(16, 16)
    pix.fill()
    payload = QByteArray()
    buffer = QBuffer(payload)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    pix.save(buffer, "PNG")
    canvas.set_tile((0, 0), bytes(payload.data()))
    assert (0, 0) in canvas._tiles
    visible = canvas.visible_regions()
    assert visible
    canvas.clear_tiles()
    assert not canvas._tiles


def test_seed_region_inventory_enables_topview_path(tmp_path: Path) -> None:
    runtime = ExecutionRuntime(
        io_limits=LaneLimits(max_workers=2, queue_capacity=8),
        cpu_limits=LaneLimits(max_workers=2, queue_capacity=8),
    )
    service = RegionMapService(runtime)
    region_dir = tmp_path / "region"
    region_dir.mkdir()
    path = region_dir / "r.0.0.mca"
    writer = WritableRegion.empty(path)
    writer.set_chunk(0, 0, nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "xPos": nbtlib.Int(0),
        "zPos": nbtlib.Int(0),
        "Status": nbtlib.String("full"),
    }))
    writer.save(path, backup=False)
    service.seed_region_inventory(
        {(0, 0): path},
        sizes={(0, 0): path.stat().st_size},
    )
    assert service.get_region_path((0, 0)) is not None
    accepted = service.request_topview_tiles([(0, 0)], tile_size=16)
    assert (0, 0) in accepted or service.has_topview_tile((0, 0))
    service.close()
    runtime.shutdown(wait=True, timeout=3.0)


def test_canvas_tile_scale_and_grid_thresholds(qt_app: object) -> None:
    del qt_app
    canvas = QtRegionMapCanvas(lambda *_args: None)
    canvas.resize(640, 480)
    canvas.set_regions({(0, 0): 1024})
    # region_px = 512 * scale; tile_scale = region_px / 32 = 16 * scale
    canvas.set_camera(256.0, 256.0, 0.1)
    assert abs(canvas.tile_scale - 1.6) < 1e-6
    canvas.set_camera(256.0, 256.0, 0.5)
    assert canvas.tile_scale >= canvas._CHUNK_GRID_TILE_SCALE
    canvas.set_camera(256.0, 256.0, 1.5)
    assert canvas.tile_scale >= canvas._BLOCK_GRID_TILE_SCALE
