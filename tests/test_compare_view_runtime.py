"""Compare view keeps validation and world parsing off the UI thread."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.presenters.compare_view_state import (
    ComparePhase,
    begin_compare,
    initial_compare_state,
)
from app.services.execution_runtime import CancellationToken
from app.services.world_compare_service import CompareItem, WorldCompareResult
from app.ui.views.compare import CompareView


def _bare_view(service: object) -> CompareView:
    view = CompareView.__new__(CompareView)
    view._service = cast(Any, service)
    return view


def test_compare_worker_validates_and_returns_pure_result(tmp_path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "level.dat").write_bytes(b"left")
    (right / "level.dat").write_bytes(b"right")
    expected = WorldCompareResult(
        summary={"changed": 0},
        world_info=[],
        players=[],
        regions=[],
    )
    calls: list[tuple[object, object]] = []
    service = SimpleNamespace(
        compare_worlds=lambda first, second: calls.append((first, second))
        or expected,
    )
    view = _bare_view(service)

    result = view._run_compare(left, right, CancellationToken())

    assert result is expected
    assert calls == [(left, right)]


def test_compare_worker_rejects_invalid_world_before_service(tmp_path) -> None:
    calls: list[object] = []
    view = _bare_view(
        SimpleNamespace(
            compare_worlds=lambda *_args: calls.append(object()),
        )
    )

    with pytest.raises(ValueError, match="level.dat"):
        view._run_compare(
            tmp_path / "missing",
            tmp_path / "other",
            CancellationToken(),
        )

    assert calls == []


def test_world_switch_cancels_compare_and_rejects_old_result(tmp_path) -> None:
    cancelled: list[bool] = []
    rendered: list[int] = []
    view = CompareView.__new__(CompareView)
    view._state = begin_compare(
        initial_compare_state(),
        tmp_path / "old",
        tmp_path / "target",
    )
    old_generation = view._state.generation
    view._task_scope = cast(Any, SimpleNamespace(
        cancel_all=lambda: cancelled.append(True),
    ))
    view._left_field = cast(Any, SimpleNamespace(value=""))
    view._render_state = lambda: rendered.append(view._state.generation)
    new_world = tmp_path / "new"

    view.on_save_selected(str(new_world))

    assert cancelled == [True]
    assert view._left_field.value == str(new_world)
    assert view._state.phase is ComparePhase.IDLE
    assert view._state.left_path == new_world
    assert view._state.groups == ()
    assert rendered == [old_generation + 1]

    stale_result = WorldCompareResult(
        summary={"changed": 1, "world_info": 1},
        world_info=[CompareItem("seed", "1", "2", same=False)],
        players=[],
        regions=[],
    )
    view._apply_compare_result(stale_result, old_generation)

    assert view._state.phase is ComparePhase.IDLE
    assert rendered == [old_generation + 1]
