"""架构重构的可重复性能与并发不变量基准。"""
from __future__ import annotations

import json
import statistics
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from app.services.cache_registry import CachePolicy, CacheRegistry
from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    LaneLimits,
    OperationCancelledError,
    TaskQueueFullError,
)
from app.services.world_index_service import WorldIndexRegistry
from app.services.world_write_coordinator import (
    WorldOperationBusyError,
    WorldWriteCoordinator,
)
from core.nbt import Compound, File, Int
from core.world_index import WorldIndexBuilder


def _create_world(root: Path, name: str) -> Path:
    """创建仅包含索引基准所需文件的隔离最小世界。"""
    world = root / name
    (world / "region").mkdir(parents=True)
    File({"Data": Compound({"DataVersion": Int(1)})}).save(
        world / "level.dat"
    )
    for index in range(16):
        (world / "region" / f"r.{index}.0.mca").write_bytes(b"region")
    return world


def _timed(callable_: Any) -> tuple[float, Any]:
    """执行一个操作并返回耗时毫秒与结果。"""
    started = time.perf_counter()
    result = callable_()
    return (time.perf_counter() - started) * 1000.0, result


def _runtime_budget_probe() -> dict[str, int | bool | float]:
    """验证线程、队列、取消延迟与任务释放预算。"""
    limits = LaneLimits(max_workers=1, queue_capacity=1)
    runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
    started = threading.Event()
    release = threading.Event()
    first = None
    queued = None
    cancelled = None

    def wait_for_release(token: Any) -> None:
        started.set()
        while not release.is_set():
            token.raise_if_cancelled()
            release.wait(0.01)

    try:
        first = runtime.submit(
            "bench_runtime",
            wait_for_release,
            lane=ExecutionLane.CPU,
        )
        if not started.wait(1):
            raise RuntimeError("运行时基准任务未启动")
        queued = runtime.submit(
            "bench_queued",
            lambda token: token.raise_if_cancelled(),
            lane=ExecutionLane.CPU,
        )
        queue_rejected = False
        try:
            runtime.submit(
                "bench_overflow",
                lambda token: None,
                lane=ExecutionLane.CPU,
            )
        except TaskQueueFullError:
            queue_rejected = True
        workers = runtime.snapshot().worker_count_by_lane[ExecutionLane.CPU]
        release.set()
        first.result(timeout=1)
        queued.result(timeout=1)

        cancel_started = threading.Event()

        def wait_for_cancel(token: Any) -> None:
            cancel_started.set()
            token.wait(1)
            token.raise_if_cancelled()

        cancelled = runtime.submit(
            "bench_cancel",
            wait_for_cancel,
            lane=ExecutionLane.CPU,
        )
        if not cancel_started.wait(1):
            raise RuntimeError("取消延迟基准任务未启动")
        cancel_start = time.perf_counter()
        cancelled.cancel()
        try:
            cancelled.result(timeout=1)
        except OperationCancelledError:
            pass
        cancel_latency_ms = (time.perf_counter() - cancel_start) * 1000.0
        active_after_cancel = runtime.active_task_count
        return {
            "cpu_workers": workers,
            "cpu_worker_limit": limits.max_workers,
            "queue_rejected": queue_rejected,
            "cancel_latency_ms": round(cancel_latency_ms, 3),
            "active_after_cancel": active_after_cancel,
        }
    finally:
        release.set()
        for handle in (first, queued, cancelled):
            if handle is None or handle.done:
                continue
            handle.cancel()
        runtime.shutdown(wait=True)


def _cache_budget_probe() -> dict[str, int | bool]:
    """验证缓存淘汰与注册预算均保持有界。"""
    registry = CacheRegistry(budget_bytes=1024)
    try:
        region = registry.create_region("benchmark", CachePolicy(2, 768))
        region.put("first", b"x", 512)
        region.put("second", b"y", 400)
        overcommit_rejected = False
        try:
            registry.create_region("overflow", CachePolicy(1, 300))
        except ValueError:
            overcommit_rejected = True
        snapshot = registry.stats()
        region_stats = region.stats()
    finally:
        registry.close()
    return {
        "budget_bytes": snapshot.budget_bytes,
        "used_bytes": snapshot.bytes_used,
        "regions": len(snapshot.regions),
        "evictions": region_stats.evictions,
        "overcommit_rejected": overcommit_rejected,
    }


def _write_lock_probe(root: Path) -> dict[str, bool]:
    """验证同世界互斥且不同世界可独立获取租约。"""
    first = _create_world(root, "first")
    second = _create_world(root, "second")
    coordinator = WorldWriteCoordinator()
    with coordinator.reserve(first):
        outcome: list[str] = []

        def reserve_same_world() -> None:
            try:
                with coordinator.reserve(first):
                    outcome.append("acquired")
            except WorldOperationBusyError:
                outcome.append("busy")
            except Exception as exc:
                outcome.append(f"error:{type(exc).__name__}")

        thread = threading.Thread(target=reserve_same_world, daemon=True)
        thread.start()
        thread.join(1)
        if thread.is_alive():
            raise RuntimeError("同世界写入租约探针超时")
        if outcome != ["busy"]:
            raise RuntimeError(f"同世界写入租约结果异常: {outcome}")
        same_world_blocked = True
        with coordinator.reserve(second):
            different_world_allowed = True
    return {
        "same_world_blocked": same_world_blocked,
        "different_world_allowed": different_world_allowed,
    }


def run_benchmark() -> dict[str, object]:
    """运行所有无需真实存档的架构基准并返回 JSON 兼容报告。"""
    with tempfile.TemporaryDirectory(prefix="mcsavehelper-architecture-") as raw:
        root = Path(raw)
        world = _create_world(root, "world")
        registry = WorldIndexRegistry(builder=WorldIndexBuilder())
        try:
            cold_ms, snapshot = _timed(lambda: registry.get(world))
            warm_samples: list[float] = []
            for _ in range(5):
                warm_ms, second = _timed(lambda: registry.get(world))
                warm_samples.append(warm_ms)
                if snapshot.probe != second.probe:
                    raise RuntimeError("世界索引热读结果不稳定")
        finally:
            registry.close()
        return {
            "world_index": {
                "cold_ms": round(cold_ms, 3),
                "warm_ms": round(statistics.median(warm_samples), 3),
                "warm_median_ms": round(statistics.median(warm_samples), 3),
                "warm_p95_ms": round(max(warm_samples), 3),
                "samples": len(warm_samples),
                "regions": len(snapshot.region_files),
            },
            "runtime": _runtime_budget_probe(),
            "cache": _cache_budget_probe(),
            "world_writes": _write_lock_probe(root),
        }


def main() -> None:
    """输出机器可读的验收报告。"""
    print(json.dumps(run_benchmark(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
