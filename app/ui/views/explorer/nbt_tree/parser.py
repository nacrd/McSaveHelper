"""NBT value parsing and traversal helpers."""

import json
from typing import Any, List, Union


_TAG_NUMERIC_CONVERTERS = {
    **dict.fromkeys(
        ("Byte", "Short", "Int", "Long", "TAG_Byte", "TAG_Short", "TAG_Int", "TAG_Long"),
        int,
    ),
    **dict.fromkeys(("Float", "Double", "TAG_Float", "TAG_Double"), float),
}
_UNHANDLED = object()


def raw_text(value: Any, type_name: str) -> str:
    try:
        if type_name in ("IntArray", "ByteArray"):
            return json.dumps([int(x) for x in list(value)], ensure_ascii=False)
        if type_name in ("dict", "list", "bool", "NoneType"):
            return json.dumps(value, ensure_ascii=False)
        return str(getattr(value, "value", value))
    except Exception:
        return str(value)


def is_mapping_node(value: Any) -> bool:
    return isinstance(value, dict) or (
        hasattr(value, "keys")
        and hasattr(value, "__getitem__")
        and type(value).__name__ in ("NBTFile", "TAG_Compound")
    )


def mapping_items(value: Any) -> List[tuple]:
    if hasattr(value, "items"):
        return list(value.items())
    return [(key, value[key]) for key in value.keys()]


def is_list_node(value: Any) -> bool:
    return isinstance(value, list) or type(value).__name__ == "TAG_List"


def parse_path(path: str) -> List[Union[str, int]]:
    parts: List[Union[str, int]] = []
    current = ""
    i = 0
    while i < len(path):
        ch = path[i]
        if ch == ".":
            if current:
                parts.append(current)
                current = ""
            i += 1
            continue
        if ch == "[":
            if current:
                parts.append(current)
                current = ""
            end = path.find("]", i)
            if end == -1:
                # 缺少闭合 ]，将剩余部分作为文本处理
                current = path[i:]
                break
            index_str = path[i + 1:end]
            if not index_str.strip():
                raise ValueError(f"NBT 路径索引为空: {path}")
            parts.append(int(index_str))
            i = end + 1
            continue
        current += ch
        i += 1
    if current:
        parts.append(current)
    return parts


def get_type_name(value: Any) -> str:
    return type(value).__name__


def detect_list_subtype(lst: list) -> str:
    if not lst:
        return ""
    return type(lst[0]).__name__


def format_primitive(value: Any, type_name: str) -> str:
    try:
        v = value.value if hasattr(value, "value") else value
        if type_name in ("IntArray", "ByteArray"):
            items = list(value)
            if len(items) <= 8:
                return "[" + ", ".join(str(x) for x in items) + "]"
            return "[" + ", ".join(str(x) for x in items[:8]) + f", …] ({len(items)} 项)"
        if type_name == "String":
            return f'"{v}"'
        return str(v)
    except Exception:
        return str(value)


def coerce_value(raw: str, original: Any, type_name: str) -> Any:
    value_type = type(original)
    converter = _TAG_NUMERIC_CONVERTERS.get(type_name)
    if converter is not None:
        return value_type(converter(raw.strip()))
    if type_name in ("String", "TAG_String"):
        return value_type(raw)
    if type_name == "str":
        return raw
    plain_value = _coerce_plain_value(raw, type_name)
    if plain_value is not _UNHANDLED:
        return plain_value
    if type_name == "NoneType":
        return _coerce_none(raw)
    if type_name in ("IntArray", "ByteArray"):
        return _coerce_array(raw, value_type)
    return _coerce_fallback(raw, value_type)


def _coerce_plain_value(raw: str, type_name: str) -> Any:
    if type_name == "int":
        return int(raw.strip())
    if type_name == "float":
        return float(raw.strip())
    if type_name == "bool":
        return _parse_bool(raw)
    return _UNHANDLED


def _coerce_none(raw: str) -> None:
    if raw.strip().lower() in ("null", "none", ""):
        return None
    raise ValueError("空值必须是 null")


def _coerce_fallback(raw: str, value_type: type) -> Any:
    try:
        return value_type(raw)
    except Exception:
        return raw


def _parse_bool(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in ("true", "1", "yes", "y", "是"):
        return True
    if normalized in ("false", "0", "no", "n", "否"):
        return False
    raise ValueError("布尔值必须是 true/false")


def _coerce_array(raw: str, value_type: type) -> Any:
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("数组值必须是 JSON 数组")
    return value_type([int(item) for item in parsed])


def create_default_value(type_name: str, raw_value: str) -> Any:
    import nbtlib
    factories = {
        "String": lambda: nbtlib.String(raw_value),
        "Compound": lambda: nbtlib.Compound({}),
        "List": lambda: [],
        "Boolean": lambda: nbtlib.Byte(
            1
            if raw_value.strip().lower() in ("true", "1", "yes", "y", "是")
            else 0
        ),
    }
    if type_name in factories:
        return factories[type_name]()
    return _numeric_default(type_name, raw_value, nbtlib)


def _numeric_default(type_name: str, raw_value: str, nbtlib_module: Any) -> Any:
    mapping = {
        "Int": (nbtlib_module.Int, int, 0),
        "Long": (nbtlib_module.Long, int, 0),
        "Byte": (nbtlib_module.Byte, int, 0),
        "Short": (nbtlib_module.Short, int, 0),
        "Float": (nbtlib_module.Float, float, 0.0),
        "Double": (nbtlib_module.Double, float, 0.0),
    }
    if type_name not in mapping:
        return raw_value
    tag_type, converter, default = mapping[type_name]
    try:
        return tag_type(converter(raw_value)) if raw_value else tag_type(default)
    except ValueError:
        return tag_type(default)
