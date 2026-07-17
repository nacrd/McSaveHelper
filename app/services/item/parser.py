"""Item parsing and formatting logic."""
from typing import Any, Callable, Dict, List

from .constants import _MAX_DURABILITY, _roman_numeral
from .models import ItemInfo


def parse_item(
    item_data: Dict[str, Any],
    get_item_name: Callable[[str], str],
    get_enchantment_name: Callable[[str], str],
) -> ItemInfo:
    """Parse item data and extract full info."""
    item_id = item_data.get("id", "")
    count = item_data.get("count", 1)
    slot = item_data.get("slot", -1)
    tag = item_data.get("tag")

    display_name = get_item_name(item_id)
    max_dur = _MAX_DURABILITY.get(item_id)
    damage = None
    durability_percent = None
    enchantments: List[Dict[str, Any]] = []
    custom_name = None
    lore: List[str] = []

    if tag is not None:
        try:
            display_tag = tag.get("display")
            if display_tag and hasattr(display_tag, "get"):
                name_tag = display_tag.get("Name")
                if name_tag:
                    custom_name = str(name_tag)
                    display_name = custom_name
                lore_tag = display_tag.get("Lore")
                if lore_tag and hasattr(lore_tag, "__iter__"):
                    lore = [str(line) for line in lore_tag]

            damage_tag = tag.get("Damage")
            if damage_tag is not None:
                damage = int(damage_tag)
                if max_dur is not None and max_dur > 0:
                    remaining = max_dur - damage
                    durability_percent = max(0, min(100, (remaining / max_dur) * 100))

            enchantments = _parse_enchantments(tag, get_enchantment_name)
        except Exception:
            pass

    return ItemInfo(
        id=item_id, display_name=display_name, count=count,
        damage=damage, max_damage=max_dur, durability_percent=durability_percent,
        enchantments=enchantments, custom_name=custom_name, lore=lore, slot=slot,
    )


def _parse_enchantments(
    tag: Any,
    get_enchantment_name: Callable[[str], str],
) -> List[Dict[str, Any]]:
    result = []
    for key in ("Enchantments", "StoredEnchantments"):
        ench_tag = tag.get(key)
        if ench_tag and hasattr(ench_tag, "__iter__"):
            for ench in ench_tag:
                if hasattr(ench, "get"):
                    ench_id = str(ench.get("id", ""))
                    ench_level = int(ench.get("lvl", 1))
                    result.append({
                        "id": ench_id,
                        "name": get_enchantment_name(ench_id),
                        "level": ench_level,
                    })
    return result


def format_item_tooltip(item_info: ItemInfo) -> str:
    """Format item tooltip text."""
    lines = [item_info.display_name]
    if item_info.custom_name:
        lines.append(f"ID: {item_info.id}")
    if item_info.count > 1:
        lines.append(f"数量: {item_info.count}")
    if item_info.durability_percent is not None:
        bar_len = 10
        filled = int(item_info.durability_percent / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        lines.append(f"耐久: {bar} {item_info.durability_percent:.0f}%")
        if item_info.damage is not None and item_info.max_damage is not None:
            lines.append(f"  ({item_info.max_damage - item_info.damage}/{item_info.max_damage})")
    if item_info.enchantments:
        lines.append("附魔:")
        for ench in item_info.enchantments:
            lines.append(f"  {ench['name']} {_roman_numeral(ench['level'])}")
    if item_info.lore:
        for lore_line in item_info.lore:
            lines.append(f"§o{lore_line}§r")
    return "\n".join(lines)
