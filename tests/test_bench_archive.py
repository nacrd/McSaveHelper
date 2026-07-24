"""Bench p95 archive helpers."""
from __future__ import annotations

from pathlib import Path

from core.bench_archive import (
    extract_p95_rows,
    render_markdown_report,
    write_bench_archive,
)


def _sample_report() -> dict:
    return {
        "reference_machine": {"profile": "synthetic-fixed-samples"},
        "loops": 1,
        "budgets_ok": True,
        "budget_violations": [],
        "samples": [
            {
                "size": "small",
                "label": "small",
                "world_index": {
                    "cold_ms": 10.0,
                    "warm_p95_ms": 2.0,
                },
                "topview": {
                    "tile_p95_ms": 20.0,
                    "cache_hit_p95_ms": 0.5,
                },
                "world_session": {
                    "shell_open_p95_ms": 0.8,
                    "cold_open_p95_ms": 12.0,
                    "open_with_index_p95_ms": 1.0,
                },
                "backup": {"backup_p95_ms": 5.0},
            }
        ],
    }


def test_extract_and_render_markdown() -> None:
    report = _sample_report()
    rows = extract_p95_rows(report)
    assert rows[0]["size"] == "small"
    assert rows[0]["topview_p95_ms"] == 20.0
    assert rows[0]["shell_p95_ms"] == 0.8
    assert rows[0]["backup_p95_ms"] == 5.0
    md = render_markdown_report(report, machine_notes="ci-runner")
    assert "index warm p95" in md
    assert "cold session p95" in md
    assert "backup p95" in md
    assert "20.000" in md
    assert "ci-runner" in md


def test_write_bench_archive(tmp_path: Path) -> None:
    paths = write_bench_archive(
        _sample_report(),
        tmp_path,
        basename="unit",
        machine_notes="test",
    )
    assert paths["json"].is_file()
    assert paths["markdown"].is_file()
    assert "small" in paths["markdown"].read_text(encoding="utf-8")
