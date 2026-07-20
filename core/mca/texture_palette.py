"""Optional Minecraft block-texture colour provider.

The map renderer must also work on machines without a Minecraft installation,
so this module never downloads assets and always returns ``None`` when a local
client JAR is unavailable.  When a JAR is present, the average of the top
texture is used as a closer approximation of Xaero/JourneyMap's material
colour before the conservative name-based palette is consulted.
"""
from __future__ import annotations

import io
import os
import threading
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, Tuple, cast

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is an application dependency
    Image = None  # type: ignore[assignment]

Color = Tuple[int, int, int]

_JAR_ENV = "MCSAVEHELPER_MINECRAFT_JAR"
_TEXTURE_ROOT = "assets/minecraft/textures/block/"
_lock = threading.RLock()
_jar_path: Optional[Path] = None
_archive: Optional[zipfile.ZipFile] = None
_archive_path: Optional[Path] = None
_archive_names: Optional[frozenset[str]] = None
_lookup_attempted = False
_palette_signature: Optional[str] = None


def set_texture_jar(path: Optional[Path | str]) -> None:
    """Set or clear the local client JAR used by the provider.

    This is intentionally explicit so a UI/settings layer can point at a
    resource pack without coupling the core renderer to application state.
    """
    global _jar_path, _archive, _archive_path, _archive_names
    global _lookup_attempted, _palette_signature
    with _lock:
        if _archive is not None:
            try:
                _archive.close()
            except Exception:
                pass
        _archive = None
        _archive_path = None
        _archive_names = None
        _jar_path = Path(path).expanduser() if path else None
        _lookup_attempted = path is not None
        _palette_signature = None
        _average_texture.cache_clear()


def _discover_jar() -> Optional[Path]:
    configured = os.environ.get(_JAR_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path
    try:
        from core.texture.client_jar import find_local_minecraft_jar

        discovered = find_local_minecraft_jar()
        if discovered is not None and discovered.is_file():
            return discovered
    except Exception:
        pass
    return None


def _get_archive() -> Optional[zipfile.ZipFile]:
    global _jar_path, _archive, _archive_path, _lookup_attempted
    with _lock:
        if _archive is not None:
            return _archive
        if not _lookup_attempted:
            _jar_path = _discover_jar()
            _lookup_attempted = True
        if _jar_path is None or not _jar_path.is_file():
            return None
        try:
            _archive = zipfile.ZipFile(_jar_path)
            _archive_path = _jar_path
            return _archive
        except (OSError, zipfile.BadZipFile):
            _jar_path = None
            return None


def _block_path(block_id: str) -> str:
    return block_id.strip().lower().rsplit(":", 1)[-1]


def _texture_candidates(block_path: str) -> tuple[str, ...]:
    """Return likely top-face textures, ordered from specific to generic."""
    candidates = [f"{_TEXTURE_ROOT}{block_path}.png"]
    # Grass and a few layered blocks have a dedicated top texture.  Prefer it
    # over the side texture because the map is a bird's-eye projection.
    candidates.insert(0, f"{_TEXTURE_ROOT}{block_path}_top.png")
    if block_path in {"water", "bubble_column"}:
        candidates.insert(0, f"{_TEXTURE_ROOT}water_still.png")
    elif block_path in {"lava"}:
        candidates.insert(0, f"{_TEXTURE_ROOT}lava_still.png")

    # Structural variants usually reuse the base block texture.
    parts = block_path.split("_")
    suffixes = {
        "button", "door", "fence", "gate", "log", "planks", "pressure",
        "plate", "sign", "slab", "stairs", "trapdoor", "wall", "wood",
    }
    while parts and parts[-1] in suffixes:
        parts.pop()
        if parts:
            base = "_".join(parts)
            candidates.extend(
                (
                    f"{_TEXTURE_ROOT}{base}_top.png",
                    f"{_TEXTURE_ROOT}{base}.png",
                )
            )
    # Preserve insertion order while removing duplicate paths.
    return tuple(dict.fromkeys(candidates))


@lru_cache(maxsize=1024)
def _average_texture(block_path: str) -> Optional[Color]:
    archive = _get_archive()
    if archive is None or Image is None:
        return None
    try:
        texture_name = _find_texture_name(archive, block_path)
        if texture_name is None:
            return None
        with Image.open(io.BytesIO(archive.read(texture_name))) as image:
            return _average_image_pixels(image)
    except Exception:
        return None


def _find_texture_name(archive: zipfile.ZipFile, block_path: str) -> Optional[str]:
    global _archive_names
    with _lock:
        if _archive_names is None:
            _archive_names = frozenset(archive.namelist())
        names = _archive_names
    return next(
        (candidate for candidate in _texture_candidates(block_path) if candidate in names),
        None,
    )


def _average_image_pixels(image: Any) -> Optional[Color]:
    rgba = image.convert("RGBA")
    try:
        pixels = rgba.load()
        if pixels is None:
            return None
        width, height = rgba.size
        step = max(1, min(4, min(width, height) // 8 or 1))
        totals = _accumulate_visible_pixels(pixels, width, height, step)
        return _color_from_weighted_totals(totals)
    finally:
        rgba.close()


def _accumulate_visible_pixels(
    pixels: Any,
    width: int,
    height: int,
    step: int,
) -> Tuple[float, float, float, float]:
    red = green = blue = weight = 0.0
    for y in range(0, height, step):
        for x in range(0, width, step):
            pixel = cast(Tuple[int, int, int, int], cast(Any, pixels[x, y]))
            pixel_red, pixel_green, pixel_blue, alpha = pixel
            if alpha <= 10:
                continue
            factor = alpha / 255.0
            red += pixel_red * factor
            green += pixel_green * factor
            blue += pixel_blue * factor
            weight += factor
    return red, green, blue, weight


def _color_from_weighted_totals(
    totals: Tuple[float, float, float, float],
) -> Optional[Color]:
    red, green, blue, weight = totals
    if weight <= 0:
        return None
    return (
        max(0, min(255, round(red / weight))),
        max(0, min(255, round(green / weight))),
        max(0, min(255, round(blue / weight))),
    )


def average_block_texture(block_id: str) -> Optional[Color]:
    """Return an averaged local-client texture colour, if available."""
    if not block_id:
        return None
    return _average_texture(_block_path(block_id))


def texture_jar_path() -> Optional[Path]:
    """Return the active JAR path for diagnostics/settings UI."""
    _get_archive()
    with _lock:
        return _archive_path


def texture_palette_signature() -> str:
    """Return a stable cache-key fragment for the active texture source."""
    global _palette_signature
    with _lock:
        if _palette_signature is not None:
            return _palette_signature
        path = texture_jar_path()
        if path is None:
            _palette_signature = "fallback"
            return _palette_signature
        try:
            stat = path.stat()
            _palette_signature = (
                f"{path.absolute()}|{int(stat.st_mtime_ns)}|{int(stat.st_size)}"
            )
        except OSError:
            _palette_signature = str(path)
        return _palette_signature


__all__ = [
    "average_block_texture",
    "set_texture_jar",
    "texture_jar_path",
    "texture_palette_signature",
]
