"""Map translation catalogs stay structurally compatible."""
from __future__ import annotations

import json
from pathlib import Path
from string import Formatter


ROOT = Path(__file__).resolve().parents[1]


def _catalog(language: str) -> dict[str, object]:
    path = ROOT / "translations" / f"{language}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _placeholders(value: object) -> set[str]:
    return {
        field_name
        for _literal, field_name, _format, _conversion in Formatter().parse(str(value))
        if field_name is not None
    }


def test_map_translation_keys_and_placeholders_match() -> None:
    zh = _catalog("zh_CN")
    en = _catalog("en_US")

    for section in ("map", "map_export"):
        zh_section = zh[section]
        en_section = en[section]
        assert isinstance(zh_section, dict)
        assert isinstance(en_section, dict)
        assert set(zh_section) == set(en_section)
        for key in zh_section:
            assert _placeholders(zh_section[key]) == _placeholders(en_section[key])
