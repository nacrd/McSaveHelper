"""Pure UI frame budget probes."""
from __future__ import annotations

import pytest

from core.ui_budget import (
    UI_FRAME_BUDGET_MS,
    UiBudgetExceededError,
    assert_within_ui_budget,
    measure_work_ms,
    within_ui_budget,
)


def test_within_ui_budget_flags_over_limit() -> None:
    assert within_ui_budget(1.0) is True
    assert within_ui_budget(UI_FRAME_BUDGET_MS) is True
    assert within_ui_budget(UI_FRAME_BUDGET_MS + 0.1) is False


def test_assert_within_ui_budget_accepts_trivial_work() -> None:
    elapsed = assert_within_ui_budget(lambda: None, budget_ms=16.0)
    assert elapsed >= 0.0
    assert elapsed <= 16.0


def test_assert_within_ui_budget_rejects_slow_work() -> None:
    import time

    def slow() -> None:
        time.sleep(0.02)

    with pytest.raises(UiBudgetExceededError):
        assert_within_ui_budget(slow, budget_ms=1.0)


def test_measure_work_ms_positive() -> None:
    assert measure_work_ms(lambda: sum(range(100))) >= 0.0
