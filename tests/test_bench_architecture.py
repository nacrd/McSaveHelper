"""架构验收基准的确定性不变量测试。"""
from typing import Any, cast

from scripts.bench_architecture import run_benchmark


def test_architecture_benchmark_reports_bounded_resources() -> None:
    report = run_benchmark()

    runtime = cast(dict[str, Any], report["runtime"])
    cache = cast(dict[str, Any], report["cache"])
    writes = cast(dict[str, Any], report["world_writes"])
    assert runtime["cpu_workers"] <= runtime["cpu_worker_limit"]
    assert cache["used_bytes"] <= cache["budget_bytes"]
    assert writes["same_world_blocked"] is True
    assert writes["different_world_allowed"] is True
