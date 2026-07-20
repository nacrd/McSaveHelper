"""NBT value display and type-preserving coercion helpers (no UI)."""
from __future__ import annotations

from typing import Any

import core.nbt as nbtlib


def tag_display_value(value: Any) -> str:
    """Return a form-friendly string for an NBT tag or plain Python value.

    Args:
        value: NBT tag or scalar.

    Returns:
        str: Unpacked display text.
    """
    if hasattr(value, "unpack"):
        value = value.unpack()
    elif hasattr(value, "value"):
        value = value.value
    return str(value)


def coerce_like_tag(raw: str, original: Any) -> Any:
    """Coerce a form string into the same NBT tag type as ``original``.

    Args:
        raw: User-entered text from a form field.
        original: Existing tag used as the type template.

    Returns:
        Any: New tag instance of the same type as ``original``, or the plain
        string when construction fails.

    Raises:
        ValueError / TypeError: Propagated for numeric parse failures when the
        original tag is a numeric NBT type.
    """
    tag_type = type(original)
    text = raw.strip()
    if "(" in text and text.endswith(")"):
        text = text[text.find("(") + 1:-1]
    if isinstance(original, (nbtlib.Float, nbtlib.Double)):
        return tag_type(float(text))
    if isinstance(
        original,
        (nbtlib.Byte, nbtlib.Short, nbtlib.Int, nbtlib.Long),
    ):
        return tag_type(int(float(text)))
    try:
        return tag_type(text)
    except (TypeError, ValueError):
        return text
