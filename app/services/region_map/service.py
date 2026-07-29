"""
存档区域地图后台扫描服务 (RegionMapService)

提供异步、非阻塞的区域文件扫描能力，
支持进度追踪和数据查询。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, Optional

from app.services.cache_registry import CachePolicy, CacheRegistration, CacheRegistry
from app.services.execution_runtime import ExecutionRuntime, OperationHandle
from app.services.region_map.meta import RegionMapMetaMixin
from app.services.region_map.scan import RegionMapScanMixin
from app.services.region_map.topview import RegionMapTopviewMixin
from app.services.region_map.types import ScanProgress


class RegionMapService(
    RegionMapScanMixin,
    RegionMapMetaMixin,
    RegionMapTopviewMixin,
):
    """
    存档区域地图后台扫描服务（每个 Explorer 会话一个实例）

    职责：
    - 异步扫描 Minecraft region 目录
    - 缓存区域文件大小数据
    - 提供进度查询接口
    - 按需渲染俯视瓦片
    """

    TOPVIEW_QUEUE_LIMIT = 128
    TOPVIEW_CACHE_ENTRY_LIMIT = 1024
    TOPVIEW_MEMORY_LIMIT = 32 * 1024 * 1024
    TOPVIEW_FAILURE_LIMIT = 2

    @staticmethod
    def _cancel_asyncio_task(task: asyncio.Task) -> None:
        """Cancel a task through its owning loop when called cross-thread."""
        if task.done():
            return
        try:
            owner_loop = task.get_loop()
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
            owner_loop = task.get_loop()
        try:
            if current_loop is owner_loop:
                task.cancel()
            elif not owner_loop.is_closed():
                owner_loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            pass

    def __init__(
        self,
        execution_runtime: ExecutionRuntime,
        cache_registry: Optional[CacheRegistry] = None,
    ) -> None:
        """初始化内部状态。

        Args:
            execution_runtime: 应用组合根持有的共享后台运行时（必填）。
            cache_registry: 可选应用缓存注册表，用于登记俯视瓦片预算。
        """
        self._init_scan_state()
        self._init_topview_state()
        self._init_topview_workers()
        self._execution_runtime = execution_runtime
        self._topview_handles: set[OperationHandle[None]] = set()
        self._cache_registration: Optional[CacheRegistration] = None
        if cache_registry is not None:
            self._cache_registration = cache_registry.register_external(
                f"map.topview.{id(self)}",
                CachePolicy(
                    self.TOPVIEW_CACHE_ENTRY_LIMIT,
                    self.TOPVIEW_MEMORY_LIMIT,
                ),
                self._topview_cache_stats,
                self._clear_topview_memory_cache,
            )

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        """返回本地图会话使用的统一后台运行时。"""
        return self._execution_runtime

    def clear_data(self) -> None:
        """清空所有缓存数据"""
        meta_tasks: list[OperationHandle[Dict[str, Any]]]
        with self._data_lock:
            self._scan_generation += 1
            self._data_revision += 1
            self._is_scanning = False
            self._mca_data.clear()
            self._region_meta.clear()
            self._region_paths.clear()
            meta_tasks = list(self._region_meta_tasks.values())
            self._region_meta_tasks.clear()
            self._topview_tiles.clear()
            self._topview_memory_bytes = 0
            self._topview_tile_sizes.clear()
            self._topview_tile_complete.clear()
            self._topview_tile_revisions.clear()
            self._topview_tile_sources.clear()
            self._topview_source_checked_at.clear()
            self._topview_source_pending.clear()
            self._topview_revision_counter = 0
            self._topview_failed_sizes.clear()
            self._topview_failed_mtimes.clear()
            self._topview_failed_file_sizes.clear()
            self._topview_failed_signatures.clear()
            self._topview_failure_counts.clear()
            self._topview_pending.clear()
            self._topview_pending_sizes.clear()
            self._topview_upgrade_sizes.clear()
            self._topview_progress_chunks.clear()
            self._topview_queue.clear()
            self._topview_cancel_event.set()
            self._topview_cancel_event = threading.Event()
            self._topview_generation += 1
            self._scanned_count = 0
            self._total_count = 0
            self._scan_progress = 0.0
            self._error = None
            self._stats_dirty = True
            self._cached_stats = None
            self._cached_data_snapshot = None
            self._cached_snapshot_count = -1
        for meta_handle in meta_tasks:
            meta_handle.cancel()

    def close(self) -> None:
        """释放回调、队列与工作线程资源（幂等）。

        可从 UI 线程调用；已在跑的原生解析无法中断，但会取消 asyncio 包装
        并递增 generation 丢弃晚到结果。
        """
        if self._closed:
            return
        self._closed = True
        self._scan_generation += 1
        self._is_scanning = False
        scan_task = self._scan_task
        self._scan_task = None
        if scan_task is not None and not scan_task.done():
            self._cancel_asyncio_task(scan_task)
        self.set_tile_ready_callback(None)
        with self._data_lock:
            meta_tasks = list(self._region_meta_tasks.values())
            self._region_meta_tasks.clear()
            self._data_revision += 1
            self._mca_data.clear()
            self._region_meta.clear()
            self._region_paths.clear()
            self._topview_tiles.clear()
            self._topview_memory_bytes = 0
            self._topview_tile_sizes.clear()
            self._cached_stats = None
            self._cached_data_snapshot = None
            self._cached_snapshot_count = -1
            self._stats_dirty = True
            self._topview_generation += 1
            self._topview_cancel_event.set()
            self._topview_queue.clear()
            self._topview_pending.clear()
            self._topview_pending_sizes.clear()
            self._topview_upgrade_sizes.clear()
            self._topview_progress_chunks.clear()
            self._topview_failed_sizes.clear()
            self._topview_failed_mtimes.clear()
            self._topview_failed_file_sizes.clear()
            self._topview_failed_signatures.clear()
            self._topview_failure_counts.clear()
            self._topview_tile_revisions.clear()
            self._topview_tile_complete.clear()
            self._topview_tile_sources.clear()
            self._topview_source_checked_at.clear()
            self._topview_source_pending.clear()
        for meta_handle in meta_tasks:
            meta_handle.cancel()
        with self._data_lock:
            handles = tuple(self._topview_handles)
            self._topview_handles.clear()
            self._topview_executor = None
        for topview_handle in handles:
            topview_handle.cancel()
        registration = self._cache_registration
        self._cache_registration = None
        if registration is not None:
            registration.close()


__all__ = ["RegionMapService", "ScanProgress"]
