"""Named Binary Tag 标签类型与二进制编解码。

实现 Java 版 NBT 标签树（TAG_End … TAG_Long_Array），行为对齐项目原先使用的
``nbtlib`` API 子集：数值/字符串标签继承对应内置类型，``Compound`` 继承 ``dict``，
``List`` 继承 ``list`` 且支持 ``List[Tag]`` 子类型，数组标签为可变序列（无 numpy）。
"""
from __future__ import annotations

from struct import Struct
from struct import error as StructError
from typing import (
    Any,
    BinaryIO,
    Callable,
    ClassVar,
    Dict,
    Iterable,
    Iterator,
    List as TypingList,
    MutableSequence,
    Optional,
    Sequence,
    SupportsIndex,
    Type,
    TypeVar,
    Union,
    cast,
    overload,
)

__all__ = [
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
]


ByteOrder = str
T = TypeVar("T", bound="Base")


def get_format(fmt: Callable[[str], Struct], string: str) -> Dict[str, Struct]:
    """Return big/little Struct formats for *string*."""
    return {"big": fmt(">" + string), "little": fmt("<" + string)}


BYTE = get_format(Struct, "b")
SHORT = get_format(Struct, "h")
USHORT = get_format(Struct, "H")
INT = get_format(Struct, "i")
LONG = get_format(Struct, "q")
FLOAT = get_format(Struct, "f")
DOUBLE = get_format(Struct, "d")


class EndInstantiation(TypeError):
    """Raised when trying to instantiate an :class:`End` tag."""

    def __init__(self) -> None:
        super().__init__("End tags can't be instantiated")


class OutOfRange(ValueError):
    """Raised when a numeric value is out of range for its tag type."""

    def __init__(self, value: Any) -> None:
        super().__init__(f"{value!r} is out of range")


class IncompatibleItemType(TypeError):
    """Raised when a list item is incompatible with the list subtype."""

    def __init__(self, item: Any, subtype: type) -> None:
        super().__init__(f"{item!r} should be a {subtype.__name__} tag")
        self.item = item
        self.subtype = subtype


class CastError(ValueError):
    """Raised when an object couldn't be converted to the required tag type."""

    def __init__(self, obj: Any, tag_type: type) -> None:
        super().__init__(f"Couldn't cast {obj!r} to {tag_type.__name__}")
        self.obj = obj
        self.tag_type = tag_type


def read_numeric(
    fmt: Dict[str, Struct],
    fileobj: BinaryIO,
    byteorder: ByteOrder = "big",
) -> Union[int, float]:
    """Read a numeric value from a file-like object."""
    try:
        struct = fmt[byteorder]
        data = fileobj.read(struct.size)
        if len(data) < struct.size:
            return 0
        value = struct.unpack(data)[0]
        return cast(Union[int, float], value)
    except StructError:
        return 0
    except KeyError as exc:
        raise ValueError("Invalid byte order") from exc


def write_numeric(
    fmt: Dict[str, Struct],
    value: Union[int, float],
    fileobj: BinaryIO,
    byteorder: ByteOrder = "big",
) -> None:
    """Write a numeric value to a file-like object."""
    try:
        fileobj.write(fmt[byteorder].pack(value))
    except KeyError as exc:
        raise ValueError("Invalid byte order") from exc


def read_string(fileobj: BinaryIO, byteorder: ByteOrder = "big") -> str:
    """Read a modified-UTF-8 length-prefixed string."""
    length = int(read_numeric(USHORT, fileobj, byteorder))
    return fileobj.read(length).decode("utf-8", "replace")


def write_string(
    value: str,
    fileobj: BinaryIO,
    byteorder: ByteOrder = "big",
) -> None:
    """Write a length-prefixed UTF-8 string."""
    data = value.encode("utf-8")
    write_numeric(USHORT, len(data), fileobj, byteorder)
    fileobj.write(data)


class Base:
    """Base class shared by all NBT tags."""

    __slots__ = ()
    all_tags: ClassVar[Dict[int, Type["Base"]]] = {}
    tag_id: ClassVar[Optional[int]] = None
    serializer: ClassVar[Optional[str]] = None

    def __init_subclass__(cls) -> None:
        if cls.tag_id is not None and cls.tag_id not in Base.all_tags:
            Base.all_tags[cls.tag_id] = cls

    @classmethod
    def get_tag(cls, tag_id: int) -> Type["Base"]:
        """Return the concrete tag class for *tag_id*."""
        return Base.all_tags[tag_id]

    @classmethod
    def parse(cls: Type[T], fileobj: BinaryIO, byteorder: ByteOrder = "big") -> T:
        """Parse payload bytes into a tag instance (overridden by tags)."""
        raise NotImplementedError

    def write(self, fileobj: BinaryIO, byteorder: ByteOrder = "big") -> None:
        """Write payload bytes (overridden by tags)."""
        raise NotImplementedError

    def unpack(self, json: bool = False) -> Any:
        """Return the plain Python value for this tag."""
        return None

    def __repr__(self) -> str:
        if self.tag_id is not None:
            return f"{self.__class__.__name__}({super().__repr__()})"
        return super().__repr__()


