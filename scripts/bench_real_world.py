#!/usr/bin/env python3
"""Strictly read-only performance benchmark for one real Java world."""
from __future__ import annotations

import os
import platform
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from app.services.world_index_service import WorldIndexRegistry
from app.services.world_repository import WorldRepository
from core.mca import RegionFile, clear_chunk_decode_cache
from core.mca.topview_renderer import PREVIEW_TILE_SIZE, render_region_topview
from core.nbt import load as load_nbt
from core.observability import p95
from core.omni.world_session import WorldSession
from core.world_index import WorldIndexBuilder


@dataclass(frozen=True)
class _WorldFileFingerprint:
    """Read-only verification fields for one file inside a real world."""

    relative_path: str
    size_bytes: int
    modified_ns: int


def _timed(callable_: Callable[[], Any]) -> tuple[float, Any]:
    started = time.perf_counter()
    result = callable_()
    return (time.perf_counter() - started) * 1000.0, result


def _median(samples: list[float]) -> float:
    return statistics.median(samples) if samples else 0.0


def _capture_world_manifest(world: Path) -> tuple[_WorldFileFingerprint, ...]:
    """Capture stable write-sensitive fields and reject linked content."""
    fingerprints: list[_WorldFileFingerprint] = []
    for path in sorted(world.rglob("*")):
        is_junction = bool(getattr(path, "is_junction", lambda: False)())
        if path.is_symlink() or is_junction:
            raise ValueError(f"真实世界基准拒绝链接路径: {path}")
        if not path.is_file():
            continue
        stat = path.stat()
        fingerprints.append(_WorldFileFingerprint(
            relative_path=path.relative_to(world).as_posix(),
            size_bytes=stat.st_size,
            modified_ns=stat.st_mtime_ns,
        ))
    return tuple(fingerprints)


def _region_files(world: Path) -> list[Path]:
    """Return chunk-region MCA files across all vanilla dimensions."""
    return sorted(
        path
        for path in world.rglob("r.*.*.mca")
        if path.parent.name == "region" and path.is_file()
    )


def _representative_region(world: Path) -> Path:
    """Choose the largest overworld region, matching the first map surface."""
    regions = sorted(
        (world / "region").glob("r.*.*.mca"),
        key=lambda path: (path.stat().st_size, path.name),
        reverse=True,
    )
    if not regions:
        raise RuntimeError(f"真实世界没有主世界区域文件: {world}")
    return regions[0]


def _machine_profile(world: Path) -> dict[str, object]:
    """Describe the machine and sample required to interpret wall-clock data."""
    return {
        "profile": "real-world-readonly",
        "os": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "world_path": str(world),
        "notes": (
            "用户提供的单个真实 Java 世界；预热后采样，基准前后验证文件未变；"
            "不执行备份或任何世界写入。"
        ),
    }


def _bench_mca(target: Path, loops: int) -> dict[str, Any]:
    """Measure a representative real region after one untimed warmup."""

    def open_and_read() -> tuple[float, float, int]:
        open_ms, region = _timed(lambda: RegionFile.open(target))
        try:
            coords = list(region.iter_present_chunks())

            def read_all() -> None:
                for chunk_x, chunk_z in coords:
                    region.read_chunk(chunk_x, chunk_z)

            read_ms, _ = _timed(read_all)
            return open_ms, read_ms, len(coords)
        finally:
            region.close()

    open_and_read()
    samples = [open_and_read() for _ in range(loops)]
    open_times = [sample[0] for sample in samples]
    read_times = [sample[1] for sample in samples]
    return {
        "region_file": target.name,
        "region_bytes": target.stat().st_size,
        "chunk_count": samples[-1][2],
        "open_median_ms": round(_median(open_times), 3),
        "open_p95_ms": round(p95(open_times), 3),
        "read_batch_median_ms": round(_median(read_times), 3),
        "read_batch_p95_ms": round(p95(read_times), 3),
        "loops": loops,
        "warmup_runs": 1,
    }


