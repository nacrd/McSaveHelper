"""Explorer world-load cancellation and delayed callback guards."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from app.services.execution_runtime import OperationContext
from app.services.operation_progress import ProgressReporter
from app.services.ui_delivery import UiDeliveryChannel
from app.ui.views.explorer.explorer_view import ExplorerView
from core.observability import OperationOutcome, OperationRecord


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


def test_cancelled_world_worker_does_not_open_or_post_result() -> None:
    view = _bare_explorer(disposed=False, generation=1)
    posted: list[object] = []
    view.app = cast(
        Any,
        SimpleNamespace(
            ui_delivery=SimpleNamespace(
                post=lambda *args, **kwargs: posted.append((args, kwargs)),
            ),
            services=SimpleNamespace(
                world_repository=SimpleNamespace(
                    get_shell_metadata=lambda _world: posted.append("shell"),
                ),
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
    read_context = SimpleNamespace(
        shell="shell",
        open_session=lambda **_kwargs: session,
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
            services=SimpleNamespace(world_repository=repository),
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
            services=SimpleNamespace(world_repository=repository),
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