class End(Base):
    """Marker type for compound termination; not instantiable."""

    __slots__ = ()
    tag_id = 0

    def __new__(cls, *args: Any, **kwargs: Any) -> "End":
        raise EndInstantiation()


class Numeric(Base):
    """Shared parse/write for packed numeric tags."""

    __slots__ = ()
    serializer = "numeric"
    fmt: ClassVar[Optional[Dict[str, Struct]]] = None
    suffix: ClassVar[str] = ""

    @classmethod
    def parse(cls, fileobj: BinaryIO, byteorder: ByteOrder = "big") -> "Numeric":
        assert cls.fmt is not None
        return cls(read_numeric(cls.fmt, fileobj, byteorder))  # type: ignore[call-arg]

    def write(self, fileobj: BinaryIO, byteorder: ByteOrder = "big") -> None:
        assert self.fmt is not None
        write_numeric(self.fmt, cast(Union[int, float], self), fileobj, byteorder)


class NumericInteger(Numeric, int):
    """Integer numeric tags with range checks."""

    __slots__ = ()
    range: ClassVar[Optional[range]] = None
    mask: ClassVar[Optional[int]] = None
    bits: ClassVar[Optional[int]] = None

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if cls.fmt is None:
            return
        limit = 2 ** (8 * cls.fmt["big"].size - 1)
        cls.range = range(-limit, limit)
        mask = limit * 2 - 1
        cls.mask = mask
        cls.bits = mask.bit_length()

    def __new__(cls, *args: Any, **kwargs: Any) -> "NumericInteger":
        self = int.__new__(cls, *args, **kwargs)
        if cls.range is not None and int(self) not in cls.range:
            raise OutOfRange(self)
        return self

    def unpack(self, json: bool = False) -> int:
        return int(self)

    @property
    def as_unsigned(self) -> int:
        """Interpret the signed value as unsigned with the tag's bit width."""
        assert self.mask is not None
        return int(self) & self.mask

    @classmethod
    def from_unsigned(cls, value: int) -> "NumericInteger":
        """Encode an unsigned integer into this signed tag type."""
        assert cls.mask is not None
        return cls(value - (value * 2 & cls.mask + 1))


class Byte(NumericInteger):
    """TAG_Byte — signed 8-bit integer."""

    __slots__ = ()
    tag_id = 1
    fmt = BYTE
    suffix = "b"


class Short(NumericInteger):
    """TAG_Short — signed 16-bit integer."""

    __slots__ = ()
    tag_id = 2
    fmt = SHORT
    suffix = "s"


class Int(NumericInteger):
    """TAG_Int — signed 32-bit integer."""

    __slots__ = ()
    tag_id = 3
    fmt = INT


class Long(NumericInteger):
    """TAG_Long — signed 64-bit integer."""

    __slots__ = ()
    tag_id = 4
    fmt = LONG
    suffix = "L"


class Float(Numeric, float):
    """TAG_Float — IEEE-754 single precision."""

    __slots__ = ()
    tag_id = 5
    fmt = FLOAT
    suffix = "f"

    def unpack(self, json: bool = False) -> float:
        return float(self)


class Double(Numeric, float):
    """TAG_Double — IEEE-754 double precision."""

    __slots__ = ()
    tag_id = 6
    fmt = DOUBLE
    suffix = "d"

    def unpack(self, json: bool = False) -> float:
        return float(self)


class String(Base, str):
    """TAG_String — UTF-8 string with 16-bit length prefix."""

    __slots__ = ()
    tag_id = 8
    serializer = "string"

    @classmethod
    def parse(cls, fileobj: BinaryIO, byteorder: ByteOrder = "big") -> "String":
        return cls(read_string(fileobj, byteorder))

    def write(self, fileobj: BinaryIO, byteorder: ByteOrder = "big") -> None:
        write_string(self, fileobj, byteorder)

    def unpack(self, json: bool = False) -> str:
        return str(self)


