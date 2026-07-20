"""Unit tests for PlayerManager extractors and name resolution."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import nbtlib
from nbtlib import Byte, Compound, Double, Float, Int, List as NbtList, String

from core.omni.player_manager import PlayerManager
from core.uuid_utils import format_uuid_with_hyphens, normalize_uuid


def _uuid_pair() -> tuple[str, str]:
    hyphen = "11111111-2222-3333-4444-555555555555"
    return hyphen, normalize_uuid(hyphen)


def _item(
    slot: int,
    item_id: str,
    count: int = 1,
    *,
    tag: Any = None,
    components: Any = None,
) -> Compound:
    data: Dict[str, Any] = {
        "Slot": Byte(slot) if -128 <= slot <= 127 else Int(slot),
        "id": String(item_id),
        "Count": Byte(count),
    }
    if tag is not None:
        data["tag"] = tag
    if components is not None:
        data["components"] = components
    return Compound(data)


def test_normalize_and_format_uuid() -> None:
    hyphen = "ABCDEF01-2345-6789-ABCD-EF0123456789"
    assert normalize_uuid(hyphen) == "abcdef0123456789abcdef0123456789"
    assert normalize_uuid("abcdef0123456789abcdef0123456789") == (
        "abcdef0123456789abcdef0123456789"
    )
    assert format_uuid_with_hyphens(hyphen) == (
        "abcdef01-2345-6789-abcd-ef0123456789"
    )
    assert PlayerManager.normalize_uuid(hyphen) == normalize_uuid(hyphen)
    assert PlayerManager.format_uuid_with_hyphens(hyphen) == (
        format_uuid_with_hyphens(hyphen)
    )
    assert normalize_uuid("") == ""
    assert format_uuid_with_hyphens("not-a-uuid") == "notauuid"


def test_seed_names_and_known_name_for_stats_only_uuid() -> None:
    manager = PlayerManager()
    hyphen, norm = _uuid_pair()
    manager.seed_names({hyphen: "Alex"})
    assert manager.get_known_name(norm) == "Alex"
    assert manager.get_known_name(hyphen) == "Alex"
    # stats-only UUID not in player_files still resolves
    assert manager.get_player_names([norm])[norm] == "Alex"


def test_initialize_names_merges_without_clobbering_seed() -> None:
    manager = PlayerManager()
    hyphen, norm = _uuid_pair()
    manager.seed_names({norm: "Seeded"})
    player_files = {norm: Path(f"{norm}.dat")}
    manager.initialize_names(
        player_files,
        {hyphen: "FromCache"},
    )
    # Existing seeded name must survive merge.
    assert manager.get_known_name(norm) == "Seeded"


def test_initialize_names_fills_from_usercache() -> None:
    manager = PlayerManager()
    hyphen, norm = _uuid_pair()
    manager.initialize_names(
        {norm: Path(f"{norm}.dat")},
        {hyphen: "Steve"},
    )
    assert manager.get_known_name(norm) == "Steve"


def test_import_usercache_normalizes_keys(tmp_path: Path) -> None:
    manager = PlayerManager()
    hyphen, norm = _uuid_pair()
    cache = tmp_path / "usercache.json"
    cache.write_text(
        json.dumps([{"uuid": hyphen.upper(), "name": "Bob"}]),
        encoding="utf-8",
    )
    imported = manager.import_usercache(cache, {norm: Path(f"{norm}.dat")})
    assert imported == 1
    assert manager.get_known_name(norm) == "Bob"


def test_resolve_player_name_from_nbt() -> None:
    manager = PlayerManager()
    _, norm = _uuid_pair()
    data = Compound({"LastKnownName": String("Notch")})
    assert manager.resolve_player_name(norm, data) == "Notch"
    assert manager.get_known_name(norm) == "Notch"


def test_extract_state_pose_spawn_death_abilities() -> None:
    manager = PlayerManager()
    data = Compound({
        "Health": Float(18.5),
        "foodLevel": Int(17),
        "foodSaturationLevel": Float(4.0),
        "XpLevel": Int(30),
        "XpTotal": Int(1395),
        "XpP": Float(0.4),
        "Air": Int(300),
        "Dimension": String("minecraft:the_nether"),
        "playerGameType": Int(1),
        "SelectedItemSlot": Int(3),
        "Score": Int(12),
        "Pos": NbtList[Double]([1.5, 64.0, -8.25]),
        "Rotation": NbtList[Float]([90.0, -15.0]),
        "SpawnX": Int(10),
        "SpawnY": Int(70),
        "SpawnZ": Int(-20),
        "SpawnDimension": String("minecraft:overworld"),
        "SpawnForced": Byte(1),
        "LastDeathLocation": Compound({
            "dimension": String("minecraft:the_end"),
            "pos": NbtList[Double]([100.0, 50.0, 200.0]),
        }),
        "abilities": Compound({
            "flying": Byte(1),
            "mayfly": Byte(1),
            "instabuild": Byte(1),
            "invulnerable": Byte(0),
            "mayBuild": Byte(1),
            "walkSpeed": Float(0.1),
            "flySpeed": Float(0.05),
        }),
    })

    state = manager.extract_state(data)
    assert state.health == 18.5
    assert state.food_level == 17
    assert state.game_type == 1
    assert state.dimension == "minecraft:the_nether"
    assert state.selected_slot == 3

    pose = manager.extract_pose(data)
    assert pose.x == 1.5
    assert pose.y == 64.0
    assert pose.z == -8.25
    assert pose.yaw == 90.0
    assert pose.pitch == -15.0

    spawn = manager.extract_spawn(data)
    assert (spawn.x, spawn.y, spawn.z) == (10, 70, -20)
    assert spawn.dimension == "minecraft:overworld"
    assert spawn.forced is True

    death = manager.extract_death(data)
    assert death is not None
    assert death.dimension == "minecraft:the_end"
    assert (death.x, death.y, death.z) == (100.0, 50.0, 200.0)

    abilities = manager.extract_abilities(data)
    assert abilities.flying is True
    assert abilities.may_fly is True
    assert abilities.instabuild is True
    assert abilities.invulnerable is False
    assert abilities.walk_speed == 0.1


def test_extract_missing_fields_are_safe() -> None:
    manager = PlayerManager()
    empty = manager.extract_state(None)
    assert empty.health is None
    assert manager.extract_death(Compound({})) is None
    containers = manager.extract_containers(None)
    assert containers.inventory == ()
    assert containers.equipment == ()
    assert containers.ender_items == ()


def test_extract_containers_partitions_inventory_and_ender() -> None:
    manager = PlayerManager()
    data = Compound({
        "Inventory": NbtList[Compound]([
            _item(0, "minecraft:stone", 64),
            _item(9, "minecraft:dirt", 32),
            _item(100, "minecraft:iron_boots", 1),
            _item(103, "minecraft:iron_helmet", 1),
            _item(-106, "minecraft:shield", 1),
            _item(5, "", 1),  # missing id -> skipped
        ]),
        "EnderItems": NbtList[Compound]([
            _item(0, "minecraft:diamond", 3),
            _item(26, "minecraft:emerald", 1),
            _item(30, "minecraft:gold_ingot", 1),  # out of range
        ]),
    })
    containers = manager.extract_containers(data)
    assert [item.slot for item in containers.inventory] == [0, 9]
    assert {item.slot for item in containers.equipment} == {100, 103, -106}
    assert [item.slot for item in containers.ender_items] == [0, 26]
    assert containers.ender_items[0].id == "minecraft:diamond"
    assert containers.ender_items[0].count == 3


def test_get_player_inventory_normalizes_count_and_components() -> None:
    manager = PlayerManager()
    # Mixed Count/count and components presence
    legacy = Compound({
        "Slot": Byte(1),
        "id": String("minecraft:apple"),
        "count": Int(8),  # modern lowercase
        "components": Compound({
            "minecraft:custom_name": String("Fancy Apple"),
        }),
    })
    data = Compound({"Inventory": NbtList[Compound]([legacy])})
    items = manager.get_player_inventory(data)
    assert len(items) == 1
    assert items[0]["slot"] == 1
    assert items[0]["id"] == "minecraft:apple"
    assert items[0]["count"] == 8
    assert items[0]["components"] is not None


def test_get_player_ender_items() -> None:
    manager = PlayerManager()
    data = Compound({
        "EnderItems": NbtList[Compound]([
            _item(2, "minecraft:ender_pearl", 16),
        ]),
    })
    items = manager.get_player_ender_items(data)
    assert items == [{
        "slot": 2,
        "id": "minecraft:ender_pearl",
        "count": 16,
    }]


def test_extract_identity() -> None:
    manager = PlayerManager()
    hyphen, norm = _uuid_pair()
    manager.seed_names({norm: "Alex"})
    identity = manager.extract_identity(hyphen)
    assert identity.uuid_norm == norm
    assert identity.uuid_hyphen == format_uuid_with_hyphens(norm)
    assert identity.name == "Alex"


def test_extract_attributes_and_effects() -> None:
    manager = PlayerManager()
    data = Compound({
        "Attributes": NbtList[Compound]([
            Compound({
                "Name": String("minecraft:generic.max_health"),
                "Base": Double(20.0),
                "Modifiers": NbtList[Compound]([
                    Compound({"Name": String("bonus"), "Amount": Double(2.0)}),
                ]),
            }),
        ]),
        "active_effects": NbtList[Compound]([
            Compound({
                "id": String("minecraft:speed"),
                "amplifier": Byte(1),
                "duration": Int(200),
                "ambient": Byte(0),
                "show_particles": Byte(1),
                "show_icon": Byte(1),
            }),
        ]),
    })
    attrs = manager.extract_attributes(data)
    assert len(attrs) == 1
    assert attrs[0].name == "minecraft:generic.max_health"
    assert attrs[0].base == 20.0
    assert attrs[0].modifiers == 1

    effects = manager.extract_effects(data)
    assert len(effects) == 1
    assert effects[0].id == "minecraft:speed"
    assert effects[0].amplifier == 1
    assert effects[0].duration == 200


def test_extract_nested_shulker_legacy_and_components() -> None:
    manager = PlayerManager()
    legacy = {
        "id": "minecraft:shulker_box",
        "count": 1,
        "tag": Compound({
            "BlockEntityTag": Compound({
                "Items": NbtList[Compound]([
                    _item(0, "minecraft:diamond", 5),
                    _item(10, "minecraft:gold_ingot", 2),
                ]),
            }),
        }),
    }
    nested = manager.extract_nested_container_items(legacy)
    assert len(nested) == 2
    assert nested[0]["id"] == "minecraft:diamond"
    assert nested[0]["count"] == 5

    modern = {
        "id": "minecraft:white_shulker_box",
        "count": 1,
        "components": Compound({
            "minecraft:container": NbtList[Compound]([
                Compound({
                    "slot": Int(3),
                    "item": Compound({
                        "id": String("minecraft:emerald"),
                        "count": Int(7),
                    }),
                }),
            ]),
        }),
    }
    nested2 = manager.extract_nested_container_items(modern)
    assert nested2 == [{
        "slot": 3,
        "id": "minecraft:emerald",
        "count": 7,
    }]

    assert manager.is_container_item("minecraft:purple_shulker_box")
    assert manager.extract_nested_container_items(
        {"id": "minecraft:shulker_box", "count": 1}
    ) == []
    assert manager.extract_nested_container_items(
        {"id": "minecraft:stone", "count": 1}
    ) == []
