"""JSON export helpers for NBT data."""

import json
from pathlib import Path
from typing import Any

from core.io_atomic import atomic_write_text


def to_serializable(obj: Any) -> Any:
    """将 NBT 值转为可 JSON 序列化结构。"""
    if hasattr(obj, "value"):
        return to_serializable(obj.value)
    if isinstance(obj, dict):
        return {k: to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_serializable(item) for item in obj]
    if isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    return str(obj)


def export_json(data: Any, path: str) -> bool:
    """Export NBT-like data to a JSON file."""
    try:
        if data is None:
            return False
        content = json.dumps(
            to_serializable(data),
            ensure_ascii=False,
            indent=2,
        )
        atomic_write_text(Path(path), content)
        return True
    except (OSError, TypeError, ValueError, RecursionError):
        return False
