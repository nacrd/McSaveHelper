import pytest

from app.services.item_icons import get_item_emoji


@pytest.mark.parametrize(
    ("item_id", "expected"),
    [
        ("minecraft:diamond_sword", "⚔️"),
        ("minecraft:diamond_pickaxe", "⛏️"),
        ("minecraft:oak_axe", "🪓"),
        ("minecraft:iron_helmet", "🪖"),
        ("minecraft:iron_ore", "⛰️"),
        ("example:cooked_meat", "🍖"),
        ("example:unknown", "📦"),
        ("unknown", "📦"),
    ],
)
def test_item_emoji_fallback_rules(item_id: str, expected: str) -> None:
    assert get_item_emoji(item_id) == expected
