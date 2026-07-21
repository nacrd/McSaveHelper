"""架构重构的可重复性能与并发不变量基准。"""
from __future__ import annotations

import json
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
)
from app.services.world_write_coordinator import WorldWriteCoordinator
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


def _runtime_budget_probe() -> dict[str, int]:
    """验证受限运行时的实际工作线程数不超过配置。"""
    limits = LaneLimits(max_workers=1, queue_capacity=2)
    runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
    started = threading.Event()
    release = threading.Event()

    def wait_for_release(token: Any) -> None:
        started.set()
        while not release.is_set():
            token.raise_if_cancelled()
            release.wait(0.01)

    handle = runtime.submit(
        "bench_runtime",
        wait_for_release,
        lane=ExecutionLane.CPU,
    )
    try:
        if not started.wait(1):
            raise RuntimeError("运行时基准任务未启动")
        workers = runtime.snapshot().worker_count_by_lane[ExecutionLane.CPU]
    finally:
        release.set()
        handle.result(timeout=1)
        runtime.shutdown(wait=True)
    return {"cpu_workers": workers, "cpu_worker_limit": limits.max_workers}


def _cache_budget_probe() -> dict[str, int]:
    """验证缓存注册表不允许超额预算。"""
    registry = CacheRegistry(budget_bytes=1024)
    region = registry.create_region("benchmark", CachePolicy(2, 768))
    region.put("entry", b"x", 512)
    snapshot = registry.stats()
    registry.close()
    return {
        "budget_bytes": snapshot.budget_bytes,
        "used_bytes": snapshot.bytes_used,
        "regions": len(snapshot.regions),
    }


def _write_lock_probe(root: Path) -> dict[str, bool]:
    """验证同世界互斥且不同世界可独立获取租约。"""
    first = _create_world(root, "first")
    second = _create_world(root, "second")
    coordinator = WorldWriteCoordinator()
    same_world_blocked = False
    with coordinator.reserve(first):
        acquired = threading.Event()
        finished = threading.Event()

        def reserve_same_world() -> None:
            try:
                with coordinator.reserve(first):
                    acquired.set()
            except Exception:
                pass
            finally:
                finished.set()

        thread = threading.Thread(target=reserve_same_world)
        thread.start()
        finished.wait(1)
        same_world_blocked = not acquired.is_set()
        thread.join(1)
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
        builder = WorldIndexBuilder()
        cold_ms, snapshot = _timed(lambda: builder.build(world))
        hot_ms, second = _timed(lambda: builder.build(world))
        if snapshot.probe != second.probe:
            raise RuntimeError("世界索引热读结果不稳定")
        return {
            "world_index": {
                "cold_ms": round(cold_ms, 3),
                "warm_ms": round(hot_ms, 3),
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
