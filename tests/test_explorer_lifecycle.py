"""Explorer world-load cancellation and delayed callback guards."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from app.services.execution_runtime import OperationContext
from app.services.operation_progress import ProgressReporter
from app.services.ui_delivery import UiDeliveryChannel
from app.ui.views.explorer.explorer_view import ExplorerView
from core.observability import OperationOutcome, OperationRecord


class _DeferredScope:
    def __init__(self) -> None:
        self.cancel_calls = 0
        self.submissions: list[tuple[str, Any, dict[str, Any]]] = []

    def cancel_all(self) -> None:
        self.cancel_calls += 1

    def submit(self, operation: str, work: Any, **kwargs: Any) -> None:
        self.submissions.append((operation, work, kwargs))


def _bare_explorer(*, disposed: bool, generation: int) -> ExplorerView:
    view = ExplorerView.__new__(ExplorerView)
    view._disposed = disposed
    view._world_load_generation = generation
    return view


def _operation_context(generation: int) -> OperationContext:
    reporter = ProgressReporter("task", "load_world", generation)
    return OperationContext(
        task_id="task",
        operation="load_world",
        feature="explorer",
        world_id="world",
        generation=generation,
        metadata={},
        reporter=reporter,
    )


def test_disposed_explorer_rejects_delayed_world_results() -> None:
    view = _bare_explorer(disposed=True, generation=4)
    applied: list[object] = []
    view._populate_world = cast(Any, lambda session: applied.append(session))

    view._apply_loaded_world(cast(Any, object()), 4)
    view._apply_shell_metadata(SimpleNamespace(), 4)
    view._show_world_load_error(RuntimeError("late"), 4)

    assert applied == []


def test_world_load_detaches_old_session_before_background_open() -> None:
    view = _bare_explorer(disposed=False, generation=4)
    old_session = object()
    map_events: list[str] = []
    scope = _DeferredScope()
    view.world_session = cast(Any, old_session)
    view.current_uuid = "old-player"
    view._current_player_data = object()
    view.player_uuid_map = {"old-player": "Old"}
    view._player_refs_cache = [object()]
    view._player_list_page = 2
    view._selected_region_coord = (3, 4)
    view._map_controller = cast(
        Any,
        SimpleNamespace(
            unbind_world=lambda: map_events.append("unbind"),
        ),
    )
    view._map_service = cast(
        Any,
        SimpleNamespace(
            clear_data=lambda: map_events.append("clear_data"),
        ),
    )
    view._world_label = cast(
        Any,
        SimpleNamespace(value="old", color=None, update=lambda: None),
    )
    view._task_scope = cast(Any, scope)
    view._invalidate_quick_backup_state = cast(Any, lambda: None)
    view._invalidate_stats_analysis_state = cast(Any, lambda: None)
    view._invalidate_player_async_state = cast(Any, lambda: None)
    view._set_map_marker_busy = cast(Any, lambda _busy: None)
    view.app = cast(
        Any,
        SimpleNamespace(
            hide_progress=lambda: None,
            handle_exception=lambda *_args, **_kwargs: None,
        ),
    )

    view._load_world("new-world")

    assert view.world_session is None
    assert view.current_uuid is None
    assert view.player_uuid_map == {}
    assert view._player_refs_cache == []
    assert view._selected_region_coord is None
    assert map_events == ["unbind", "clear_data"]
    assert scope.cancel_calls == 1
    assert scope.submissions[0][0] == "load_world"
    assert scope.submissions[0][2]["generation"] == 5


def test_clear_save_cancels_world_tasks_and_resets_projection() -> None:
    view = _bare_explorer(disposed=False, generation=7)
    events: list[object] = []
    scope = _DeferredScope()
    view._detach_current_world = cast(Any, lambda: events.append("detach"))
    view._invalidate_quick_backup_state = cast(
        Any, lambda: events.append("quick")
    )
    view._invalidate_stats_analysis_state = cast(
        Any, lambda: events.append("stats")
    )
    view._invalidate_player_async_state = cast(
        Any, lambda: events.append("player")
    )
    view._set_map_marker_busy = cast(
        Any, lambda busy: events.append(("marker", busy))
    )
    view._task_scope = cast(Any, scope)
    view._world_label = cast(
        Any,
        SimpleNamespace(value="old", color=None, update=lambda: None),
    )
    view.app = cast(
        Any,
        SimpleNamespace(
            hide_progress=lambda: events.append("hide"),
            translate=lambda _key, default="": default,
        ),
    )

    view.on_save_cleared()

    assert view._world_load_generation == 8
    assert scope.cancel_calls == 1
    assert view._world_label.value == "未设置当前存档"
    assert events == [
        "detach",
        "quick",
        "stats",
        "player",
        ("marker", False),
        "hide",
    ]


def test_cancelled_world_worker_does_not_open_or_post_result() -> None:
    view = _bare_explorer(disposed=False, generation=1)
    posted: list[object] = []
    view.app = cast(
        Any,
        SimpleNamespace(
            ui_delivery=SimpleNamespace(
                post=lambda *args, **kwargs: posted.append((args, kwargs)),
            ),
            world_repository=SimpleNamespace(
                get_shell_metadata=lambda _world: posted.append("shell"),
            ),
            log=lambda *_args: None,
        ),
    )
    context = _operation_context(1)
    context.cancel()

    view._load_world_worker("ignored", 1, context)

    assert posted == []


def test_world_worker_publishes_shell_then_opens_same_read_context() -> None:
    view = _bare_explorer(disposed=False, generation=1)
    posted: list[tuple[Any, ...]] = []
    opened: list[object] = []
    session = object()
    snapshot = object()
    read_context = SimpleNamespace(
        shell="shell",
        get_index_progressive=lambda **_kwargs: snapshot,
        open_session_with_index=lambda _snapshot, **_kwargs: session,
    )
    repository = SimpleNamespace(
        open=lambda world: opened.append(world) or read_context,
    )
    view.app = cast(
        Any,
        SimpleNamespace(
            ui_delivery=SimpleNamespace(
                post=lambda spec, callback, **kwargs: posted.append(
                    (spec, callback, kwargs)
                ),
            ),
            world_repository=repository,
            log=lambda *_args: None,
        ),
    )

    view._load_world_worker("world", 1, _operation_context(1))

    assert len(opened) == 1
    assert [entry[0].event for entry in posted] == ["shell", "result"]
    assert all(entry[0].generation == 1 for entry in posted)


def test_world_worker_binds_error_before_delayed_ui_delivery() -> None:
    view = _bare_explorer(disposed=False, generation=1)
    queued: list[Any] = []
    observed: list[tuple[BaseException, int]] = []
    repository = SimpleNamespace(
        open=lambda _world: (_ for _ in ()).throw(FileNotFoundError()),
    )
    view.app = cast(
        Any,
        SimpleNamespace(
            ui_delivery=SimpleNamespace(
                post=lambda _spec, callback, **_kwargs: queued.append(callback),
            ),
            world_repository=repository,
            log=lambda *_args: None,
        ),
    )

    def fail_session(*_args: Any, **_kwargs: Any) -> object:
        raise RuntimeError("session failed")

    view._create_world_session = cast(Any, fail_session)
    view._show_world_load_error = cast(
        Any,
        lambda error, generation: observed.append((error, generation)),
    )

    view._load_world_worker("world", 1, _operation_context(1))
    assert len(queued) == 1
    queued[0]()

    assert isinstance(observed[0][0], RuntimeError)
    assert str(observed[0][0]) == "session failed"
    assert observed[0][1] == 1


def test_world_ui_delivery_records_stale_generation() -> None:
    view = _bare_explorer(disposed=False, generation=1)
    scheduled: list[Any] = []
    records: list[OperationRecord] = []
    channel = UiDeliveryChannel(
        lambda callback: scheduled.append(callback) or True,
        records.append,
    )
    view.app = cast(Any, SimpleNamespace(ui_delivery=channel))
    delivered: list[str] = []

    view._post_world_ui(
        _operation_context(1),
        "result",
        lambda: delivered.append("late"),
    )
    view._world_load_generation = 2
    scheduled.pop()()

    assert delivered == []
    assert records[0].outcome is OperationOutcome.STALE
    assert records[0].metadata["task_id"] == "task"