def _bench_nbt(world: Path, loops: int) -> dict[str, Any]:
    """Measure level.dat and one representative player NBT read."""
    level_path = world / "level.dat"
    player_files = sorted((world / "playerdata").glob("*.dat"))
    player_path = max(player_files, key=lambda path: path.stat().st_size, default=None)

    def measure(path: Path) -> dict[str, object]:
        load_nbt(path)
        samples = [_timed(lambda: load_nbt(path))[0] for _ in range(loops)]
        return {
            "file": path.relative_to(world).as_posix(),
            "bytes": path.stat().st_size,
            "median_ms": round(_median(samples), 3),
            "p95_ms": round(p95(samples), 3),
        }

    result: dict[str, Any] = {
        "level": measure(level_path),
        "loops": loops,
        "warmup_runs": 1,
    }
    result["player"] = measure(player_path) if player_path is not None else None
    return result


def _bench_world_index(world: Path, loops: int) -> dict[str, Any]:
    """Measure forced index rebuilds and cached reads after one warmup."""
    registry = WorldIndexRegistry(builder=WorldIndexBuilder())
    try:
        registry.get(world, force_refresh=True)
        cold_samples: list[float] = []
        snapshot = None
        for _ in range(loops):
            cold_ms, snapshot = _timed(
                lambda: registry.get(world, force_refresh=True)
            )
            cold_samples.append(cold_ms)
        if snapshot is None:
            raise RuntimeError("真实世界索引基准没有生成快照")
        warm_samples = [
            _timed(lambda: registry.get(world))[0]
            for _ in range(loops)
        ]
        return {
            "cold_ms": round(_median(cold_samples), 3),
            "cold_median_ms": round(_median(cold_samples), 3),
            "cold_p95_ms": round(p95(cold_samples), 3),
            "warm_median_ms": round(_median(warm_samples), 3),
            "warm_p95_ms": round(p95(warm_samples), 3),
            "regions": len(snapshot.region_files),
            "players": len(snapshot.player_files),
            "loops": loops,
            "warmup_runs": 1,
        }
    finally:
        registry.close()


def _bench_world_session(world: Path, loops: int) -> dict[str, Any]:
    """Measure shell, cold indexed session, and pre-indexed session paths."""
    registry = WorldIndexRegistry(builder=WorldIndexBuilder())
    repository = WorldRepository(registry)
    try:
        repository.open(world)
        shell_samples = [
            _timed(lambda: repository.open(world))[0]
            for _ in range(loops)
        ]
        cold_samples: list[float] = []
        snapshot = None
        for _ in range(loops):
            repository.invalidate(world)
            context = repository.open(world)
            cold_ms, session = _timed(context.open_session)
            cold_samples.append(cold_ms)
            snapshot = context.get_index()
            del session
        if snapshot is None:
            raise RuntimeError("真实世界会话基准没有生成索引")
        WorldSession(world, index_snapshot=snapshot)
        warm_samples: list[float] = []
        for _ in range(loops):
            warm_ms, session = _timed(
                lambda: WorldSession(world, index_snapshot=snapshot)
            )
            warm_samples.append(warm_ms)
            del session
        return {
            "shell_open_median_ms": round(_median(shell_samples), 3),
            "shell_open_p95_ms": round(p95(shell_samples), 3),
            "cold_open_median_ms": round(_median(cold_samples), 3),
            "cold_open_p95_ms": round(p95(cold_samples), 3),
            "open_with_index_median_ms": round(_median(warm_samples), 3),
            "open_with_index_p95_ms": round(p95(warm_samples), 3),
            "player_count": len(snapshot.player_files),
            "region_count": len(snapshot.region_files),
            "loops": loops,
            "warmup_runs": 1,
        }
    finally:
        repository.close()


def _bench_cache_hit(
    region_path: Path,
    png: bytes,
    tile_size: int,
    loops: int,
) -> dict[str, Any]:
    """Measure disk cache hits inside an isolated temporary cache."""
    from core.mca import tile_cache

    previous_cache_dir = tile_cache._CACHE_DIR
    with tempfile.TemporaryDirectory(prefix="mcsavehelper-real-tile-bench-") as raw:
        tile_cache._CACHE_DIR = Path(raw)
        try:
            tile_cache.store_tile(region_path, tile_size, png)
            samples: list[float] = []
            for _ in range(loops):
                hit_ms, cached = _timed(
                    lambda: tile_cache.load_tile(region_path, tile_size)
                )
                if cached is None:
                    raise RuntimeError("真实世界俯视图磁盘缓存命中丢失")
                samples.append(hit_ms)
            return {
                "cache_hit_median_ms": round(_median(samples), 3),
                "cache_hit_p95_ms": round(p95(samples), 3),
                "cache_hit_samples": len(samples),
                "cache_hit_count": len(samples),
            }
        finally:
            tile_cache._CACHE_DIR = previous_cache_dir


