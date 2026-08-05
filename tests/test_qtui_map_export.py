"""Qt 地图导出对话框生命周期与预填测试。"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator, cast
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from app.presenters.map_export_state import begin_map_export
from app.qtui.views.map_export_dialog import (
    MapExportSession,
    QtMapExportDialog,
)
from app.qtui.views.region_map_coordinator import QtRegionMapCoordinator
from app.services.execution_runtime import ExecutionRuntime, TaskQueueFullError
from app.services.world_transaction import WorldTransactionResult
from core.omni.world_session import WorldSession


def _wait_until(
    predicate: Callable[[], bool],
    timeout_s: float = 3.0,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _App:
    """地图导出所需端口的最小实现。"""

    def __init__(self) -> None:
        self.runtime = ExecutionRuntime()
        self.warnings: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.infos: list[tuple[str, str]] = []
        self.progress: list[tuple[str, float]] = []
        self.save_path: str | None = None

    @staticmethod
    def translate(key: str, default: str = "", **kwargs: object) -> str:
        del key
        return default.format(**kwargs)

    def log(self, msg: str, level: str = "INFO") -> None:
        del msg, level

    def warn_dialog(self, title: str, message: str) -> None:
        self.warnings.append((title, message))

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Exception | None = None,
        show_details: bool = False,
    ) -> None:
        del exception, show_details
        self.errors.append((title, message))

    def info_dialog(self, title: str, message: str) -> None:
        self.infos.append((title, message))

    def handle_exception(
        self,
        exception: Exception,
        title: str | None = None,
        log: bool = True,
        show_dialog: bool = True,
    ) -> None:
        del log, show_dialog
        self.errors.append((title or "异常", str(exception)))

    def show_progress(self, task_name: str = "") -> None:
        self.progress.append((task_name, 0.0))

    def hide_progress(self) -> None:
        self.progress.append(("hide", 0.0))

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        self.progress.append((task_name, value))

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: list[tuple[str, str]] | None = None,
    ) -> str | None:
        del title, default_ext, file_types
        return self.save_path

    def pick_directory(self) -> str | None:
        return None

    def pick_file(self, **_kwargs: object) -> str | None:
        return None

    def pick_files(self, **_kwargs: object) -> list[str] | None:
        return None

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        return self.runtime

    @property
    def world_transactions(self) -> object:
        return SimpleNamespace(
            mutate=lambda *a, **k: WorldTransactionResult(
                value=True,
                world_path=Path("."),
                backup=cast(Any, SimpleNamespace(backup_path=Path("b"))),
            )
        )

    def close(self) -> None:
        self.runtime.shutdown(wait=True, timeout=5.0)


@pytest.fixture
def app(qt_app: object) -> Iterator[_App]:
    del qt_app
    host = _App()
    yield host
    host.close()


def test_default_output_path_uses_dimension_suffix() -> None:
    path = QtMapExportDialog.default_output_path(
        Path(r"C:\saves\world"),
        "minecraft:the_nether",
    )
    assert path.name == "world_minecraft_the_nether_map.png"


def test_open_prefills_selected_region(app: _App, tmp_path: Path) -> None:
    dialog = QtMapExportDialog(cast(Any, app))
    world = tmp_path / "world"
    world.mkdir()
    dialog.open(MapExportSession(
        world_path=world,
        dimension_id="overworld",
        selected_region=(3, -2),
    ))
    assert dialog._range_mode.currentData() == "region"
    assert dialog._start_x.text() == "3"
    assert dialog._start_z.text() == "-2"
    assert dialog._selection_host.isVisible() is True
    assert dialog._dialog is not None
    assert dialog._dialog.isVisible() is True
    dialog.dispose()


def test_open_without_selection_defaults_to_full(
    app: _App,
    tmp_path: Path,
) -> None:
    dialog = QtMapExportDialog(cast(Any, app))
    world = tmp_path / "world"
    world.mkdir()
    dialog.open(MapExportSession(
        world_path=world,
        dimension_id="overworld",
        selected_region=None,
    ))
    assert dialog._range_mode.currentData() == "full"
    assert dialog._selection_host.isVisible() is False
    dialog.dispose()


def test_dispose_cancels_export_and_closes_dialog(
    app: _App,
    tmp_path: Path,
) -> None:
    dialog = QtMapExportDialog(cast(Any, app))
    world = tmp_path / "world"
    world.mkdir()
    dialog.open(MapExportSession(world, "overworld"))
    cancel = MagicMock()
    dialog._cancel_event = cancel
    dialog._export_state = begin_map_export(dialog._export_state)

    dialog.dispose()

    assert dialog._export_state.is_disposed is True
    assert dialog._export_state.is_running is False
    cancel.set.assert_called_once()
    assert dialog._dialog is None


def test_world_switch_invalidates_export_session_but_allows_reopen(
    app: _App,
    tmp_path: Path,
) -> None:
    dialog = QtMapExportDialog(cast(Any, app))
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    dialog.open(MapExportSession(first, "overworld"))
    cancel = MagicMock()
    dialog._cancel_event = cancel
    dialog._export_state = begin_map_export(dialog._export_state)
    old_generation = dialog._export_state.generation
    cancel_all = MagicMock()
    dialog._task_scope = cast(
        Any,
        SimpleNamespace(cancel_all=cancel_all, close=lambda: None),
    )

    dialog.invalidate_session()

    assert dialog._export_state.generation == old_generation + 1
    assert dialog._export_state.is_running is False
    assert dialog._export_state.is_disposed is False
    assert dialog._session is None
    assert dialog._dialog is None
    cancel.set.assert_called_once()
    cancel_all.assert_called_once()

    # 恢复真实作用域以便 reopen / dispose
    dialog._task_scope = app.execution_runtime.create_scope(
        "qt_map_export_reopen"
    )
    dialog.open(MapExportSession(second, "nether"))
    assert dialog._session is not None
    assert dialog._session.world_path == second
    dialog.dispose()


def test_submission_failure_restores_export_controls(
    app: _App,
    tmp_path: Path,
) -> None:
    dialog = QtMapExportDialog(cast(Any, app))
    world = tmp_path / "world"
    world.mkdir()
    dialog.open(MapExportSession(world, "overworld"))
    dialog._service = cast(Any, object())
    dialog._output_path.setText(str(tmp_path / "map.png"))
    real_scope = dialog._task_scope
    dialog._task_scope = cast(
        Any,
        SimpleNamespace(
            submit=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                TaskQueueFullError("full")
            ),
            close=real_scope.close,
            cancel_all=real_scope.cancel_all,
        ),
    )

    dialog._start_export()

    assert dialog._export_state.is_running is False
    assert dialog._cancel_event is None
    assert dialog._export_btn.isEnabled() is True
    assert dialog._cancel_export_btn.isEnabled() is False
    assert app.errors == [("错误", "地图导出失败")]
    dialog.dispose()


def test_coordinator_open_export_uses_map_context(
    app: _App,
    tmp_path: Path,
) -> None:
    coordinator = QtRegionMapCoordinator(cast(Any, app))
    world = tmp_path / "world"
    world.mkdir()
    (world / "region").mkdir()
    session = cast(
        WorldSession,
        SimpleNamespace(
            world_path=world,
            get_dimensions=lambda: [{
                "id": "nether",
                "name": "Nether",
                "region_dir": str(world / "region"),
                "coordinate_scale": 8.0,
            }],
        ),
    )
    coordinator.set_world(session)
    coordinator._selected_region = (1, 2)
    opened: list[MapExportSession] = []
    coordinator._map_export_dialog.open = (  # type: ignore[method-assign]
        lambda session: opened.append(session)
    )

    coordinator._open_map_export_dialog()

    assert len(opened) == 1
    assert opened[0].world_path == world
    assert opened[0].dimension_id in {"nether", "overworld"}
    assert opened[0].selected_region == (1, 2)
    coordinator.close()


def test_coordinator_export_requires_save(app: _App) -> None:
    coordinator = QtRegionMapCoordinator(cast(Any, app))
    coordinator._open_map_export_dialog()
    assert app.warnings
    coordinator.close()


def test_stale_progress_callback_is_dropped(
    app: _App,
    tmp_path: Path,
) -> None:
    dialog = QtMapExportDialog(cast(Any, app))
    world = tmp_path / "world"
    world.mkdir()
    dialog.open(MapExportSession(world, "overworld"))
    dialog._export_state = begin_map_export(dialog._export_state)
    generation = dialog._export_state.generation
    dialog._finish_export(
        generation,
        {"success": False, "cancelled": True},
    )
    assert dialog._export_state.is_running is False
    delivered: list[str] = []
    dialog._run_for_generation(generation, delivered.append, "progress")
    assert _wait_until(lambda: True)  # 让出事件循环一次
    app_qt = QApplication.instance()
    if app_qt is not None:
        app_qt.processEvents()
    assert delivered == []
    dialog.dispose()
