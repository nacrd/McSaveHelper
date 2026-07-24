"""存档检测器维度识别与容错回归。"""
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import cast

import core.nbt as nbtlib

from app.services.execution_runtime import ExecutionRuntime
from app.services.save_repair.detector import (
    WorldDetector,
    _read_int_tag,
    dimension_for_region_parts,
)
from app.services.save_repair.models import DetectReport


def test_dimension_for_region_parts_known_layouts() -> None:
    assert dimension_for_region_parts(("region", "r.0.0.mca")) == (
        "minecraft:overworld"
    )
    assert dimension_for_region_parts(("DIM-1", "region", "r.0.0.mca")) == (
        "minecraft:the_nether"
    )
    assert dimension_for_region_parts(("DIM1", "region", "r.0.0.mca")) == (
        "minecraft:the_end"
    )
    assert dimension_for_region_parts(
        ("dimensions", "minecraft", "foo", "region", "r.0.0.mca")
    ) == "minecraft:foo"


def test_detect_dimensions_includes_overworld_region_layout(tmp_path: Path) -> None:
    world = tmp_path / "world"
    (world / "region").mkdir(parents=True)
    (world / "DIM-1" / "region").mkdir(parents=True)
    (world / "DIM1" / "region").mkdir(parents=True)
    (world / "region" / "r.0.0.mca").write_bytes(b"\x00" * 4096)
    (world / "DIM-1" / "region" / "r.0.0.mca").write_bytes(b"\x00" * 4096)
    (world / "DIM1" / "region" / "r.0.0.mca").write_bytes(b"\x00" * 4096)

    info = DetectReport().world_info
    WorldDetector(threading.Event(), ExecutionRuntime())._detect_dimensions(
        world,
        info,
    )

    assert info.dimensions == [
        "minecraft:overworld",
        "minecraft:the_end",
        "minecraft:the_nether",
    ]
    assert info.region_count == 3


def test_read_int_tag_falls_back_for_missing_or_invalid_values() -> None:
    compound = cast(
        nbtlib.tag.Compound,
        SimpleNamespace(get=lambda key: None if key == "missing" else "bad"),
    )

    assert _read_int_tag(compound, "missing", 7) == 7
    assert _read_int_tag(compound, "bad", 9) == 9
