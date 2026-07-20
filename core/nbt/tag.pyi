"""Type stubs for core.nbt.tag — make ``List[Tag]`` indexable under mypy."""
from __future__ import annotations

from struct import Struct
from typing import (
    Any,
    BinaryIO,
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
    overload,
)

ByteOrder = str
T = TypeVar("T")

def get_format(fmt: Any, string: str) -> Dict[str, Struct]: ...

BYTE: Dict[str, Struct]
SHORT: Dict[str, Struct]
USHORT: Dict[str, Struct]
INT: Dict[str, Struct]
LONG: Dict[str, Struct]
FLOAT: Dict[str, Struct]
DOUBLE: Dict[str, Struct]

class EndInstantiation(TypeError): ...
class OutOfRange(ValueError): ...
class IncompatibleItemType(TypeError):
    item: Any
    subtype: type
    def __init__(self, item: Any, subtype: type) -> None: ...

class CastError(ValueError):
    obj: Any
    tag_type: type
    def __init__(self, obj: Any, tag_type: type) -> None: ...

def read_numeric(
    fmt: Dict[str, Struct],
    fileobj: BinaryIO,
    byteorder: ByteOrder = ...,
) -> Union[int, float]: ...

def write_numeric(
    fmt: Dict[str, Struct],
    value: Union[int, float],
    fileobj: BinaryIO,
    byteorder: ByteOrder = ...,
) -> None: ...

def read_string(fileobj: BinaryIO, byteorder: ByteOrder = ...) -> str: ...
def write_string(value: str, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> None: ...

class Base:
    all_tags: Dict[int, Type[Base]]
    tag_id: Optional[int]
    serializer: Optional[str]
    @classmethod
    def get_tag(cls, tag_id: int) -> Type[Base]: ...
    @classmethod
    def parse(cls, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> Base: ...
    def write(self, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> None: ...
    def unpack(self, json: bool = ...) -> Any: ...

class End(Base):
    tag_id: int

class Numeric(Base):
    fmt: Optional[Dict[str, Struct]]
    suffix: str
    @classmethod
    def parse(cls, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> Numeric: ...
    def write(self, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> None: ...

class NumericInteger(Numeric, int):
    range: Optional[range]
    mask: Optional[int]
    bits: Optional[int]
    def unpack(self, json: bool = ...) -> int: ...
    @property
    def as_unsigned(self) -> int: ...
    @classmethod
    def from_unsigned(cls, value: int) -> NumericInteger: ...

class Byte(NumericInteger):
    tag_id: int

class Short(NumericInteger):
    tag_id: int

class Int(NumericInteger):
    tag_id: int

class Long(NumericInteger):
    tag_id: int

class Float(Numeric, float):
    tag_id: int
    def unpack(self, json: bool = ...) -> float: ...

class Double(Numeric, float):
    tag_id: int
    def unpack(self, json: bool = ...) -> float: ...

class String(Base, str):
    tag_id: int
    @classmethod
    def parse(cls, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> String: ...
    def write(self, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> None: ...
    def unpack(self, json: bool = ...) -> str: ...

class Array(Base, MutableSequence[int]):
    def __init__(
        self,
        value: Optional[Iterable[int]] = ...,
        *,
        length: int = ...,
        byteorder: ByteOrder = ...,
    ) -> None: ...
    @classmethod
    def parse(cls, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> Array: ...
    def write(self, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> None: ...
    def unpack(self, json: bool = ...) -> TypingList[int]: ...
    def __len__(self) -> int: ...
    @overload
    def __getitem__(self, index: int) -> NumericInteger: ...
    @overload
    def __getitem__(self, index: slice) -> Array: ...
    def __setitem__(self, index: Any, value: Any) -> None: ...
    def __delitem__(self, index: Union[int, slice]) -> None: ...
    def insert(self, index: int, value: int) -> None: ...
    def __iter__(self) -> Iterator[NumericInteger]: ...

class ByteArray(Array):
    tag_id: int

class IntArray(Array):
    tag_id: int

class LongArray(Array):
    tag_id: int

class List(Base, TypingList[T]):
    tag_id: int
    subtype: Type[Base]
    def __init__(self, iterable: Iterable[Any] = ...) -> None: ...
    @staticmethod
    def infer_list_subtype(items: Sequence[Any]) -> Type[Base]: ...
    @classmethod
    def parse(cls, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> List[Any]: ...
    def write(self, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> None: ...
    def unpack(self, json: bool = ...) -> TypingList[Any]: ...
    def append(self, value: Any) -> None: ...
    def extend(self, iterable: Iterable[Any]) -> None: ...
    def insert(self, index: SupportsIndex, value: Any) -> None: ...
    @classmethod
    def cast_item(cls, item: Any) -> Base: ...

class Compound(Base, Dict[str, Any]):
    tag_id: int
    end_tag: bytes
    @classmethod
    def parse(cls, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> Compound: ...
    def write(self, fileobj: BinaryIO, byteorder: ByteOrder = ...) -> None: ...
    def unpack(self, json: bool = ...) -> Dict[str, Any]: ...
    def merge(self, other: Dict[str, Any]) -> None: ...
