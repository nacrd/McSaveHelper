"""玩家字段缺失检测与默认值填充的纯逻辑测试。"""
from __future__ import annotations

import threading
from pathlib import Path

import core.nbt as nbtlib
from core.nbt import Compound, Float, Int

from app.services.save_repair.models import IssueLevel, RepairReport
from app.services.save_repair.player_repairer import (
    PLAYER_REQUIRED_FIELDS,
    PlayerRepairer,
    apply_player_field_defaults,
    find_missing_player_fields,
    get_player_defaults,
)


def test_find_missing_player_fields_preserves_required_order() -> None:
    data = {"Health": Float(20.0), "foodLevel": Int(20)}
    missing = find_missing_player_fields(data)
    assert missing[0] == "Pos"
    assert "Health" not in missing
    assert "foodLevel" not in missing
    assert missing == [name for name in PLAYER_REQUIRED_FIELDS if name not in data]


def test_apply_player_field_defaults_writes_only_requested() -> None:
    data: dict = {}
    repaired = apply_player_field_defaults(data, ["Pos", "missing_key"])
    assert repaired == ["Pos"]
    assert "Pos" in data
    assert "Health" not in data


def test_apply_skips_incompatible_assignment() -> None:
    class BrokenMap(dict):
        def __setitem__(self, key, value):  # type: ignore[no-untyped-def]
            if key == "Pos":
                raise TypeError("incompatible")
            super().__setitem__(key, value)

    data = BrokenMap()
    repaired = apply_player_field_defaults(data, ["Pos", "Health"])
    assert repaired == ["Health"]
    assert "Health" in data
    assert "Pos" not in data


def test_get_player_defaults_returns_fresh_instances() -> None:
    a = get_player_defaults()
    b = get_player_defaults()
    assert a is not b
    assert a["Pos"] is not b["Pos"]


def test_repair_players_fills_empty_player_dat(tmp_path: Path) -> None:
    world = tmp_path / "world"
    player_dir = world / "playerdata"
    player_dir.mkdir(parents=True)
    player_path = player_dir / "player.dat"
    nbtlib.File(Compound({})).save(player_path)

    report = RepairReport()
    logs: list[tuple[str, str]] = []
    PlayerRepairer(threading.Event()).repair_players(
        world,
        report,
        lambda msg, level: logs.append((level, msg)),
    )

    assert report.players_checked == 1
    assert report.players_fixed == 1
    assert report.players_quarantined == 0
    repaired = nbtlib.load(player_path)
    for field in PLAYER_REQUIRED_FIELDS:
        assert field in repaired
    assert any(issue.level == IssueLevel.FIXED for issue in report.issues)


def test_repair_players_respects_cancel(tmp_path: Path) -> None:
    world = tmp_path / "world"
    player_dir = world / "playerdata"
    player_dir.mkdir(parents=True)
    for name in ("a.dat", "b.dat"):
        nbtlib.File(Compound({})).save(player_dir / name)

    cancel = threading.Event()
    cancel.set()
    report = RepairReport()
    PlayerRepairer(cancel).repair_players(world, report, lambda *_: None)
    assert report.players_checked == 0
    assert report.players_fixed == 0
