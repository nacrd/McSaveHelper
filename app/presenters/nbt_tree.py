"""框架无关的 NBT 树遍历、显示和叶子值转换。"""
from __future__ import annotations

import json
from typing import Any, Iterable

from app.models.nbt_edit import NbtPath, NbtPathPart


_NUMERIC_CONVERTERS = {
    **dict.fromkeys(("Byte", "Short", "Int", "Long"), int),
    **dict.fromkeys(("Float", "Double"), float),
}


def is_nbt_container(value: Any) -> bool:
    """返回值是否为可展开的映射或列表节点。

    Args:
        value: NBT tag 或 JSON 值。

    Returns:
        值拥有子节点时为 True。
    """
    return isinstance(value, (dict, list))


def iter_nbt_children(value: Any) -> Iterable[tuple[NbtPathPart, Any]]:
    """按确定顺序遍历一个 NBT/JSON 容器的直接子节点。

    Args:
        value: 映射或列表节点。

    Returns:
        键或下标与子值的可迭代对象。
    """
    if isinstance(value, dict):
        return tuple(value.items())
    if isinstance(value, list):
        return tuple(enumerate(value))
    return ()


def nbt_type_name(value: Any) -> str:
    """返回适合界面显示的 NBT/JSON 类型名。

    Args:
        value: NBT tag 或 JSON 值。

    Returns:
        稳定的类型名称。
    """
    name = type(value).__name__
    aliases = {
        "dict": "Object",
        "list": "Array",
        "str": "String",
        "int": "Number",
        "float": "Number",
        "bool": "Boolean",
        "NoneType": "Null",
        "File": "Compound",
    }
    return aliases.get(name, name)


def format_nbt_value(value: Any, limit: int = 120) -> str:
    """把节点值格式化为单行摘要并限制长度。

    Args:
        value: NBT tag 或 JSON 值。
        limit: 输出字符上限。

    Returns:
        单行、可截断的摘要。
    """
    if isinstance(value, dict):
        text = f"{{{len(value)} fields}}"
    elif isinstance(value, list):
        text = f"[{len(value)} items]"
    else:
        raw = getattr(value, "value", value)
        text = json.dumps(raw, ensure_ascii=False) if isinstance(raw, str) else str(raw)
    text = text.replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def raw_nbt_value(value: Any) -> str:
    """返回叶子编辑框使用的未截断文本。

    Args:
        value: NBT tag 或 JSON 叶子值。

    Returns:
        可再次交给 :func:`coerce_nbt_value` 的文本。
    """
    raw = getattr(value, "value", value)
    if isinstance(raw, (bool, type(None))):
        return json.dumps(raw)
    return str(raw)


def coerce_nbt_value(raw: str, original: Any) -> Any:
    """把文本转换为与原叶子值兼容的 Python 或 NBT 类型。

    Args:
        raw: 用户输入文本。
        original: 当前叶子值，用于保留 NBT tag 类型。

    Returns:
        类型化的新值。

    Raises:
        ValueError: 输入无法转换为原类型。
    """
    type_name = type(original).__name__
    value_type = type(original)
    converter = _NUMERIC_CONVERTERS.get(type_name)
    if converter is not None:
        return value_type(converter(raw.strip()))
    if type_name == "String":
        return value_type(raw)
    if isinstance(original, bool):
        return _parse_bool(raw)
    if original is None:
        if raw.strip().lower() in ("", "null", "none"):
            return None
        raise ValueError("空值必须是 null")
    if isinstance(original, int):
        return int(raw.strip())
    if isinstance(original, float):
        return float(raw.strip())
    if isinstance(original, str):
        return raw
    raise ValueError(f"暂不支持编辑 {type_name} 类型")


def format_nbt_path(path: NbtPath) -> str:
    """把键与列表下标格式化为可读路径。

    Args:
        path: 从文档根节点开始的路径。

    Returns:
        例如 ``Data.Player.Pos[0]`` 的路径。
    """
    parts: list[str] = []
    for component in path:
        if isinstance(component, int):
            parts.append(f"[{component}]")
        elif parts:
            parts.append(f".{component}")
        else:
            parts.append(component)
    return "".join(parts) or "<root>"


def latest_staged_value(
    path: NbtPath,
    changes: Iterable[tuple[NbtPath, Any]],
    fallback: Any,
) -> Any:
    """返回指定路径最后一个暂存值，不存在时使用磁盘值。

    Args:
        path: 要查询的节点路径。
        changes: 按提交顺序排列的 ``(路径, 新值)``。
        fallback: 未命中时返回的原值。

    Returns:
        最后一个匹配暂存值或 ``fallback``。
    """
    result = fallback
    for staged_path, new_value in changes:
        if staged_path == path:
            result = new_value
    return result


def _parse_bool(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in ("true", "1", "yes", "y", "是"):
        return True
    if normalized in ("false", "0", "no", "n", "否"):
        return False
    raise ValueError("布尔值必须是 true 或 false")


__all__ = [
    "coerce_nbt_value",
    "format_nbt_path",
    "format_nbt_value",
    "is_nbt_container",
    "iter_nbt_children",
    "latest_staged_value",
    "nbt_type_name",
    "raw_nbt_value",
]
