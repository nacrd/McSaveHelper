"""固定合成样本与 MCA 架构基准不变量。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from core.bench_samples import SAMPLE_SPECS, SampleSize, create_sample_world
from scripts.bench_mca import run_benchmark


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
