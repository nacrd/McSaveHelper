"""Synthetic p95 budget helpers."""
from __future__ import annotations

from core.bench_budgets import (
    DEFAULT_BUDGETS,
    PathBudget,
    evaluate_sample_against_budget,
)
from core.bench_samples import SampleSize


def test_default_budgets_cover_all_sample_sizes() -> None:
    assert set(DEFAULT_BUDGETS) == set(SampleSize)


def test_evaluate_sample_detects_over_budget() -> None:
    budget = PathBudget(
        world_index_cold_ms=10.0,
        world_index_warm_ms=5.0,
        topview_tile_ms=20.0,
        session_open_ms=15.0,
    )
    sample = {
        "world_index": {"cold_ms": 50.0, "warm_p95_ms": 1.0},
        "topview": {"tile_p95_ms": 5.0},
        "world_session": {"open_with_index_p95_ms": 2.0},
    }
    violations = evaluate_sample_against_budget(sample, budget)
    assert any("cold_ms" in item for item in violations)


def test_evaluate_sample_passes_when_within_budget() -> None:
    budget = DEFAULT_BUDGETS[SampleSize.SMALL]
    sample = {
        "world_index": {
            "cold_ms": 1.0,
            "warm_p95_ms": 1.0,
        },
        "topview": {"tile_p95_ms": 1.0},
        "world_session": {"open_with_index_p95_ms": 1.0},
    }
    assert evaluate_sample_against_budget(sample, budget) == []
