"""Tests for map-integrated export dialog."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from app.presenters.map_export_state import begin_map_export
from app.services.execution_runtime import ExecutionRuntime, TaskQueueFullError
from app.ui.feature_context import FeatureContext
from app.ui.views.explorer.map.export_dialog import (
    MapExportDialog,
    MapExportSession,
)
from app.ui.views.explorer.explorer_view import ExplorerView
from app.ui.views.explorer.region_tab import RegionTabMixin
from core.omni.world_session import WorldSession


class _App:
    page: Any = SimpleNamespace(
        show_dialog=lambda dialog: setattr(dialog, "open", True),
        update=lambda: None,
    )

    def __init__(self) -> None:
        self.warnings: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.infos: list[tuple[str, str]] = []
        self.execution_runtime = ExecutionRuntime()

    @staticmethod
    def translate(key: str, default: str = "", **kwargs: object) -> str:
        del key
        return default.format(**kwargs)

    def warn_dialog(self, title: str, message: str) -> None:
        self.warnings.append((title, message))

    def error_dialog(self, title: str, message: str) -> None:
        self.errors.append((title, message))

    def info_dialog(self, title: str, message: str) -> None:
        self.infos.append((title, message))

    def show_progress(self, *_args: object, **_kwargs: object) -> None:
        return None

    def hide_progress(self) -> None:
        return None

    def update_progress_with_task(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> None:
        return None

    def save_file(self, **_kwargs: object) -> str | None:
        return None


class _QueuedPage:
    """Queue Flet async callables so tests can control delivery order."""

    def __init__(self) -> None:
        self.tasks: list[Callable[[], Coroutine[Any, Any, None]]] = []

    def run_task(
        self,
        callback: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        self.tasks.append(callback)

    def show_dialog(self, dialog: Any) -> None:
        dialog.open = True


def test_default_output_path_uses_dimension_suffix() -> None:
    path = MapExportDialog.default_output_path(
        Path(r"C:\saves\world"),
        "minecraft:the_nether",
    )
    assert path.name == "world_minecraft_the_nether_map.png"


def test_open_prefills_selected_region(tmp_path: Path) -> None:
    app = _App()
    dialog = MapExportDialog(cast(FeatureContext, app))
    session = MapExportSession(
        world_path=tmp_path / "world",
        dimension_id="overworld",
        selected_region=(3, -2),
    )
    (tmp_path / "world").mkdir()

    dialog.open(session)

    assert dialog._range_mode_dropdown.value == "region"
    assert dialog._selection_start_x.value == "3"
    assert dialog._selection_start_z.value == "-2"
    assert dialog._selection_fields.visible is True
    assert dialog._dialog is not None
    assert dialog._dialog.open is True


def test_open_without_selection_defaults_to_full_dimension(tmp_path: Path) -> None:
    app = _App()
    dialog = MapExportDialog(cast(FeatureContext, app))
    (tmp_path / "world").mkdir()

    dialog.open(
        MapExportSession(
            world_path=tmp_path / "world",
            dimension_id="overworld",
            selected_region=None,
        )
    )

    assert dialog._range_mode_dropdown.value == "full"
    assert dialog._selection_fields.visible is False


def test_dispose_cancels_export_and_closes_dialog(tmp_path: Path) -> None:
    app = _App()
    dialog = MapExportDialog(cast(FeatureContext, app))
    (tmp_path / "world").mkdir()
    dialog.open(
        MapExportSession(
            world_path=tmp_path / "world",
            dimension_id="overworld",
        )
    )
    cancel = MagicMock()
    cancel.set = MagicMock()
    dialog._cancel_event = cancel
    dialog._export_state = begin_map_export(dialog._export_state)

    dialog.dispose()

    assert dialog._export_state.is_disposed is True
    assert dialog._export_state.is_running is False
    cancel.set.assert_called_once()
    assert dialog._dialog is None


def test_world_switch_invalidates_export_session_but_allows_reopen(
    tmp_path: Path,
) -> None:
    app = _App()
    dialog = MapExportDialog(cast(FeatureContext, app))
    first_world = tmp_path / "first"
    second_world = tmp_path / "second"
    first_world.mkdir()
    second_world.mkdir()
    dialog.open(MapExportSession(first_world, "overworld"))
    cancel = MagicMock()
    dialog._cancel_event = cancel
    dialog._export_state = begin_map_export(dialog._export_state)
    old_generation = dialog._export_state.generation
    cancel_all = MagicMock()
    dialog._task_scope = cast(Any, SimpleNamespace(cancel_all=cancel_all))

    dialog.invalidate_session()

    assert dialog._export_state.generation == old_generation + 1
    assert dialog._export_state.is_running is False
    assert dialog._export_state.is_disposed is False
    assert dialog._session is None
    assert dialog._dialog is None
    cancel.set.assert_called_once()
    cancel_all.assert_called_once()

    dialog.open(MapExportSession(second_world, "nether"))

    assert dialog._session is not None
    assert dialog._session.world_path == second_world


def test_explorer_detach_invalidates_open_map_export(tmp_path: Path) -> None:
    view = ExplorerView.__new__(ExplorerView)
    view.world_session = cast(
        WorldSession,
        SimpleNamespace(world_path=tmp_path / "old"),
    )
    view._selected_region_coord = (1, 2)
    view._map_export_dialog = MagicMock()
    view._map_controller = MagicMock()
    view._map_service = MagicMock()
    view._reset_player_selection = MagicMock()

    view._detach_current_world()

    view._map_export_dialog.invalidate_session.assert_called_once()
    assert view.world_session is None


def test_region_tab_open_export_uses_map_context(tmp_path: Path) -> None:
    app = _App()
    tab = RegionTabMixin()
    tab.app = cast(Any, app)
    tab.world_session = cast(
        WorldSession,
        SimpleNamespace(world_path=tmp_path / "world"),
    )
    tab._current_dimension = "nether"
    tab._selected_region_coord = (1, 2)
    dialog = MagicMock()
    tab._map_export_dialog = dialog

    tab._open_map_export_dialog()

    dialog.open.assert_called_once()
    session = dialog.open.call_args.args[0]
    assert session.world_path == tmp_path / "world"
    assert session.dimension_id == "nether"
    assert session.selected_region == (1, 2)


def test_region_tab_export_requires_save() -> None:
    app = _App()
    tab = RegionTabMixin()
    tab.app = cast(Any, app)
    tab.world_session = None

    tab._open_map_export_dialog()

    assert app.warnings


def test_submission_failure_restores_export_controls_for_retry(
    tmp_path: Path,
) -> None:
    app = _App()
    dialog = MapExportDialog(cast(FeatureContext, app))
    world = tmp_path / "world"
    world.mkdir()
    dialog.open(MapExportSession(world, "overworld"))
    dialog._service = cast(Any, object())
    dialog._output_path_field.value = str(tmp_path / "map.png")
    dialog._task_scope = cast(
        Any,
        SimpleNamespace(
            submit=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                TaskQueueFullError("full")
            ),
        ),
    )

    dialog._start_export()

    assert dialog._export_state.is_running is False
    assert dialog._cancel_event is None
    assert dialog._export_btn.disabled is False
    assert dialog._cancel_export_btn.disabled is True
    assert app.errors == [("错误", "地图导出失败")]


def test_completion_invalidates_queued_progress_callback(tmp_path: Path) -> None:
    app = _App()
    page = _QueuedPage()
    app.page = cast(Any, page)
    dialog = MapExportDialog(cast(FeatureContext, app))
    world = tmp_path / "world"
    world.mkdir()
    dialog.open(MapExportSession(world, "overworld"))
    dialog._export_state = begin_map_export(dialog._export_state)
    generation = dialog._export_state.generation
    delivered: list[str] = []
    dialog._run_for_generation(generation, delivered.append, "progress")
    dialog._run_for_generation(
        generation,
        dialog._finish_export,
        generation,
        {"success": False, "cancelled": True},
    )

    asyncio.run(page.tasks[1]())
    asyncio.run(page.tasks[0]())

    assert dialog._export_state.is_running is False
    assert delivered == []
