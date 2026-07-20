"""Shared Minecraft language/texture import orchestration for UI entry points."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from app.services.item.language_loader import normalize_locale


@dataclass(frozen=True)
class AssetImportCounts:
    """Counts returned by a unified language + texture import pass."""

    lang_count: int = 0
    texture_count: int = 0
    jar_count: int = 0
    lang_sources: int = 0


def preferred_mc_locale(app: Any) -> str:
    """Map the app UI language to a Minecraft jar lang stem (e.g. ``zh_cn``)."""
    try:
        code = ""
        i18n = getattr(app, "i18n", None)
        if i18n is not None:
            code = str(getattr(i18n, "current_language", "") or "")
        if not code:
            config = getattr(app, "config", None)
            if config is not None:
                settings = getattr(config, "get_settings", None)
                if callable(settings):
                    code = str(getattr(settings(), "language", "") or "")
                else:
                    code = str(getattr(config, "language", "") or "")
        if code:
            return normalize_locale(code)
    except (AttributeError, TypeError, ValueError):
        pass
    except Exception:
        # Best-effort: locale lookup must not block import.
        pass
    return "zh_cn"


def configured_minecraft_dir(app: Any) -> Optional[Path]:
    """Resolve the configured ``.minecraft`` directory from app config, if any."""
    try:
        config = getattr(app, "config", None)
        if config is None:
            return None
        getter = getattr(config, "get_minecraft_dir", None)
        raw = ""
        if callable(getter):
            raw = str(getter() or "")
        else:
            settings = getattr(config, "get_settings", None)
            if callable(settings):
                raw = str(getattr(settings(), "minecraft_dir", "") or "")
        text = raw.strip()
        return Path(text) if text else None
    except (AttributeError, TypeError, ValueError, OSError):
        return None
    except Exception:
        return None


def current_save_start_path(app: Any) -> Optional[Path]:
    """Resolve the current save path as a discovery start point, if set."""
    try:
        value = getattr(app, "current_save_path", None)
        if callable(value):
            try:
                value = value()
            except TypeError:
                pass
        text = str(value or "").strip()
        return Path(text) if text else None
    except (AttributeError, TypeError, ValueError, OSError):
        return None
    except Exception:
        return None


def pick_asset_sources(app: Any, title: str) -> list[Path]:
    """Pick JSON and/or JAR sources (multi-select when the host supports it)."""
    file_types = [
        ("JSON / JAR", "*.json;*.jar"),
        ("JSON (*.json)", "*.json"),
        ("JAR (*.jar)", "*.jar"),
    ]
    pick_files = getattr(app, "pick_files", None)
    if callable(pick_files):
        selected = pick_files(title=title, file_types=file_types)
        if selected:
            return [Path(item) for item in selected if item]
        return []
    path = app.pick_file(title=title, file_types=file_types)
    return [Path(path)] if path else []


def import_assets_from_sources(
    *,
    item_service: Any,
    texture_service: Any,
    paths: Sequence[Path],
    locale: str,
    configured_dir: Optional[Path] = None,
    start_path: Optional[Path] = None,
    empty_paths_fallback: bool = False,
    empty_jar_results_fallback: bool = False,
) -> AssetImportCounts:
    """Import language names and textures from JSON/JAR paths.

    Args:
        item_service: ``ItemService`` (or compatible) for language loading.
        texture_service: ``TextureService`` (or compatible) for jar textures.
        paths: Selected source files; may be empty when ``empty_paths_fallback``.
        locale: Preferred Minecraft lang stem (e.g. ``zh_cn``).
        configured_dir: Optional configured ``.minecraft`` root.
        start_path: Optional path used to infer ``.minecraft`` (usually a save).
        empty_paths_fallback: When no files are selected, import from local client.
        empty_jar_results_fallback: When jars were selected but yielded nothing,
            try local client language as an extra source.

    Returns:
        AssetImportCounts: Aggregated import counts (no UI side effects).
    """
    path_list = [Path(p) for p in paths if p]
    if not path_list and empty_paths_fallback:
        return _import_from_local_minecraft(
            item_service=item_service,
            texture_service=texture_service,
            locale=locale,
            configured_dir=configured_dir,
            start_path=start_path,
            with_textures=True,
        )

    lang_count = 0
    texture_count = 0
    jar_count = 0
    lang_sources = 0
    json_files = [p for p in path_list if p.suffix.lower() == ".json"]
    jar_files = [p for p in path_list if p.suffix.lower() == ".jar"]

    for json_path in json_files:
        lang_count += int(item_service.load_language_file(json_path) or 0)

    if jar_files:
        for jar_path in jar_files:
            result = item_service.extract_language_from_jar_detailed(
                jar_path,
                locale=locale,
            )
            count = int(getattr(result, "count", 0) or 0)
            if count > 0:
                lang_count += count
                sources = getattr(result, "sources", ()) or ()
                lang_sources += len(sources)
                jar_count += 1
        tex = texture_service.import_textures_from_jars(jar_files)
        texture_count = int(getattr(tex, "extracted", 0) or 0)
        tex_jars = int(getattr(tex, "jars", 0) or 0)
        if tex_jars and not jar_count:
            jar_count = tex_jars
        elif tex_jars:
            jar_count = max(jar_count, tex_jars)

    if (
        lang_count == 0
        and texture_count == 0
        and jar_files
        and empty_jar_results_fallback
    ):
        local = item_service.import_language_from_local_minecraft(
            locale=locale,
            configured_dir=configured_dir,
            start_path=start_path,
        )
        local_count = int(getattr(local, "count", 0) or 0)
        if local_count > 0:
            lang_count = local_count
            if getattr(local, "jar_path", None):
                jar_count = max(jar_count, 1)
            lang_sources = max(lang_sources, 1)

    return AssetImportCounts(
        lang_count=lang_count,
        texture_count=texture_count,
        jar_count=jar_count,
        lang_sources=lang_sources,
    )


def _import_from_local_minecraft(
    *,
    item_service: Any,
    texture_service: Any,
    locale: str,
    configured_dir: Optional[Path],
    start_path: Optional[Path],
    with_textures: bool,
) -> AssetImportCounts:
    result = item_service.import_language_from_local_minecraft(
        locale=locale,
        configured_dir=configured_dir,
        start_path=start_path,
    )
    lang_count = int(getattr(result, "count", 0) or 0)
    texture_count = 0
    jar_count = 0
    jar_path_raw = getattr(result, "jar_path", None)
    if (
        with_textures
        and jar_path_raw
        and str(jar_path_raw).lower().endswith(".jar")
    ):
        jar_path = Path(jar_path_raw)
        tex = texture_service.import_textures_from_jars([jar_path])
        texture_count = int(getattr(tex, "extracted", 0) or 0)
        jar_count = max(1, int(getattr(tex, "jars", 0) or 0))
        set_jar = getattr(texture_service, "set_minecraft_jar", None)
        if callable(set_jar):
            set_jar(jar_path)
    elif jar_path_raw:
        jar_count = 1
    return AssetImportCounts(
        lang_count=lang_count,
        texture_count=texture_count,
        jar_count=jar_count,
        lang_sources=1 if lang_count else 0,
    )
