"""Qt 俯视瓦片首批测试。"""
from __future__ import annotations

from pathlib import Path
from threading import Lock
from types import SimpleNamespace

from PySide6.QtCore import QBuffer, QByteArray
from PySide6.QtGui import QPixmap

from app.qtui.views.region_map_canvas import QtRegionMapCanvas
from app.qtui.views import region_map_coordinator as coordinator_module
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


def test_canvas_coalesces_drag_camera_callbacks(qt_app: object) -> None:
    del qt_app
    events: list[tuple[float, float, float]] = []
    canvas = QtRegionMapCanvas(
        lambda *_args: None,
        lambda x, z, scale: events.append((x, z, scale)),
    )

    canvas._emit_camera(immediate=False)
    canvas._center_x = 128.0
    canvas._emit_camera(immediate=False)

    assert events == []
    assert canvas._camera_emit_pending is True

    canvas._flush_camera()

    assert events == [(128.0, 0.0, canvas.scale)]
    assert canvas._camera_emit_pending is False


def test_canvas_reuses_revision_and_bounds_native_tile_cache(qt_app: object) -> None:
    del qt_app
    canvas = QtRegionMapCanvas(lambda *_args: None)
    pix = QPixmap(32, 32)
    pix.fill()
    payload = QByteArray()
    buffer = QBuffer(payload)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    pix.save(buffer, "PNG")
    png = bytes(payload.data())

    assert canvas.set_tile((0, 0), png, revision=1) is True
    original = canvas._tiles[(0, 0)]
    original_bytes = canvas._tile_memory_bytes
    for _index in range(1000):
        assert canvas.set_tile((0, 0), b"invalid", revision=1) is True

    assert canvas._tiles[(0, 0)] is original
    assert canvas._tile_memory_bytes == original_bytes

    canvas.__dict__["_TILE_CACHE_ENTRY_LIMIT"] = 2
    canvas.__dict__["_TILE_CACHE_MEMORY_LIMIT"] = original_bytes * 2
    assert canvas.set_tile((1, 0), png, revision=2) is True
    canvas.set_tile((0, 0), b"invalid", revision=1)
    assert canvas.set_tile((2, 0), png, revision=3) is True

    assert tuple(canvas._tiles) == ((0, 0), (2, 0))
    assert (1, 0) not in canvas._tile_revisions
    assert canvas._tile_memory_bytes <= canvas._TILE_CACHE_MEMORY_LIMIT


def test_region_map_coalesces_tile_ready_ui_dispatches(monkeypatch) -> None:
    coordinator = object.__new__(coordinator_module.QtRegionMapCoordinator)
    coordinator._tile_ready_lock = Lock()
    coordinator._pending_tile_ready = set()
    coordinator._tile_ready_dispatch_pending = False
    coordinator._closed = False
    dispatched: list[object] = []
    monkeypatch.setattr(
        coordinator_module,
        "run_on_ui",
        lambda callback: dispatched.append(callback),
    )

    coordinator._on_topview_tile_ready((0, 0))
    coordinator._on_topview_tile_ready((0, 0))
    coordinator._on_topview_tile_ready((1, 0))

    assert len(dispatched) == 1
    assert coordinator._pending_tile_ready == {(0, 0), (1, 0)}


def test_region_map_pauses_queued_tiles_while_dragging() -> None:
    class _Canvas:
        is_dragging = True

    class _MapController:
        def __init__(self) -> None:
            self.camera_updates: list[tuple[float, float, float]] = []

        def update_camera(self, x: float, z: float, scale: float) -> None:
            self.camera_updates.append((x, z, scale))

    class _MapService:
        def __init__(self) -> None:
            self.retained: list[set[tuple[int, int]]] = []

        def retain_topview_requests(self, coords: set[tuple[int, int]]) -> int:
            self.retained.append(coords)
            return 0

    class _Requests:
        def __init__(self) -> None:
            self.reset_count = 0

        def reset(self) -> None:
            self.reset_count += 1

    canvas = _Canvas()
    controller = _MapController()
    service = _MapService()
    requests = _Requests()
    coordinator = object.__new__(coordinator_module.QtRegionMapCoordinator)
    coordinator.__dict__["panel"] = SimpleNamespace(canvas=canvas)
    coordinator.__dict__["_map_controller"] = controller
    coordinator.__dict__["_map_service"] = service
    coordinator.__dict__["_tile_requests"] = requests

    coordinator._on_camera_changed(128.0, 256.0, 0.5)

    assert controller.camera_updates == [(128.0, 256.0, 0.5)]
    assert service.retained == [set()]
    assert requests.reset_count == 1

    canvas.is_dragging = False
    requested: list[bool] = []
    coordinator.__dict__["_request_visible_tiles"] = lambda: requested.append(True)
    coordinator._on_camera_changed(128.0, 256.0, 0.5)

    assert requested == [True]


def test_region_map_flush_applies_only_currently_visible_tiles() -> None:
    class _Canvas:
        def __init__(self) -> None:
            self.applied: list[tuple[tuple[int, int], bytes, int]] = []

        @staticmethod
        def visible_regions() -> list[tuple[int, int]]:
            return [(0, 0)]

        def set_tile(
            self,
            coord: tuple[int, int],
            png: bytes,
            *,
            revision: int,
        ) -> None:
            self.applied.append((coord, png, revision))

    class _MapService:
        def __init__(self) -> None:
            self.snapshot_coords: list[tuple[int, int]] = []

        def get_topview_snapshot(
            self,
            coords: list[tuple[int, int]],
        ) -> tuple[
            int,
            dict[tuple[int, int], bytes],
            dict[tuple[int, int], int],
        ]:
            self.snapshot_coords = list(coords)
            return 1, {(0, 0): b"visible"}, {(0, 0): 7}

    class _Requests:
        def __init__(self) -> None:
            self.completed: list[tuple[int, int]] = []

        def on_tile_ready(self, coord: tuple[int, int]) -> bool:
            self.completed.append(coord)
            return True

    canvas = _Canvas()
    service = _MapService()
    requests = _Requests()
    coordinator = object.__new__(coordinator_module.QtRegionMapCoordinator)
    coordinator._tile_ready_lock = Lock()
    coordinator._pending_tile_ready = {(0, 0), (99, 99)}
    coordinator._tile_ready_dispatch_pending = True
    coordinator._closed = False
    coordinator.__dict__["panel"] = SimpleNamespace(canvas=canvas)
    coordinator.__dict__["_map_service"] = service
    coordinator.__dict__["_tile_requests"] = requests

    coordinator._flush_tile_ready()

    assert service.snapshot_coords == [(0, 0)]
    assert canvas.applied == [((0, 0), b"visible", 7)]
    assert set(requests.completed) == {(0, 0), (99, 99)}
