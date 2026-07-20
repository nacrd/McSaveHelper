import os
import threading
from pathlib import Path
from typing import Any

import core.nbt as nbtlib

from app.services.save_repair.level_repairer import LevelRepairer
from app.services.save_repair.models import RepairReport
from app.services.save_repair.player_repairer import PlayerRepairer


def _log(_message: str, _level: str) -> None:
    return None


def test_player_defaults_are_flat_typed_lists_after_reload(tmp_path: Path) -> None:
    world = tmp_path / "world"
    player_dir = world / "playerdata"
    player_dir.mkdir(parents=True)
    player_path = player_dir / "player.dat"
    nbtlib.File({}).save(player_path)

    report = RepairReport()
    PlayerRepairer(threading.Event()).repair_players(world, report, _log)

    repaired = nbtlib.load(player_path)
    assert type(repaired["Pos"]) is nbtlib.List[nbtlib.Double]
    assert [float(value) for value in repaired["Pos"]] == [0.0, 64.0, 0.0]
    assert all(isinstance(value, nbtlib.Double) for value in repaired["Pos"])
    assert type(repaired["Rotation"]) is nbtlib.List[nbtlib.Float]
    assert [float(value) for value in repaired["Rotation"]] == [0.0, 0.0]
    assert all(isinstance(value, nbtlib.Float) for value in repaired["Rotation"])


def test_level_repair_uses_nbt_scalars_and_sets_status_after_save(
    tmp_path: Path,
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    level_path = world / "level.dat"
    nbtlib.File({"Data": nbtlib.Compound({})}).save(level_path)

    report = RepairReport()
    LevelRepairer(threading.Event()).repair_level_dat(world, report, _log)

    repaired = nbtlib.load(level_path)["Data"]
    assert report.level_dat_fixed is True
    assert isinstance(repaired["DataVersion"], nbtlib.Int)
    assert isinstance(repaired["LevelName"], nbtlib.String)
    assert isinstance(repaired["RandomSeed"], nbtlib.Long)
    assert isinstance(repaired["Difficulty"], nbtlib.Byte)


def test_level_repair_failure_preserves_original_and_failure_status(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    level_path = world / "level.dat"
    nbtlib.File({"Data": nbtlib.Compound({})}).save(level_path)
    original = level_path.read_bytes()

    def fail_replace(_source: os.PathLike[str], _target: os.PathLike[str]) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(
        "app.services.save_repair.level_repairer.os.replace", fail_replace
    )
    report = RepairReport()
    LevelRepairer(threading.Event()).repair_level_dat(world, report, _log)

    assert report.level_dat_fixed is False
    assert report.level_dat_repaired_fields == []
    assert level_path.read_bytes() == original
    assert not list(world.glob(".level.dat.*.tmp"))
