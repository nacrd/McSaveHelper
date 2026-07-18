"""Read mod-loader metadata preserved in Java Edition ``level.dat`` files."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

from .models import ModInfo


_MOD_LIST_KEYS = {"modlist", "mods", "loadingmodlist"}
_SYSTEM_MOD_LOADERS = {
    "forge": "Forge",
    "neoforge": "NeoForge",
    "fabric-loader": "Fabric Loader",
    "fabricloader": "Fabric Loader",
    "quilt-loader": "Quilt Loader",
    "quilt_loader": "Quilt Loader",
}
_SYSTEM_MOD_IDS = {"minecraft", "mcp", "fml", "java", *_SYSTEM_MOD_LOADERS}


@dataclass(frozen=True)
class ModMetadata:
    """Normalized mod information with an explicit-list completeness marker."""

    mods: tuple[ModInfo, ...]
    loaders: tuple[str, ...]
    list_complete: bool = False


def detect_mod_metadata(
    root: Mapping[str, Any],
    data: Mapping[str, Any],
    data_packs: Optional[Mapping[str, list[str]]] = None,
    server_brands: Optional[Iterable[Any]] = None,
) -> ModMetadata:
    """Detect explicit Forge lists and conservative loader/datapack hints."""
    mods: dict[str, ModInfo] = {}
    loaders: set[str] = set()
    explicit_list_found = False

    for container_name in ("FML", "fml"):
        for parent in (data, root):
            container = parent.get(container_name)
            if not isinstance(container, Mapping):
                continue
            _add_loader(loaders, "Forge")
            for collection in _find_mod_collections(container):
                explicit_list_found = True
                for mod in _parse_mod_collection(collection):
                    _add_mod(mods, loaders, mod)

    enabled_packs = (data_packs or {}).get("enabled", [])
    for pack_name in enabled_packs:
        value = str(pack_name).strip()
        if not value.lower().startswith("mod:"):
            continue
        mod_id = value.split(":", 1)[1].strip()
        if mod_id:
            _add_mod(mods, loaders, ModInfo(mod_id=mod_id))

    for brand in server_brands or ():
        normalized = str(brand).casefold()
        if "neoforge" in normalized:
            _add_loader(loaders, "NeoForge")
        elif "forge" in normalized:
            _add_loader(loaders, "Forge")
        if "fabric" in normalized:
            _add_loader(loaders, "Fabric Loader")
        if "quilt" in normalized:
            _add_loader(loaders, "Quilt Loader")

    return ModMetadata(
        mods=tuple(sorted(mods.values(), key=lambda item: item.mod_id.casefold())),
        loaders=tuple(sorted(loaders)),
        list_complete=explicit_list_found,
    )


def _find_mod_collections(value: Mapping[str, Any], depth: int = 0) -> list[Any]:
    if depth > 3:
        return []
    collections: list[Any] = []
    for key, child in value.items():
        normalized_key = str(key).replace("_", "").replace("-", "").casefold()
        if normalized_key in _MOD_LIST_KEYS:
            collections.append(child)
        elif isinstance(child, Mapping):
            collections.extend(_find_mod_collections(child, depth + 1))
    return collections


def _parse_mod_collection(collection: Any) -> list[ModInfo]:
    if isinstance(collection, Mapping):
        parsed_mapping: list[ModInfo] = []
        for mod_id, value in collection.items():
            if isinstance(value, Mapping):
                entry = _parse_mod_entry(value, fallback_id=str(mod_id))
            else:
                entry = ModInfo(mod_id=str(mod_id), version=_clean_text(value))
            if entry is not None:
                parsed_mapping.append(entry)
        return parsed_mapping

    if isinstance(collection, (str, bytes)) or not isinstance(collection, Iterable):
        return []

    parsed: list[ModInfo] = []
    for value in collection:
        if isinstance(value, Mapping):
            entry = _parse_mod_entry(value)
        else:
            mod_id = _clean_text(value)
            entry = ModInfo(mod_id=mod_id) if mod_id else None
        if entry is not None:
            parsed.append(entry)
    return parsed


def _parse_mod_entry(
    entry: Mapping[str, Any],
    fallback_id: str = "",
) -> Optional[ModInfo]:
    normalized = {
        str(key).replace("_", "").replace("-", "").casefold(): value
        for key, value in entry.items()
    }
    mod_id = _first_text(normalized, "modid", "id") or fallback_id.strip()
    if not mod_id:
        return None
    return ModInfo(
        mod_id=mod_id,
        version=_first_text(normalized, "modversion", "version"),
        name=_first_text(normalized, "modname", "displayname", "name"),
    )


def _first_text(values: Mapping[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        cleaned = _clean_text(values.get(key))
        if cleaned:
            return cleaned
    return None


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _add_mod(
    mods: dict[str, ModInfo],
    loaders: set[str],
    mod: ModInfo,
) -> None:
    mod_id = mod.mod_id.strip()
    if not mod_id:
        return
    normalized_id = mod_id.casefold()
    loader_name = _SYSTEM_MOD_LOADERS.get(normalized_id)
    if loader_name:
        _add_loader(loaders, loader_name, mod.version)
        return
    if normalized_id in _SYSTEM_MOD_IDS:
        return

    current = mods.get(normalized_id)
    if current is None:
        mods[normalized_id] = ModInfo(
            mod_id=mod_id,
            version=mod.version,
            name=mod.name,
        )
        return
    mods[normalized_id] = ModInfo(
        mod_id=current.mod_id,
        version=current.version or mod.version,
        name=current.name or mod.name,
    )


def _add_loader(
    loaders: set[str],
    loader_name: str,
    version: Optional[str] = None,
) -> None:
    prefix = f"{loader_name} "
    versioned = {value for value in loaders if value.startswith(prefix)}
    if version:
        loaders.discard(loader_name)
        loaders.difference_update(versioned)
        loaders.add(f"{loader_name} {version}")
    elif not versioned:
        loaders.add(loader_name)
