"""Qt 物品格子与背包网格投影测试。"""
from __future__ import annotations

from typing import Any

import pytest

from app.qtui.views.equipment_preview import QtEquipmentPreview
from app.qtui.views.inventory_grid import QtInventoryGrid
from app.qtui.views.item_slot import (
    SLOT_BG_EMPTY,
    SLOT_BG_FILLED,
    QtItemSlot,
)
from app.services.item.models import ItemInfo
from app.services.item_service import ItemService
from app.services.player_service import PlayerService
from app.qtui.views.player_editor import QtPlayerEditor
from app.qtui.views.player_tasks import PlayerDetailResult
from app.services.player.models import (
    PlayerContainersView,
    PlayerRef,
    PlayerSummary,
)
from core.nbt import Compound
from core.omni.player_manager import (
    PlayerAbilities,
    PlayerPose,
    PlayerSpawn,
    PlayerState,
)


@pytest.fixture
def qt_app_local(qt_app: object) -> object:
    return qt_app


def test_item_slot_applies_and_resets(qt_app_local: object) -> None:
    del qt_app_local
    slot = QtItemSlot(48)
    item = ItemInfo(
        id="minecraft:diamond_sword",
        display_name="Diamond Sword",
        count=2,
        slot=0,
        durability_percent=50,
        enchantments=[{"id": "minecraft:sharpness", "level": 1}],
    )
    slot.apply_item(item, "tooltip")
    assert SLOT_BG_FILLED in slot.styleSheet()
    assert slot.toolTip() == "tooltip"
    assert slot._count.text() == "×2"
    assert slot._durability.text()
    assert slot._enchant.text() == "✦"
    slot.reset()
    assert SLOT_BG_EMPTY in slot.styleSheet()
    assert slot.toolTip() == ""
    assert slot._count.text() == ""


def test_inventory_grid_fills_main_and_hotbar_highlight(
    qt_app_local: object,
) -> None:
    del qt_app_local
    grid = QtInventoryGrid(ItemService(), layout="main", slot_size=36)
    grid.set_inventory(
        [
            {"slot": 0, "id": "minecraft:dirt", "count": 64},
            {"slot": 10, "id": "minecraft:stone", "count": 1},
            {"slot": 99, "id": "minecraft:ignored", "count": 1},
        ],
        selected_slot=0,
    )
    assert grid.slot_item(0) is not None
    assert grid.slot_item(10) is not None
    assert grid.slot_item(99) is None
    assert grid._slots[0]._icon.text()
    assert SELECTED_BORDER_IN_STYLE(grid._slots[0])
    grid.set_selected_slot(None)
    assert not SELECTED_BORDER_IN_STYLE(grid._slots[0])
    grid.dispose()


def SELECTED_BORDER_IN_STYLE(slot: QtItemSlot) -> bool:
    return "#42A5F5" in slot.styleSheet()


def test_inventory_grid_click_callback(qt_app_local: object) -> None:
    del qt_app_local
    clicked: list[tuple[int, Any]] = []
    grid = QtInventoryGrid(
        ItemService(),
        layout="main",
        on_slot_click=lambda slot, item: clicked.append((slot, item)),
    )
    grid.set_inventory([{"slot": 3, "id": "minecraft:apple", "count": 2}])
    grid._handle_slot_click(3)
    assert clicked and clicked[0][0] == 3
    assert clicked[0][1] is not None
    assert clicked[0][1]["id"] == "minecraft:apple"
    grid.dispose()


def test_equipment_preview_fills_known_slots(qt_app_local: object) -> None:
    del qt_app_local
    preview = QtEquipmentPreview(ItemService(), slot_size=36)
    preview.set_equipment([
        {"slot": 103, "id": "minecraft:diamond_helmet", "count": 1},
        {"slot": -106, "id": "minecraft:shield", "count": 1},
        {"slot": 5, "id": "minecraft:dirt", "count": 1},
    ])
    assert preview._slot_controls[103]._icon.text()
    assert preview._slot_controls[-106]._icon.text()
    assert preview._slot_controls[100]._icon.text() == ""
    preview.dispose()


def test_player_editor_opens_nested_container_preview(
    qt_app_local: object,
) -> None:
    del qt_app_local

    class _NestedPlayerService(PlayerService):
        def open_nested_container(self, item: dict[str, Any]):
            if "shulker" in str(item.get("id", "")):
                return [
                    {"slot": 0, "id": "minecraft:diamond", "count": 3},
                    {"slot": 1, "id": "minecraft:emerald", "count": 1},
                ]
            return None

    editor = QtPlayerEditor(
        lambda key, default="", **kw: default.format(**kw),
        lambda: None,
        lambda: None,
        lambda: None,
        lambda: None,
        item_service=ItemService(),
        player_service=_NestedPlayerService(),
    )
    summary = PlayerSummary(
        ref=PlayerRef(
            uuid_norm="a" * 32,
            uuid_hyphen="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            name="Alex",
        ),
        state=PlayerState(
            health=20.0,
            food_level=20,
            food_saturation=5.0,
            xp_level=0,
            xp_total=0,
            xp_p=0.0,
            air=300,
            dimension="minecraft:overworld",
            game_type=0,
            selected_slot=0,
            score=None,
        ),
        pose=PlayerPose(x=0.0, y=64.0, z=0.0, yaw=0.0, pitch=0.0),
        spawn=PlayerSpawn(
            x=None, y=None, z=None, dimension=None, forced=None
        ),
        death=None,
        abilities=PlayerAbilities(
            flying=False,
            may_fly=False,
            instabuild=False,
            invulnerable=False,
            may_build=True,
            walk_speed=0.1,
            fly_speed=0.05,
        ),
        inventory_count=1,
        ender_count=0,
        equipment_count=0,
        issues=(),
    )
    containers = PlayerContainersView(
        inventory=(
            {
                "slot": 0,
                "id": "minecraft:shulker_box",
                "count": 1,
            },
        ),
        equipment=(),
        ender_items=(),
        selected_slot=0,
    )
    editor.show_detail(PlayerDetailResult(
        player_data=Compound({}),
        summary=summary,
        containers=containers,
        attributes=(),
        effects=(),
    ))
    assert editor._inventory.slot_item(0) is not None
    editor._on_inventory_slot_click(
        0,
        {"slot": 0, "id": "minecraft:shulker_box", "count": 1},
    )
    assert editor._container_preview.isHidden() is False
    assert editor._container_preview.slot_item(0) is not None
    assert editor._container_preview.slot_item(0)["id"] == "minecraft:diamond"
    editor.dispose()
