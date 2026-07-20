"""Item parsing and formatting logic."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional

from .constants import _MAX_DURABILITY, _roman_numeral
from .models import ItemInfo


def parse_item(
    item_data: Dict[str, Any],
    get_item_name: Callable[[str], str],
    get_enchantment_name: Callable[[str], str],
) -> ItemInfo:
    """解析物品数据并提取完整信息。

    同时支持旧版 ``tag`` 复合标签与 1.20.5+ ``components`` 映射；
    二者并存时优先 components，再用 legacy 补齐缺失字段。

    Args:
        item_data: 原始物品字典。
        get_item_name: 物品 ID → 显示名。
        get_enchantment_name: 附魔 ID → 显示名。

    Returns:
        ItemInfo: 结构化物品信息。
    """
    item_id = str(item_data.get("id", "") or "")
    count = _as_int(item_data.get("count", item_data.get("Count", 1))) or 1
    slot = _as_int(item_data.get("slot", item_data.get("Slot", -1)))
    if slot is None:
        slot = -1
    tag = item_data.get("tag")
    components = item_data.get("components")

    display_name = get_item_name(item_id)
    max_dur = _MAX_DURABILITY.get(item_id)
    damage: Optional[int] = None
    durability_percent: Optional[float] = None
    enchantments: List[Dict[str, Any]] = []
    custom_name: Optional[str] = None
    lore: List[str] = []

    if components is not None:
        custom_name, lore, damage, enchantments = _safe_parse_components(
            components,
            get_enchantment_name,
        )
        if custom_name:
            display_name = custom_name

    needs_legacy = (
        tag is not None
        and (custom_name is None or not enchantments or damage is None)
    )
    if needs_legacy:
        legacy = _safe_parse_legacy_tag(tag, get_enchantment_name)
        if custom_name is None and legacy["custom_name"]:
            custom_name = legacy["custom_name"]
            display_name = custom_name
        if not lore and legacy["lore"]:
            lore = legacy["lore"]
        if damage is None and legacy["damage"] is not None:
            damage = legacy["damage"]
        if not enchantments and legacy["enchantments"]:
            enchantments = legacy["enchantments"]

    if damage is not None and max_dur is not None and max_dur > 0:
        remaining = max_dur - damage
        durability_percent = max(
            0.0,
            min(100.0, (remaining / max_dur) * 100.0),
        )

    return ItemInfo(
        id=item_id,
        display_name=display_name,
        count=count,
        damage=damage,
        max_damage=max_dur,
        durability_percent=durability_percent,
        enchantments=enchantments,
        custom_name=custom_name,
        lore=lore,
        slot=slot,
    )


def _safe_parse_components(
    components: Any,
    get_enchantment_name: Callable[[str], str],
) -> tuple[Optional[str], List[str], Optional[int], List[Dict[str, Any]]]:
    """Parse modern components; return empty defaults on structural errors."""
    try:
        return _parse_components(components, get_enchantment_name)
    except (TypeError, ValueError, AttributeError, KeyError):
        return None, [], None, []


def _safe_parse_legacy_tag(
    tag: Any,
    get_enchantment_name: Callable[[str], str],
) -> Dict[str, Any]:
    """Parse legacy tag; return empty defaults on structural errors."""
    empty = {
        "custom_name": None,
        "lore": [],
        "damage": None,
        "enchantments": [],
    }
    try:
        return _parse_legacy_tag(tag, get_enchantment_name)
    except (TypeError, ValueError, AttributeError, KeyError):
        return empty


def _parse_legacy_tag(
    tag: Any,
    get_enchantment_name: Callable[[str], str],
) -> Dict[str, Any]:
    """Parse pre-1.20.5 item ``tag`` compound."""
    custom_name: Optional[str] = None
    lore: List[str] = []
    damage: Optional[int] = None
    enchantments: List[Dict[str, Any]] = []

    if not hasattr(tag, "get"):
        return {
            "custom_name": custom_name,
            "lore": lore,
            "damage": damage,
            "enchantments": enchantments,
        }

    display_tag = tag.get("display")
    if display_tag is not None and hasattr(display_tag, "get"):
        name_tag = display_tag.get("Name")
        if name_tag is not None:
            custom_name = _clean_text(name_tag)
        lore_tag = display_tag.get("Lore")
        if lore_tag is not None and hasattr(lore_tag, "__iter__"):
            lore = [
                _clean_text(line) for line in lore_tag if line is not None
            ]

    damage_tag = tag.get("Damage")
    if damage_tag is not None:
        damage = _as_int(damage_tag)

    enchantments = _parse_enchantment_list(tag, get_enchantment_name)
    return {
        "custom_name": custom_name,
        "lore": lore,
        "damage": damage,
        "enchantments": enchantments,
    }


def _parse_components(
    components: Any,
    get_enchantment_name: Callable[[str], str],
) -> tuple[Optional[str], List[str], Optional[int], List[Dict[str, Any]]]:
    custom_name: Optional[str] = None
    lore: List[str] = []
    damage: Optional[int] = None
    enchantments: List[Dict[str, Any]] = []

    if not hasattr(components, "get") and not isinstance(components, Mapping):
        return custom_name, lore, damage, enchantments

    def _get(key: str) -> Any:
        try:
            if hasattr(components, "get"):
                return components.get(key)
            return components[key]  # type: ignore[index]
        except (KeyError, TypeError):
            return None

    # Keys may be stored with or without the minecraft: namespace.
    name_value = _get("minecraft:custom_name")
    if name_value is None:
        name_value = _get("custom_name")
    if name_value is not None:
        custom_name = _clean_text(name_value)

    lore_value = _get("minecraft:lore")
    if lore_value is None:
        lore_value = _get("lore")
    if (
        lore_value is not None
        and hasattr(lore_value, "__iter__")
        and not isinstance(lore_value, (str, bytes))
    ):
        lore = [_clean_text(line) for line in lore_value if line is not None]

    damage_value = _get("minecraft:damage")
    if damage_value is None:
        damage_value = _get("damage")
    if damage_value is not None:
        damage = _as_int(damage_value)

    for key in (
        "minecraft:enchantments",
        "enchantments",
        "minecraft:stored_enchantments",
        "stored_enchantments",
    ):
        ench_value = _get(key)
        if ench_value is None:
            continue
        enchantments.extend(
            _parse_component_enchantments(ench_value, get_enchantment_name)
        )

    return custom_name, lore, damage, enchantments


def _parse_enchantment_list(
    tag: Any,
    get_enchantment_name: Callable[[str], str],
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    if not hasattr(tag, "get"):
        return result
    for key in ("Enchantments", "StoredEnchantments"):
        ench_tag = tag.get(key)
        if ench_tag is None or not hasattr(ench_tag, "__iter__"):
            continue
        for ench in ench_tag:
            if not hasattr(ench, "get"):
                continue
            ench_id = str(ench.get("id", "") or "")
            ench_level = _as_int_required(ench.get("lvl", 1), 1)
            if not ench_id:
                continue
            result.append({
                "id": ench_id,
                "name": get_enchantment_name(ench_id),
                "level": ench_level,
            })
    return result


def _parse_component_enchantments(
    value: Any,
    get_enchantment_name: Callable[[str], str],
) -> List[Dict[str, Any]]:
    """Parse 1.20.5+ enchantment component shapes.

    Common shapes:
    - ``{"levels": {"minecraft:sharpness": 5}}``
    - ``{"minecraft:sharpness": 5}``
    - list of ``{id, lvl}`` (rare / transitional)
    """
    result: List[Dict[str, Any]] = []
    if value is None:
        return result

    # List form
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, Mapping)):
        if not hasattr(value, "get"):
            for ench in value:
                if hasattr(ench, "get"):
                    ench_id = str(ench.get("id", "") or "")
                    level = _as_int_required(ench.get("lvl", ench.get("level", 1)), 1)
                    if ench_id:
                        result.append({
                            "id": ench_id,
                            "name": get_enchantment_name(ench_id),
                            "level": level,
                        })
            if result:
                return result

    levels: Any = value
    if hasattr(value, "get"):
        nested = value.get("levels")
        if nested is not None:
            levels = nested

    if isinstance(levels, Mapping) or hasattr(levels, "items"):
        try:
            items = levels.items()
        except (TypeError, AttributeError):
            return result
        for ench_id, level in items:
            ench_id_str = str(ench_id)
            level_int = _as_int_required(level, 1)
            result.append({
                "id": ench_id_str,
                "name": get_enchantment_name(ench_id_str),
                "level": level_int,
            })
    return result


def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """Best-effort integer coercion for NBT/JSON scalar tags."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_int_required(value: Any, default: int = 0) -> int:
    """Integer coercion that always returns an int."""
    parsed = _as_int(value, default=default)
    return default if parsed is None else parsed


def _clean_text(value: Any) -> str:
    """Normalize display text by stripping quotes/whitespace."""
    text = str(value)
    return text.strip().strip("'\"")


def format_item_tooltip(item_info: ItemInfo) -> str:
    """格式化物品悬停提示文本。

    Args:
        item_info: 已解析的物品信息。

    Returns:
        str: 多行提示字符串。
    """
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
            lines.append(
                f"  ({item_info.max_damage - item_info.damage}/{item_info.max_damage})"
            )
    if item_info.enchantments:
        lines.append("附魔:")
        for ench in item_info.enchantments:
            lines.append(f"  {ench['name']} {_roman_numeral(ench['level'])}")
    if item_info.lore:
        for lore_line in item_info.lore:
            lines.append(f"§o{lore_line}§r")
    return "\n".join(lines)
