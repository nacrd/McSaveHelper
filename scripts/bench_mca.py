#!/usr/bin/env python3
"""Benchmark MCA, world index, session open, topview, and backup paths.

The default mode uses fixed synthetic worlds. ``--world`` enables a strictly
read-only benchmark for a supplied real Java world and never runs backup or
other write paths.

Examples
--------
  python scripts/bench_mca.py
  python scripts/bench_mca.py --sizes small medium --json
  python scripts/bench_mca.py --sizes large --loops 1
  python scripts/bench_mca.py --world example_saves/world --sample-size small --json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.backup_service import BackupService  # noqa: E402
from app.services.cache_registry import CachePolicy, CacheRegistry  # noqa: E402
from app.services.execution_runtime import (  # noqa: E402
    ExecutionRuntime,
    LaneLimits,
)
from app.services.runtime_probes import probe_stale_ui_delivery  # noqa: E402
from app.services.world_index_service import WorldIndexRegistry  # noqa: E402
from app.services.world_repository import WorldRepository  # noqa: E402
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
    repository = WorldRepository(registry)
    try:
        shell_samples: list[float] = []
        cold_open_samples: list[float] = []
        read_context = None
        for _ in range(max(1, loops)):
            shell_ms, read_context = _timed(lambda: repository.open(world))
            shell_samples.append(shell_ms)
            repository.invalidate(world)
            cold_open_ms, session = _timed(read_context.open_session)
            cold_open_samples.append(cold_open_ms)
            del session
        if read_context is None:
            raise RuntimeError("世界读取上下文基准没有生成结果")
        snapshot = read_context.get_index()
        warm_samples: list[float] = []
        for _ in range(max(1, loops)):
            open_ms, session = _timed(
                lambda: WorldSession(world, index_snapshot=snapshot)
            )
            warm_samples.append(open_ms)
            del session
        return {
            "shell_open_median_ms": round(_median(shell_samples), 3),
            "shell_open_p95_ms": round(p95(shell_samples), 3),
            "cold_open_median_ms": round(_median(cold_open_samples), 3),
            "cold_open_p95_ms": round(p95(cold_open_samples), 3),
            "open_with_index_median_ms": round(_median(warm_samples), 3),
            "open_with_index_p95_ms": round(p95(warm_samples), 3),
            "player_count": len(snapshot.player_files),
            "region_count": len(snapshot.region_files),
        }
    finally:
        repository.close()


def _bench_topview(world: Path, loops: int) -> dict[str, Any]:
    region_files = sorted((world / "region").glob("r.*.*.mca"))
    target = region_files[0]
    samples: list[float] = []
    tile_bytes = 0
    effective_loops = max(1, loops)
    png: Optional[bytes] = None
    for _ in range(effective_loops):
        render_ms, current_png = _timed(
            lambda: render_region_topview(
                target,
                tile_size=32,
                use_disk_cache=False,
                decode_workers=1,
            )
        )
        samples.append(render_ms)
        if current_png is not None:
            png = current_png
            tile_bytes = len(current_png)
    if tile_bytes <= 0:
        raise RuntimeError(f"俯视图渲染没有生成有效瓦片: {target}")
    cache_hit = _bench_topview_cache_hit(
        target,
        32,
        png,
        effective_loops,
    )
    return {
        "region_file": target.name,
        "tile_median_ms": round(_median(samples), 3),
        "tile_p95_ms": round(p95(samples), 3),
        "tile_bytes": tile_bytes,
        "rendered": tile_bytes > 0,
        **cache_hit,
    }


def _bench_topview_cache_hit(
    region_path: Path,
    tile_size: int,
    png: Optional[bytes],
    loops: int,
) -> dict[str, Any]:
    """在隔离磁盘缓存中测量已预热瓦片的读取命中延迟。"""
    if not png:
        raise RuntimeError(f"缓存预热缺少瓦片内容: {region_path}")
    from core.mca import tile_cache

    previous_cache_dir = tile_cache._CACHE_DIR
    with tempfile.TemporaryDirectory(prefix="mcsavehelper-tile-bench-") as raw:
        cache_root = Path(raw)
        tile_cache._CACHE_DIR = cache_root
        try:
            tile_cache.store_tile(region_path, tile_size, png)
            if tile_cache.load_tile(region_path, tile_size) is None:
                raise RuntimeError("俯视图磁盘缓存预热失败")
            samples: list[float] = []

            def load_cached() -> Optional[bytes]:
                return tile_cache.load_tile(region_path, tile_size)

            for _ in range(max(1, loops)):
                hit_ms, cached = _timed(load_cached)
                if cached is None:
                    raise RuntimeError("俯视图磁盘缓存命中丢失")
                samples.append(hit_ms)
            return {
                "cache_hit_median_ms": round(_median(samples), 3),
                "cache_hit_p95_ms": round(p95(samples), 3),
                "cache_hit_samples": len(samples),
                "cache_hit_count": len(samples),
            }
        finally:
            tile_cache._CACHE_DIR = previous_cache_dir


def _bench_backup(world: Path, loops: int) -> dict[str, Any]:
    coordinator = WorldWriteCoordinator()
    service = BackupService(coordinator)
    samples: list[float] = []
    record = None

    def create_backup(label_index: int) -> Any:
        return service.create_backup(world, label=f"bench-{label_index}")

    for index in range(max(1, loops)):
        backup_ms, record = _timed(lambda: create_backup(index))
        samples.append(backup_ms)
    if record is None:
        raise RuntimeError("备份基准没有生成结果")
    return {
        "backup_ms": round(_median(samples), 3),
        "backup_median_ms": round(_median(samples), 3),
        "backup_p95_ms": round(p95(samples), 3),
        "backup_samples": len(samples),
        "file_count": record.file_count,
        "size_bytes": record.size_bytes,
        "valid": record.valid,
    }


def _bench_runtime_and_stale() -> dict[str, Any]:
    """Capture worker bounds and stale-callback discard count."""
    limits = LaneLimits(max_workers=2, queue_capacity=8)
    runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
    cache = CacheRegistry(budget_bytes=1024 * 1024)
    cache.create_region("bench.tiles", CachePolicy(4, 512 * 1024))

    def schedule(callback: Callable[[], None]) -> bool:
        callback()
        return True

    try:
        stale_result = probe_stale_ui_delivery(schedule)
        snapshot = runtime.snapshot()
        cache_stats = cache.stats()
        return {
            "worker_count_by_lane": {
                lane.value: count
                for lane, count in snapshot.worker_count_by_lane.items()
            },
            "active_tasks": runtime.active_task_count,
            "stale_callbacks": int(stale_result.outcome.value == "stale"),
            "accepted_callbacks": int(stale_result.callback_delivered),
            "stale_queue_wait_ms": round(stale_result.queue_wait_ms, 3),
            "cache_bytes_used": cache_stats.bytes_used,
            "cache_budget_bytes": cache_stats.budget_bytes,
        }
    finally:
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
        "backup": _bench_backup(world, loops),
    }


def run_benchmark(
    sizes: Optional[list[SampleSize]] = None,
    loops: int = 3,
) -> dict[str, Any]:
    """Run fixed-sample MCA/index/session/tile/backup benchmarks."""
    selected = sizes or [SampleSize.SMALL, SampleSize.MEDIUM, SampleSize.LARGE]
    effective_loops = max(1, int(loops))
    with tempfile.TemporaryDirectory(prefix="mcsavehelper-mca-bench-") as raw:
        root = Path(raw)
        samples = [
            _bench_size(size, root / size.value, effective_loops)
            for size in selected
        ]
        runtime = _bench_runtime_and_stale()
    report = {
        "reference_machine": REFERENCE_MACHINE,
        "loops": effective_loops,
        "samples": samples,
        "runtime": runtime,
    }
    budget_violations = evaluate_report_budgets(report)
    report["budget_violations"] = budget_violations
    report["budgets_ok"] = not budget_violations
    report["budget_result"] = {
        "ok": not budget_violations,
        "violations": budget_violations,
        "checked_samples": len(samples),
    }
    return report


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
            f"bytes={topview['tile_bytes']} rendered={topview['rendered']} "
            f"cache-hit-p95={topview['cache_hit_p95_ms']}ms"
        )
        if backup.get("skipped"):
            print(f"  backup=skipped ({backup.get('reason', 'n/a')})")
        else:
            print(
                f"  backup={backup['backup_ms']}ms files={backup['file_count']} "
                f"bytes={backup['size_bytes']} p95={backup['backup_p95_ms']}ms"
            )
    runtime = report.get("runtime")
    if isinstance(runtime, dict):
        print(
            f"runtime workers={runtime['worker_count_by_lane']} "
            f"stale={runtime['stale_callbacks']} "
            f"cache_bytes={runtime['cache_bytes_used']}"
        )
    print(
        f"budgets ok={report['budgets_ok']} "
        f"violations={len(report['budget_violations'])}"
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
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--sizes",
        nargs="+",
        choices=[item.value for item in SampleSize],
        default=None,
    )
    source.add_argument("--world", default="")
    parser.add_argument(
        "--sample-size",
        choices=[item.value for item in SampleSize],
        default=None,
        help="Required caller-assigned class for --world",
    )
    parser.add_argument("--loops", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--check-budgets",
        action="store_true",
        help="Fail with exit 2 when synthetic p95 budgets are exceeded",
    )
    args = parser.parse_args()
    if args.world:
        if args.sample_size is None:
            parser.error("--world 必须同时指定 --sample-size")
        if args.check_budgets:
            parser.error("--check-budgets 仅适用于固定合成样本")
        from scripts.bench_real_world import run_real_world_benchmark

        report = run_real_world_benchmark(
            args.world,
            sample_size=args.sample_size,
            loops=max(1, args.loops),
        )
    else:
        if args.sample_size is not None:
            parser.error("--sample-size 仅适用于 --world")
        selected = args.sizes or [item.value for item in SampleSize]
        sizes = [SampleSize(item) for item in selected]
        report = run_benchmark(sizes=sizes, loops=max(1, args.loops))
    budget_violations = report["budget_violations"]
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