class Array(Base, MutableSequence[int]):
    """Homogeneous integer array stored as a plain Python list (no numpy)."""

    __slots__ = ("_items",)
    serializer = "array"
    array_prefix: ClassVar[Optional[str]] = None
    wrapper: ClassVar[Optional[Type[NumericInteger]]] = None
    item_fmt: ClassVar[Optional[Dict[str, Struct]]] = None
    item_bits: ClassVar[int] = 8
    signed: ClassVar[bool] = True

    def __init__(
        self,
        value: Optional[Iterable[int]] = None,
        *,
        length: int = 0,
        byteorder: ByteOrder = "big",
    ) -> None:
        del byteorder  # kept for nbtlib-compatible signature
        if value is None:
            self._items = [0] * length
        else:
            self._items = [self._normalize(int(item)) for item in value]

    def _normalize(self, value: int) -> int:
        bits = self.item_bits
        mask = (1 << bits) - 1
        value &= mask
        if self.signed and value >= (1 << (bits - 1)):
            value -= 1 << bits
        return value

    @classmethod
    def parse(cls, fileobj: BinaryIO, byteorder: ByteOrder = "big") -> "Array":
        assert cls.item_fmt is not None
        count = int(read_numeric(INT, fileobj, byteorder))
        item_size = cls.item_fmt["big"].size
        raw = fileobj.read(count * item_size)
        if len(raw) < count * item_size:
            raise ValueError(
                f"{cls.__name__} truncated: need {count * item_size} bytes, "
                f"got {len(raw)}"
            )
        fmt = cls.item_fmt[byteorder]
        items = [
            int(fmt.unpack_from(raw, offset)[0])
            for offset in range(0, count * item_size, item_size)
        ]
        return cls(items)

    def write(self, fileobj: BinaryIO, byteorder: ByteOrder = "big") -> None:
        assert self.item_fmt is not None
        write_numeric(INT, len(self._items), fileobj, byteorder)
        fmt = self.item_fmt[byteorder]
        for item in self._items:
            fileobj.write(fmt.pack(item))

    def unpack(self, json: bool = False) -> TypingList[int]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    @overload
    def __getitem__(self, index: int) -> NumericInteger:
        ...

    @overload
    def __getitem__(self, index: slice) -> "Array":
        ...

    def __getitem__(
        self, index: Union[int, slice]
    ) -> Union[NumericInteger, "Array"]:
        if isinstance(index, slice):
            return type(self)(self._items[index])
        assert self.wrapper is not None
        return self.wrapper(self._items[index])

    @overload
    def __setitem__(self, index: int, value: int) -> None:
        ...

    @overload
    def __setitem__(self, index: slice, value: Iterable[int]) -> None:
        ...

    def __setitem__(
        self,
        index: Union[int, slice],
        value: Union[int, Iterable[int]],
    ) -> None:
        if isinstance(index, slice):
            assert isinstance(value, Iterable)
            self._items[index] = [self._normalize(int(item)) for item in value]
            return
        self._items[index] = self._normalize(int(cast(int, value)))

    def __delitem__(self, index: Union[int, slice]) -> None:
        del self._items[index]

    def insert(self, index: int, value: int) -> None:
        self._items.insert(index, self._normalize(int(value)))

    def __iter__(self) -> Iterator[NumericInteger]:
        assert self.wrapper is not None
        wrapper = self.wrapper
        for item in self._items:
            yield wrapper(item)

    def __bool__(self) -> bool:
        return all(self._items) if self._items else False

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Array):
            return self._items == other._items
        if isinstance(other, (list, tuple)):
            try:
                return self._items == [int(item) for item in other]
            except (TypeError, ValueError):
                return False
        return NotImplemented

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}([{', '.join(map(str, self._items))}])"


class ByteArray(Array):
    """TAG_Byte_Array — signed 8-bit integers."""

    __slots__ = ()
    tag_id = 7
    array_prefix = "B"
    wrapper = Byte
    item_fmt = BYTE
    item_bits = 8


class IntArray(Array):
    """TAG_Int_Array — signed 32-bit integers."""

    __slots__ = ()
    tag_id = 11
    array_prefix = "I"
    wrapper = Int
    item_fmt = INT
    item_bits = 32


class LongArray(Array):
    """TAG_Long_Array — signed 64-bit integers."""

    __slots__ = ()
    tag_id = 12
    array_prefix = "L"
    wrapper = Long
    item_fmt = LONG
    item_bits = 64


