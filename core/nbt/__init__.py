"""自研 NBT 读写库（取代 nbtlib）。

公共 API 与项目原先使用的 ``nbtlib`` 子集对齐，便于现有调用点平滑迁移::

    from core.nbt import File, Compound, Int, String, List, load, save

模块结构：

- :mod:`core.nbt.tag` — 标签类型与 payload 编解码
- :mod:`core.nbt.file` — 根 ``File``、磁盘 ``load`` / ``save``
"""
from __future__ import annotations

from core.nbt.file import File, load, save
from core.nbt.tag import (
    BYTE,
    DOUBLE,
    FLOAT,
    INT,
    LONG,
    SHORT,
    USHORT,
    Array,
    Base,
    Byte,
    ByteArray,
    CastError,
    Compound,
    Double,
    End,
    EndInstantiation,
    Float,
    IncompatibleItemType,
    Int,
    IntArray,
    List,
    Long,
    LongArray,
    Numeric,
    NumericInteger,
    OutOfRange,
    Short,
    String,
    get_format,
    read_numeric,
    read_string,
    write_numeric,
    write_string,
)

# 兼容 ``import core.nbt as nbt; nbt.tag.Compound`` 风格
from . import tag as tag  # noqa: F401

__all__ = [
    "load",
    "save",
    "File",
    "Base",
    "Numeric",
    "NumericInteger",
    "Byte",
    "Short",
    "Int",
    "Long",
    "Float",
    "Double",
    "String",
    "List",
    "Compound",
    "End",
    "Array",
    "ByteArray",
    "IntArray",
    "LongArray",
    "EndInstantiation",
    "OutOfRange",
    "IncompatibleItemType",
    "CastError",
    "get_format",
    "read_numeric",
    "write_numeric",
    "read_string",
    "write_string",
    "BYTE",
    "SHORT",
    "USHORT",
    "INT",
    "LONG",
    "FLOAT",
    "DOUBLE",
    "tag",
]

__version__ = "1.0.0"
