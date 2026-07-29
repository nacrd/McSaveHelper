"""Synthetic p95 budget helpers."""
from __future__ import annotations

from core.bench_budgets import (
    DEFAULT_BUDGETS,
    DEFAULT_REAL_WORLD_LOD_BUDGET,
    PathBudget,
    evaluate_real_world_lod_report,
    evaluate_real_world_lod_sample,
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
        shell_open_ms=8.0,
        topview_cache_hit_ms=3.0,
        backup_ms=4.0,
    )
    sample = {
        "world_index": {"cold_ms": 50.0, "warm_p95_ms": 1.0},
        "topview": {"tile_p95_ms": 5.0, "cache_hit_p95_ms": 1.0},
        "world_session": {
            "shell_open_p95_ms": 2.0,
            "open_with_index_p95_ms": 2.0,
        },
        "backup": {"backup_p95_ms": 2.0},
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
        "topview": {"tile_p95_ms": 1.0, "cache_hit_p95_ms": 1.0},
        "world_session": {
            "shell_open_p95_ms": 1.0,
            "open_with_index_p95_ms": 1.0,
        },
        "backup": {"backup_p95_ms": 1.0},
    }
    assert evaluate_sample_against_budget(sample, budget) == []


def _real_world_lod_sample() -> dict[str, object]:
    return {
        "read_only_verified": True,
        "world_session": {"shell_open_p95_ms": 250.0},
        "topview": {
            "rendered": True,
            "tile_p95_ms": 120.0,
            "cache_hit_p95_ms": 10.0,
            "visible_process_warm_p95_ms": 400.0,
            "visible_first_progress_p95_ms": 600.0,
            "visible_upgrade_p95_ms": 3500.0,
        },
    }


def test_real_world_lod_budget_accepts_progressive_reference_path() -> None:
    assert evaluate_real_world_lod_sample(_real_world_lod_sample()) == []
    assert DEFAULT_REAL_WORLD_LOD_BUDGET.visible_upgrade_ms == 4000.0


def test_real_world_lod_budget_rejects_slow_or_mutated_sample() -> None:
    sample = _real_world_lod_sample()
    sample["read_only_verified"] = False
    topview = sample["topview"]
    assert isinstance(topview, dict)
    topview["visible_first_progress_p95_ms"] = 900.0

    violations = evaluate_real_world_lod_sample(sample)

    assert "read_only_verified: expected true" in violations
    assert any("visible_first_progress_p95_ms" in item for item in violations)


def test_real_world_lod_budget_rejects_empty_report_or_boolean_metric() -> None:
    assert evaluate_real_world_lod_report({"samples": []}) == [
        "report has no samples",
    ]
    sample = _real_world_lod_sample()
    session = sample["world_session"]
    assert isinstance(session, dict)
    session["shell_open_p95_ms"] = True

    assert "session.shell_open_p95_ms: missing" in (
        evaluate_real_world_lod_sample(sample)
    )
