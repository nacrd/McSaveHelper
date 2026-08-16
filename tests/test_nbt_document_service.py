"""NBT 文档服务与树值 presenter 的边界测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.presenters.nbt_tree import (
    coerce_nbt_value,
    format_nbt_path,
    latest_staged_value,
)
from app.services.nbt_document_service import (
    NbtDocumentPathError,
    NbtDocumentTarget,
    find_nbt_documents,
    load_nbt_document,
)
from core.nbt import Compound, File, Int, String


def _create_world(path: Path) -> Path:
    path.mkdir(exist_ok=True)
    File({
        "Data": Compound({
            "GameType": Int(0),
            "LevelName": String("Demo"),
        }),
    }).save(path / "level.dat")
    (path / "data").mkdir()
    File({"Value": Int(7)}).save(path / "data" / "custom.dat")
    (path / "stats").mkdir()
    (path / "stats" / "player.json").write_text(
        json.dumps({"minecraft:custom": {"value": 3}}),
        encoding="utf-8",
    )
    return path


def test_find_and_load_documents_preserve_types(tmp_path: Path) -> None:
    world = _create_world(tmp_path / "world")

    targets = find_nbt_documents(world)
    labels = [target.label for target in targets]
    level = load_nbt_document(world, targets[0])
    stats = load_nbt_document(world, targets[-1])

    assert labels == [
        "世界 / level.dat",
        "数据 / custom.dat",
        "统计 / player.json",
    ]
    assert isinstance(level.data["Data"]["GameType"], Int)
    assert stats.data["minecraft:custom"]["value"] == 3


def test_load_document_rejects_path_escape(tmp_path: Path) -> None:
    world = _create_world(tmp_path / "world")
    outside = tmp_path / "outside.dat"
    File({"Value": Int(1)}).save(outside)
    target = NbtDocumentTarget("outside", Path("../outside.dat"), "nbt")

    with pytest.raises(NbtDocumentPathError):
        load_nbt_document(world, target)


def test_tree_value_conversion_keeps_nbt_type_and_latest_stage() -> None:
    original = Int(1)
    converted = coerce_nbt_value("42", original)
    path = ("Data", "GameType")

    assert isinstance(converted, Int)
    assert int(converted) == 42
    assert format_nbt_path(path) == "Data.GameType"
    assert latest_staged_value(
        path,
        ((path, Int(2)), (path, Int(3))),
        original,
    ) == Int(3)


@pytest.mark.parametrize("raw", ["yes", "true", "1"])
def test_tree_value_conversion_accepts_boolean_aliases(raw: str) -> None:
    assert coerce_nbt_value(raw, False) is True
