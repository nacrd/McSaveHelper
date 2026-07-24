"""Explorer statistics operation ownership tests."""
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, cast

from app.presenters.stats_view_state import (
    StatsAnalysisState,
    begin_stats_analysis,
)
from app.ui.views.explorer.stats_tab import StatsTabMixin


def test_stats_callbacks_expire_after_world_generation_changes(
    tmp_path: Path,
) -> None:
    world = tmp_path / "world"
    host = StatsTabMixin()
    host.world_session = cast(Any, SimpleNamespace(world_path=world))
    host._world_load_generation = 4
    setattr(host, "_disposed", False)
    host._stats_analysis_state = begin_stats_analysis(
        StatsAnalysisState(),
        world,
        host._world_load_generation,
    )
    generation = host._stats_analysis_state.generation

    assert host._is_stats_analysis_current(generation)

    host._world_load_generation += 1
    host._invalidate_stats_analysis_state()

    assert not host._is_stats_analysis_current(generation)


def test_queued_stats_progress_drops_after_world_switch(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    queued: list[Callable[[], None]] = []
    events: list[str] = []

    def queue_ui(
        page: object,
        callback: Callable[..., object],
        *args: object,
    ) -> None:
        del page

        def invoke() -> None:
            callback(*args)

        queued.append(invoke)

    monkeypatch.setattr(
        "app.ui.views.explorer.stats_tab.run_on_ui",
        queue_ui,
    )
    world = tmp_path / "world"
    host = StatsTabMixin()
    host.app = cast(Any, SimpleNamespace(page=object()))
    host.world_session = cast(Any, SimpleNamespace(world_path=world))
    host._world_load_generation = 4
    setattr(host, "_disposed", False)
    host._stats_analysis_state = begin_stats_analysis(
        StatsAnalysisState(),
        world,
        host._world_load_generation,
    )
    generation = host._stats_analysis_state.generation

    host._post_stats_ui(generation, events.append, "old progress")
    host._world_load_generation += 1
    host._invalidate_stats_analysis_state()
    for callback in queued:
        callback()

    assert events == []
