"""Search helpers for NBT trees."""

from typing import Any, Set

from .parser import is_list_node, is_mapping_node, mapping_items


def collect_matches(data: Any, query: str) -> Set[str]:
    """Return lower-cased tree paths whose key or primitive value matches query."""
    matches: Set[str] = set()
    q = query.strip().lower()
    if not q:
        return matches
    _collect(data, "", q, matches)
    return matches


def _collect(data: Any, path_prefix: str, query: str, matches: Set[str]) -> None:
    try:
        if is_mapping_node(data):
            _collect_mapping(data, path_prefix, query, matches)
        elif is_list_node(data):
            _collect_list(data, path_prefix, query, matches)
    except Exception:
        pass


def _collect_mapping(data: Any, path_prefix: str, query: str, matches: Set[str]) -> None:
    for key, value in mapping_items(data):
        child_path = f"{path_prefix}.{key}" if path_prefix else str(key)
        if query in str(key).lower():
            matches.add(child_path.lower())
        if is_mapping_node(value) or is_list_node(value):
            _collect(value, child_path, query, matches)
        elif query in str(getattr(value, "value", value)).lower():
            matches.add(child_path.lower())


def _collect_list(data: Any, path_prefix: str, query: str, matches: Set[str]) -> None:
    for i, item in enumerate(data):
        child_path = f"{path_prefix}[{i}]"
        if is_mapping_node(item) or is_list_node(item):
            _collect(item, child_path, query, matches)
        elif query in str(getattr(item, "value", item)).lower():
            matches.add(child_path.lower())
