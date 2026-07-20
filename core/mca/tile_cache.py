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
from typing import Any, Dict, Optional, Sequence, Union

PathLike = Union[str, Path]

ALGO_VERSION = "v14-biome-strata-soft-relief-leaf512"

_CACHE_DIR: Optional[Path] = None
_LOCK = threading.Lock()
_MAX_FILES = 4000
_LADDER: Sequence[int] = (16, 32, 64, 128, 256, 512)


def cache_dir() -> Path:
    """俯视瓦片磁盘缓存根目录（惰性创建）。"""
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
    try:
        from core.mca.texture_palette import texture_palette_signature

        texture_signature = texture_palette_signature()
    except (ImportError, RuntimeError, AttributeError, TypeError, ValueError):
        texture_signature = "fallback"
    except Exception:
        texture_signature = "fallback"
    raw = (
        f"{region_path.absolute()}|{mtime_ns}|{size}|{tile_size}|"
        f"{ALGO_VERSION}|{texture_signature}"
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def cache_path_for(region_path: PathLike, tile_size: int) -> Path:
    """区域路径 + 瓦片边长对应的缓存 PNG 路径。

    Args:
        region_path: ``r.x.z.mca`` 路径。
        tile_size: 输出边长（像素）。
    """
    key = _cache_key(Path(region_path), int(tile_size))
    return cache_dir() / f"{key}.png"


def load_tile(region_path: PathLike, tile_size: int) -> Optional[bytes]:
    """读取已缓存的俯视 PNG 字节；缺失或过小则 None。"""
    path = cache_path_for(region_path, tile_size)
    try:
        if path.stat().st_size > 32:
            return path.read_bytes()
    except OSError:
        return None
    return None


def store_tile(region_path: PathLike, tile_size: int, png: bytes) -> None:
    """原子写入瓦片缓存，并在超限时淘汰旧文件。

    Args:
        region_path: 区域文件路径。
        tile_size: 瓦片边长。
        png: PNG 字节；空内容忽略。
    """
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
    except (OSError, ValueError, TypeError, ImportError):
        return None
    except Exception:
        return None


def get_cache_stats() -> Dict[str, Any]:
    """Return disk + memory cache stats for settings UI."""
    root = cache_dir()
    file_count = 0
    total_bytes = 0
    try:
        for path in root.glob("*.png"):
            if not path.is_file():
                continue
            try:
                total_bytes += path.stat().st_size
                file_count += 1
            except OSError:
                continue
    except OSError:
        pass

    mem_entries = 0
    try:
        from core.mca.surface import chunk_decode_cache_size
        mem_entries = int(chunk_decode_cache_size())
    except (ImportError, TypeError, ValueError, AttributeError, RuntimeError):
        mem_entries = 0
    except Exception:
        mem_entries = 0

    return {
        "path": str(root),
        "file_count": file_count,
        "total_bytes": total_bytes,
        "max_files": _MAX_FILES,
        "algo_version": ALGO_VERSION,
        "memory_chunks": mem_entries,
    }


def clear_disk_cache() -> Dict[str, int]:
    """Delete all cached topview PNG files."""
    root = cache_dir()
    deleted = 0
    freed = 0
    with _LOCK:
        try:
            for p in list(root.glob("*.png")) + list(root.glob("*.tmp")):
                try:
                    sz = p.stat().st_size if p.is_file() else 0
                    p.unlink()
                    deleted += 1
                    freed += int(sz)
                except OSError:
                    continue
        except OSError:
            pass
    return {"deleted_files": deleted, "freed_bytes": freed}


def clear_all_caches() -> Dict[str, Any]:
    """Clear disk PNG cache and in-process decoded chunk cache."""
    disk = clear_disk_cache()
    mem_cleared = 0
    try:
        from core.mca.surface import clear_chunk_decode_cache, chunk_decode_cache_size
        mem_cleared = int(chunk_decode_cache_size())
        clear_chunk_decode_cache()
    except (ImportError, TypeError, ValueError, AttributeError, RuntimeError):
        pass
    except Exception:
        pass
    return {**disk, "memory_chunks_cleared": mem_cleared}


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
