"""Lifecycle tests for the Flet map export view."""
from __future__ import annotations

import threading
from typing import Any, cast

from app.application import Application
from app.ui.views import map_export as map_export_module
from app.ui.views.map_export import MapExportView


class _App:
    page: Any = object()

    @staticmethod
    def translate(key: str, default: str = "", **kwargs: object) -> str:
        del key
        return default.format(**kwargs)


def _view() -> MapExportView:
    return MapExportView(cast(Application, _App()))


def test_dispose_is_safe_when_pillow_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(map_export_module, "PIL_AVAILABLE", False)

    view = _view()
    view.dispose()

    assert view._disposed is True


def test_dispose_cancels_export_and_drops_scheduled_callback(monkeypatch) -> None:
    scheduled: list[tuple[object, tuple[object, ...]]] = []
    monkeypatch.setattr(
        map_export_module,
        "run_on_ui",
        lambda _page, callback, *args: scheduled.append((callback, args)),
    )
    view = _view()
    event = threading.Event()
    view._cancel_event = event
    generation = view._task_generation
    calls: list[str] = []

    view._run_for_generation(generation, calls.append, "late")
    view.dispose()
    callback, args = scheduled.pop()
    assert callable(callback)
    callback(*args)

    assert event.is_set()
    assert calls == []
