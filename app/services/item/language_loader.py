"""Language file loading for item names."""
import json
import zipfile
from pathlib import Path
from typing import Any, Dict


def load_language_file(path: Path, name_map: Dict[str, str],
                       enchantment_names: Dict[str, str],
                       namespace: str = "minecraft") -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return 0
    return _load_language_dict(data, name_map, enchantment_names, namespace)


def load_custom_mapping(path: Path, name_map: Dict[str, str],
                        enchantment_names: Dict[str, str]) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    items = data.get("items", data)
    enchantments = data.get("enchantments", {})
    count = 0
    if isinstance(items, dict):
        for key, value in items.items():
            if isinstance(key, str) and isinstance(value, str) and ":" in key:
                name_map[key] = value
                count += 1
    if isinstance(enchantments, dict):
        for key, value in enchantments.items():
            if isinstance(key, str) and isinstance(value, str):
                enchantment_names[key] = value
                count += 1
    return count


def save_custom_mapping(path: Path, name_map: Dict[str, str],
                        enchantment_names: Dict[str, str],
                        vanilla_items: Dict[str, str],
                        vanilla_enchants: Dict[str, str]) -> None:
    items = {k: v for k, v in name_map.items() if vanilla_items.get(k) != v}
    enchants = {k: v for k, v in enchantment_names.items() if vanilla_enchants.get(k) != v}
    path.write_text(
        json.dumps(
            {"items": items, "enchantments": enchants},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def extract_language_from_jar(jar_path: Path, name_map: Dict[str, str],
                              enchantment_names: Dict[str, str],
                              locale: str = "zh_cn") -> int:
    count = 0
    try:
        with zipfile.ZipFile(jar_path) as jar:
            for name in jar.namelist():
                lower = name.lower()
                if lower.endswith(f"/lang/{locale.lower()}.json") or \
                   lower.endswith(f"/lang/{locale.lower()}.lang"):
                    raw = jar.read(name).decode("utf-8", errors="replace")
                    if lower.endswith(".json"):
                        tmp = json.loads(raw)
                    else:
                        tmp = _parse_lang_file(raw)
                    count += _load_language_dict(tmp, name_map, enchantment_names)
    except Exception:
        pass
    return count


def _parse_lang_file(raw: str) -> Dict[str, str]:
    result = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _load_language_dict(data: Dict[str, Any], name_map: Dict[str, str],
                        enchantment_names: Dict[str, str],
                        namespace: str = "minecraft") -> int:
    count = 0
    for key, value in data.items():
        if not isinstance(value, str):
            continue
        if key.startswith(("item.", "block.")):
            parts = key.split(".")
            if len(parts) >= 3:
                name_map[f"{parts[1]}:{'_'.join(parts[2:])}"] = value
                count += 1
        elif key.startswith("enchantment."):
            parts = key.split(".")
            if len(parts) >= 3:
                enchantment_names[f"{parts[1]}:{'_'.join(parts[2:])}"] = value
                count += 1
        elif ":" in key:
            name_map[key] = value
            count += 1
    return count
