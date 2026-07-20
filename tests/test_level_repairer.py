"""level.dat 字段修复纯逻辑与原子保存回归测试。"""
from __future__ import annotations

import threading
from pathlib import Path

import nbtlib

from app.services.save_repair.level_repairer import (
    LEVEL_DAT_REQUIRED_FIELDS,
    LevelRepairer,
    add_missing_level_fields,
    collect_level_field_repairs,
    repair_difficulty_if_out_of_range,
    repair_spawn_y_if_out_of_range,
)
from app.services.save_repair.models import RepairReport


def test_add_missing_level_fields_fills_required() -> None:
    data = nbtlib.Compound({})
    logs: list[tuple[str, str]] = []
    repaired = add_missing_level_fields(
        data,
        log=lambda msg, level: logs.append((level, msg)),
    )
    assert set(repaired) == set(LEVEL_DAT_REQUIRED_FIELDS)
    for name in LEVEL_DAT_REQUIRED_FIELDS:
        assert name in data
    assert any("补充缺失字段" in msg for _, msg in logs)


def test_repair_spawn_y_out_of_range() -> None:
    data = nbtlib.Compound({"SpawnY": nbtlib.Int(9999)})
    assert repair_spawn_y_if_out_of_range(data) == "SpawnY(范围修正)"
    assert int(data["SpawnY"]) == 64


def test_repair_spawn_y_in_range_noop() -> None:
    data = nbtlib.Compound({"SpawnY": nbtlib.Int(72)})
    assert repair_spawn_y_if_out_of_range(data) is None
    assert int(data["SpawnY"]) == 72


def test_repair_difficulty_out_of_range() -> None:
    data = nbtlib.Compound({"Difficulty": nbtlib.Byte(9)})
    assert repair_difficulty_if_out_of_range(data) == "Difficulty(范围修正)"
    assert int(data["Difficulty"]) == 2


def test_collect_level_field_repairs_combines_fixes() -> None:
    data = nbtlib.Compound({
        "SpawnY": nbtlib.Int(-200),
        "Difficulty": nbtlib.Byte(8),
    })
    repaired = collect_level_field_repairs(data)
    assert "SpawnY(范围修正)" in repaired
    assert "Difficulty(范围修正)" in repaired
    # Missing required fields still get filled.
    assert "LevelName" in repaired


def test_level_repairer_writes_defaults_to_empty_data(tmp_path: Path) -> None:
    world = tmp_path / "world"
    world.mkdir()
    level_path = world / "level.dat"
    nbtlib.File({"Data": nbtlib.Compound({})}).save(level_path)

    report = RepairReport()
    LevelRepairer(threading.Event()).repair_level_dat(
        world,
        report,
        lambda *_: None,
    )

    assert report.level_dat_fixed is True
    assert report.level_dat_repaired_fields
    repaired = nbtlib.load(level_path)["Data"]
    assert "LevelName" in repaired
    assert isinstance(repaired["DataVersion"], nbtlib.Int)
