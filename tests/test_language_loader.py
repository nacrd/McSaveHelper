"""Tests for jar language extraction."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.services.item.language_loader import (
    extract_language_from_jar,
    extract_language_from_local_minecraft,
    extract_language_from_minecraft_assets,
    list_lang_entries_in_jar,
    locale_fallbacks,
    normalize_locale,
    resolve_lang_object_path,
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
    assert normalize_locale("zh_CN") == "zh_cn"
    assert normalize_locale("zh") == "zh_cn"
    assert normalize_locale("en_US") == "en_us"
    assert normalize_locale("") == "en_us"
    # UI language first; en_us only as fallback — never bare "zh".
    assert locale_fallbacks("zh_CN") == ("zh_cn", "en_us")
    assert locale_fallbacks("en_US") == ("en_us",)
    assert "zh" not in locale_fallbacks("zh_CN")


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


def test_extract_prefers_ui_locale_over_en_us(tmp_path: Path) -> None:
    jar = _write_jar(
        tmp_path / "client.jar",
        {
            "assets/minecraft/lang/zh_cn.json": {
                "item.minecraft.apple": "苹果",
            },
            "assets/minecraft/lang/en_us.json": {
                "item.minecraft.apple": "Apple",
            },
        },
    )
    names: dict[str, str] = {}
    result = extract_language_from_jar(jar, names, {}, locale="zh_CN")
    assert result.locale == "zh_cn"
    assert names["minecraft:apple"] == "苹果"


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


def test_extract_from_minecraft_assets_index_and_objects(tmp_path: Path) -> None:
    """1.8+ style: lang JSON lives in assets/objects via indexes hash map."""
    mc = tmp_path / ".minecraft"
    indexes = mc / "assets" / "indexes"
    objects = mc / "assets" / "objects"
    indexes.mkdir(parents=True)
    objects.mkdir(parents=True)

    payload = {
        "item.minecraft.diamond": "钻石",
        "block.minecraft.dirt": "泥土",
        "enchantment.minecraft.efficiency": "效率",
    }
    # Simulate unicode-escaped storage; json.loads will decode it.
    raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    digest = "8fb4f6725d8317a37e7f823ff424e66a46b9ef75"
    obj_dir = objects / digest[:2]
    obj_dir.mkdir(parents=True)
    obj_path = obj_dir / digest
    obj_path.write_bytes(raw)

    index = {
        "objects": {
            "minecraft/lang/zh_cn.json": {
                "hash": digest,
                "size": len(raw),
            },
            "minecraft/lang/en_us.json": {
                "hash": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
                "size": 1,
            },
        }
    }
    (indexes / "1.17.json").write_text(
        json.dumps(index),
        encoding="utf-8",
    )

    names: dict[str, str] = {}
    enchants: dict[str, str] = {}
    result = extract_language_from_minecraft_assets(
        names,
        enchants,
        locale="zh_CN",
        minecraft_dir=mc,
    )
    assert result.count >= 3
    assert result.locale == "zh_cn"
    assert names["minecraft:diamond"] == "钻石"
    assert names["minecraft:dirt"] == "泥土"
    assert enchants["minecraft:efficiency"] == "效率"
    assert resolve_lang_object_path(mc, "zh_cn") == obj_path


def test_local_minecraft_prefers_assets_over_empty_jar(tmp_path: Path) -> None:
    mc = tmp_path / ".minecraft"
    indexes = mc / "assets" / "indexes"
    objects = mc / "assets" / "objects"
    versions = mc / "versions" / "1.20.1"
    indexes.mkdir(parents=True)
    objects.mkdir(parents=True)
    versions.mkdir(parents=True)

    payload = {"item.minecraft.apple": "苹果"}
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    digest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    (objects / digest[:2]).mkdir(parents=True)
    (objects / digest[:2] / digest).write_bytes(raw)
    (indexes / "5.json").write_text(
        json.dumps(
            {
                "objects": {
                    "minecraft/lang/zh_cn.json": {
                        "hash": digest,
                        "size": len(raw),
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    empty_jar = versions / "1.20.1.jar"
    with zipfile.ZipFile(empty_jar, "w") as jar:
        jar.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")

    names: dict[str, str] = {}
    result = extract_language_from_local_minecraft(
        names,
        {},
        locale="zh_cn",
        jar_path=empty_jar,
        minecraft_dir=mc,
    )
    assert result.count >= 1
    assert names["minecraft:apple"] == "苹果"
    assert "assets/objects/" in result.sources[0]


def test_discover_from_save_relative_path(tmp_path: Path) -> None:
    """Custom install: F:/Game/minecraft/.minecraft/saves/World."""
    from core.texture.client_jar import (
        discover_minecraft_directory,
        is_minecraft_data_dir,
        minecraft_dir_from_start_path,
    )

    root = tmp_path / "Game" / "minecraft" / ".minecraft"
    save = root / "saves" / "World"
    save.mkdir(parents=True)
    (root / "assets" / "indexes").mkdir(parents=True)
    (root / "assets" / "objects").mkdir(parents=True)
    (root / "versions").mkdir(parents=True)
    assert is_minecraft_data_dir(root)
    assert minecraft_dir_from_start_path(save) == root.resolve()
    assert discover_minecraft_directory(start_path=save) == root.resolve()


def test_configured_dir_overrides_default(tmp_path: Path) -> None:
    from core.texture.client_jar import discover_minecraft_directory

    custom = tmp_path / "custom_mc"
    (custom / "assets" / "indexes").mkdir(parents=True)
    (custom / "versions").mkdir(parents=True)
    found = discover_minecraft_directory(configured=custom)
    assert found == custom.resolve()


def test_legacy_lang_inside_jar(tmp_path: Path) -> None:
    jar = tmp_path / "1.7.10.jar"
    modernish = (
        "item.minecraft.diamond_sword=钻石剑\n"
        "block.minecraft.stone=石头\n"
        "enchantment.minecraft.sharpness=锋利\n"
    )
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr("assets/minecraft/lang/zh_CN.lang", modernish)

    names: dict[str, str] = {}
    enchants: dict[str, str] = {}
    result = extract_language_from_jar(jar, names, enchants, locale="zh_cn")
    assert result.count >= 3
    assert names["minecraft:diamond_sword"] == "钻石剑"
    assert names["minecraft:stone"] == "石头"
    assert enchants["minecraft:sharpness"] == "锋利"


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
        minecraft_dir=tmp_path / "no_mc",
    )
    assert result.count == 0
