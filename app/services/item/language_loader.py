"""Language file loading for item names."""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class LanguageImportResult:
    """Outcome of loading language entries from a file or jar/assets."""

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

    App UI codes such as ``zh_CN`` / ``en_US`` map to jar/assets stems
    ``zh_cn`` / ``en_us``. Bare ``zh`` expands to ``zh_cn``.
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
    """Return locale preference chain for language extraction.

    Always tries the UI/app-preferred locale first, then ``en_us``.
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
    """Extract language files from a jar.

    For modern clients (1.8+), vanilla lang JSON is usually *not* inside the
    client jar. Prefer :func:`extract_language_from_local_minecraft` which also
    resolves ``.minecraft/assets/indexes`` + ``objects``.

    This function still handles:
    - legacy ``assets/minecraft/lang/*.lang`` inside old jars
    - mod jars that still package ``assets/*/lang/*.json``
    - rare client jars that still embed lang files
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
    minecraft_dir: Optional[Path] = None,
    start_path: Optional[Path] = None,
    configured_dir: Optional[Path] = None,
) -> LanguageImportResult:
    """Load language from a local Minecraft install.

    Resolution order:
    1. Resolve data dir from config / jar / save path / platform default
    2. Modern assets: ``assets/indexes/*.json`` → ``assets/objects/<hh>/<hash>``
    3. Client jar embedded lang (legacy ``.lang`` or rare embeds)
    """
    from core.texture.client_jar import (
        discover_minecraft_directory,
        find_local_minecraft_jar,
    )

    mc_dir = discover_minecraft_directory(
        configured=configured_dir if configured_dir is not None else minecraft_dir,
        start_path=start_path,
        jar_path=jar_path,
    )
    locales = locale_fallbacks(locale)
    used_locale = locales[0]

    assets_result = LanguageImportResult(count=0, locale=used_locale)
    if mc_dir is not None:
        assets_result = extract_language_from_minecraft_assets(
            name_map,
            enchantment_names,
            locale=locale,
            minecraft_dir=mc_dir,
        )
        if assets_result.count > 0:
            return assets_result

    # Client jar (legacy .lang or embedded JSON).
    resolved = jar_path
    if resolved is None and mc_dir is not None:
        resolved = find_local_minecraft_jar(mc_dir)
    if resolved is None:
        resolved = find_local_minecraft_jar()
    jar_result = LanguageImportResult(count=0, locale=used_locale)
    if resolved is not None and Path(resolved).is_file():
        jar_result = extract_language_from_jar(
            Path(resolved),
            name_map,
            enchantment_names,
            locale=locale,
            include_mods=True,
        )
        if jar_result.count > 0:
            return jar_result

    if assets_result.sources or assets_result.locale:
        return assets_result
    return jar_result


def extract_language_from_minecraft_assets(
    name_map: Dict[str, str],
    enchantment_names: Dict[str, str],
    locale: str = "zh_cn",
    *,
    minecraft_dir: Path,
) -> LanguageImportResult:
    """Load vanilla lang from ``.minecraft/assets`` index + objects.

    Modern clients (1.8+) store language files hashed under
    ``assets/objects/<first two hash chars>/<full hash>``, referenced by
    ``assets/indexes/<version>.json`` as ``minecraft/lang/zh_cn.json``.
    """
    locales = locale_fallbacks(locale)
    indexes_dir = minecraft_dir / "assets" / "indexes"
    objects_dir = minecraft_dir / "assets" / "objects"
    if not indexes_dir.is_dir() or not objects_dir.is_dir():
        return LanguageImportResult(
            count=0,
            locale=locales[0] if locales else normalize_locale(locale),
        )

    index_paths = _list_asset_index_files(indexes_dir)
    if not index_paths:
        return LanguageImportResult(
            count=0,
            locale=locales[0] if locales else normalize_locale(locale),
        )

    for index_path in index_paths:
        objects_map = _load_asset_index_objects(index_path)
        if not objects_map:
            continue
        for loc in locales:
            for asset_key in (
                f"minecraft/lang/{loc}.json",
                f"minecraft/lang/{loc}.lang",
            ):
                entry = objects_map.get(asset_key)
                if not isinstance(entry, dict):
                    continue
                digest = str(entry.get("hash", "") or "").strip().lower()
                if len(digest) < 3:
                    continue
                object_path = objects_dir / digest[:2] / digest
                if not object_path.is_file():
                    continue
                loaded = _load_language_object_file(
                    object_path,
                    name_map,
                    enchantment_names,
                    namespace="minecraft",
                    as_lang=asset_key.endswith(".lang"),
                )
                if loaded > 0:
                    return LanguageImportResult(
                        count=loaded,
                        sources=(f"assets/objects/{digest[:2]}/{digest}",),
                        locale=loc,
                        jar_path=str(index_path),
                    )
    return LanguageImportResult(
        count=0,
        locale=locales[0] if locales else normalize_locale(locale),
    )


def resolve_lang_object_path(
    minecraft_dir: Path,
    locale: str = "zh_cn",
) -> Optional[Path]:
    """Resolve the on-disk assets object path for a vanilla lang file."""
    locales = locale_fallbacks(locale)
    indexes_dir = minecraft_dir / "assets" / "indexes"
    objects_dir = minecraft_dir / "assets" / "objects"
    if not indexes_dir.is_dir() or not objects_dir.is_dir():
        return None
    for index_path in _list_asset_index_files(indexes_dir):
        objects_map = _load_asset_index_objects(index_path)
        if not objects_map:
            continue
        for loc in locales:
            for asset_key in (
                f"minecraft/lang/{loc}.json",
                f"minecraft/lang/{loc}.lang",
            ):
                entry = objects_map.get(asset_key)
                if not isinstance(entry, dict):
                    continue
                digest = str(entry.get("hash", "") or "").strip().lower()
                if len(digest) < 3:
                    continue
                object_path = objects_dir / digest[:2] / digest
                if object_path.is_file():
                    return object_path
    return None


def _list_asset_index_files(indexes_dir: Path) -> List[Path]:
    try:
        files = [path for path in indexes_dir.glob("*.json") if path.is_file()]
    except OSError:
        return []
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def _load_asset_index_objects(index_path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    objects = payload.get("objects")
    if not isinstance(objects, dict):
        return {}
    return objects


def _load_language_object_file(
    path: Path,
    name_map: Dict[str, str],
    enchantment_names: Dict[str, str],
    *,
    namespace: str,
    as_lang: bool,
) -> int:
    try:
        raw = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return 0
    try:
        if as_lang:
            data = _parse_lang_file(raw)
        else:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return 0
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0
    return _load_language_dict(data, name_map, enchantment_names, namespace)


def _select_lang_paths(
    names: Sequence[str],
    locale: str,
    *,
    include_mods: bool,
) -> List[str]:
    loc = normalize_locale(locale)
    stems = {
        loc,
        loc.lower(),
        loc.upper(),
        f"{loc[:2]}_{loc[3:].upper()}" if "_" in loc else loc,
    }
    selected: List[str] = []
    lower_map = {name.lower().replace("\\", "/"): name for name in names}

    vanilla_candidates: List[str] = []
    for stem in stems:
        vanilla_candidates.extend(
            (
                f"assets/minecraft/lang/{stem}.json",
                f"assets/minecraft/lang/{stem}.lang",
            )
        )
    for candidate in vanilla_candidates:
        original = lower_map.get(candidate.lower())
        if original is not None and original not in selected:
            selected.append(original)

    if include_mods:
        for lower, original in lower_map.items():
            if original in selected:
                continue
            if "/lang/" not in lower:
                continue
            if not (lower.endswith(".json") or lower.endswith(".lang")):
                continue
            if any(
                lower.endswith(f"/lang/{stem}.json")
                or lower.endswith(f"/lang/{stem}.lang")
                for stem in stems
            ):
                selected.append(original)
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
        # json.loads already unescapes \\uXXXX sequences.
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
        elif key.count(".") == 0:
            name_map[f"{namespace}:{key}"] = value
            count += 1
    return count
