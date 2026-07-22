"""区域地图 mixin 宿主合约。"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Deque, Dict, Optional, Tuple

from app.services.cache_registry import CacheRegistration
from app.services.execution_runtime import ExecutionRuntime, OperationHandle


class RegionMapHost:
    """声明 RegionMapService 提供给 scan/meta/topview mixin 的共享状态。"""

    TOPVIEW_QUEUE_LIMIT: int
    TOPVIEW_MEMORY_LIMIT: int
    TOPVIEW_FAILURE_LIMIT: int

    _data_lock: threading.Lock
    _closed: bool
    _execution_runtime: ExecutionRuntime
    _cache_registration: Optional[CacheRegistration]
    _topview_handles: set[OperationHandle[None]]

    _mca_data: Dict[Tuple[int, int], int]
    _region_meta: Dict[Tuple[int, int], Dict[str, Any]]
    _region_meta_tasks: Dict[Tuple[int, int], OperationHandle[Dict[str, Any]]]
    _region_paths: Dict[Tuple[int, int], str]
    _is_scanning: bool
    _scan_progress: float
    _scan_task: Optional[Any]
    _scan_generation: int
    _data_revision: int
    _scanned_count: int
    _total_count: int
    _error: Optional[str]
    _stats_dirty: bool
    _cached_stats: Optional[Dict[str, Any]]
    _cached_data_snapshot: Optional[Dict[Tuple[int, int], int]]
    _cached_snapshot_count: int

    _topview_tiles: OrderedDict[Tuple[int, int], bytes]
    _topview_memory_bytes: int
    _topview_generation: int
    _topview_pending: Dict[Tuple[int, int], int]
    _topview_pending_sizes: Dict[Tuple[int, int], int]
    _topview_upgrade_sizes: Dict[Tuple[int, int], int]
    _topview_tile_size: int
    _topview_enabled: bool
    _topview_tile_sizes: Dict[Tuple[int, int], int]
    _topview_tile_complete: Dict[Tuple[int, int], bool]
    _topview_tile_revisions: Dict[Tuple[int, int], int]
    _topview_tile_sources: Dict[Tuple[int, int], Tuple[int, int, str]]
    _topview_source_checked_at: Dict[Tuple[int, int], float]
    _topview_source_pending: set[Tuple[int, int]]
    _topview_revision_counter: int
    _topview_failed_sizes: Dict[Tuple[int, int], int]
    _topview_failed_mtimes: Dict[Tuple[int, int], int]
    _topview_failed_file_sizes: Dict[Tuple[int, int], int]
    _topview_failed_signatures: Dict[Tuple[int, int], str]
    _topview_failure_counts: Dict[Tuple[Tuple[int, int], int, str], int]
    _tile_ready_callback: Optional[Any]
    _topview_max_workers: int
    _topview_active: int
    _topview_cancel_event: threading.Event
    _topview_queue: Deque[
        Tuple[Tuple[int, int], str, int, int, threading.Event, int]
    ]
    _topview_executor: Optional[ExecutionRuntime]

    def clear_data(self) -> None:
        """由组合类实现：清空扫描与瓦片状态。"""
        raise NotImplementedError

    def close(self) -> None:
        """由组合类实现：释放会话资源。"""
        raise NotImplementedError


__all__ = ["RegionMapHost"]
