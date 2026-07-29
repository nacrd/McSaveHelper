"""俯视磁盘瓦片缓存的索引与统一淘汰。

避免每次写入都全量 ``glob`` 目录；索引以 JSON 维护路径、大小与 mtime。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional


_INDEX_NAME = "index.json"
_LOCK = threading.Lock()


def index_path(cache_root: Path) -> Path:
    """返回索引文件路径。"""
    return cache_root / _INDEX_NAME


def load_index(cache_root: Path) -> dict[str, dict[str, Any]]:
    """加载索引；损坏或缺失时返回空表。"""
    path = index_path(cache_root)
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            entries = data.get("entries", data)
            if isinstance(entries, dict):
                return {
                    str(key): value
                    for key, value in entries.items()
                    if isinstance(value, dict)
                }
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    return {}


def save_index(cache_root: Path, entries: dict[str, dict[str, Any]]) -> None:
    """原子写入索引。"""
    path = index_path(cache_root)
    tmp = path.with_suffix(".tmp")
    payload = {"version": 1, "entries": entries}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def record_file(
    cache_root: Path,
    file_path: Path,
    *,
    size: Optional[int] = None,
    mtime: Optional[float] = None,
) -> None:
    """登记或更新一个缓存文件条目。"""
    with _LOCK:
        entries = load_index(cache_root)
        try:
            st = file_path.stat()
            size = int(st.st_size if size is None else size)
            mtime = float(st.st_mtime if mtime is None else mtime)
        except OSError:
            return
        entries[file_path.name] = {
            "size": size,
            "mtime": mtime,
        }
        try:
            save_index(cache_root, entries)
        except OSError:
            pass


def remove_file(cache_root: Path, file_name: str) -> None:
    """从索引移除条目。"""
    with _LOCK:
        entries = load_index(cache_root)
        if file_name in entries:
            entries.pop(file_name, None)
            try:
                save_index(cache_root, entries)
            except OSError:
                pass


def _scan_cache_files(cache_root: Path) -> dict[str, dict[str, Any]]:
    """扫描磁盘 PNG；调用方负责持有索引锁。"""
    entries: dict[str, dict[str, Any]] = {}
    try:
        for path in cache_root.glob("*.png"):
            if not path.is_file():
                continue
            try:
                st = path.stat()
                entries[path.name] = {
                    "size": int(st.st_size),
                    "mtime": float(st.st_mtime),
                }
            except OSError:
                continue
    except OSError:
        return {}
    return entries


def _rebuild_index_locked(cache_root: Path) -> dict[str, dict[str, Any]]:
    """在已持有索引锁时扫描并保存索引。"""
    entries = _scan_cache_files(cache_root)
    try:
        save_index(cache_root, entries)
    except OSError:
        return {}
    return entries


def rebuild_index(cache_root: Path) -> dict[str, dict[str, Any]]:
    """从磁盘 PNG 重建索引。"""
    with _LOCK:
        return _rebuild_index_locked(cache_root)


def clear_index(cache_root: Path) -> None:
    """删除磁盘索引及未完成的临时索引。"""
    path = index_path(cache_root)
    with _LOCK:
        for target in (path, path.with_suffix(".tmp")):
            try:
                target.unlink()
            except FileNotFoundError:
                continue


def prune_to_limit(
    cache_root: Path,
    max_files: int,
) -> tuple[int, int]:
    """按索引 mtime 淘汰最旧文件，返回 (deleted, freed_bytes)。"""
    if max_files < 1:
        raise ValueError("max_files must be >= 1")
    with _LOCK:
        entries = load_index(cache_root)
        if not entries:
            entries = _rebuild_index_locked(cache_root)
        if len(entries) <= max_files:
            return 0, 0
        ordered = sorted(
            entries.items(),
            key=lambda item: float(item[1].get("mtime", 0.0)),
        )
        remove_count = len(entries) - max_files
        # Drop half of excess at once to amortize prune cost.
        remove_count = max(remove_count, len(entries) // 4)
        deleted = 0
        freed = 0
        for name, meta in ordered[:remove_count]:
            path = cache_root / name
            try:
                size = int(meta.get("size", 0) or 0)
                if path.is_file():
                    size = path.stat().st_size
                    path.unlink()
                deleted += 1
                freed += size
                entries.pop(name, None)
            except OSError:
                entries.pop(name, None)
                continue
        try:
            save_index(cache_root, entries)
        except OSError:
            pass
        return deleted, freed


def index_stats(cache_root: Path) -> dict[str, Any]:
    """返回索引导出的占用统计（不全量扫描目录）。"""
    with _LOCK:
        entries = load_index(cache_root)
    if not entries:
        entries = rebuild_index(cache_root)
    total_bytes = sum(int(item.get("size", 0) or 0) for item in entries.values())
    return {
        "indexed_files": len(entries),
        "indexed_bytes": total_bytes,
        "index_path": str(index_path(cache_root)),
    }


__all__ = [
    "clear_index",
    "index_path",
    "index_stats",
    "load_index",
    "prune_to_limit",
    "rebuild_index",
    "record_file",
    "remove_file",
    "save_index",
]
