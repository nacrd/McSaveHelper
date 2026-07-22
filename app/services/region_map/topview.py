"""俯视瓦片队列、渲染与内存缓存。"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from app.services.cache_registry import CacheStats
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    ExecutionRuntime,
    OperationHandle,
    TaskPriority,
)
from app.services.region_map.host import RegionMapHost
from core.mca.errors import McaError
from core.mca.region_file import RegionFile
from core.mca.topview_renderer import LEAF_TILE_SIZE, render_region_topview


TopviewCoord = Tuple[int, int]
TopviewSourceStamp = Tuple[int, int]
TopviewSourceState = Tuple[int, int, str]
TopviewFailureState = Tuple[int, int, Optional[int], str]
TopviewJob = Tuple[TopviewCoord, str, int, int, threading.Event, int]


@dataclass(frozen=True)
class _TopviewSourceCheck:
    """A lock-free filesystem probe requested from a consistent state snapshot."""

    coord: TopviewCoord
    path: str
    tile_state: Optional[TopviewSourceState]
    failure_state: Optional[TopviewFailureState]


class RegionMapTopviewMixin(RegionMapHost):
    """Mixin host contract is fulfilled by RegionMapService."""

    TOPVIEW_SOURCE_CHECK_INTERVAL_SECONDS = 1.0

    def _init_topview_state(self) -> None:
        # region 坐标 → PNG bytes（顶视瓦片缓存）
        self._topview_tiles: OrderedDict[Tuple[int, int], bytes] = OrderedDict()
        self._topview_memory_bytes = 0
        # 俯视图生成代数：clear/start 时递增，丢弃过期回调
        self._topview_generation: int = 0
        # coord -> generation.  The generation check prevents an old worker
        # from removing a same-coordinate request belonging to a new scan.
        self._topview_pending: Dict[Tuple[int, int], int] = {}
        self._topview_pending_sizes: Dict[Tuple[int, int], int] = {}
        self._topview_upgrade_sizes: Dict[Tuple[int, int], int] = {}
        self._topview_tile_size: int = 32
        self._topview_enabled: bool = True
        # Track rendered tile size so we can upgrade 64→128 later if needed.
        self._topview_tile_sizes: Dict[Tuple[int, int], int] = {}
        self._topview_tile_complete: Dict[Tuple[int, int], bool] = {}
        self._topview_tile_revisions: Dict[Tuple[int, int], int] = {}
        # coord -> MCA stamp plus external MCC signature for stale PNG detection.
        self._topview_tile_sources: Dict[
            Tuple[int, int], TopviewSourceState
        ] = {}
        self._topview_source_checked_at: Dict[Tuple[int, int], float] = {}
        self._topview_source_pending: set[Tuple[int, int]] = set()
        self._topview_revision_counter = 0
        # A failed tile should not be retried on every rebuild.  A later,
        # higher-resolution request may still retry it.
        self._topview_failed_sizes: Dict[Tuple[int, int], int] = {}
        self._topview_failed_mtimes: Dict[Tuple[int, int], int] = {}
        self._topview_failed_file_sizes: Dict[Tuple[int, int], int] = {}
        self._topview_failed_signatures: Dict[Tuple[int, int], str] = {}
        self._topview_failure_counts: Dict[
            Tuple[Tuple[int, int], int, str], int
        ] = {}
        # 瓦片变更回调（由 UI 注册，在 UI 线程调度）
        self._tile_ready_callback: Optional[Any] = None
        self._topview_cache_hits = 0
        self._topview_cache_misses = 0
        self._stale_callback_discards = 0

    def _init_topview_workers(self) -> None:
        # 渲染统一使用应用计算通道，局部并发上限仅用于请求泵的可见预算。
        self._topview_max_workers: int = 2
        self._topview_active: int = 0
        self._topview_cancel_event = threading.Event()
        self._topview_queue: Deque[
            Tuple[Tuple[int, int], str, int, int, threading.Event, int]
        ] = deque()
        self._topview_executor: Optional[ExecutionRuntime] = None

    def _ensure_topview_executor(self) -> ExecutionRuntime:
        """返回统一计算运行时，保留旧测试/兼容入口名称。"""
        with self._data_lock:
            if self._closed:
                raise RuntimeError("区域地图服务已关闭")
            self._topview_executor = self._execution_runtime
            return self._execution_runtime

    def _topview_cache_stats(self) -> CacheStats:
        """返回本地图会话的内存瓦片缓存统计。"""
        with self._data_lock:
            return CacheStats(
                name=f"map.topview.{id(self)}",
                entries=len(self._topview_tiles),
                bytes_used=self._topview_memory_bytes,
                max_entries=self.TOPVIEW_QUEUE_LIMIT,
                max_bytes=self.TOPVIEW_MEMORY_LIMIT,
                hits=self._topview_cache_hits,
                misses=self._topview_cache_misses,
                evictions=0,
            )

    def get_stale_callback_discards(self) -> int:
        """返回因 generation 过期而丢弃的瓦片回调/任务次数。"""
        with self._data_lock:
            return int(self._stale_callback_discards)

    def _clear_topview_memory_cache(self) -> None:
        """在注册表清理请求中仅释放可重建的瓦片内存。"""
        with self._data_lock:
            self._topview_tiles.clear()
            self._topview_memory_bytes = 0
            self._topview_tile_sizes.clear()
            self._topview_tile_complete.clear()
            self._topview_tile_revisions.clear()
            self._topview_tile_sources.clear()
            self._topview_source_checked_at.clear()
            self._topview_source_pending.clear()
            self._data_revision += 1

    def set_tile_ready_callback(self, callback: Optional[Any]) -> None:
        """注册俯视图瓦片就绪回调。

        回调可能从 topview 工作线程触发；UI 侧需自行切回 UI 线程。

        Args:
            callback: ``callback(coord)``；传 None 清除。
        """
        self._tile_ready_callback = callback

    def get_topview_tile(self, coord: Tuple[int, int]) -> Optional[bytes]:
        """取缓存的俯视 PNG 瓦片（命中则刷新 LRU）。

        Args:
            coord: 区域坐标。

        Returns:
            PNG 字节；未缓存为 None。
        """
        self._schedule_topview_source_checks([coord])
        with self._data_lock:
            tile = self._topview_tiles.get(coord)
            if tile is not None:
                self._topview_tiles.move_to_end(coord)
                self._topview_cache_hits += 1
                return tile
            self._topview_cache_misses += 1
            return None

    def has_topview_tile(self, coord: Tuple[int, int], min_size: int = 0) -> bool:
        """判断是否已有满足最小尺寸的完整瓦片。

        未完成渲染且失败尺寸小于缓存尺寸时视为不可用。

        Args:
            coord: 区域坐标。
            min_size: 要求的最小边长像素；0 表示任意缓存即可。

        Returns:
            是否可作为当前 LOD 使用。
        """
        self._schedule_topview_source_checks([coord])
        with self._data_lock:
            if coord not in self._topview_tiles:
                return False
            self._topview_tiles.move_to_end(coord)
            if not self._topview_tile_complete.get(coord, True):
                cached_size = int(self._topview_tile_sizes.get(coord, 0) or 0)
                failed_size = int(self._topview_failed_sizes.get(coord, 0) or 0)
                if failed_size < cached_size:
                    return False
            if min_size <= 0:
                return True
            return int(self._topview_tile_sizes.get(coord, 0) or 0) >= min_size

    def get_topview_tile_size(self, coord: Tuple[int, int]) -> int:
        """返回已缓存瓦片边长。

        Args:
            coord: 区域坐标。

        Returns:
            像素边长；无缓存为 0。
        """
        self._schedule_topview_source_checks([coord])
        with self._data_lock:
            return int(self._topview_tile_sizes.get(coord, 0) or 0)

    def get_topview_tile_revision(self, coord: Tuple[int, int]) -> int:
        """返回单瓦片修订号（缓存更新时递增）。

        Args:
            coord: 区域坐标。

        Returns:
            修订号；无记录为 0。
        """
        with self._data_lock:
            return int(self._topview_tile_revisions.get(coord, 0) or 0)

    def is_topview_tile_pending(
        self,
        coord: Tuple[int, int],
        *,
        min_size: int = 0,
    ) -> bool:
        """当前代数是否仍持有对该坐标且不低于 ``min_size`` 的请求。

        地图视图只保留小账本；有界队列可能丢弃尾部，须与服务对账。

        Args:
            coord: 区域坐标。
            min_size: 要求的最小请求尺寸。

        Returns:
            当前 generation 是否仍 pending/upgrade。
        """
        required = max(0, int(min_size))
        with self._data_lock:
            generation = self._topview_generation
            if self._topview_pending.get(coord) != generation:
                return False
            pending_size = int(self._topview_pending_sizes.get(coord, 0) or 0)
            upgrade_size = int(self._topview_upgrade_sizes.get(coord, 0) or 0)
            return max(pending_size, upgrade_size) >= required

    def get_topview_snapshot(
        self,
        coords: list[Tuple[int, int]],
    ) -> tuple[int, Dict[Tuple[int, int], bytes], Dict[Tuple[int, int], int]]:
        """为单帧表面读取一致的瓦片/修订快照。

        Args:
            coords: 本帧可见区域坐标列表。

        Returns:
            ``(generation, tiles, revisions)``；generation 用于丢弃过期帧。
        """
        self._schedule_topview_source_checks(coords)
        tiles: Dict[Tuple[int, int], bytes] = {}
        revisions: Dict[Tuple[int, int], int] = {}
        with self._data_lock:
            generation = self._topview_generation
            for coord in coords:
                tile = self._topview_tiles.get(coord)
                if tile is not None:
                    self._topview_tiles.move_to_end(coord)
                    tiles[coord] = tile
                revisions[coord] = int(
                    self._topview_tile_revisions.get(coord, 0) or 0
                )
        return generation, tiles, revisions

    def get_data_revision(self) -> int:
        """返回扫描数据变更的单调修订号。

        Returns:
            数据修订计数。
        """
        with self._data_lock:
            return self._data_revision

    def get_topview_generation(self) -> int:
        """返回俯视图会话代数（clear/start 时递增）。

        Returns:
            当前 topview generation。
        """
        with self._data_lock:
            return self._topview_generation

    def _promote_pending_topview_locked(
        self,
        coord: Tuple[int, int],
        size: int,
        priority: bool,
        generation: int,
        cancel_event: threading.Event,
    ) -> bool:
        if self._topview_pending.get(coord) != generation:
            return False
        pending_size = int(self._topview_pending_sizes.get(coord, 0) or 0)
        if size > pending_size:
            for index, queued_job in enumerate(self._topview_queue):
                if queued_job[0] != coord:
                    continue
                del self._topview_queue[index]
                upgraded = (
                    coord,
                    queued_job[1],
                    size,
                    generation,
                    cancel_event,
                    queued_job[5],
                )
                self._topview_pending_sizes[coord] = size
                if priority:
                    self._topview_queue.appendleft(upgraded)
                else:
                    self._topview_queue.append(upgraded)
                return True
            # The old request is already running.  Queue the detail upgrade
            # for the worker completion instead of dropping it.
            self._topview_upgrade_sizes[coord] = max(
                size,
                int(self._topview_upgrade_sizes.get(coord, 0) or 0),
            )
        if priority:
            for index, queued_job in enumerate(self._topview_queue):
                if queued_job[0] == coord:
                    del self._topview_queue[index]
                    self._topview_queue.appendleft(queued_job)
                    break
        return True

    def _topview_path_for_request_locked(
        self,
        coord: Tuple[int, int],
        size: int,
    ) -> Optional[str]:
        existing = self._topview_tiles.get(coord)
        existing_size = int(self._topview_tile_sizes.get(coord, 0) or 0)
        complete = self._topview_tile_complete.get(coord, True)
        if (
            existing is not None
            and existing_size >= size
            and complete
        ):
            return None
        path = self._region_paths.get(coord)
        if not path:
            return None
        if int(self._topview_failed_sizes.get(coord, 0) or 0) < size:
            return path
        return None

    def _schedule_topview_source_checks(
        self,
        coords: list[TopviewCoord],
        *,
        failure_size: Optional[int] = None,
        force: bool = False,
    ) -> None:
        """Submit throttled source probes without blocking the UI caller."""
        checks = self._collect_topview_source_checks(
            coords,
            failure_size=failure_size,
            force=force,
        )
        if not checks:
            return
        try:
            handle = self._execution_runtime.submit(
                "probe_topview_sources",
                lambda token: self._run_topview_source_checks(token, checks),
                lane=ExecutionLane.IO,
                priority=TaskPriority.BACKGROUND,
            )
        except (RuntimeError, ValueError):
            self._release_topview_source_checks(checks)
            return
        self._track_topview_source_handle(handle, checks)

    def _run_topview_source_checks(
        self,
        token: CancellationToken,
        checks: tuple[_TopviewSourceCheck, ...],
    ) -> None:
        """Probe one batch on the shared I/O lane and publish current results."""
        for check in checks:
            if token.is_cancelled:
                return
            current_stamp = self._read_topview_source_stat(check.path, 0)
            current_signature = self._source_signature_for_check(
                check,
                current_stamp,
                token,
            )
            if token.is_cancelled:
                return
            callback = self._apply_topview_source_check(
                check,
                current_stamp,
                current_signature,
            )
            self._notify_topview_ready(callback, check.coord)

    def _track_topview_source_handle(
        self,
        handle: OperationHandle[None],
        checks: tuple[_TopviewSourceCheck, ...],
    ) -> None:
        """Own a source-probe handle until completion or service close."""
        with self._data_lock:
            should_cancel = self._closed
            if not should_cancel:
                self._topview_handles.add(handle)
        handle.add_done_callback(
            lambda completed: self._complete_topview_source_handle(
                completed,
                checks,
            )
        )
        if should_cancel:
            handle.cancel()

    def _complete_topview_source_handle(
        self,
        handle: OperationHandle[None],
        checks: tuple[_TopviewSourceCheck, ...],
    ) -> None:
        """Release in-flight source identities after every completion path."""
        with self._data_lock:
            self._topview_handles.discard(handle)
        self._release_topview_source_checks(checks)

    def _release_topview_source_checks(
        self,
        checks: tuple[_TopviewSourceCheck, ...],
    ) -> None:
        """Allow later probes for coordinates in a completed batch."""
        with self._data_lock:
            for check in checks:
                self._topview_source_pending.discard(check.coord)

    def _collect_topview_source_checks(
        self,
        coords: list[TopviewCoord],
        *,
        failure_size: Optional[int],
        force: bool,
    ) -> tuple[_TopviewSourceCheck, ...]:
        """Capture source identities under the lock without touching the disk."""
        now = time.monotonic()
        checks: list[_TopviewSourceCheck] = []
        with self._data_lock:
            for coord in dict.fromkeys(coords):
                path = self._region_paths.get(coord)
                if not path:
                    continue
                if coord in self._topview_source_pending:
                    continue
                checked_at = self._topview_source_checked_at.get(coord, 0.0)
                due = force or (
                    now - checked_at >= self.TOPVIEW_SOURCE_CHECK_INTERVAL_SECONDS
                )
                if not due:
                    continue
                tile_state = self._topview_tile_sources.get(coord)
                failure_state = self._topview_failure_state_locked(
                    coord,
                    failure_size,
                )
                if tile_state is None and failure_state is None:
                    continue
                self._topview_source_checked_at[coord] = now
                self._topview_source_pending.add(coord)
                checks.append(_TopviewSourceCheck(
                    coord=coord,
                    path=path,
                    tile_state=tile_state,
                    failure_state=failure_state,
                ))
        return tuple(checks)

    def _topview_failure_state_locked(
        self,
        coord: TopviewCoord,
        failure_size: Optional[int],
    ) -> Optional[TopviewFailureState]:
        if failure_size is None:
            return None
        failed_size = int(self._topview_failed_sizes.get(coord, 0) or 0)
        if failed_size < failure_size:
            return None
        return (
            failed_size,
            int(self._topview_failed_mtimes.get(coord, 0) or 0),
            self._topview_failed_file_sizes.get(coord),
            self._topview_failed_signatures.get(coord, ""),
        )

    def _source_signature_for_check(
        self,
        check: _TopviewSourceCheck,
        current_stamp: TopviewSourceStamp,
        token: CancellationToken,
    ) -> str:
        failure_state = check.failure_state
        needs_signature = check.tile_state is not None or (
            failure_state is not None and bool(failure_state[3])
        )
        if not needs_signature:
            return ""
        return self._topview_source_signature(
            check.path,
            check.coord,
            current_stamp[0],
            current_stamp[1],
            cancel_check=lambda: token.is_cancelled,
        )

    def _apply_topview_source_check(
        self,
        check: _TopviewSourceCheck,
        current_stamp: TopviewSourceStamp,
        current_signature: str,
    ) -> Optional[Any]:
        callback = None
        with self._data_lock:
            if self._region_paths.get(check.coord) != check.path:
                return None
            compared_signature = (
                current_signature
                if check.tile_state is not None and check.tile_state[2]
                else ""
            )
            current_state = (
                current_stamp[0],
                current_stamp[1],
                compared_signature,
            )
            if (
                check.tile_state is not None
                and self._topview_tile_sources.get(check.coord) == check.tile_state
                and current_state != check.tile_state
            ):
                self._drop_topview_tile_locked(check.coord)
                callback = self._tile_ready_callback
            if check.failure_state != self._topview_failure_state_locked(
                check.coord,
                check.failure_state[0] if check.failure_state else None,
            ):
                return callback
            if self._topview_failure_changed(
                check.failure_state,
                current_stamp,
                current_signature,
            ):
                self._clear_topview_failure_locked(check.coord)
                callback = self._tile_ready_callback
        return callback

    @staticmethod
    def _topview_failure_changed(
        failure_state: Optional[TopviewFailureState],
        current_stamp: TopviewSourceStamp,
        current_signature: str,
    ) -> bool:
        if failure_state is None:
            return False
        _size, failed_mtime, failed_file_size, failed_signature = failure_state
        if failed_signature:
            return failed_signature != current_signature
        return failed_mtime != current_stamp[0] or (
            failed_file_size is not None
            and failed_file_size != current_stamp[1]
        )

    def _drop_topview_tile_locked(self, coord: TopviewCoord) -> None:
        """Remove one cached tile after its source identity changed."""
        previous = self._topview_tiles.pop(coord, None)
        if previous is not None:
            self._topview_memory_bytes -= len(previous)
        self._topview_tile_sizes.pop(coord, None)
        self._topview_tile_complete.pop(coord, None)
        self._topview_tile_revisions.pop(coord, None)
        self._topview_tile_sources.pop(coord, None)
        self._topview_source_checked_at.pop(coord, None)
        self._data_revision += 1

    def _make_topview_queue_room_locked(
        self,
        generation: int,
        priority: bool,
        queued: int,
    ) -> Optional[int]:
        if queued < self.TOPVIEW_QUEUE_LIMIT:
            return queued
        if not priority or not self._topview_queue:
            return None
        dropped_coord = self._topview_queue.pop()[0]
        if self._topview_pending.get(dropped_coord) == generation:
            self._topview_pending.pop(dropped_coord, None)
            self._topview_pending_sizes.pop(dropped_coord, None)
        return queued - 1

    def request_topview_tiles(
        self,
        coords: list[Tuple[int, int]],
        tile_size: Optional[int] = None,
        *,
        force: bool = False,
        priority: bool = False,
    ) -> set[Tuple[int, int]]:
        """为缺失缓存的坐标入队俯视渲染。

        使用有界线程池；可见瓦片应由地图视图请求，扫描本身不灌满队列。

        Args:
            coords: 区域坐标列表。
            tile_size: 目标边长；缺省用内部默认，限制在 8..LEAF。
            force: 优先不完整/升级请求；同尺寸完整瓦片仍缓存不重解。
            priority: 插队到队列前端（选中区域）。

        Returns:
            当前代数实际接纳的坐标集合。有界队列可能拒绝尾部，调用方
            只能记录返回集并允许被拒坐标重试。
        """
        size = max(
            8,
            min(LEAF_TILE_SIZE, int(tile_size or self._topview_tile_size)),
        )
        self._schedule_topview_source_checks(
            coords,
            failure_size=size,
            force=force,
        )
        accepted: set[Tuple[int, int]] = set()
        with self._data_lock:
            if self._closed or not self._topview_enabled:
                return accepted
            generation = self._topview_generation
            cancel_event = self._topview_cancel_event
            queued = len(self._topview_queue) + self._topview_active
            for coord in coords:
                queued, keep_going = self._enqueue_topview_coord_locked(
                    coord=coord,
                    size=size,
                    priority=priority,
                    generation=generation,
                    cancel_event=cancel_event,
                    queued=queued,
                    accepted=accepted,
                )
                if not keep_going:
                    break
        self._pump_topview_queue()
        return accepted

    def _enqueue_topview_coord_locked(
        self,
        *,
        coord: Tuple[int, int],
        size: int,
        priority: bool,
        generation: int,
        cancel_event: threading.Event,
        queued: int,
        accepted: set[Tuple[int, int]],
    ) -> tuple[int, bool]:
        """Try to enqueue one coord. Returns ``(queued, continue_loop)``."""
        if self._promote_pending_topview_locked(
            coord,
            size,
            priority,
            generation,
            cancel_event,
        ):
            accepted.add(coord)
            return queued, True
        path = self._topview_path_for_request_locked(coord, size)
        if path is None:
            return queued, True
        # A large modded save can contain thousands of visible regions.
        # Keep only a bounded window in memory; later rebuilds refill
        # the queue as earlier tiles complete.
        available = self._make_topview_queue_room_locked(
            generation,
            priority,
            queued,
        )
        if available is None:
            return queued, False
        queued = available
        self._topview_pending[coord] = generation
        self._topview_pending_sizes[coord] = size
        job = (
            coord,
            path,
            size,
            generation,
            cancel_event,
            0,
        )
        if priority:
            self._topview_queue.appendleft(job)
        else:
            self._topview_queue.append(job)
        accepted.add(coord)
        return queued + 1, True

    def _pump_topview_queue(self) -> None:
        """Start queued jobs up to the worker cap."""
        jobs: list[TopviewJob] = []
        with self._data_lock:
            while (
                self._topview_active < self._topview_max_workers
                and self._topview_queue
            ):
                job = self._topview_queue.popleft()
                # Drop stale jobs from a previous generation.
                if job[3] != self._topview_generation:
                    self._stale_callback_discards += 1
                    if self._topview_pending.get(job[0]) == job[3]:
                        self._topview_pending.pop(job[0], None)
                        self._topview_pending_sizes.pop(job[0], None)
                    continue
                self._topview_active += 1
                jobs.append(job)

        if not jobs:
            return

        try:
            executor = self._ensure_topview_executor()
        except (RuntimeError, ValueError, OSError):
            self._rollback_topview_jobs(jobs)
            return
        except Exception:
            self._rollback_topview_jobs(jobs)
            return
        for job in jobs:
            started = threading.Event()
            try:
                handle = executor.submit(
                    "render_topview_tile",
                    self._make_topview_work(job, started),
                    lane=ExecutionLane.CPU,
                    priority=TaskPriority.VISIBLE,
                )
                self._track_topview_handle(handle, job, started)
            except (RuntimeError, ValueError):
                self._rollback_topview_jobs([job])
            except Exception:
                self._rollback_topview_jobs([job])

    def _run_topview_job(
        self,
        token: CancellationToken,
        render_job: TopviewJob,
    ) -> None:
        """运行时适配：取消时通知旧队列协议并执行一个瓦片任务。"""
        if token.is_cancelled:
            render_job[4].set()
        self._render_topview_worker(*render_job)

    def _track_topview_handle(
        self,
        handle: OperationHandle[None],
        job: TopviewJob,
        started: threading.Event,
    ) -> None:
        """登记瓦片任务，并统一处理执行前取消与正常完成。"""
        with self._data_lock:
            should_cancel = self._closed
            if not should_cancel:
                self._topview_handles.add(handle)
        handle.add_done_callback(
            lambda completed: self._complete_topview_handle(
                completed,
                job,
                started,
            )
        )
        if should_cancel:
            handle.cancel()

    def _complete_topview_handle(
        self,
        handle: OperationHandle[None],
        job: TopviewJob,
        started: threading.Event,
    ) -> None:
        """释放任务身份，并回收执行前取消任务占用的本地名额。"""
        with self._data_lock:
            self._topview_handles.discard(handle)
        if started.is_set():
            return
        self._rollback_topview_jobs([job])
        self._safe_pump_topview_queue()

    def _make_topview_work(
        self,
        render_job: TopviewJob,
        started: threading.Event,
    ) -> Callable[[CancellationToken], None]:
        """将旧队列任务绑定为统一运行时可提交的单参数函数。"""
        def work(token: CancellationToken) -> None:
            started.set()
            self._run_topview_job(token, render_job)

        return work

    def _rollback_topview_jobs(
        self,
        jobs: list[TopviewJob],
    ) -> None:
        """Return jobs that could not be submitted after a close race."""
        with self._data_lock:
            for coord, _path, _size, generation, _cancel, _mtime in jobs:
                self._topview_active = max(0, self._topview_active - 1)
                if self._topview_pending.get(coord) == generation:
                    self._topview_pending.pop(coord, None)
                    self._topview_pending_sizes.pop(coord, None)
                    self._topview_upgrade_sizes.pop(coord, None)

    def _clear_topview_failure_locked(self, coord: Tuple[int, int]) -> None:
        self._topview_failed_sizes.pop(coord, None)
        self._topview_failed_mtimes.pop(coord, None)
        self._topview_failed_file_sizes.pop(coord, None)
        self._topview_failed_signatures.pop(coord, None)
        stale = [key for key in self._topview_failure_counts if key[0] == coord]
        for key in stale:
            self._topview_failure_counts.pop(key, None)

    def _record_topview_failure_locked(
        self,
        coord: Tuple[int, int],
        tile_size: int,
        source_mtime_ns: int,
        source_file_size: int,
        source_signature: str,
    ) -> None:
        failure_key = (coord, int(tile_size), source_signature)
        failure_count = self._topview_failure_counts.get(failure_key, 0) + 1
        self._topview_failure_counts[failure_key] = failure_count
        if failure_count >= self.TOPVIEW_FAILURE_LIMIT:
            self._topview_failed_sizes[coord] = max(
                int(self._topview_failed_sizes.get(coord, 0) or 0),
                int(tile_size),
            )
            self._topview_failed_mtimes[coord] = int(source_mtime_ns)
            self._topview_failed_file_sizes[coord] = int(source_file_size)
            self._topview_failed_signatures[coord] = source_signature

    @staticmethod
    def _topview_source_signature(
        path: str,
        _coord: Tuple[int, int],
        mca_mtime_ns: int,
        mca_size: int = 0,
        cancel_check: Optional[Any] = None,
    ) -> str:
        """Fingerprint the MCA and external MCC streams in its region."""
        parts = [str(int(mca_mtime_ns)), str(int(mca_size))]
        try:
            with RegionFile.open(path) as region:
                external_signature = region.external_chunk_signature(
                    region.iter_present_chunks(),
                    cancel_check=cancel_check,
                )
            if external_signature:
                parts.append(f"mcc:{external_signature}")
        except (OSError, ValueError, TypeError, RuntimeError, McaError):
            # The MCA signature still prevents stale suppression when the
            # region is replaced or removed while a retry is being checked.
            pass
        return hashlib.sha1("|".join(parts).encode("ascii")).hexdigest()

    def _render_topview_worker(
        self,
        coord: Tuple[int, int],
        path: str,
        tile_size: int,
        generation: int,
        cancel_event: threading.Event,
        source_mtime_ns: int = 0,
    ) -> None:
        """Render one region topview tile and publish it if still current."""
        png: Optional[bytes] = None
        render_complete = True
        source_file_size = 0
        try:
            if self._topview_generation_stale(generation, cancel_event):
                with self._data_lock:
                    self._stale_callback_discards += 1
                return
            source_mtime_ns, source_file_size = self._read_topview_source_stat(
                path,
                source_mtime_ns,
            )
            png, render_complete = self._render_topview_png(
                path,
                tile_size,
                cancel_event,
            )
        except (OSError, ValueError, TypeError, RuntimeError):
            png = None
        except Exception:
            # Topview worker boundary: keep the map session alive on render faults.
            png = None
        finally:
            self._finalize_topview_job(
                coord=coord,
                path=path,
                tile_size=tile_size,
                generation=generation,
                cancel_event=cancel_event,
                png=png,
                render_complete=render_complete,
                source_mtime_ns=source_mtime_ns,
                source_file_size=source_file_size,
            )

    def _topview_generation_stale(
        self,
        generation: int,
        cancel_event: threading.Event,
    ) -> bool:
        with self._data_lock:
            return (
                generation != self._topview_generation
                or cancel_event.is_set()
                or self._closed
            )

    @staticmethod
    def _read_topview_source_stat(
        path: str,
        source_mtime_ns: int,
    ) -> tuple[int, int]:
        try:
            source_stat = Path(path).stat()
            if source_mtime_ns <= 0:
                source_mtime_ns = int(source_stat.st_mtime_ns)
            return source_mtime_ns, int(source_stat.st_size)
        except OSError:
            return 0, 0

    @staticmethod
    def _render_topview_png(
        path: str,
        tile_size: int,
        cancel_event: threading.Event,
    ) -> tuple[Optional[bytes], bool]:
        render_status: list[bool] = []
        png = render_region_topview(
            path,
            tile_size=tile_size,
            cancel_check=cancel_event.is_set,
            # Tile jobs already occupy the shared CPU lane.  A nested decoder
            # pool would multiply concurrency and can starve sibling tiles.
            decode_workers=1,
            status_out=render_status,
        )
        render_complete = render_status[-1] if render_status else True
        return png, render_complete

    def _finalize_topview_job(
        self,
        *,
        coord: Tuple[int, int],
        path: str,
        tile_size: int,
        generation: int,
        cancel_event: threading.Event,
        png: Optional[bytes],
        render_complete: bool,
        source_mtime_ns: int,
        source_file_size: int,
    ) -> None:
        """Publish worker output, notify UI, and refill the queue."""
        source_signature = self._topview_result_signature(
            path=path,
            coord=coord,
            generation=generation,
            cancel_event=cancel_event,
            png=png,
            render_complete=render_complete,
            source_mtime_ns=source_mtime_ns,
            source_file_size=source_file_size,
        )
        callback, upgrade_size = self._publish_topview_result_locked(
            coord=coord,
            tile_size=tile_size,
            generation=generation,
            cancel_event=cancel_event,
            png=png,
            render_complete=render_complete,
            source_mtime_ns=source_mtime_ns,
            source_file_size=source_file_size,
            source_signature=source_signature,
        )
        self._notify_topview_ready(callback, coord)
        self._safe_pump_topview_queue()
        self._request_topview_upgrade_if_needed(
            coord,
            tile_size,
            generation,
            upgrade_size,
        )

    def _topview_result_signature(
        self,
        *,
        path: str,
        coord: Tuple[int, int],
        generation: int,
        cancel_event: threading.Event,
        png: Optional[bytes],
        render_complete: bool,
        source_mtime_ns: int,
        source_file_size: int,
    ) -> str:
        with self._data_lock:
            result_is_current = (
                generation == self._topview_generation
                and not cancel_event.is_set()
                and not self._closed
            )
        if result_is_current:
            return self._topview_source_signature(
                path,
                coord,
                source_mtime_ns,
                source_file_size,
                cancel_check=cancel_event.is_set,
            )
        return ""

    def _notify_topview_ready(
        self,
        callback: Optional[Any],
        coord: Tuple[int, int],
    ) -> None:
        if callback is None:
            return
        try:
            callback(coord)
        except Exception:
            # UI callback may fail after dispose; keep worker alive.
            pass

    def _safe_pump_topview_queue(self) -> None:
        try:
            self._pump_topview_queue()
        except (RuntimeError, ValueError, OSError):
            # Queue pump failures must not kill the worker thread.
            pass

    def _request_topview_upgrade_if_needed(
        self,
        coord: Tuple[int, int],
        tile_size: int,
        generation: int,
        upgrade_size: Optional[int],
    ) -> None:
        if (
            upgrade_size is not None
            and upgrade_size > tile_size
            and generation == self.get_topview_generation()
        ):
            self.request_topview_tiles(
                [coord],
                tile_size=upgrade_size,
                force=True,
                priority=True,
            )

    def _publish_topview_result_locked(
        self,
        *,
        coord: Tuple[int, int],
        tile_size: int,
        generation: int,
        cancel_event: threading.Event,
        png: Optional[bytes],
        render_complete: bool,
        source_mtime_ns: int,
        source_file_size: int,
        source_signature: str,
    ) -> tuple[Optional[Any], Optional[int]]:
        """Apply success/failure bookkeeping under the data lock.

        Returns:
            tuple: ``(callback, upgrade_size)``.
        """
        callback = None
        upgrade_size: Optional[int] = None
        with self._data_lock:
            if self._topview_pending.get(coord) == generation:
                self._topview_pending.pop(coord, None)
                self._topview_pending_sizes.pop(coord, None)
                upgrade_size = self._topview_upgrade_sizes.pop(coord, None)
            self._topview_active = max(0, self._topview_active - 1)
            current = (
                generation == self._topview_generation
                and not cancel_event.is_set()
                and not self._closed
            )
            if current and png is not None:
                self._store_topview_tile_locked(
                    coord,
                    png,
                    tile_size,
                    render_complete,
                    source_mtime_ns,
                    source_file_size,
                    source_signature,
                )
                callback = self._tile_ready_callback
            elif current and png is None:
                self._record_topview_failure_locked(
                    coord,
                    tile_size,
                    source_mtime_ns,
                    source_file_size,
                    source_signature,
                )
                callback = self._tile_ready_callback
        return callback, upgrade_size

    def _store_topview_tile_locked(
        self,
        coord: Tuple[int, int],
        png: bytes,
        tile_size: int,
        render_complete: bool,
        source_mtime_ns: int,
        source_file_size: int,
        source_signature: str,
    ) -> None:
        """Store a rendered tile and trim the in-memory cache (lock held)."""
        if render_complete:
            self._clear_topview_failure_locked(coord)
        else:
            self._record_topview_failure_locked(
                coord,
                tile_size,
                source_mtime_ns,
                source_file_size,
                source_signature,
            )
        previous = self._topview_tiles.pop(coord, None)
        if previous is not None:
            self._topview_memory_bytes -= len(previous)
        self._topview_tiles[coord] = png
        self._topview_memory_bytes += len(png)
        self._topview_tile_sizes[coord] = int(tile_size)
        self._topview_tile_complete[coord] = render_complete
        self._topview_tile_sources[coord] = (
            int(source_mtime_ns),
            int(source_file_size),
            source_signature,
        )
        self._topview_source_checked_at.pop(coord, None)
        self._topview_revision_counter += 1
        self._topview_tile_revisions[coord] = self._topview_revision_counter
        while (
            self._topview_memory_bytes > self.TOPVIEW_MEMORY_LIMIT
            and self._topview_tiles
        ):
            old_coord, old_png = self._topview_tiles.popitem(last=False)
            self._topview_memory_bytes -= len(old_png)
            self._topview_tile_sizes.pop(old_coord, None)
            self._topview_tile_complete.pop(old_coord, None)
            self._topview_tile_revisions.pop(old_coord, None)
            self._topview_tile_sources.pop(old_coord, None)
            self._topview_source_checked_at.pop(old_coord, None)
