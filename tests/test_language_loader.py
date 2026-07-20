"""Tests for jar language extraction."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.services.item.language_loader import (
    extract_language_from_jar,
    extract_language_from_local_minecraft,
    list_lang_entries_in_jar,
    locale_fallbacks,
    normalize_locale,
)
from app.services.item_service import ItemService


def _write_jar(path: Path, entries: dict[str, dict | str]) -> Path:
    with zipfile.ZipFile(path, "w") as jar:
        for name, payload in entries.items():
            if isinstance(payload, dict):
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            else:
                data = str(payload).encode("utf-8")
            jar.writestr(name, data)
    return path


def test_normalize_and_fallback_locale() -> None:
    assert normalize_locale("zh-CN") == "zh_cn"
    assert normalize_locale("") == "en_us"
    assert locale_fallbacks("zh_CN")[0] == "zh_cn"
    assert "en_us" in locale_fallbacks("zh_cn")


def test_extract_language_from_client_jar_style(tmp_path: Path) -> None:
    jar = _write_jar(
        tmp_path / "1.21.jar",
        {
            "assets/minecraft/lang/zh_cn.json": {
                "item.minecraft.diamond_sword": "钻石剑",
                "block.minecraft.stone": "石头",
                "enchantment.minecraft.sharpness": "锋利",
            },
            "assets/examplemod/lang/zh_cn.json": {
                "item.examplemod.widget": "小零件",
            },
        },
    )
    names: dict[str, str] = {}
    enchants: dict[str, str] = {}
    result = extract_language_from_jar(jar, names, enchants, locale="zh_cn")
    assert result.count >= 4
    assert names["minecraft:diamond_sword"] == "钻石剑"
    assert names["minecraft:stone"] == "石头"
    assert enchants["minecraft:sharpness"] == "锋利"
    assert names["examplemod:widget"] == "小零件"
    assert any(path.endswith("zh_cn.json") for path in result.sources)


def test_extract_falls_back_to_en_us(tmp_path: Path) -> None:
    jar = _write_jar(
        tmp_path / "client.jar",
        {
            "assets/minecraft/lang/en_us.json": {
                "item.minecraft.apple": "Apple",
            },
        },
    )
    names: dict[str, str] = {}
    result = extract_language_from_jar(jar, names, {}, locale="zh_cn")
    assert result.locale == "en_us"
    assert names["minecraft:apple"] == "Apple"


def test_list_lang_entries_in_jar(tmp_path: Path) -> None:
    jar = _write_jar(
        tmp_path / "mod.jar",
        {
            "assets/minecraft/lang/zh_cn.json": {"item.minecraft.stick": "木棍"},
            "assets/foo/lang/zh_cn.json": {"item.foo.bar": "Bar"},
            "assets/foo/lang/en_us.json": {"item.foo.bar": "Bar"},
        },
    )
    entries = list_lang_entries_in_jar(jar, "zh_cn")
    assert any(e.endswith("minecraft/lang/zh_cn.json") for e in entries)
    assert any("foo/lang/zh_cn.json" in e for e in entries)


def test_item_service_import_from_local_minecraft_with_path(
    tmp_path: Path,
) -> None:
    jar = _write_jar(
        tmp_path / "client.jar",
        {
            "assets/minecraft/lang/zh_cn.json": {
                "item.minecraft.iron_ingot": "铁锭",
            },
        },
    )
    service = ItemService()
    result = service.import_language_from_local_minecraft(
        locale="zh_cn",
        jar_path=jar,
    )
    assert result.count >= 1
    assert service.get_item_name("minecraft:iron_ingot") == "铁锭"


def test_extract_missing_jar_returns_zero(tmp_path: Path) -> None:
    result = extract_language_from_local_minecraft(
        {},
        {},
        locale="zh_cn",
        jar_path=tmp_path / "missing.jar",
    )
    assert result.count == 0
