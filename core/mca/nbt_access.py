"""Small nbtlib tree helpers shared by heightmaps / block palette."""
from __future__ import annotations

from typing import Any, List, Optional, Tuple


def tag_value(node: Any) -> Any:
    """Unwrap nbtlib tags to plain Python values when possible.

    Args:
        node: An nbtlib tag or already-plain Python value.

    Returns:
        Any: Unpacked value when available, otherwise ``node`` itself.
    """
    if node is None:
        return None
    # nbtlib numeric/string tags expose .unpack() or behave like their type
    unpack = getattr(node, "unpack", None)
    if callable(unpack):
        try:
            return unpack()
        except (TypeError, ValueError, AttributeError):
            pass
    if hasattr(node, "value") and not isinstance(node, (dict, list)):
        try:
            return node.value
        except (AttributeError, TypeError, ValueError):
            pass
    return node


def as_int(node: Any) -> Optional[int]:
    """Best-effort integer conversion of an NBT node."""
    try:
        return int(tag_value(node))
    except (TypeError, ValueError):
        return None


def as_str(node: Any) -> str:
    """Best-effort string conversion of an NBT node."""
    value = tag_value(node)
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def mapping_get(node: Any, key: str) -> Any:
    """Read ``key`` from a mapping-like NBT node without raising."""
    if node is None:
        return None
    try:
        if hasattr(node, "get"):
            return node.get(key)
        return node[key]
    except (TypeError, KeyError, AttributeError, IndexError):
        return None


def first_key(node: Any, *keys: str) -> Any:
    """Return the first present key among ``keys``."""
    for key in keys:
        value = mapping_get(node, key)
        if value is not None:
            return value
    return None


def section_y(section: Any) -> Optional[int]:
    """Decode a section Y as a signed world section index.

    NBT Byte tags are normally already signed, but plain JSON-like test trees
    may carry the equivalent unsigned byte (``128..255``).
    """
    value = as_int(first_key(section, "Y", "y"))
    if value is None:
        return None
    return value - 256 if value > 127 else value


def is_mapping(node: Any) -> bool:
    """Whether *node* behaves like a key/value mapping."""
    raw = tag_value(node)
    return isinstance(raw, dict) or (
        hasattr(node, "get") and hasattr(node, "keys")
    )


def is_sequence(node: Any) -> bool:
    """Whether *node* behaves like a non-string sequence."""
    raw = tag_value(node)
    if isinstance(raw, (str, bytes, dict)):
        return False
    return isinstance(raw, (list, tuple)) or (
        hasattr(raw, "__iter__") and not is_mapping(node)
    )


def iter_sequence(node: Any) -> List[Any]:
    """Materialize a sequence-like NBT node into a list."""
    if node is None:
        return []
    raw = tag_value(node)
    try:
        return list(raw)
    except (TypeError, ValueError):
        try:
            return list(node)
        except (TypeError, ValueError):
            return []


def long_array_values(node: Any) -> List[int]:
    """Return unsigned 64-bit values from a LongArray / list of longs."""
    items = iter_sequence(node)
    out: List[int] = []
    for item in items:
        try:
            value = int(tag_value(item))
        except (TypeError, ValueError):
            continue
        if value < 0:
            value &= (1 << 64) - 1
        out.append(value)
    return out


def chunk_root_and_version(chunk_nbt: Any) -> Tuple[Any, Optional[int]]:
    """Return ``(payload_root, data_version)``.

    Modern chunks store fields at root; older ones nest under ``Level``.
    """
    if chunk_nbt is None:
        return None, None
    version = as_int(first_key(chunk_nbt, "DataVersion", "dataVersion"))
    level = first_key(chunk_nbt, "Level")
    if is_mapping(level):
        if version is None:
            version = as_int(first_key(level, "DataVersion", "dataVersion"))
        # Prefer Level when present for pre-1.18 style, but modern 1.18+
        # often has both; if sections live on root, use root.
        if first_key(chunk_nbt, "sections", "Sections") is not None:
            return chunk_nbt, version
        return level, version
    return chunk_nbt, version
