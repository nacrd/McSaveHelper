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
                    "cold_p95_ms": 11.0,
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
                "mca": {
                    "open_p95_ms": 0.4,
                    "read_batch_p95_ms": 8.0,
                },
                "nbt": {
                    "level": {"p95_ms": 1.2},
                    "player": {"p95_ms": 0.7},
                },
            }
        ],
    }


def test_extract_and_render_markdown() -> None:
    report = _sample_report()
    rows = extract_p95_rows(report)
    assert rows[0]["size"] == "small"
    assert rows[0]["index_cold_p95_ms"] == 11.0
    assert rows[0]["topview_p95_ms"] == 20.0
    assert rows[0]["shell_p95_ms"] == 0.8
    assert rows[0]["backup_p95_ms"] == 5.0
    assert rows[0]["mca_read_p95_ms"] == 8.0
    assert rows[0]["level_nbt_p95_ms"] == 1.2
    md = render_markdown_report(report, machine_notes="ci-runner")
    assert "index warm p95" in md
    assert "cold session p95" in md
    assert "backup p95" in md
    assert "MCA read p95" in md
    assert "20.000" in md
    assert "ci-runner" in md


def test_render_real_sample_metadata_and_process_warm_metrics() -> None:
    report = _sample_report()
    sample = report["samples"][0]
    sample.update(
        {
            "scale_hint": "large",
            "read_only_verified": True,
            "source": {
                "file_count": 79,
                "size_bytes": 105_143_991,
                "region_count": 23,
            },
        }
    )
    sample["topview"].update(
        {
            "memory_warm_p95_ms": 26.9,
            "tile_size": 16,
            "visible_upgrade_tile_size": 256,
            "progressive_upgrade_tile_size": 32,
            "progressive_upgrade_p95_ms": 1600.0,
            "visible_upgrade_p95_ms": 6500.0,
            "visible_process_warm_p95_ms": 360.0,
            "path_semantics": "ui_initial_preview_largest_overworld_region",
        }
    )

    rows = extract_p95_rows(report)
    markdown = render_markdown_report(report)

    assert rows[0]["topview_process_warm_p95_ms"] == 26.9
    assert rows[0]["topview_visible_upgrade_p95_ms"] == 6500.0
    assert rows[0]["topview_progressive_upgrade_p95_ms"] == 1600.0
    assert rows[0]["read_only_verified"] is True
    assert "Real sample metadata" in markdown
    assert "105143991" in markdown
    assert "ui_initial_preview_largest_overworld_region" in markdown
    assert "6500.000" in markdown
    assert "1600.000" in markdown


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
