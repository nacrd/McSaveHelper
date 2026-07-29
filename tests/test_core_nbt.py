"""core.nbt 往返与 API 兼容性测试（自研库，无 nbtlib）。"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from core.nbt import (
    Byte,
    ByteArray,
    Compound,
    CompoundProjection,
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
from core.nbt.tag import read_string


def test_numeric_roundtrip_and_range() -> None:
    assert Int(42) == 42
    assert isinstance(Int(42), int)
    assert Byte(-128).unpack() == -128
    with pytest.raises(OutOfRange):
        Byte(128)
    assert Long(-1).as_unsigned == (1 << 64) - 1
    assert float(Float(1.5)) == pytest.approx(1.5)


@pytest.mark.parametrize("tag_type", (Byte, Int, Long, Float, Double))
def test_numeric_parser_keeps_short_payload_zero_compatibility(tag_type) -> None:
    parsed = tag_type.parse(io.BytesIO(b"\x00"))

    assert isinstance(parsed, tag_type)
    assert float(parsed) == 0.0


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


@pytest.mark.parametrize("byteorder", ("big", "little"))
def test_array_parser_preserves_signed_width_boundaries(byteorder: str) -> None:
    root = File(
        {
            "bytes": ByteArray([-128, 127]),
            "ints": IntArray([-(1 << 31), (1 << 31) - 1]),
            "longs": LongArray([-(1 << 63), (1 << 63) - 1]),
        },
        byteorder=byteorder,
    )
    raw = io.BytesIO()
    root.write(raw, byteorder=byteorder)

    parsed = File.parse(io.BytesIO(raw.getvalue()), byteorder=byteorder)

    assert [int(value) for value in parsed["bytes"]] == [-128, 127]
    assert [int(value) for value in parsed["ints"]] == [-(1 << 31), (1 << 31) - 1]
    assert [int(value) for value in parsed["longs"]] == [
        -(1 << 63),
        (1 << 63) - 1,
    ]


def test_little_endian_roundtrip() -> None:
    root = File({"x": Int(1)}, byteorder="little")
    buf = io.BytesIO()
    root.write(buf, byteorder="little")
    raw = buf.getvalue()
    # little-endian int 1 payload ends with 01 00 00 00
    assert raw[-5:-1] == b"\x01\x00\x00\x00"
    parsed = File.parse(io.BytesIO(raw), byteorder="little")
    assert int(parsed["x"]) == 1


@pytest.mark.parametrize(
    ("byteorder", "raw"),
    (("big", b"\x00\x05stone"), ("little", b"\x05\x00stone")),
)
def test_read_string_handles_both_byte_orders(byteorder: str, raw: bytes) -> None:
    assert read_string(io.BytesIO(raw), byteorder) == "stone"


def test_read_string_keeps_short_prefix_compatibility() -> None:
    assert read_string(io.BytesIO(b"\x00")) == ""


def test_container_parsers_keep_short_header_compatibility() -> None:
    assert IntArray.parse(io.BytesIO()) == []
    assert List.parse(io.BytesIO()) == []
    assert Compound.parse(io.BytesIO()) == {}


@pytest.mark.parametrize("byteorder", ("big", "little"))
def test_root_field_projection_skips_every_payload_type(byteorder: str) -> None:
    root = File(
        {
            "byte": Byte(1),
            "short": Short(2),
            "int": Int(3),
            "long": Long(4),
            "float": Float(5.0),
            "double": Double(6.0),
            "bytes": ByteArray([1, 2]),
            "string": String("skip"),
            "list": List[Int]([Int(7), Int(8)]),
            "compound": Compound({"nested": String("skip")}),
            "ints": IntArray([9, 10]),
            "longs": LongArray([11, 12]),
            "keep": String("selected"),
        },
        byteorder=byteorder,
    )
    raw = io.BytesIO()
    root.write(raw, byteorder=byteorder)

    projected = File.parse_root_fields(
        io.BytesIO(raw.getvalue()),
        {"keep"},
        byteorder,
    )

    assert list(projected) == ["keep"]
    assert projected["keep"] == "selected"


def test_root_field_projection_rejects_truncated_skipped_payload() -> None:
    raw = b"\x0a\x00\x00\x07\x00\x04skip\x00\x00\x00\x03\x01"

    with pytest.raises(ValueError, match="truncated"):
        File.parse_root_fields(io.BytesIO(raw), {"keep"})


def test_root_field_projection_keeps_selected_compound_complete() -> None:
    root = File({
        "Level": Compound({
            "Sections": List[Compound]([
                Compound({"Y": Byte(4), "Name": String("kept")}),
            ]),
        }),
        "structures": Compound({"skip": String("unused")}),
    })
    raw = io.BytesIO()
    root.write(raw)

    projected = File.parse_root_fields(io.BytesIO(raw.getvalue()), {"Level"})

    assert list(projected) == ["Level"]
    assert projected["Level"]["Sections"][0]["Name"] == "kept"


def test_root_field_projection_filters_direct_compound_lists() -> None:
    root = File({
        "sections": List[Compound]([
            Compound({
                "Y": Byte(4),
                "block_states": Compound({"value": Int(1)}),
                "BlockLight": ByteArray([1, 2, 3]),
            }),
        ]),
    })
    raw = io.BytesIO()
    root.write(raw)

    projected = File.parse_root_fields(
        io.BytesIO(raw.getvalue()),
        {"sections"},
        compound_list_fields={
            "sections": {"Y", "block_states"},
        },
    )

    section = projected["sections"][0]
    assert set(section) == {"Y", "block_states"}
    assert int(section["Y"]) == 4
    assert int(section["block_states"]["value"]) == 1


def test_root_field_projection_rejects_non_compound_projected_list() -> None:
    root = File({"sections": List[Int]([Int(1)])})
    raw = io.BytesIO()
    root.write(raw)

    with pytest.raises(ValueError, match="must contain TAG_Compound"):
        File.parse_root_fields(
            io.BytesIO(raw.getvalue()),
            {"sections"},
            compound_list_fields={"sections": {"Y"}},
        )


def test_root_field_projection_filters_nested_compounds_and_lists() -> None:
    root = File({
        "sections": List[Compound]([
            Compound({
                "Y": Byte(4),
                "block_states": Compound({
                    "palette": List[Compound]([
                        Compound({
                            "Name": String("minecraft:oak_log"),
                            "Properties": Compound({
                                "axis": String("y"),
                            }),
                        }),
                    ]),
                    "data": LongArray([1, 2]),
                    "unused": String("skip"),
                }),
                "BlockLight": ByteArray([1, 2, 3]),
            }),
        ]),
    })
    raw = io.BytesIO()
    root.write(raw)
    palette_entry = CompoundProjection({"Name"})
    block_states = CompoundProjection(
        {"palette", "data"},
        compound_list_fields={"palette": palette_entry},
    )
    section = CompoundProjection(
        {"Y", "block_states"},
        compound_fields={"block_states": block_states},
    )

    projected = File.parse_root_fields(
        io.BytesIO(raw.getvalue()),
        {"sections"},
        compound_list_fields={"sections": section},
    )

    selected_section = projected["sections"][0]
    selected_states = selected_section["block_states"]
    assert set(selected_section) == {"Y", "block_states"}
    assert set(selected_states) == {"palette", "data"}
    assert set(selected_states["palette"][0]) == {"Name"}
    assert selected_states["palette"][0]["Name"] == "minecraft:oak_log"
    assert list(selected_states["data"]) == [1, 2]


def test_nested_compound_projection_rejects_wrong_tag_type() -> None:
    root = File({
        "sections": List[Compound]([
            Compound({"block_states": String("invalid")}),
        ]),
    })
    raw = io.BytesIO()
    root.write(raw)
    section = CompoundProjection(
        {"block_states"},
        compound_fields={
            "block_states": CompoundProjection({"palette"}),
        },
    )

    with pytest.raises(ValueError, match="must be TAG_Compound"):
        File.parse_root_fields(
            io.BytesIO(raw.getvalue()),
            {"sections"},
            compound_list_fields={"sections": section},
        )


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
