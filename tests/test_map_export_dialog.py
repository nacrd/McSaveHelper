"""Tests for map-integrated export dialog."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from app.application import Application
from app.services.execution_runtime import ExecutionRuntime
from app.ui.views.explorer.map.export_dialog import (
    MapExportDialog,
    MapExportSession,
)
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


def test_default_output_path_uses_dimension_suffix() -> None:
    path = MapExportDialog.default_output_path(
        Path(r"C:\saves\world"),
        "minecraft:the_nether",
    )
    assert path.name == "world_minecraft_the_nether_map.png"


def test_open_prefills_selected_region(tmp_path: Path) -> None:
    app = _App()
    dialog = MapExportDialog(cast(Application, app))
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
    dialog = MapExportDialog(cast(Application, app))
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
    dialog = MapExportDialog(cast(Application, app))
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
    dialog._exporting = True

    dialog.dispose()

    assert dialog._disposed is True
    assert dialog._exporting is False
    cancel.set.assert_called_once()
    assert dialog._dialog is None


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
