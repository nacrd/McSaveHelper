#!/usr/bin/env python3
"""Benchmark MCA, world index, session open, topview, and backup paths.

Uses fixed synthetic sample worlds (small/medium/large) so results are
repeatable without real Minecraft saves.

Examples
--------
  python scripts/bench_mca.py
  python scripts/bench_mca.py --sizes small medium --json
  python scripts/bench_mca.py --sizes large --loops 1
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.backup_service import BackupService  # noqa: E402
from app.services.cache_registry import CachePolicy, CacheRegistry  # noqa: E402
from app.services.execution_runtime import (  # noqa: E402
    ExecutionLane,
    ExecutionRuntime,
    LaneLimits,
)
from app.services.world_index_service import WorldIndexRegistry  # noqa: E402
from app.services.world_write_coordinator import WorldWriteCoordinator  # noqa: E402
from core.bench_budgets import (  # noqa: E402
    DEFAULT_BUDGETS,
    evaluate_sample_against_budget,
)
from core.bench_samples import (  # noqa: E402
    REFERENCE_MACHINE,
    SAMPLE_SPECS,
    SampleSize,
    create_sample_world,
)
from core.mca import RegionFile  # noqa: E402
from core.mca.topview_renderer import render_region_topview  # noqa: E402
from core.observability import p95  # noqa: E402
from core.omni.world_session import WorldSession  # noqa: E402
from core.world_index import WorldIndexBuilder  # noqa: E402


def _ms(seconds: float) -> float:
    return seconds * 1000.0


def _timed(callable_: Callable[[], Any]) -> tuple[float, Any]:
    started = time.perf_counter()
    result = callable_()
    return _ms(time.perf_counter() - started), result


def _median(samples: list[float]) -> float:
    return statistics.median(samples) if samples else 0.0


def _bench_mca_open_read(world: Path, loops: int) -> dict[str, Any]:
    region_files = sorted((world / "region").glob("r.*.*.mca"))
    if not region_files:
        raise RuntimeError(f"样本世界没有区域文件: {world}")
    target = region_files[0]
    open_samples: list[float] = []
    read_samples: list[float] = []
    chunk_count = 0
    for _ in range(loops):
        open_ms, region = _timed(lambda: RegionFile.open(target))
        open_samples.append(open_ms)
        try:
            coords = list(region.iter_present_chunks())
            chunk_count = len(coords)

            def read_all() -> int:
                for cx, cz in coords:
                    region.read_chunk(cx, cz)
                return len(coords)

            read_ms, _ = _timed(read_all)
            read_samples.append(read_ms)
        finally:
            region.close()
    return {
        "region_file": target.name,
        "chunk_count": chunk_count,
        "open_median_ms": round(_median(open_samples), 3),
        "read_batch_median_ms": round(_median(read_samples), 3),
        "loops": loops,
    }


def _bench_world_index(world: Path, loops: int) -> dict[str, Any]:
    registry = WorldIndexRegistry(builder=WorldIndexBuilder())
    try:
        cold_ms, snapshot = _timed(lambda: registry.get(world))
        warm_samples: list[float] = []
        for _ in range(max(1, loops)):
            warm_ms, second = _timed(lambda: registry.get(world))
            warm_samples.append(warm_ms)
            if second.probe != snapshot.probe:
                raise RuntimeError("世界索引热读不稳定")
        stats = registry.stats()
        return {
            "cold_ms": round(cold_ms, 3),
            "warm_median_ms": round(_median(warm_samples), 3),
            "warm_p95_ms": round(p95(warm_samples), 3),
            "regions": len(snapshot.region_files),
            "players": len(snapshot.player_files),
            "hits": stats.hits,
            "builds": stats.builds,
        }
    finally:
        registry.close()


def _bench_world_session(world: Path, loops: int) -> dict[str, Any]:
    registry = WorldIndexRegistry(builder=WorldIndexBuilder())
    try:
        snapshot = registry.get(world)
        samples: list[float] = []
        for _ in range(max(1, loops)):
            open_ms, session = _timed(
                lambda: WorldSession(world, index_snapshot=snapshot)
            )
            samples.append(open_ms)
            del session
        return {
            "open_with_index_median_ms": round(_median(samples), 3),
            "open_with_index_p95_ms": round(p95(samples), 3),
            "player_count": len(snapshot.player_files),
            "region_count": len(snapshot.region_files),
        }
    finally:
        registry.close()


def _bench_topview(world: Path, loops: int) -> dict[str, Any]:
    region_files = sorted((world / "region").glob("r.*.*.mca"))
    target = region_files[0]
    samples: list[float] = []
    tile_bytes = 0
    for _ in range(max(1, loops)):
        render_ms, png = _timed(
            lambda: render_region_topview(
                target,
                tile_size=32,
                use_disk_cache=False,
                decode_workers=1,
            )
        )
        samples.append(render_ms)
        if png is not None:
            tile_bytes = len(png)
    return {
        "region_file": target.name,
        "tile_median_ms": round(_median(samples), 3),
        "tile_p95_ms": round(p95(samples), 3),
        "tile_bytes": tile_bytes,
        "rendered": tile_bytes > 0,
    }


def _bench_backup(world: Path) -> dict[str, Any]:
    coordinator = WorldWriteCoordinator()
    service = BackupService(coordinator)
    backup_ms, record = _timed(
        lambda: service.create_backup(world, label="bench")
    )
    return {
        "backup_ms": round(backup_ms, 3),
        "file_count": record.file_count,
        "size_bytes": record.size_bytes,
        "valid": record.valid,
    }


def _bench_runtime_and_stale() -> dict[str, Any]:
    """Capture worker bounds and stale-callback discard count."""
    limits = LaneLimits(max_workers=2, queue_capacity=8)
    runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
    cache = CacheRegistry(budget_bytes=1024 * 1024)
    region = cache.create_region("bench.tiles", CachePolicy(4, 512 * 1024))
    generation = 0
    accepted = 0
    stale = 0
    lock = threading.Lock()
    started = threading.Event()
    release = threading.Event()

    def worker(token: Any, gen: int) -> None:
        nonlocal accepted, stale
        del token
        started.set()
        release.wait(1)
        with lock:
            if gen != generation:
                stale += 1
            else:
                accepted += 1
                region.put(f"tile-{accepted}", b"x" * 64, 64)

    try:
        first = runtime.submit(
            "stale_callback_probe",
            lambda token: worker(token, generation),
            lane=ExecutionLane.CPU,
        )
        if not started.wait(1):
            raise RuntimeError("stale 回调探针未启动")
        generation += 1
        release.set()
        first.result(timeout=1)
        snapshot = runtime.snapshot()
        cache_stats = cache.stats()
        return {
            "worker_count_by_lane": {
                lane.value: count
                for lane, count in snapshot.worker_count_by_lane.items()
            },
            "active_tasks": snapshot.active_task_count
            if hasattr(snapshot, "active_task_count")
            else runtime.active_task_count,
            "stale_callbacks": stale,
            "accepted_callbacks": accepted,
            "cache_bytes_used": cache_stats.bytes_used,
            "cache_budget_bytes": cache_stats.budget_bytes,
        }
    finally:
        release.set()
        runtime.shutdown(wait=True)
        cache.close()


def _bench_size(size: SampleSize, root: Path, loops: int) -> dict[str, Any]:
    spec = SAMPLE_SPECS[size]
    world = create_sample_world(root, size)
    return {
        "size": size.value,
        "label": spec.label,
        "region_count": spec.region_count,
        "chunks_per_region": spec.chunks_per_region,
        "mca": _bench_mca_open_read(world, loops),
        "world_index": _bench_world_index(world, loops),
        "world_session": _bench_world_session(world, loops),
        "topview": _bench_topview(world, loops),
        "backup": _bench_backup(world),
    }


def run_benchmark(
    sizes: Optional[list[SampleSize]] = None,
    loops: int = 3,
) -> dict[str, Any]:
    """Run fixed-sample MCA/index/session/tile/backup benchmarks."""
    selected = sizes or [SampleSize.SMALL, SampleSize.MEDIUM, SampleSize.LARGE]
    with tempfile.TemporaryDirectory(prefix="mcsavehelper-mca-bench-") as raw:
        root = Path(raw)
        samples = [
            _bench_size(size, root / size.value, loops) for size in selected
        ]
        runtime = _bench_runtime_and_stale()
    return {
        "reference_machine": REFERENCE_MACHINE,
        "loops": loops,
        "samples": samples,
        "runtime": runtime,
    }


def _print_human(report: dict[str, Any]) -> None:
    print("=== MCA / architecture sample bench ===")
    print(f"profile: {report['reference_machine']['profile']}")
    for sample in report["samples"]:
        print(f"- {sample['label']}")
        mca = sample["mca"]
        index = sample["world_index"]
        session = sample["world_session"]
        topview = sample["topview"]
        backup = sample["backup"]
        print(
            f"  mca open={mca['open_median_ms']}ms "
            f"read={mca['read_batch_median_ms']}ms chunks={mca['chunk_count']}"
        )
        print(
            f"  index cold={index['cold_ms']}ms "
            f"warm={index['warm_median_ms']}ms regions={index['regions']}"
        )
        print(
            f"  session open={session['open_with_index_median_ms']}ms"
        )
        print(
            f"  topview={topview['tile_median_ms']}ms "
            f"bytes={topview['tile_bytes']} rendered={topview['rendered']}"
        )
        print(
            f"  backup={backup['backup_ms']}ms files={backup['file_count']} "
            f"bytes={backup['size_bytes']}"
        )
    runtime = report["runtime"]
    print(
        f"runtime workers={runtime['worker_count_by_lane']} "
        f"stale={runtime['stale_callbacks']} "
        f"cache_bytes={runtime['cache_bytes_used']}"
    )


def evaluate_report_budgets(report: dict[str, Any]) -> list[str]:
    """对照 DEFAULT_BUDGETS 检查报告；返回全部违规描述。"""
    violations: list[str] = []
    for sample in report.get("samples", []):
        if not isinstance(sample, dict):
            continue
        size_name = str(sample.get("size", ""))
        try:
            size = SampleSize(size_name)
        except ValueError:
            violations.append(f"unknown size {size_name}")
            continue
        budget = DEFAULT_BUDGETS.get(size)
        if budget is None:
            continue
        for item in evaluate_sample_against_budget(sample, budget):
            violations.append(f"{size_name}: {item}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Bench MCA and world paths")
    parser.add_argument(
        "--sizes",
        nargs="+",
        choices=[item.value for item in SampleSize],
        default=[item.value for item in SampleSize],
    )
    parser.add_argument("--loops", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--check-budgets",
        action="store_true",
        help="Fail with exit 2 when synthetic p95 budgets are exceeded",
    )
    args = parser.parse_args()
    sizes = [SampleSize(item) for item in args.sizes]
    report = run_benchmark(sizes=sizes, loops=max(1, args.loops))
    budget_violations = evaluate_report_budgets(report)
    report["budget_violations"] = budget_violations
    report["budgets_ok"] = not budget_violations
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        _print_human(report)
        if budget_violations:
            print("budget violations:")
            for item in budget_violations:
                print(f"  - {item}")
        elif args.check_budgets:
            print("budgets: ok")
    if args.check_budgets and budget_violations:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
