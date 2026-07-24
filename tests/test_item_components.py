"""Item component parsing and inventory UI service injection tests."""
from typing import Any, Callable, Dict, Optional, cast

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


class _DeferredTextureService:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[str, Optional[str]], None]] = []

    def load_textures_async(
        self,
        item_ids: list[str],
        on_loaded: Callable[[str, Optional[str]], None],
    ) -> None:
        del item_ids
        self.callbacks.append(on_loaded)


def test_item_components_drop_texture_callbacks_after_dispose(
    monkeypatch: Any,
) -> None:
    applied = []
    textures = _DeferredTextureService()
    texture_service = cast(TextureService, textures)
    monkeypatch.setattr(
        "app.ui.views.explorer.inventory_grid.run_on_ui",
        lambda page, callback: callback(),
    )
    monkeypatch.setattr(
        "app.ui.views.explorer.equipment_preview.run_on_ui",
        lambda page, callback: callback(),
    )
    monkeypatch.setattr(
        "app.ui.views.explorer.inventory_grid.apply_texture_to_slot",
        lambda slot, uri: applied.append((slot, uri)),
    )
    monkeypatch.setattr(
        "app.ui.views.explorer.equipment_preview.apply_texture_to_slot",
        lambda slot, uri: applied.append((slot, uri)),
    )
    inventory = InventoryGrid(ItemService(), texture_service)
    equipment = EquipmentPreview(ItemService(), texture_service)
    inventory.set_inventory([
        {"id": "minecraft:stone", "count": 1, "slot": 0},
    ])
    equipment.set_equipment([
        {"id": "minecraft:diamond_helmet", "count": 1, "slot": 103},
    ])

    inventory.dispose()
    equipment.dispose()
    inventory_generation = inventory._texture_generation
    equipment_generation = equipment._texture_generation
    inventory.dispose()
    equipment.dispose()
    for callback in textures.callbacks:
        callback("minecraft:stone", "stone.png")
        callback("minecraft:diamond_helmet", "helmet.png")

    assert inventory._texture_generation == inventory_generation
    assert equipment._texture_generation == equipment_generation
    assert applied == []


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
