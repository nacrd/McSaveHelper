"""Language file loading for item names."""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class LanguageImportResult:
    """Outcome of loading language entries from a file or jar."""

    count: int
    sources: Tuple[str, ...] = ()
    locale: str = ""
    jar_path: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.count > 0


def load_language_file(
    path: Path,
    name_map: Dict[str, str],
    enchantment_names: Dict[str, str],
    namespace: str = "minecraft",
) -> int:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0
    return _load_language_dict(data, name_map, enchantment_names, namespace)


def load_custom_mapping(
    path: Path,
    name_map: Dict[str, str],
    enchantment_names: Dict[str, str],
) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
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


def save_custom_mapping(
    path: Path,
    name_map: Dict[str, str],
    enchantment_names: Dict[str, str],
    vanilla_items: Dict[str, str],
    vanilla_enchants: Dict[str, str],
) -> None:
    items = {k: v for k, v in name_map.items() if vanilla_items.get(k) != v}
    enchants = {
        k: v for k, v in enchantment_names.items() if vanilla_enchants.get(k) != v
    }
    path.write_text(
        json.dumps(
            {"items": items, "enchantments": enchants},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def normalize_locale(locale: str) -> str:
    """Normalize locale codes to Minecraft lang file form (e.g. zh_cn).

    App UI codes such as ``zh_CN`` / ``en_US`` map to jar lang stems
    ``zh_cn`` / ``en_us``. Bare ``zh`` is expanded to ``zh_cn`` because
    vanilla client jars do not ship a ``zh.json`` language file.
    """
    text = (locale or "").strip().replace("-", "_").lower()
    if not text:
        return "en_us"
    if text == "zh" or text.startswith("zh_"):
        return "zh_cn"
    if text == "en" or text.startswith("en_"):
        return "en_us"
    return text


def locale_fallbacks(locale: str) -> Tuple[str, ...]:
    """Return locale preference chain for jar language extraction.

    Always tries the UI/app-preferred locale first, then ``en_us`` as the
    only automatic fallback (never a bare language tag like ``zh``).
    """
    primary = normalize_locale(locale)
    chain: List[str] = [primary]
    if primary != "en_us":
        chain.append("en_us")
    return tuple(chain)


def list_lang_entries_in_jar(
    jar_path: Path,
    locale: str = "zh_cn",
) -> List[str]:
    """List language resource paths inside a jar for the given locale."""
    locales = locale_fallbacks(locale)
    matches: List[str] = []
    try:
        with zipfile.ZipFile(jar_path) as jar:
            names = jar.namelist()
    except (OSError, zipfile.BadZipFile):
        return []

    for loc in locales:
        matches.extend(_match_lang_paths(names, loc))
        if matches:
            break
    return matches


def extract_language_from_jar(
    jar_path: Path,
    name_map: Dict[str, str],
    enchantment_names: Dict[str, str],
    locale: str = "zh_cn",
    *,
    include_mods: bool = True,
) -> LanguageImportResult:
    """Extract and load language files from a Minecraft client or mod jar.

    Preference order for each locale in the fallback chain:
    1. ``assets/minecraft/lang/<locale>.json`` (vanilla client)
    2. ``assets/minecraft/lang/<locale>.lang`` (legacy)
    3. other ``assets/*/lang/<locale>.json|.lang`` when ``include_mods`` is True
    """
    locales = locale_fallbacks(locale)
    total = 0
    sources: List[str] = []
    used_locale = locales[0] if locales else normalize_locale(locale)

    try:
        with zipfile.ZipFile(jar_path) as jar:
            names = jar.namelist()
            for loc in locales:
                paths = _select_lang_paths(names, loc, include_mods=include_mods)
                if not paths:
                    continue
                used_locale = loc
                for entry in paths:
                    loaded = _load_jar_lang_entry(
                        jar, entry, name_map, enchantment_names
                    )
                    if loaded > 0:
                        total += loaded
                        sources.append(entry)
                # Stop at the first locale that contributed any entries.
                if total > 0:
                    break
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return LanguageImportResult(
            count=0,
            sources=(),
            locale=used_locale,
            jar_path=str(jar_path),
        )

    return LanguageImportResult(
        count=total,
        sources=tuple(sources),
        locale=used_locale,
        jar_path=str(jar_path),
    )


def extract_language_from_local_minecraft(
    name_map: Dict[str, str],
    enchantment_names: Dict[str, str],
    locale: str = "zh_cn",
    *,
    jar_path: Optional[Path] = None,
) -> LanguageImportResult:
    """Load language from a discovered or provided Minecraft client jar."""
    resolved = jar_path
    if resolved is None:
        from core.texture.client_jar import find_local_minecraft_jar

        resolved = find_local_minecraft_jar()
    if resolved is None or not Path(resolved).is_file():
        return LanguageImportResult(count=0, locale=normalize_locale(locale))
    return extract_language_from_jar(
        Path(resolved),
        name_map,
        enchantment_names,
        locale=locale,
        include_mods=True,
    )


def _select_lang_paths(
    names: Sequence[str],
    locale: str,
    *,
    include_mods: bool,
) -> List[str]:
    loc = normalize_locale(locale)
    vanilla_json = f"assets/minecraft/lang/{loc}.json"
    vanilla_lang = f"assets/minecraft/lang/{loc}.lang"
    selected: List[str] = []

    # Case-insensitive lookup while preserving original zip member names.
    lower_map = {name.lower(): name for name in names}
    for candidate in (vanilla_json, vanilla_lang):
        original = lower_map.get(candidate.lower())
        if original is not None:
            selected.append(original)

    if include_mods:
        for name in names:
            lower = name.lower()
            if name in selected:
                continue
            if lower.endswith(f"/lang/{loc}.json") or lower.endswith(
                f"/lang/{loc}.lang"
            ):
                # Skip already-added vanilla paths.
                if lower in {vanilla_json, vanilla_lang}:
                    continue
                selected.append(name)
    return selected


def _match_lang_paths(names: Sequence[str], locale: str) -> List[str]:
    return _select_lang_paths(names, locale, include_mods=True)


def _load_jar_lang_entry(
    jar: zipfile.ZipFile,
    entry: str,
    name_map: Dict[str, str],
    enchantment_names: Dict[str, str],
) -> int:
    try:
        raw_bytes = jar.read(entry)
    except KeyError:
        return 0
    raw = raw_bytes.decode("utf-8", errors="replace")
    lower = entry.lower()
    try:
        if lower.endswith(".json"):
            data = json.loads(raw)
            if not isinstance(data, dict):
                return 0
        else:
            data = _parse_lang_file(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0

    namespace = _namespace_from_lang_path(entry)
    return _load_language_dict(data, name_map, enchantment_names, namespace)


def _namespace_from_lang_path(entry: str) -> str:
    # assets/<namespace>/lang/xx_xx.json
    parts = entry.replace("\\", "/").split("/")
    if len(parts) >= 4 and parts[0].lower() == "assets":
        return parts[1] or "minecraft"
    return "minecraft"


def _parse_lang_file(raw: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _load_language_dict(
    data: Dict[str, Any],
    name_map: Dict[str, str],
    enchantment_names: Dict[str, str],
    namespace: str = "minecraft",
) -> int:
    count = 0
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
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
        elif key.startswith("item.") is False and key.count(".") == 0:
            # Rare flat keys without namespace — map under default namespace.
            name_map[f"{namespace}:{key}"] = value
            count += 1
    return count
