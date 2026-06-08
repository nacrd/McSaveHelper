from app.services.item_service import ItemInfo
from app.ui.views.explorer.item_slot import (
    SLOT_BG_EMPTY,
    SLOT_BG_FILLED,
    apply_item_to_slot,
    create_item_slot,
    reset_item_slot,
)


def test_item_slot_applies_and_resets_item_state():
    slot = create_item_slot(48)
    item = ItemInfo(
        id="minecraft:diamond_sword",
        display_name="Diamond Sword",
        count=2,
        slot=0,
        durability_percent=50,
        enchantments=["minecraft:sharpness"],
    )

    apply_item_to_slot(slot, item, "tooltip")

    assert slot.container.bgcolor == SLOT_BG_FILLED
    assert slot.container.tooltip == "tooltip"
    assert slot.count_text.value == "×2"
    assert slot.durability_text.value
    assert slot.enchantment_text.value == "✦"

    reset_item_slot(slot)

    assert slot.container.bgcolor == SLOT_BG_EMPTY
    assert slot.container.tooltip is None
    assert slot.count_text.value == ""
    assert slot.durability_text.value == ""
    assert slot.enchantment_text.value == ""
