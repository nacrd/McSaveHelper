"""NBT 文件根节点与磁盘 I/O。

``File`` 是带可选 gzip / 字节序元数据的根 ``Compound``。``load`` 根据魔数自动识别 gzip。
"""
from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any, BinaryIO, Optional, Union, cast

from core.nbt.tag import BYTE, Compound, read_numeric, read_string, write_numeric, write_string

__all__ = ["load", "save", "File"]

PathLike = Union[str, Path]
ByteOrder = str
# gzip.GzipFile 与 BufferedReader 均可作为二进制流读写 NBT。
Stream = Any


def load(
    filename: PathLike,
    *,
    gzipped: Optional[bool] = None,
    byteorder: ByteOrder = "big",
) -> "File":
    """Load an NBT file from disk.

    Args:
        filename: Path to a ``.dat`` / uncompressed NBT blob.
        gzipped: Force gzip on/off; ``None`` auto-detects via magic number.
        byteorder: ``"big"`` (Java) or ``"little"`` (Bedrock-style).

    Returns:
        File: Parsed root compound with metadata filled in.
    """
    path = Path(filename)
    if gzipped is not None:
        return File.load(path, gzipped, byteorder)

    with path.open("rb") as fileobj:
        magic = fileobj.read(2)
        fileobj.seek(0)
        if magic == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=fileobj) as gz:
                result = File.parse(cast(BinaryIO, gz), byteorder)
                result.filename = str(path)
                result.gzipped = True
                result.byteorder = byteorder
                return result
        result = File.parse(fileobj, byteorder)
        result.filename = str(path)
        result.gzipped = False
        result.byteorder = byteorder
        return result


def save(
    nbt: "File",
    filename: Optional[PathLike] = None,
    *,
    gzipped: Optional[bool] = None,
    byteorder: Optional[ByteOrder] = None,
) -> None:
    """Module-level save helper (``save(file, path)``), matching common call sites.

    Args:
        nbt: Root file tag to write.
        filename: Destination path; defaults to ``nbt.filename``.
        gzipped: Override gzip flag.
        byteorder: Override endianness.
    """
    nbt.save(filename, gzipped=gzipped, byteorder=byteorder)


class File(Compound):
    """Root compound representing a full NBT document on disk."""

    filename: Optional[str]
    gzipped: bool
    byteorder: ByteOrder
    root_name: str

    def __init__(
        self,
        *args: Any,
        gzipped: bool = False,
        byteorder: ByteOrder = "big",
        filename: Optional[str] = None,
        root_name: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.filename = filename
        self.gzipped = gzipped
        self.byteorder = byteorder
        self.root_name = root_name

    @classmethod
    def parse(cls, fileobj: Stream, byteorder: ByteOrder = "big") -> "File":
        """Parse a named root compound from *fileobj*."""
        tag_id = int(read_numeric(BYTE, fileobj, byteorder))
        if tag_id != cls.tag_id:
            tag_name = (
                cls.get_tag(tag_id).__name__
                if tag_id in cls.all_tags
                else tag_id
            )
            raise TypeError(
                f"Non-Compound root tags is not supported: {tag_name}"
            )
        name = read_string(fileobj, byteorder)
        self = cast("File", super().parse(fileobj, byteorder))
        self.root_name = name
        self.byteorder = byteorder
        if not hasattr(self, "filename"):
            self.filename = None
        if not hasattr(self, "gzipped"):
            self.gzipped = False
        return self

    def write(self, fileobj: Stream, byteorder: ByteOrder = "big") -> None:
        """Write the named root compound (id + name + body + end)."""
        write_numeric(BYTE, self.tag_id or 0, fileobj, byteorder)
        write_string(self.root_name, fileobj, byteorder)
        Compound.write(self, fileobj, byteorder)

    @classmethod
    def from_fileobj(cls, fileobj: Stream, byteorder: ByteOrder = "big") -> "File":
        """Parse from an already-opened (possibly gzip) file object."""
        self = cls.parse(fileobj, byteorder)
        self.filename = getattr(fileobj, "name", self.filename)
        self.gzipped = isinstance(fileobj, gzip.GzipFile)
        self.byteorder = byteorder
        return self

    @classmethod
    def load(
        cls,
        filename: PathLike,
        gzipped: bool,
        byteorder: ByteOrder = "big",
    ) -> "File":
        """Open *filename* with an explicit gzip flag and parse it."""
        path = Path(filename)
        if gzipped:
            with gzip.open(path, "rb") as fileobj:
                return cls.from_fileobj(fileobj, byteorder)
        with path.open("rb") as fileobj:
            return cls.from_fileobj(fileobj, byteorder)

    def save(
        self,
        filename: Optional[PathLike] = None,
        *,
        gzipped: Optional[bool] = None,
        byteorder: Optional[ByteOrder] = None,
    ) -> None:
        """Write this file to disk.

        Args:
            filename: Destination; defaults to ``self.filename``.
            gzipped: Override instance gzip flag.
            byteorder: Override instance endianness.

        Raises:
            ValueError: No filename is available.
        """
        if gzipped is None:
            gzipped = self.gzipped
        if filename is None:
            filename = self.filename
        if filename is None:
            raise ValueError("No filename specified")

        path = Path(filename)
        order = byteorder or self.byteorder
        if gzipped:
            with gzip.open(path, "wb") as fileobj:
                self.write(fileobj, order)
        else:
            with path.open("wb") as fileobj:
                self.write(fileobj, order)
        self.filename = str(path)
        self.gzipped = bool(gzipped)
        self.byteorder = order

    def __enter__(self) -> "File":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.save()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, File):
            return Compound.__eq__(self, other)
        return Compound.__eq__(self, other) and self.root_name == other.root_name

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.root_name!r}: {dict.__repr__(self)}>"
