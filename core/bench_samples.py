"""可重复的合成 Minecraft 世界样本，供架构与 MCA 基准使用。

样本仅包含最小合法 level.dat 与区域文件，不依赖真实存档。
尺寸档位固定，便于跨机器比较相对性能趋势。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

import core.nbt as nbtlib
from core.mca import WritableRegion


class SampleSize(str, Enum):
    """固定的合成世界规模档位。"""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


@dataclass(frozen=True)
class SampleSpec:
    """一个样本档位的可观测规模。"""

    size: SampleSize
    region_count: int
    chunks_per_region: int
    label: str


SAMPLE_SPECS: dict[SampleSize, SampleSpec] = {
    SampleSize.SMALL: SampleSpec(
        SampleSize.SMALL,
        region_count=1,
        chunks_per_region=4,
        label="small (1 region x 4 chunks)",
    ),
    SampleSize.MEDIUM: SampleSpec(
        SampleSize.MEDIUM,
        region_count=4,
        chunks_per_region=16,
        label="medium (4 regions x 16 chunks)",
    ),
    SampleSize.LARGE: SampleSpec(
        SampleSize.LARGE,
        region_count=16,
        chunks_per_region=32,
        label="large (16 regions x 32 chunks)",
    ),
}


REFERENCE_MACHINE = {
    "profile": "synthetic-fixed-samples",
    "notes": (
        "使用固定合成世界档位，而不是真实存档路径；"
        "跨机器比较相对耗时与缓存命中，而不是绝对 wall-clock 基线。"
    ),
    "budget_module": "core.bench_budgets.DEFAULT_BUDGETS",
    "how_to_run": (
        "python scripts/bench_mca.py --sizes small medium large "
        "--loops 3 --check-budgets --json"
    ),
    "true_machine_sla": (
        "真机 p95 需在固定硬件上手动采集真实存档并归档；"
        "本仓库默认门禁仅使用合成预算。"
    ),
}


def _mini_chunk(x: int, z: int, marker: str = "full") -> nbtlib.File:
    """构造最小可读写区块 NBT。"""
    return nbtlib.File(
        {
            "DataVersion": nbtlib.Int(3463),
            "xPos": nbtlib.Int(x),
            "zPos": nbtlib.Int(z),
            "Status": nbtlib.String(marker),
        }
    )


def _write_level_dat(world: Path) -> None:
    """写入最小合法 level.dat。"""
    nbtlib.File(
        {
            "Data": nbtlib.Compound(
                {
                    "DataVersion": nbtlib.Int(3463),
                    "LevelName": nbtlib.String(world.name),
                    "version": nbtlib.Int(19133),
                }
            )
        }
    ).save(world / "level.dat")


def _region_coords(count: int) -> list[tuple[int, int]]:
    """按螺旋近似顺序生成固定数量的区域坐标。"""
    coords: list[tuple[int, int]] = []
    ring = 0
    while len(coords) < count:
        if ring == 0:
            coords.append((0, 0))
            ring = 1
            continue
        for x in range(-ring, ring + 1):
            for z in (-ring, ring):
                coords.append((x, z))
                if len(coords) >= count:
                    return coords
        for z in range(-ring + 1, ring):
            for x in (-ring, ring):
                coords.append((x, z))
                if len(coords) >= count:
                    return coords
        ring += 1
    return coords[:count]


def _chunk_coords(count: int) -> list[tuple[int, int]]:
    """在单个区域局部坐标范围内生成固定数量的区块坐标。"""
    coords: list[tuple[int, int]] = []
    for z in range(32):
        for x in range(32):
            coords.append((x, z))
            if len(coords) >= count:
                return coords
    return coords


def create_sample_world(
    root: Path | str,
    size: SampleSize | str = SampleSize.SMALL,
    *,
    name: str | None = None,
) -> Path:
    """在 root 下创建指定档位的合成世界。

    Args:
        root: 父目录；会在其中创建世界子目录。
        size: small/medium/large。
        name: 可选世界目录名；默认使用档位名。

    Returns:
        世界根路径（含 level.dat 与 region/）。
    """
    sample_size = SampleSize(size)
    spec = SAMPLE_SPECS[sample_size]
    world = Path(root) / (name or sample_size.value)
    if world.exists():
        raise FileExistsError(f"样本世界目录已存在: {world}")
    region_dir = world / "region"
    region_dir.mkdir(parents=True)
    (world / "playerdata").mkdir()
    (world / "data").mkdir()
    (world / "stats").mkdir()
    _write_level_dat(world)

    chunk_coords = _chunk_coords(spec.chunks_per_region)
    for region_x, region_z in _region_coords(spec.region_count):
        path = region_dir / f"r.{region_x}.{region_z}.mca"
        writer = WritableRegion.empty(path)
        for local_x, local_z in chunk_coords:
            writer.set_chunk(
                local_x,
                local_z,
                _mini_chunk(
                    region_x * 32 + local_x,
                    region_z * 32 + local_z,
                ),
            )
        writer.save(path, backup=False)
    return world.resolve()


def create_all_sample_worlds(root: Path | str) -> dict[SampleSize, Path]:
    """创建全部固定档位样本并返回映射。"""
    parent = Path(root)
    parent.mkdir(parents=True, exist_ok=True)
    return {
        size: create_sample_world(parent, size)
        for size in (SampleSize.SMALL, SampleSize.MEDIUM, SampleSize.LARGE)
    }


def iter_sample_specs() -> Iterable[SampleSpec]:
    """按 small -> medium -> large 顺序迭代规格。"""
    for size in (SampleSize.SMALL, SampleSize.MEDIUM, SampleSize.LARGE):
        yield SAMPLE_SPECS[size]


__all__ = [
    "REFERENCE_MACHINE",
    "SAMPLE_SPECS",
    "SampleSize",
    "SampleSpec",
    "create_all_sample_worlds",
    "create_sample_world",
    "iter_sample_specs",
]
