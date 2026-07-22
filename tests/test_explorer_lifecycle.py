"""Explorer world-load cancellation and delayed callback guards."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from app.services.execution_runtime import CancellationToken
from app.ui.views.explorer.explorer_view import ExplorerView


def _bare_explorer(*, disposed: bool, generation: int) -> ExplorerView:
    view = ExplorerView.__new__(ExplorerView)
    view._disposed = disposed
    view._world_load_generation = generation
    return view


def test_disposed_explorer_rejects_delayed_world_results() -> None:
    view = _bare_explorer(disposed=True, generation=4)
    applied: list[object] = []
    view._populate_world = cast(Any, lambda session: applied.append(session))

    asyncio.run(view._apply_loaded_world(cast(Any, object()), 4))
    asyncio.run(view._apply_shell_metadata(SimpleNamespace(), 4))
    asyncio.run(view._show_world_load_error(RuntimeError("late"), 4))

    assert applied == []


def test_cancelled_world_worker_does_not_open_or_post_result() -> None:
    view = _bare_explorer(disposed=False, generation=1)
    posted: list[object] = []
    view.app = cast(
        Any,
        SimpleNamespace(
            page=SimpleNamespace(
                run_task=lambda *args: posted.append(args),
            ),
            services=SimpleNamespace(
                world_repository=SimpleNamespace(
                    get_shell_metadata=lambda _world: posted.append("shell"),
                ),
            ),
            log=lambda *_args: None,
        ),
    )
    token = CancellationToken()
    token.cancel()

    view._load_world_worker("ignored", 1, token)

    assert posted == []
