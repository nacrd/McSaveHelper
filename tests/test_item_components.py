"""Item component parsing and inventory UI service injection tests."""
from typing import Any, Dict, cast

from app.services.item.parser import parse_item
from app.services.item_service import ItemService
from app.services.texture_service import TextureService
from app.ui.views.explorer.equipment_preview import EquipmentPreview
from app.ui.views.explorer.inventory_grid import InventoryGrid


def _identity(name: str) -> str:
    return name


def test_item_components_keep_injected_services() -> None:
    item_service = ItemService()
    texture_service = cast(TextureService, object())

    inventory = InventoryGrid(item_service, texture_service)
    equipment = EquipmentPreview(item_service, texture_service)

    assert inventory._item_service is item_service
    assert inventory._texture_service is texture_service
    assert equipment._item_service is item_service
    assert equipment._texture_service is texture_service


def test_parse_item_legacy_tag() -> None:
    item_data: Dict[str, Any] = {
        "id": "minecraft:diamond_sword",
        "count": 1,
        "slot": 0,
        "tag": {
            "display": {
                "Name": "Excalibur",
                "Lore": ["Sharp", "Shiny"],
            },
            "Damage": 10,
            "Enchantments": [
                {"id": "minecraft:sharpness", "lvl": 5},
            ],
        },
    }
    info = parse_item(item_data, _identity, _identity)
    assert info.custom_name == "Excalibur"
    assert info.display_name == "Excalibur"
    assert info.damage == 10
    assert info.lore == ["Sharp", "Shiny"]
    assert info.enchantments[0]["id"] == "minecraft:sharpness"
    assert info.enchantments[0]["level"] == 5


def test_parse_item_components_shape() -> None:
    item_data: Dict[str, Any] = {
        "id": "minecraft:netherite_pickaxe",
        "count": 1,
        "slot": 1,
        "components": {
            "minecraft:custom_name": "Deep Miner",
            "minecraft:lore": ["1.20.5+"],
            "minecraft:damage": 42,
            "minecraft:enchantments": {
                "levels": {
                    "minecraft:efficiency": 5,
                    "minecraft:unbreaking": 3,
                }
            },
        },
    }
    info = parse_item(item_data, _identity, _identity)
    assert info.custom_name == "Deep Miner"
    assert info.damage == 42
    assert info.lore == ["1.20.5+"]
    levels = {ench["id"]: ench["level"] for ench in info.enchantments}
    assert levels["minecraft:efficiency"] == 5
    assert levels["minecraft:unbreaking"] == 3


def test_parse_item_prefers_components_over_tag() -> None:
    item_data: Dict[str, Any] = {
        "id": "minecraft:stick",
        "count": 1,
        "tag": {
            "display": {"Name": "Legacy"},
            "Damage": 1,
        },
        "components": {
            "minecraft:custom_name": "Modern",
            "minecraft:damage": 7,
        },
    }
    info = parse_item(item_data, _identity, _identity)
    assert info.custom_name == "Modern"
    assert info.damage == 7


def test_parse_item_count_accepts_legacy_Count() -> None:
    info = parse_item(
        {"id": "minecraft:dirt", "Count": 33, "Slot": 4},
        _identity,
        _identity,
    )
    assert info.count == 33
    assert info.slot == 4
