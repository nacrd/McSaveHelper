"""固定合成样本与 MCA 架构基准不变量。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, cast

import pytest

from core.bench_samples import SAMPLE_SPECS, SampleSize, create_sample_world
from core.mca.topview_renderer import PREVIEW_TILE_SIZE, ULTRA_TILE_SIZE
from scripts.archive_bench_report import main as archive_bench_main
from scripts.bench_mca import main as bench_main
from scripts.bench_mca import run_benchmark
from scripts.bench_real_world import run_real_world_benchmark


def test_sample_world_sizes_are_fixed(tmp_path: Path) -> None:
    for size, spec in SAMPLE_SPECS.items():
        world = create_sample_world(tmp_path / size.value, size, name="world")
        regions = list((world / "region").glob("r.*.*.mca"))
        assert (world / "level.dat").is_file()
        assert len(regions) == spec.region_count


def test_mca_benchmark_reports_core_metrics() -> None:
    report = run_benchmark(sizes=[SampleSize.SMALL], loops=1)
    samples = cast(list[dict[str, Any]], report["samples"])
    assert len(samples) == 1
    sample = samples[0]
    assert sample["mca"]["chunk_count"] == SAMPLE_SPECS[SampleSize.SMALL].chunks_per_region
    assert sample["world_index"]["regions"] == 1
    assert sample["world_session"]["region_count"] == 1
    assert sample["world_session"]["shell_open_p95_ms"] < 500.0
    assert sample["world_session"]["cold_open_p95_ms"] >= 0.0
    assert sample["backup"]["file_count"] >= 1
    assert sample["backup"]["backup_p95_ms"] >= 0.0
    assert sample["topview"]["cache_hit_count"] >= 1
    assert sample["topview"]["cache_hit_p95_ms"] >= 0.0
    assert report["budgets_ok"] is True
    assert report["budget_result"]["ok"] is True
    assert report["budget_result"]["checked_samples"] == 1
    runtime = cast(dict[str, Any], report["runtime"])
    assert runtime["stale_callbacks"] >= 1
    assert runtime["cache_bytes_used"] >= 0
    assert "cpu" in runtime["worker_count_by_lane"] or "CPU" in {
        str(key).lower() for key in runtime["worker_count_by_lane"]
    }


def test_real_world_benchmark_is_read_only_and_skips_backup(tmp_path: Path) -> None:
    world = create_sample_world(tmp_path, SampleSize.SMALL, name="real")
    before = {
        path.relative_to(world): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in world.rglob("*")
        if path.is_file()
    }

    report = run_real_world_benchmark(
        world,
        sample_size=SampleSize.SMALL,
        loops=1,
    )

    sample = cast(list[dict[str, Any]], report["samples"])[0]
    after = {
        path.relative_to(world): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in world.rglob("*")
        if path.is_file()
    }
    assert sample["read_only_verified"] is True
    assert sample["sample_size"] == "small"
    assert sample["backup"]["skipped"] is True
    assert sample["nbt"]["level"]["p95_ms"] >= 0.0
    assert sample["world_index"]["cold_p95_ms"] >= 0.0
    assert sample["topview"]["memory_warm_p95_ms"] >= 0.0
    assert sample["topview"]["tile_size"] == PREVIEW_TILE_SIZE
    assert sample["topview"]["path_semantics"] == (
        "ui_initial_preview_largest_overworld_region"
    )
    assert sample["topview"]["visible_upgrade_tile_size"] == ULTRA_TILE_SIZE
    assert sample["topview"]["progressive_upgrade_tile_size"] == 32
    assert sample["topview"]["progressive_upgrade_p95_ms"] >= 0.0
    assert sample["topview"]["visible_upgrade_p95_ms"] >= 0.0
    assert sample["topview"]["visible_first_progress_p95_ms"] >= 0.0
    assert sample["topview"]["visible_progress_batch_chunks"] == 256
    assert (
        sample["topview"]["visible_progress_publish_count_min"]
        <= sample["topview"]["visible_progress_publish_count_max"]
    )
    assert sample["topview"]["visible_cache_entries"] >= 1
    assert after == before


@pytest.mark.parametrize(
    ("entrypoint", "program_name"),
    [
        (bench_main, "bench_mca.py"),
        (archive_bench_main, "archive_bench_report.py"),
    ],
)
def test_real_world_cli_requires_explicit_sample_size(
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: Callable[[], int],
    program_name: str,
) -> None:
    monkeypatch.setattr(sys, "argv", [program_name, "--world", "missing"])

    with pytest.raises(SystemExit) as error:
        entrypoint()

    assert error.value.code == 2
