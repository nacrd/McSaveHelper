"""core.nbt 往返与 API 兼容性测试（自研库，无 nbtlib）。"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from core.nbt import (
    Byte,
    ByteArray,
    Compound,
    Double,
    File,
    Float,
    Int,
    IntArray,
    List,
    Long,
    LongArray,
    OutOfRange,
    Short,
    String,
    load,
    save,
)


def test_numeric_roundtrip_and_range() -> None:
    assert Int(42) == 42
    assert isinstance(Int(42), int)
    assert Byte(-128).unpack() == -128
    with pytest.raises(OutOfRange):
        Byte(128)
    assert Long(-1).as_unsigned == (1 << 64) - 1
    assert float(Float(1.5)) == pytest.approx(1.5)


def test_string_and_compound_write_parse() -> None:
    root = File(
        {
            "Data": Compound(
                {
                    "LevelName": String("test"),
                    "x": Int(42),
                    "flag": Byte(1),
                }
            )
        }
    )
    buf = io.BytesIO()
    root.write(buf)
    raw = buf.getvalue()
    assert raw[0] == 10  # TAG_Compound
    parsed = File.parse(io.BytesIO(raw))
    assert str(parsed["Data"]["LevelName"]) == "test"
    assert int(parsed["Data"]["x"]) == 42
    assert isinstance(parsed["Data"]["x"], Int)


def test_list_subtype_and_cast() -> None:
    typed = List[String]([String("a"), "b"])
    assert type(typed).__name__ == "List[String]"
    assert all(isinstance(item, String) for item in typed)
    inferred = List([Int(1), Int(2)])
    assert type(inferred) is List[Int]
    assert inferred.unpack() == [1, 2]


def test_arrays_roundtrip_signed() -> None:
    ia = IntArray([1, 2, -3])
    la = LongArray([1, 2, -1])
    ba = ByteArray([1, 2, -1])
    assert list(ia)[0] == 1
    assert isinstance(list(ia)[0], Int)
    assert int(list(la)[-1]) == -1
    assert int(list(ba)[-1]) == -1

    compound = File({"ids": ia, "longs": la, "bytes": ba})
    raw = io.BytesIO()
    compound.write(raw)
    parsed = File.parse(io.BytesIO(raw.getvalue()))
    assert [int(x) for x in parsed["ids"]] == [1, 2, -3]
    assert [int(x) for x in parsed["longs"]] == [1, 2, -1]
    assert [int(x) for x in parsed["bytes"]] == [1, 2, -1]


def test_little_endian_roundtrip() -> None:
    root = File({"x": Int(1)}, byteorder="little")
    buf = io.BytesIO()
    root.write(buf, byteorder="little")
    raw = buf.getvalue()
    # little-endian int 1 payload ends with 01 00 00 00
    assert raw[-5:-1] == b"\x01\x00\x00\x00"
    parsed = File.parse(io.BytesIO(raw), byteorder="little")
    assert int(parsed["x"]) == 1


def test_gzip_load_save(tmp_path: Path) -> None:
    path = tmp_path / "level.dat"
    original = File(
        {"Data": Compound({"LevelName": String("World"), "SpawnY": Int(64)})}
    )
    original.save(path, gzipped=True)
    raw = path.read_bytes()
    assert raw[:2] == b"\x1f\x8b"
    loaded = load(path)
    assert loaded.gzipped is True
    assert str(loaded["Data"]["LevelName"]) == "World"
    assert int(loaded["Data"]["SpawnY"]) == 64


def test_ungzipped_save_and_module_save(tmp_path: Path) -> None:
    path = tmp_path / "plain.nbt"
    original = File({"a": Int(7)})
    save(original, path, gzipped=False)
    assert path.read_bytes()[:1] == b"\n"
    loaded = load(path)
    assert int(loaded["a"]) == 7
    assert loaded.gzipped is False


def test_list_of_compound_and_doubles() -> None:
    pos = List[Double]([0.0, 64.0, 0.0])
    assert type(pos) is List[Double]
    assert [float(v) for v in pos] == [0.0, 64.0, 0.0]
    root = File({"Pos": pos, "Rotation": List[Float]([0.0, 0.0])})
    buf = io.BytesIO()
    root.write(buf)
    parsed = File.parse(io.BytesIO(buf.getvalue()))
    assert type(parsed["Pos"]) is List[Double]
    assert type(parsed["Rotation"]) is List[Float]


def test_empty_list_defaults_to_end_subtype() -> None:
    bare = List([])
    assert bare.subtype.tag_id == 0
    buf = io.BytesIO()
    File({"e": bare}).write(buf)
    parsed = File.parse(io.BytesIO(buf.getvalue()))
    assert list(parsed["e"]) == []


def test_short_float_double_types() -> None:
    root = File(
        {
            "s": Short(1000),
            "f": Float(1.25),
            "d": Double(2.5),
        }
    )
    raw = io.BytesIO()
    root.write(raw)
    parsed = File.parse(io.BytesIO(raw.getvalue()))
    assert isinstance(parsed["s"], Short)
    assert int(parsed["s"]) == 1000
    assert float(parsed["f"]) == pytest.approx(1.25)
    assert float(parsed["d"]) == pytest.approx(2.5)
