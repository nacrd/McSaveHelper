"""Language file loading for item and enchantment display names.

Supports JSON lang files, legacy ``.lang`` files, client/mod jars, and modern
``.minecraft/assets`` index + object storage.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

NameMap = Dict[str, str]
EnchantMap = Dict[str, str]


@dataclass(frozen=True)
class LanguageImportResult:
    """Outcome of loading language entries from a file, jar, or assets.

    Attributes:
        count: Number of name/enchantment entries applied to the maps.
        sources: Human-readable resource paths that contributed entries.
        locale: Locale stem actually used (may be a fallback such as ``en_us``).
        jar_path: Source jar path, or assets index path when loading objects.
    """

    count: int
    sources: Tuple[str, ...] = ()
    locale: str = ""
    jar_path: Optional[str] = None

    @property
    def ok(self) -> bool:
        """Whether at least one entry was imported."""
        return self.count > 0


@dataclass(frozen=True)
class _LangAssetHit:
    """Resolved vanilla lang object under ``assets/objects``."""

    locale: str
    asset_key: str
    digest: str
    object_path: Path
    index_path: Path


def load_language_file(
    path: Path,
    name_map: NameMap,
    enchantment_names: EnchantMap,
    namespace: str = "minecraft",
) -> int:
    """Load a Minecraft language JSON file into the given maps.

    Args:
        path: Path to a ``*.json`` language file.
        name_map: Mutable item/block id → display name map (updated in place).
        enchantment_names: Mutable enchantment id → display name map.
        namespace: Default namespace for bare keys without ``:`` or dotted form.

    Returns:
        int: Number of entries applied; ``0`` when the file is missing or invalid.
    """
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
    name_map: NameMap,
    enchantment_names: EnchantMap,
) -> int:
    """Load a custom JSON mapping of items and/or enchantments.

    Accepts either ``{"items": {...}, "enchantments": {...}}`` or a flat
    items object at the root.

    Args:
        path: Custom mapping JSON path.
        name_map: Mutable item map updated in place.
        enchantment_names: Mutable enchantment map updated in place.

    Returns:
        int: Number of entries applied; ``0`` on I/O or parse failure.
    """
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
    name_map: NameMap,
    enchantment_names: EnchantMap,
    vanilla_items: NameMap,
    vanilla_enchants: EnchantMap,
) -> None:
    """Write non-vanilla item/enchantment overrides to JSON.

    Args:
        path: Destination file path.
        name_map: Current full item name map.
        enchantment_names: Current full enchantment name map.
        vanilla_items: Built-in item defaults used to detect overrides.
        vanilla_enchants: Built-in enchantment defaults.

    Raises:
        OSError: If the destination cannot be written.
    """
    items = {k: v for k, v in name_map.items() if vanilla_items.get(k) != v}
    enchants = {
        k: v
        for k, v in enchantment_names.items()
        if vanilla_enchants.get(k) != v
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
    """Normalize locale codes to Minecraft lang file form (e.g. ``zh_cn``).

    App UI codes such as ``zh_CN`` / ``en_US`` map to jar/assets stems
    ``zh_cn`` / ``en_us``. Bare ``zh`` expands to ``zh_cn``.

    Args:
        locale: UI or Minecraft locale string; empty/None-like becomes ``en_us``.

    Returns:
        str: Lowercase underscore form suitable for lang file stems.
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

    Always tries the UI/app-preferred locale first, then ``en_us`` when needed.

    Args:
        locale: Preferred locale (any form accepted by :func:`normalize_locale`).

    Returns:
        tuple[str, ...]: Ordered locale stems to try.
    """
    primary = normalize_locale(locale)
    if primary == "en_us":
        return (primary,)
    return (primary, "en_us")


def list_lang_entries_in_jar(
    jar_path: Path,
    locale: str = "zh_cn",
) -> List[str]:
    """List language resource paths inside a jar for the given locale.

    Args:
        jar_path: Path to a client or mod jar.
        locale: Preferred locale stem or UI code.

    Returns:
        list[str]: Jar entry paths for the first matching locale in the
        fallback chain; empty when the jar is unreadable or has no lang files.
    """
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
    name_map: NameMap,
    enchantment_names: EnchantMap,
    locale: str = "zh_cn",
    *,
    include_mods: bool = True,
) -> LanguageImportResult:
    """Extract language files from a jar into the given maps.

    For modern clients (1.8+), vanilla lang JSON is usually *not* inside the
    client jar. Prefer :func:`extract_language_from_local_minecraft` which also
    resolves ``.minecraft/assets/indexes`` + ``objects``.

    This function still handles:

    - legacy ``assets/minecraft/lang/*.lang`` inside old jars
    - mod jars that still package ``assets/*/lang/*.json``
    - rare client jars that still embed lang files

    Args:
        jar_path: Path to the jar file.
        name_map: Mutable item/block name map.
        enchantment_names: Mutable enchantment name map.
        locale: Preferred locale.
        include_mods: When True, also load non-vanilla ``assets/*/lang`` entries.

    Returns:
        LanguageImportResult: Counts and sources; ``count`` is 0 on failure.
    """
    locales = locale_fallbacks(locale)
    total = 0
    sources: List[str] = []
    used_locale = locales[0]

    try:
        with zipfile.ZipFile(jar_path) as jar:
            total, sources, used_locale = _load_locales_from_jar(
                jar,
                locales=locales,
                include_mods=include_mods,
                name_map=name_map,
                enchantment_names=enchantment_names,
            )
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


def _load_locales_from_jar(
    jar: zipfile.ZipFile,
    *,
    locales: Sequence[str],
    include_mods: bool,
    name_map: NameMap,
    enchantment_names: EnchantMap,
) -> tuple[int, List[str], str]:
    names = jar.namelist()
    total = 0
    sources: List[str] = []
    used_locale = locales[0]
    for loc in locales:
        paths = _select_lang_paths(
            names, loc, include_mods=include_mods
        )
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
    return total, sources, used_locale


def extract_language_from_local_minecraft(
    name_map: NameMap,
    enchantment_names: EnchantMap,
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
    from core.texture.client_jar import discover_minecraft_directory

    mc_dir = discover_minecraft_directory(
        configured=(
            configured_dir if configured_dir is not None else minecraft_dir
        ),
        start_path=start_path,
        jar_path=jar_path,
    )
    used_locale = locale_fallbacks(locale)[0]
    assets_result = _try_import_from_assets(
        name_map,
        enchantment_names,
        locale=locale,
        used_locale=used_locale,
        mc_dir=mc_dir,
    )
    if assets_result is not None:
        return assets_result
    return _try_import_from_client_jar(
        name_map,
        enchantment_names,
        locale=locale,
        used_locale=used_locale,
        jar_path=jar_path,
        mc_dir=mc_dir,
    )


def _try_import_from_assets(
    name_map: NameMap,
    enchantment_names: EnchantMap,
    *,
    locale: str,
    used_locale: str,
    mc_dir: Optional[Path],
) -> Optional[LanguageImportResult]:
    if mc_dir is None:
        return None
    assets_result = extract_language_from_minecraft_assets(
        name_map,
        enchantment_names,
        locale=locale,
        minecraft_dir=mc_dir,
    )
    if assets_result.count > 0:
        return assets_result
    if assets_result.sources or assets_result.locale:
        return assets_result
    return LanguageImportResult(count=0, locale=used_locale)


def _try_import_from_client_jar(
    name_map: NameMap,
    enchantment_names: EnchantMap,
    *,
    locale: str,
    used_locale: str,
    jar_path: Optional[Path],
    mc_dir: Optional[Path],
) -> LanguageImportResult:
    from core.texture.client_jar import find_local_minecraft_jar

    resolved = jar_path
    if resolved is None and mc_dir is not None:
        resolved = find_local_minecraft_jar(mc_dir)
    if resolved is None:
        resolved = find_local_minecraft_jar()
    if resolved is None or not Path(resolved).is_file():
        return LanguageImportResult(count=0, locale=used_locale)
    return extract_language_from_jar(
        Path(resolved),
        name_map,
        enchantment_names,
        locale=locale,
        include_mods=True,
    )


def extract_language_from_minecraft_assets(
    name_map: NameMap,
    enchantment_names: EnchantMap,
    locale: str = "zh_cn",
    *,
    minecraft_dir: Path,
) -> LanguageImportResult:
    """Load vanilla lang from ``.minecraft/assets`` index + objects.

    Modern clients (1.8+) store language files hashed under
    ``assets/objects/<first two hash chars>/<full hash>``, referenced by
    ``assets/indexes/<version>.json`` as ``minecraft/lang/zh_cn.json``.

    Args:
        name_map: Mutable item/block name map.
        enchantment_names: Mutable enchantment name map.
        locale: Preferred locale.
        minecraft_dir: ``.minecraft`` (or equivalent) data directory.

    Returns:
        LanguageImportResult: Loaded count and object source; empty when missing.
    """
    preferred = locale_fallbacks(locale)[0]
    for hit in _iter_lang_asset_hits(minecraft_dir, locale):
        loaded = _load_language_object_file(
            hit.object_path,
            name_map,
            enchantment_names,
            namespace="minecraft",
            as_lang=hit.asset_key.endswith(".lang"),
        )
        if loaded > 0:
            return LanguageImportResult(
                count=loaded,
                sources=(
                    f"assets/objects/{hit.digest[:2]}/{hit.digest}",
                ),
                locale=hit.locale,
                jar_path=str(hit.index_path),
            )
    return LanguageImportResult(count=0, locale=preferred)


def resolve_lang_object_path(
    minecraft_dir: Path,
    locale: str = "zh_cn",
) -> Optional[Path]:
    """Resolve the on-disk assets object path for a vanilla lang file.

    Args:
        minecraft_dir: ``.minecraft`` data directory.
        locale: Preferred locale.

    Returns:
        Path | None: First existing hashed object path, or ``None`` if unresolved.
    """
    for hit in _iter_lang_asset_hits(minecraft_dir, locale):
        return hit.object_path
    return None


def _iter_lang_asset_hits(
    minecraft_dir: Path,
    locale: str,
) -> Iterator[_LangAssetHit]:
    """Yield existing vanilla lang object hits in locale/index preference order.

    Newer asset indexes (by mtime) are tried first; within an index, locales
    follow :func:`locale_fallbacks`, then ``.json`` before ``.lang``.
    """
    locales = locale_fallbacks(locale)
    indexes_dir = minecraft_dir / "assets" / "indexes"
    objects_dir = minecraft_dir / "assets" / "objects"
    if not indexes_dir.is_dir() or not objects_dir.is_dir():
        return

    for index_path in _list_asset_index_files(indexes_dir):
        objects_map = _load_asset_index_objects(index_path)
        if not objects_map:
            continue
        for loc in locales:
            for asset_key in (
                f"minecraft/lang/{loc}.json",
                f"minecraft/lang/{loc}.lang",
            ):
                hit = _resolve_object_hit(
                    objects_map,
                    asset_key,
                    loc,
                    objects_dir,
                    index_path,
                )
                if hit is not None:
                    yield hit


def _resolve_object_hit(
    objects_map: Dict[str, Any],
    asset_key: str,
    locale: str,
    objects_dir: Path,
    index_path: Path,
) -> Optional[_LangAssetHit]:
    """Map an assets index key to a readable object file, if present."""
    entry = objects_map.get(asset_key)
    if not isinstance(entry, dict):
        return None
    digest = str(entry.get("hash", "") or "").strip().lower()
    if len(digest) < 3:
        return None
    object_path = objects_dir / digest[:2] / digest
    if not object_path.is_file():
        return None
    return _LangAssetHit(
        locale=locale,
        asset_key=asset_key,
        digest=digest,
        object_path=object_path,
        index_path=index_path,
    )


def _list_asset_index_files(indexes_dir: Path) -> List[Path]:
    """List asset index JSON files, newest mtime first."""
    try:
        files = [path for path in indexes_dir.glob("*.json") if path.is_file()]
    except OSError:
        return []
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def _load_asset_index_objects(index_path: Path) -> Dict[str, Any]:
    """Load the ``objects`` map from an assets index file."""
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
    name_map: NameMap,
    enchantment_names: EnchantMap,
    *,
    namespace: str,
    as_lang: bool,
) -> int:
    """Load a hashed assets object file as JSON or legacy ``.lang`` text."""
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
    """Pick jar entry paths for a locale, vanilla first then optional mods."""
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
    """Match jar lang paths including mod namespaces."""
    return _select_lang_paths(names, locale, include_mods=True)


def _load_jar_lang_entry(
    jar: zipfile.ZipFile,
    entry: str,
    name_map: NameMap,
    enchantment_names: EnchantMap,
) -> int:
    """Read and apply one jar language entry."""
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
    """Infer resource namespace from an ``assets/<ns>/lang/...`` path."""
    parts = entry.replace("\\", "/").split("/")
    if len(parts) >= 4 and parts[0].lower() == "assets":
        return parts[1] or "minecraft"
    return "minecraft"


def _parse_lang_file(raw: str) -> Dict[str, str]:
    """Parse legacy key=value ``.lang`` text into a dictionary."""
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
    name_map: NameMap,
    enchantment_names: EnchantMap,
    namespace: str = "minecraft",
) -> int:
    """Merge a language dictionary into name maps.

    Supports dotted Minecraft keys (``item.``/``block.``/``enchantment.``),
    already-namespaced ids (``ns:id``), and bare ids under ``namespace``.
    """
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
                enchantment_names[
                    f"{parts[1]}:{'_'.join(parts[2:])}"
                ] = value
                count += 1
        elif ":" in key:
            name_map[key] = value
            count += 1
        elif key.count(".") == 0:
            name_map[f"{namespace}:{key}"] = value
            count += 1
    return count
