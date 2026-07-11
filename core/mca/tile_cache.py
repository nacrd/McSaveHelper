"""Disk cache for rendered topview PNG tiles.

Key = hash(absolute path, mtime_ns, size, tile_size, algo_version).
Stored under ~/.mc_save_helper/topview_tiles/ as raw PNG files.
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Optional, Union

PathLike = Union[str, Path]

# Bump when sampling/color/heightmap logic changes so stale tiles are ignored.
ALGO_VERSION = "v5-chunk-subsample"

_CACHE_DIR: Optional[Path] = None
_LOCK = threading.Lock()
_MAX_FILES = 4000


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


def _maybe_prune() -> None:
    """Best-effort: if too many files, delete oldest half."""
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
