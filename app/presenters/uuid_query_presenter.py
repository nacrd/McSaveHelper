"""UUID → 玩家名查询结果的纯校验与格式化。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.uuid_utils import (
    NameHistoryEntry,
    format_uuid_with_hyphens,
    normalize_uuid,
)


_HEX_DIGITS = frozenset("0123456789abcdef")


def normalize_query_uuid(raw: str) -> Optional[str]:
    """规范化用户输入的 UUID；无效输入返回 None。

    Args:
        raw: 用户输入的 UUID（可带连字符、大小写混合）。

    Returns:
        32 位小写十六进制 UUID；不是 32 位十六进制时返回 None。
    """
    cleaned = normalize_uuid(raw)
    if len(cleaned) != 32 or any(c not in _HEX_DIGITS for c in cleaned):
        return None
    return cleaned


def format_name_history_query(
    raw_uuid: str,
    history: Optional[list[NameHistoryEntry]],
) -> str:
    """把姓名历史查询结果格式化为结果面板文本。

    Args:
        raw_uuid: 用户输入的原始 UUID。
        history: Mojang names API 返回的姓名历史；None 表示查询失败。

    Returns:
        多行展示文本：UUID、当前名与曾用名列表。
    """
    uuid_text = format_uuid_with_hyphens(raw_uuid) or raw_uuid
    if not history:
        return (
            f"UUID: {uuid_text}\n"
            "未找到对应的正版玩家（可能为离线模式生成的 UUID）"
        )
    lines = [f"UUID: {uuid_text}", f"当前名称: {history[-1].name}"]
    if len(history) > 1:
        lines.append("曾用名（从旧到新）:")
        for entry in history[:-1]:
            lines.append(f"  - {entry.name}{_format_changed_at(entry)}")
    return chr(10).join(lines)


def _format_changed_at(entry: NameHistoryEntry) -> str:
    """把改名时间戳（毫秒）格式化为 ``（YYYY-MM-DD 起）`` 后缀。"""
    if entry.changed_to_at is None:
        return ""
    try:
        date = datetime.fromtimestamp(
            entry.changed_to_at / 1000
        ).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        # 超出平台时间范围的时间戳只显示名字，不阻塞查询结果。
        return ""
    return f"（{date} 起）"


__all__ = [
    "format_name_history_query",
    "normalize_query_uuid",
]
