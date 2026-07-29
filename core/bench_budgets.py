"""合成回归预算与参考机真实世界交互预算。

合成预算针对 ``core.bench_samples`` 固定世界，用于 CI 回归门禁；真实
世界预算只适用于归档报告和固定参考机，不是跨机器 SLA。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, cast

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


@dataclass(frozen=True)
class RealWorldLodBudget:
    """固定参考机的渐进地图交互 p95 上限（毫秒）。"""

    shell_open_ms: float = 500.0
    preview_tile_ms: float = 250.0
    cache_hit_ms: float = 30.0
    visible_process_warm_ms: float = 500.0
    first_progress_ms: float = 750.0
    visible_upgrade_ms: float = 4000.0


DEFAULT_REAL_WORLD_LOD_BUDGET = RealWorldLodBudget()


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


def _metric_violation(
    name: str,
    value: object,
    limit: float,
) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{name}: missing"
    if float(value) <= limit:
        return None
    return f"{name}={float(value):.3f}ms > budget {limit:.3f}ms"


def evaluate_real_world_lod_sample(
    sample: Mapping[str, object],
    budget: RealWorldLodBudget = DEFAULT_REAL_WORLD_LOD_BUDGET,
) -> list[str]:
    """检查固定参考机真实世界渐进地图体验。

    Args:
        sample: 单个真实世界基准样本。
        budget: 参考机交互预算。

    Returns:
        预算违规描述；空列表表示通过。
    """
    violations: list[str] = []
    if sample.get("read_only_verified") is not True:
        violations.append("read_only_verified: expected true")
    topview = sample.get("topview")
    session = sample.get("world_session")
    if not isinstance(topview, dict) or not isinstance(session, dict):
        return violations + ["sample missing topview,world_session"]
    if topview.get("rendered") is not True:
        violations.append("topview.rendered: expected true")
    checks = (
        (
            "session.shell_open_p95_ms",
            session.get("shell_open_p95_ms"),
            budget.shell_open_ms,
        ),
        (
            "topview.tile_p95_ms",
            topview.get("tile_p95_ms"),
            budget.preview_tile_ms,
        ),
        (
            "topview.cache_hit_p95_ms",
            topview.get("cache_hit_p95_ms"),
            budget.cache_hit_ms,
        ),
        (
            "topview.visible_process_warm_p95_ms",
            topview.get("visible_process_warm_p95_ms"),
            budget.visible_process_warm_ms,
        ),
        (
            "topview.visible_first_progress_p95_ms",
            topview.get("visible_first_progress_p95_ms"),
            budget.first_progress_ms,
        ),
        (
            "topview.visible_upgrade_p95_ms",
            topview.get("visible_upgrade_p95_ms"),
            budget.visible_upgrade_ms,
        ),
    )
    violations.extend(
        violation
        for name, value, limit in checks
        if (violation := _metric_violation(name, value, limit)) is not None
    )
    return violations


def evaluate_real_world_lod_report(
    report: Mapping[str, object],
    budget: RealWorldLodBudget = DEFAULT_REAL_WORLD_LOD_BUDGET,
) -> list[str]:
    """检查报告中的全部真实世界样本并标注样本档位。

    Args:
        report: 包含 ``samples`` 列表的真实世界基准报告。
        budget: 参考机交互预算。

    Returns:
        带样本档位的预算违规描述；空列表表示通过。
    """
    samples = report.get("samples")
    if not isinstance(samples, list):
        return ["report missing samples"]
    if not samples:
        return ["report has no samples"]
    violations: list[str] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            violations.append(f"sample[{index}]: invalid")
            continue
        label = sample.get("sample_size", sample.get("label", index))
        violations.extend(
            f"{label}: {item}"
            for item in evaluate_real_world_lod_sample(sample, budget)
        )
    return violations


__all__ = [
    "DEFAULT_BUDGETS",
    "DEFAULT_REAL_WORLD_LOD_BUDGET",
    "PathBudget",
    "RealWorldLodBudget",
    "evaluate_real_world_lod_report",
    "evaluate_real_world_lod_sample",
    "evaluate_sample_against_budget",
]
