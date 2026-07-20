"""NBT value display and type-preserving coercion helpers (no UI)."""
from __future__ import annotations

from typing import Any

import nbtlib


def tag_display_value(value: Any) -> str:
    if hasattr(value, "unpack"):
        value = value.unpack()
    elif hasattr(value, "value"):
        value = value.value
    return str(value)


def coerce_like_tag(raw: str, original: Any) -> Any:
    """Coerce a form string into the same nbtlib tag type as ``original``."""
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
    except Exception:
        return text
