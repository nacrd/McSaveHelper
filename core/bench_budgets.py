"""合成样本基准的 p95 预算（非实机 SLA，可回归门禁）。

预算针对 ``core.bench_samples`` 固定合成世界，用于防止架构回退后
冷路径明显变慢。数值留有余量；真机 p95 仍需在参考机器上另行采集。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, cast

from core.bench_samples import SampleSize


@dataclass(frozen=True)
class PathBudget:
    """单条路径的 p95 上限（毫秒）。"""

    world_index_cold_ms: float
    world_index_warm_ms: float
    topview_tile_ms: float
    session_open_ms: float
    shell_open_ms: float = 500.0
    topview_cache_hit_ms: float = 30.0
    backup_ms: float = 5000.0


# 合成世界在 CI 共享机上的宽松预算；仅作回归闸门。
DEFAULT_BUDGETS: Mapping[SampleSize, PathBudget] = {
    SampleSize.SMALL: PathBudget(
        world_index_cold_ms=500.0,
        world_index_warm_ms=50.0,
        topview_tile_ms=250.0,
        session_open_ms=500.0,
        topview_cache_hit_ms=30.0,
        backup_ms=5000.0,
    ),
    SampleSize.MEDIUM: PathBudget(
        world_index_cold_ms=1500.0,
        world_index_warm_ms=80.0,
        topview_tile_ms=800.0,
        session_open_ms=1500.0,
        topview_cache_hit_ms=30.0,
        backup_ms=5000.0,
    ),
    SampleSize.LARGE: PathBudget(
        world_index_cold_ms=5000.0,
        world_index_warm_ms=150.0,
        topview_tile_ms=2500.0,
        session_open_ms=5000.0,
        topview_cache_hit_ms=30.0,
        backup_ms=5000.0,
    ),
}


def evaluate_sample_against_budget(
    sample: Mapping[str, object],
    budget: PathBudget,
) -> list[str]:
    """对照预算检查一个 bench 样本；返回违规描述（空=通过）。"""
    violations: list[str] = []
    index = sample.get("world_index")
    topview = sample.get("topview")
    session = sample.get("world_session")
    backup = sample.get("backup")
    missing: list[str] = []
    if not isinstance(index, dict):
        missing.append("world_index")
    if not isinstance(topview, dict):
        missing.append("topview")
    if not isinstance(session, dict):
        missing.append("world_session")
    if not isinstance(backup, dict):
        missing.append("backup")
    if missing:
        return [f"sample missing {','.join(missing)}"]
    index_data = cast(dict[str, object], index)
    topview_data = cast(dict[str, object], topview)
    session_data = cast(dict[str, object], session)
    backup_data = cast(dict[str, object], backup)

    checks = (
        (
            "world_index.cold_ms",
            index_data.get("cold_ms"),
            budget.world_index_cold_ms,
        ),
        (
            "world_index.warm_p95_ms",
            index_data.get("warm_p95_ms", index_data.get("warm_median_ms")),
            budget.world_index_warm_ms,
        ),
        (
            "topview.tile_p95_ms",
            topview_data.get(
                "tile_p95_ms",
                topview_data.get("tile_median_ms"),
            ),
            budget.topview_tile_ms,
        ),
        (
            "topview.cache_hit_p95_ms",
            topview_data.get("cache_hit_p95_ms"),
            budget.topview_cache_hit_ms,
        ),
        (
            "session.shell_open_p95_ms",
            session_data.get("shell_open_p95_ms"),
            budget.shell_open_ms,
        ),
        (
            "session.open_p95_ms",
            session_data.get(
                "open_with_index_p95_ms",
                session_data.get("open_with_index_median_ms"),
            ),
            budget.session_open_ms,
        ),
        (
            "backup.p95_ms",
            backup_data.get(
                "backup_p95_ms",
                backup_data.get("backup_ms"),
            ),
            budget.backup_ms,
        ),
    )
    for name, value, limit in checks:
        if not isinstance(value, (int, float)):
            violations.append(f"{name}: missing")
            continue
        if float(value) > float(limit):
            violations.append(
                f"{name}={float(value):.3f}ms > budget {float(limit):.3f}ms"
            )
    return violations


__all__ = [
    "DEFAULT_BUDGETS",
    "PathBudget",
    "evaluate_sample_against_budget",
]