def _bench_topview(target: Path, loops: int) -> dict[str, Any]:
    """Measure the UI's initial preview path cold, process-warm and disk-warm."""
    tile_size = PREVIEW_TILE_SIZE

    def render() -> Optional[bytes]:
        return render_region_topview(
            target,
            tile_size=tile_size,
            use_disk_cache=False,
            decode_workers=1,
        )

    clear_chunk_decode_cache()
    render()
    cold_samples: list[float] = []
    png: Optional[bytes] = None
    for _ in range(loops):
        clear_chunk_decode_cache()
        render_ms, png = _timed(render)
        cold_samples.append(render_ms)
    clear_chunk_decode_cache()
    png = render()
    warm_samples: list[float] = []
    for _ in range(loops):
        render_ms, png = _timed(render)
        warm_samples.append(render_ms)
    if not png:
        raise RuntimeError(f"真实世界俯视图渲染没有生成瓦片: {target}")
    cache_hit = _bench_cache_hit(target, png, tile_size, loops)
    clear_chunk_decode_cache()
    return {
        "region_file": target.name,
        "tile_size": tile_size,
        "path_semantics": "ui_initial_preview_largest_overworld_region",
        "tile_median_ms": round(_median(cold_samples), 3),
        "tile_p95_ms": round(p95(cold_samples), 3),
        "memory_warm_median_ms": round(_median(warm_samples), 3),
        "memory_warm_p95_ms": round(p95(warm_samples), 3),
        "tile_bytes": len(png),
        "rendered": True,
        "loops": loops,
        "warmup_runs": 1,
        **cache_hit,
    }


def run_real_world_benchmark(
    world_path: Path | str,
    loops: int = 3,
) -> dict[str, Any]:
    """Run a read-only benchmark against one supplied real Java world.

    Args:
        world_path: World root containing ``level.dat`` and overworld regions.
        loops: Timed samples after one untimed warmup.
    Returns:
        JSON-compatible benchmark report with read-only verification.
    Raises:
        FileNotFoundError: The path is not a Java world.
        RuntimeError: Benchmarking changed the source or a metric failed.
        ValueError: The world contains a linked path.
    """
    world = Path(world_path).expanduser().resolve()
    if not (world / "level.dat").is_file():
        raise FileNotFoundError(f"真实世界缺少 level.dat: {world}")
    before = _capture_world_manifest(world)
    if not before:
        raise RuntimeError(f"真实世界没有可读文件: {world}")
    effective_loops = max(1, int(loops))
    regions = _region_files(world)
    target = _representative_region(world)
    sample: dict[str, Any] = {
        "size": "real",
        "scale_hint": "large" if len(regions) >= 16 else "unclassified",
        "label": f"real world: {world.name}",
        "source": {
            "world_name": world.name,
            "world_path": str(world),
            "file_count": len(before),
            "size_bytes": sum(item.size_bytes for item in before),
            "region_count": len(regions),
        },
        "mca": _bench_mca(target, effective_loops),
        "nbt": _bench_nbt(world, effective_loops),
        "world_index": _bench_world_index(world, effective_loops),
        "world_session": _bench_world_session(world, effective_loops),
        "topview": _bench_topview(target, effective_loops),
        "backup": {
            "skipped": True,
            "reason": "真实世界模式严格只读",
        },
    }
    after = _capture_world_manifest(world)
    if after != before:
        raise RuntimeError("真实世界基准检测到源文件变化，报告已拒绝")
    sample["read_only_verified"] = True
    return {
        "reference_machine": _machine_profile(world),
        "loops": effective_loops,
        "warmup_runs": 1,
        "samples": [sample],
        "budgets_ok": None,
        "budget_violations": [],
        "budget_result": {
            "ok": None,
            "violations": [],
            "checked_samples": 0,
            "reason": "真实样本不套用合成预算",
        },
    }


__all__ = ["run_real_world_benchmark"]
