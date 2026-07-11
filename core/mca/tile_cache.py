"""Disk cache for rendered topview PNG tiles.

Key = hash(absolute path, mtime_ns, size, tile_size, algo_version).
Stored under ~/.mc_save_helper/topview_tiles/ as raw PNG files.
"""
from __future__ import annotations

import hashlib
import io
import os
import threading
from pathlib import Path
from typing import Optional, Sequence, Union

PathLike = Union[str, Path]

ALGO_VERSION = "v6-chunk-lru"

_CACHE_DIR: Optional[Path] = None
_LOCK = threading.Lock()
_MAX_FILES = 4000
_LADDER: Sequence[int] = (16, 32, 64, 128)


def cache_dir() -> Path:
    global _CACHE_DIR
    if _CACHE_DIR is None:
        root = Path.home() / ".mc_save_helper" / "topview_tiles"
        root.mkdir(parents=True, exist_ok=True)
        _CACHE_DIR = root
    return _CACHE_DIR


def _cache_key(region_path: Path, tile_size: int) -> str:
    try:
        st = region_path.stat()
        mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
        size = st.st_size
    except OSError:
        mtime_ns = 0
        size = 0
    raw = f"{region_path.resolve()}|{mtime_ns}|{size}|{tile_size}|{ALGO_VERSION}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def cache_path_for(region_path: PathLike, tile_size: int) -> Path:
    key = _cache_key(Path(region_path), int(tile_size))
    return cache_dir() / f"{key}.png"


def load_tile(region_path: PathLike, tile_size: int) -> Optional[bytes]:
    path = cache_path_for(region_path, tile_size)
    try:
        if path.is_file() and path.stat().st_size > 32:
            return path.read_bytes()
    except OSError:
        return None
    return None


def store_tile(region_path: PathLike, tile_size: int, png: bytes) -> None:
    if not png:
        return
    path = cache_path_for(region_path, tile_size)
    tmp = path.with_suffix(".tmp")
    try:
        with _LOCK:
            tmp.write_bytes(png)
            os.replace(tmp, path)
            _maybe_prune()
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def upscale_cached_tile(region_path: PathLike, tile_size: int) -> Optional[bytes]:
    """Nearest-neighbor upscale of a lower-res cached tile (not stored as hi-res)."""
    tile_size = int(tile_size)
    path = Path(region_path)
    src_png = None
    for s in reversed(_LADDER):
        if s >= tile_size:
            continue
        raw = load_tile(path, s)
        if raw:
            src_png = raw
            break
    if not src_png:
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(src_png)) as im:
            out = im.resize((tile_size, tile_size), Image.Resampling.NEAREST)
            buf = io.BytesIO()
            out.save(buf, format="PNG", optimize=False, compress_level=1)
            return buf.getvalue()
    except Exception:
        return None


def _maybe_prune() -> None:
    try:
        root = cache_dir()
        files = [p for p in root.glob("*.png") if p.is_file()]
        if len(files) <= _MAX_FILES:
            return
        files.sort(key=lambda p: p.stat().st_mtime)
        for p in files[: len(files) // 2]:
            try:
                p.unlink()
            except OSError:
                pass
    except OSError:
        pass
