"""Tests for PlayerService edit proposals, summary, and export."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

from nbtlib import Byte, Compound, Double, Float, Int, List as NbtList, String

from app.services.player_service import PlayerService
from app.presenters.player_presenter import format_player_summary_text
from core.omni.player_manager import PlayerManager
from core.uuid_utils import normalize_uuid


def _uuid() -> str:
    return "11111111222233334444555555555555"


def _player_compound() -> Compound:
    return Compound({
        "Health": Float(20.0),
        "foodLevel": Int(20),
        "foodSaturationLevel": Float(5.0),
        "XpLevel": Int(5),
        "XpTotal": Int(55),
        "XpP": Float(0.2),
        "Air": Int(300),
        "Dimension": String("minecraft:overworld"),
        "playerGameType": Int(0),
        "SelectedItemSlot": Int(0),
        "Pos": NbtList[Double]([10.0, 64.0, -3.0]),
        "Rotation": NbtList[Float]([0.0, 0.0]),
        "SpawnX": Int(0),
        "SpawnY": Int(64),
        "SpawnZ": Int(0),
        "SpawnDimension": String("minecraft:overworld"),
        "SpawnForced": Byte(0),
        "LastDeathLocation": Compound({
            "dimension": String("minecraft:the_nether"),
            "pos": NbtList[Double]([1.0, 40.0, 2.0]),
        }),
        "abilities": Compound({
            "flying": Byte(0),
            "mayfly": Byte(0),
            "instabuild": Byte(0),
            "invulnerable": Byte(0),
            "mayBuild": Byte(1),
            "walkSpeed": Float(0.1),
            "flySpeed": Float(0.05),
        }),
        "Inventory": NbtList[Compound]([
            Compound({
                "Slot": Byte(0),
                "id": String("minecraft:stone"),
                "Count": Byte(3),
            }),
            Compound({
                "Slot": Byte(100),
                "id": String("minecraft:iron_boots"),
                "Count": Byte(1),
            }),
        ]),
        "EnderItems": NbtList[Compound]([
            Compound({
                "Slot": Byte(0),
                "id": String("minecraft:diamond"),
                "Count": Byte(1),
            }),
        ]),
    })


def _session(data: Compound, uuid: Optional[str] = None) -> MagicMock:
    uid = uuid or _uuid()
    session = MagicMock()
    session.get_player_uuids.return_value = [uid]
    session.get_player_names.return_value = {uid: "Alex"}
    session.get_known_player_name.return_value = "Alex"
    session.get_player_data.return_value = data
    session.get_player_file_path.return_value = Path(f"{uid}.dat")
    return session


def test_list_players_sorted_by_display_name() -> None:
    session = MagicMock()
    session.get_player_uuids.return_value = [
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ]
    session.get_player_names.return_value = {
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": "Zed",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": "Amy",
    }
    session.get_known_player_name.side_effect = lambda u: None
    session.get_player_file_path.return_value = None

    refs = PlayerService().list_players(session)
    assert [ref.display_name for ref in refs] == ["Amy", "Zed"]


def test_load_summary_and_containers() -> None:
    data = _player_compound()
    session = _session(data)
    service = PlayerService()

    summary = service.load_summary(session, _uuid())
    assert summary is not None
    assert summary.ref.name == "Alex"
    assert summary.state.health == 20.0
    assert summary.inventory_count == 1
    assert summary.equipment_count == 1
    assert summary.ender_count == 1
    assert summary.death is not None
    assert summary.death.dimension == "minecraft:the_nether"

    containers = service.load_containers(session, _uuid())
    assert containers is not None
    assert containers.inventory[0]["id"] == "minecraft:stone"
    assert containers.equipment[0]["slot"] == 100
    assert containers.ender_items[0]["id"] == "minecraft:diamond"


def test_build_edit_changes_stages_diff_only() -> None:
    data = _player_compound()
    service = PlayerService()
    result = service.build_edit_changes(
        _uuid(),
        data,
        {
            "Health": "20.0",  # unchanged
            "foodLevel": "10",
            "playerGameType": "1",
        },
    )
    assert result.errors == ()
    assert result.staged_count == 2
    paths = {change.display_path for change in result.changes}
    assert paths == {"foodLevel", "playerGameType"}
    for change in result.changes:
        assert change.operation == "set"
        assert change.format == "nbt"


def test_build_edit_changes_rejects_out_of_range() -> None:
    data = _player_compound()
    service = PlayerService()
    result = service.build_edit_changes(
        _uuid(),
        data,
        {"Health": "99999", "foodLevel": "-1"},
    )
    assert result.staged_count == 0
    assert any("Health:above_max" in err for err in result.errors)
    assert any("foodLevel:below_min" in err for err in result.errors)


def test_build_teleport_to_death_changes() -> None:
    data = _player_compound()
    service = PlayerService()
    result = service.build_teleport_to_death_changes(_uuid(), data)
    assert result.errors == ()
    assert result.staged_count >= 3
    paths = {change.display_path for change in result.changes}
    assert "Pos.0" in paths or "Pos" in {p.split(".")[0] for p in paths}
    # Dimension should also be staged when different
    assert "Dimension" in paths


def test_form_values_from_data() -> None:
    data = _player_compound()
    values = PlayerService().form_values_from_data(data)
    assert values["Health"] == "20.0" or values["Health"].startswith("20")
    assert values["foodLevel"] == "20"
    assert "Pos.0" in values


def test_build_export_dict_and_presenter() -> None:
    data = _player_compound()
    session = _session(data)
    service = PlayerService()
    bundle = service.build_export(session, _uuid(), include_items=True)
    assert bundle is not None
    payload = bundle.to_dict()
    assert payload["name"] == "Alex"
    assert payload["counts"]["inventory"] == 1
    assert payload["inventory"][0]["id"] == "minecraft:stone"

    text = format_player_summary_text(bundle.summary)
    assert "Alex" in text
    assert "玩家摘要" in text


def test_player_manager_normalize_used_in_service_path() -> None:
    assert normalize_uuid("A-B") == PlayerManager.normalize_uuid("A-B")