class List(Base, list):  # type: ignore[type-arg]
    """TAG_List — homogeneous list of a single tag subtype."""

    __slots__ = ()
    tag_id = 9
    serializer = "list"
    variants: ClassVar[Dict[Any, Any]] = {}
    subtype: ClassVar[Type[Base]] = End

    def __new__(cls, iterable: Iterable[Any] = ()) -> "List":
        if cls.subtype is End:
            items = tuple(iterable)
            subtype = cls.infer_list_subtype(items)
            cls = cls.__class_getitem__(subtype)
            iterable = items
        return list.__new__(cls)

    def __init__(self, iterable: Iterable[Any] = ()) -> None:
        list.__init__(self, map(self.cast_item, iterable))

    def __class_getitem__(cls, item: Any) -> Any:
        # 返回运行时子类；返回 Any 以便类型检查器接受 List[Tag] 下标。
        if item is End:
            return List
        try:
            return cls.variants[item]
        except KeyError:
            variant = type(
                f"List[{getattr(item, '__name__', item)}]",
                (List,),
                {"__slots__": (), "subtype": item},
            )
            cls.variants[item] = variant
            return variant

    @staticmethod
    def infer_list_subtype(items: Sequence[Any]) -> Type[Base]:
        """Infer list element tag type from sample items."""
        subtype: Type[Base] = End
        for item in items:
            item_type = type(item)
            if not issubclass(item_type, Base):
                continue
            if subtype is End:
                subtype = item_type
                if not issubclass(subtype, List):
                    return subtype
            elif subtype is not item_type:
                stype: Type[Base] = subtype
                itype: Type[Base] = item_type
                while issubclass(stype, List) and issubclass(itype, List):
                    stype = stype.subtype
                    itype = itype.subtype
                if stype is End:
                    subtype = item_type
                elif itype is not End:
                    return End
        return subtype

    @classmethod
    def parse(cls, fileobj: BinaryIO, byteorder: ByteOrder = "big") -> "List":
        tag = cls.get_tag(int(read_numeric(BYTE, fileobj, byteorder)))
        length = int(read_numeric(INT, fileobj, byteorder))
        list_cls = cls.__class_getitem__(tag)
        return list_cls(tag.parse(fileobj, byteorder) for _ in range(length))

    def write(self, fileobj: BinaryIO, byteorder: ByteOrder = "big") -> None:
        write_numeric(BYTE, self.subtype.tag_id or 0, fileobj, byteorder)
        write_numeric(INT, len(self), fileobj, byteorder)
        for elem in self:
            cast(Base, elem).write(fileobj, byteorder)

    def unpack(self, json: bool = False) -> TypingList[Any]:
        return [cast(Base, item).unpack(json) for item in self]

    def append(self, value: Any) -> None:
        super().append(self.cast_item(value))

    def extend(self, iterable: Iterable[Any]) -> None:
        super().extend(map(self.cast_item, iterable))

    def insert(self, index: SupportsIndex, value: Any) -> None:
        super().insert(index, self.cast_item(value))

    def __setitem__(self, index: Any, value: Any) -> None:
        if isinstance(index, slice):
            super().__setitem__(index, [self.cast_item(item) for item in value])
        elif isinstance(index, int):
            super().__setitem__(index, self.cast_item(value))
        else:
            raise TypeError(
                f"List indices must be integers or slices, not {type(index)!r}"
            )

    @classmethod
    def cast_item(cls, item: Any) -> Base:
        """Cast *item* to this list's subtype tag."""
        if not isinstance(item, cls.subtype):
            incompatible = isinstance(item, Base) and not any(
                issubclass(cls.subtype, tag_type) and isinstance(item, tag_type)
                for tag_type in Base.all_tags.values()
            )
            if incompatible:
                raise IncompatibleItemType(item, cls.subtype)
            try:
                return cast(Base, cls.subtype(item))  # type: ignore[call-arg]
            except EndInstantiation as exc:
                raise ValueError(
                    "List tags without an explicit subtype must either be empty "
                    "or instantiated with elements from which a subtype can be "
                    "inferred"
                ) from exc
            except (IncompatibleItemType, CastError):
                raise
            except Exception as exc:
                raise CastError(item, cls.subtype) from exc
        return item


class Compound(Base, Dict[str, Any]):
    """TAG_Compound — string-keyed mapping of tags."""

    __slots__ = ()
    tag_id = 10
    serializer = "compound"
    end_tag = b"\x00"

    @classmethod
    def parse(cls, fileobj: BinaryIO, byteorder: ByteOrder = "big") -> "Compound":
        self = cls()
        tag_id = int(read_numeric(BYTE, fileobj, byteorder))
        while tag_id != 0:
            name = read_string(fileobj, byteorder)
            self[name] = cls.get_tag(tag_id).parse(fileobj, byteorder)
            tag_id = int(read_numeric(BYTE, fileobj, byteorder))
        return self

    def write(self, fileobj: BinaryIO, byteorder: ByteOrder = "big") -> None:
        for name, tag in self.items():
            write_numeric(BYTE, cast(Base, tag).tag_id or 0, fileobj, byteorder)
            write_string(str(name), fileobj, byteorder)
            cast(Base, tag).write(fileobj, byteorder)
        fileobj.write(self.end_tag)

    def unpack(self, json: bool = False) -> Dict[str, Any]:
        return {key: cast(Base, value).unpack(json) for key, value in self.items()}

    def merge(self, other: Dict[str, Any]) -> None:
        """Recursively merge tags from another mapping into this compound."""
        for key, value in other.items():
            if key in self and isinstance(self[key], Compound) and isinstance(value, dict):
                cast(Compound, self[key]).merge(value)
            else:
                self[key] = value
