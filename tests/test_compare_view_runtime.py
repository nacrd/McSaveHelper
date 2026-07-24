"""Compare view keeps validation and world parsing off the UI thread."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.services.execution_runtime import CancellationToken
from app.services.world_compare_service import WorldCompareResult
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
