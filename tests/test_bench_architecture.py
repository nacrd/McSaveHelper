"""架构验收基准的确定性不变量测试。"""
from typing import Any, cast

from scripts.bench_architecture import run_benchmark


def test_architecture_benchmark_reports_bounded_resources() -> None:
    report = run_benchmark()

    runtime = cast(dict[str, Any], report["runtime"])
    cache = cast(dict[str, Any], report["cache"])
    world_index = cast(dict[str, Any], report["world_index"])
    writes = cast(dict[str, Any], report["world_writes"])
    assert runtime["cpu_workers"] <= runtime["cpu_worker_limit"]
    assert runtime["queue_rejected"] is True
    assert runtime["active_after_cancel"] == 0
    assert runtime["cancel_latency_ms"] < 500
    assert cache["used_bytes"] <= cache["budget_bytes"]
    assert cache["evictions"] >= 1
    assert cache["overcommit_rejected"] is True
    assert world_index["samples"] >= 5
    assert world_index["warm_median_ms"] <= world_index["cold_ms"] * 1.5
    assert writes["same_world_blocked"] is True
    assert writes["different_world_allowed"] is True
