"""
存档区域地图后台扫描服务 (RegionMapService)

提供异步、非阻塞的区域文件扫描能力，
支持进度追踪和数据查询。
"""
import os
import threading
import asyncio
import hashlib
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Deque, Dict, Tuple, Optional
from dataclasses import dataclass

from core.region_utils import parse_region_coords, scan_region_dir
from core.mca.errors import McaError
from core.mca.topview_renderer import LEAF_TILE_SIZE, render_region_topview
from core.mca.region_meta import scan_region_meta
from core.mca.region_file import RegionFile


@dataclass
class ScanProgress:
    """扫描进度信息"""
    total_files: int = 0
    scanned_files: int = 0
    progress: float = 0.0  # 0.0 到 1.0
    is_scanning: bool = False
    error: Optional[str] = None


class RegionMapService:
    """
    存档区域地图后台扫描服务（每个 Explorer 会话一个实例）

    职责：
    - 异步扫描 Minecraft region 目录
    - 缓存区域文件大小数据
    - 提供进度查询接口
    """

    TOPVIEW_QUEUE_LIMIT = 128
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

    def __init__(self) -> None:
        """初始化内部状态"""
        self._init_scan_state()
        self._init_topview_state()
        self._init_topview_workers()

    def _init_scan_state(self) -> None:
        self._mca_data: Dict[Tuple[int, int], int] = {}
        self._region_meta: Dict[Tuple[int, int], Dict[str, Any]] = {}
        # Metadata is intentionally loaded on demand.  Keep in-flight loads
        # per coordinate so two UI consumers cannot parse the same MCA twice.
        self._region_meta_tasks: Dict[Tuple[int, int], asyncio.Task] = {}
        # region 坐标 → mca 文件路径（俯视图渲染用）
        self._region_paths: Dict[Tuple[int, int], str] = {}
        self._is_scanning: bool = False
        self._scan_progress: float = 0.0
        self._scan_task: Optional[asyncio.Task] = None
        self._scan_generation: int = 0
        self._data_revision: int = 0
        self._closed: bool = False
        self._scanned_count: int = 0
        self._total_count: int = 0
        self._error: Optional[str] = None
        # 统计/快照缓存：仅数据变化时重算，避免 _update_loop 每 0.2s 全量遍历
        self._stats_dirty: bool = True
        self._cached_stats: Optional[Dict[str, Any]] = None
        self._cached_data_snapshot: Optional[Dict[Tuple[int, int], int]] = None
        self._cached_snapshot_count: int = -1
        # 扫描线程与 UI 查询之间的共享数据保护。
        self._data_lock = threading.Lock()

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

    def _init_topview_workers(self) -> None:
        # Bounded topview queue: rendering also performs limited parallel chunk
        # decoding, so keep the outer pool small to avoid nested thread storms.
        cpu = os.cpu_count() or 2
        self._topview_max_workers: int = min(2, max(1, cpu // 2))
        self._topview_active: int = 0
        self._topview_cancel_event = threading.Event()
        self._topview_queue: Deque[
            Tuple[Tuple[int, int], str, int, int, threading.Event, int]
        ] = deque()
        self._topview_executor: Optional[ThreadPoolExecutor] = None

    def _ensure_topview_executor(self) -> ThreadPoolExecutor:
        # Serialize creation with close().  close() may be called from the UI
        # while a worker is submitting the next visible tile.
        with self._data_lock:
            if self._closed:
                raise RuntimeError("区域地图服务已关闭")
            if self._topview_executor is None:
                self._topview_executor = ThreadPoolExecutor(
                    max_workers=self._topview_max_workers,
                    thread_name_prefix="topview",
                )
            return self._topview_executor

    @property
    def is_scanning(self) -> bool:
        """当前是否正在扫描"""
        return self._is_scanning

    @property
    def scan_progress(self) -> float:
        """扫描进度 (0.0 到 1.0)"""
        return self._scan_progress

    @property
    def progress_info(self) -> ScanProgress:
        """获取完整的进度信息"""
        return ScanProgress(
            total_files=self._total_count,
            scanned_files=self._scanned_count,
            progress=self._scan_progress,
            is_scanning=self._is_scanning,
            error=self._error
        )

    def get_all_data(self) -> Dict[Tuple[int, int], int]:
        """
        获取当前已扫描到的完整数据快照

        Returns:
            Dict[Tuple[int, int], int]: 坐标到文件大小的映射
        """
        with self._data_lock:
            # 扫描期间 _scanned_count 未变则复用快照，避免每帧 .copy()
            if (self._cached_data_snapshot is not None
                    and self._cached_snapshot_count == self._scanned_count
                    and not self._stats_dirty):
                return self._cached_data_snapshot
            snapshot = self._mca_data.copy()
            self._cached_data_snapshot = snapshot
            self._cached_snapshot_count = self._scanned_count
            return snapshot

    def get_region_meta(self, coord: Tuple[int, int]) -> Dict[str, Any]:
        """返回已缓存的区域元数据，不在 UI 线程做 I/O。

        Args:
            coord: ``(region_x, region_z)``。

        Returns:
            元数据副本；未加载时为空字典。
        """
        with self._data_lock:
            return dict(self._region_meta.get(coord, {}))

    def get_all_region_meta(self) -> Dict[Tuple[int, int], Dict[str, Any]]:
        """返回当前已加载区域元数据的深拷贝快照。

        Returns:
            坐标到元数据字典的映射副本。
        """
        with self._data_lock:
            return {coord: dict(meta) for coord, meta in self._region_meta.items()}

    def _finish_region_meta_task(
        self,
        coord: Tuple[int, int],
        path: str,
        generation: int,
        task: asyncio.Task,
    ) -> None:
        """Publish or discard an on-demand parse and release its task."""
        try:
            meta = task.result()
        except (asyncio.CancelledError, Exception):
            meta = None
        with self._data_lock:
            if self._region_meta_tasks.get(coord) is task:
                self._region_meta_tasks.pop(coord, None)
            if (
                meta is not None
                and not self._closed
                and generation == self._scan_generation
                and self._region_paths.get(coord) == path
            ):
                self._region_meta[coord] = dict(meta or {})

    async def ensure_region_meta(self, coord: Tuple[int, int]) -> Dict[str, Any]:
        """按需加载单区域元数据，不阻塞 UI 循环。

        常规扫描只登记坐标/大小/路径；需要 biome/结构元数据时再 opt-in。
        同坐标并发请求共享一次后台解析；过期扫描结果按 generation 丢弃。

        Args:
            coord: ``(region_x, region_z)``。

        Returns:
            元数据字典副本；无路径或已关闭时为空字典。

        Raises:
            RuntimeError: 服务已 ``close``。
        """
        with self._data_lock:
            if self._closed:
                raise RuntimeError("区域地图服务已关闭")
            cached = self._region_meta.get(coord)
            if cached is not None:
                return dict(cached)
            path = self._region_paths.get(coord)
            generation = self._scan_generation
            task = self._region_meta_tasks.get(coord)
        if not path:
            return {}

        task = self._get_or_create_region_meta_task(coord, path, generation, task)
        meta = await self._await_region_meta_task(coord, task)
        return self._store_region_meta_if_current(
            coord,
            path,
            generation,
            meta,
        )

    def _get_or_create_region_meta_task(
        self,
        coord: Tuple[int, int],
        path: str,
        generation: int,
        task: Optional[Any],
    ) -> Any:
        if task is not None:
            return task
        task = asyncio.create_task(
            asyncio.to_thread(scan_region_meta, Path(path))
        )
        with self._data_lock:
            existing = self._region_meta_tasks.get(coord)
            if existing is None:
                self._region_meta_tasks[coord] = task
                task.add_done_callback(
                    lambda completed: self._finish_region_meta_task(
                        coord,
                        path,
                        generation,
                        completed,
                    )
                )
                return task
            task.cancel()
            return existing

    async def _await_region_meta_task(
        self,
        coord: Tuple[int, int],
        task: Any,
    ) -> Dict[str, Any]:
        try:
            # One caller cancelling its UI operation must not cancel a shared
            # parse still awaited by another consumer. Lifecycle methods can
            # still cancel the underlying task explicitly.
            meta = await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, TypeError, RuntimeError, KeyError):
            meta = {}
        except Exception:
            # Shared region-meta parse may fail for damaged MCA; treat as empty.
            meta = {}
        finally:
            with self._data_lock:
                current = self._region_meta_tasks.get(coord)
                if current is task and current is not None and current.done():
                    self._region_meta_tasks.pop(coord, None)
        return dict(meta or {})

    def _store_region_meta_if_current(
        self,
        coord: Tuple[int, int],
        path: str,
        generation: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        with self._data_lock:
            if (
                self._closed
                or generation != self._scan_generation
                or self._region_paths.get(coord) != path
            ):
                return {}
            self._region_meta[coord] = dict(meta)
            return dict(self._region_meta[coord])

    def clear_data(self) -> None:
        """清空所有缓存数据"""
        meta_tasks: list[asyncio.Task]
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
            self._topview_revision_counter = 0
            self._topview_failed_sizes.clear()
            self._topview_failed_mtimes.clear()
            self._topview_failed_file_sizes.clear()
            self._topview_failed_signatures.clear()
            self._topview_failure_counts.clear()
            self._topview_pending.clear()
            self._topview_pending_sizes.clear()
            self._topview_upgrade_sizes.clear()
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
        # ``to_thread`` cannot interrupt an already-running native parse, but
        # cancelling its asyncio wrapper prevents a late result from keeping
        # references alive or being published to the new world.
        for task in meta_tasks:
            self._cancel_asyncio_task(task)
        # A new scan represents a new world/dimension, so release old-world
        # compact surface entries instead of carrying them into the next map.
        try:
            from core.mca.surface import clear_chunk_decode_cache

            clear_chunk_decode_cache()
        except (ImportError, RuntimeError, AttributeError):
            pass

    def set_tile_ready_callback(self, callback: Optional[Any]) -> None:
        """注册俯视图瓦片就绪回调。

        回调可能从 topview 工作线程触发；UI 侧需自行切回 UI 线程。

        Args:
            callback: ``callback(coord)``；传 None 清除。
        """
        self._tile_ready_callback = callback

    def get_region_path(self, coord: Tuple[int, int]) -> Optional[str]:
        """返回区域 MCA 文件路径。

        Args:
            coord: ``(region_x, region_z)``。

        Returns:
            路径字符串；未知坐标为 None。
        """
        with self._data_lock:
            return self._region_paths.get(coord)

    def get_topview_tile(self, coord: Tuple[int, int]) -> Optional[bytes]:
        """取缓存的俯视 PNG 瓦片（命中则刷新 LRU）。

        Args:
            coord: 区域坐标。

        Returns:
            PNG 字节；未缓存为 None。
        """
        with self._data_lock:
            tile = self._topview_tiles.get(coord)
            if tile is not None:
                self._topview_tiles.move_to_end(coord)
            return tile

    def has_topview_tile(self, coord: Tuple[int, int], min_size: int = 0) -> bool:
        """判断是否已有满足最小尺寸的完整瓦片。

        未完成渲染且失败尺寸小于缓存尺寸时视为不可用。

        Args:
            coord: 区域坐标。
            min_size: 要求的最小边长像素；0 表示任意缓存即可。

        Returns:
            是否可作为当前 LOD 使用。
        """
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
        _force: bool,
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
        try:
            current_stat = Path(path).stat()
            current_mtime = int(current_stat.st_mtime_ns)
            current_size = int(current_stat.st_size)
        except OSError:
            current_mtime = 0
            current_size = 0
        current_signature = self._topview_source_signature(
            path,
            coord,
            current_mtime,
            current_size,
        )
        if (
            self._topview_failed_signatures.get(coord) == current_signature
            or (
                not self._topview_failed_signatures.get(coord)
                and self._topview_failed_mtimes.get(coord) == current_mtime
                and (
                    self._topview_failed_file_sizes.get(coord) is None
                    or self._topview_failed_file_sizes.get(coord) == current_size
                )
            )
        ):
            return None
        self._clear_topview_failure_locked(coord)
        return path

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
                    force=force,
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
        force: bool,
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
        path = self._topview_path_for_request_locked(coord, size, force)
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
        jobs: list[
            Tuple[Tuple[int, int], str, int, int, threading.Event, int]
        ] = []
        with self._data_lock:
            while (
                self._topview_active < self._topview_max_workers
                and self._topview_queue
            ):
                job = self._topview_queue.popleft()
                # Drop stale jobs from a previous generation.
                if job[3] != self._topview_generation:
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
            try:
                executor.submit(self._render_topview_worker, *job)
            except (RuntimeError, ValueError):
                self._rollback_topview_jobs([job])
            except Exception:
                self._rollback_topview_jobs([job])

    def _rollback_topview_jobs(
        self,
        jobs: list[
            Tuple[Tuple[int, int], str, int, int, threading.Event, int]
        ],
    ) -> None:
        """Return jobs that could not be submitted after a close race."""
        with self._data_lock:
            for coord, _path, _size, generation, _cancel, _mtime in jobs:
                self._topview_active = max(0, self._topview_active - 1)
                if self._topview_pending.get(coord) == generation:
                    self._topview_pending.pop(coord, None)
                    self._topview_pending_sizes.pop(coord, None)

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
            decode_workers=2 if tile_size >= LEAF_TILE_SIZE else 1,
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
        if result_is_current and (png is None or not render_complete):
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

    def _mark_data_dirty(self) -> None:
        """标记数据变更，下次 get_statistics/get_all_data 时重算。"""
        self._stats_dirty = True
        self._cached_data_snapshot = None
        self._data_revision += 1
        self._cached_snapshot_count = -1

    async def start_silent_scan(
            self,
            region_dir: str,
            batch_size: int = 30) -> None:
        """
        启动静默扫描任务

        Args:
            region_dir: region 目录路径
            batch_size: 每批处理文件数量（用于进度更新）
        """
        scan_generation = await self._prepare_silent_scan()
        try:
            region_path = Path(region_dir)
            mca_files = await asyncio.to_thread(scan_region_dir, region_path)
            self._total_count = len(mca_files)
            if not mca_files:
                self._finish_silent_scan(scan_generation)
                return

            await self._scan_region_files(
                mca_files,
                scan_generation,
                batch_size,
            )
            self._finish_silent_scan(scan_generation)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self._error = str(exc)
            self._is_scanning = False
            raise
        except Exception as exc:
            self._error = str(exc)
            self._is_scanning = False
            raise

    async def _prepare_silent_scan(self) -> int:
        if self._closed:
            raise RuntimeError("区域地图服务已关闭")
        if self._is_scanning:
            await self.cancel_scan()
        self.clear_data()
        self._is_scanning = True
        self._error = None
        return self._scan_generation

    async def _scan_region_files(
        self,
        mca_files: list[Path],
        scan_generation: int,
        batch_size: int,
    ) -> None:
        for mca_file in mca_files:
            if not self._scan_is_current(scan_generation):
                return
            try:
                if not self._record_scanned_region(mca_file, scan_generation):
                    return
                if self._scanned_count % batch_size == 0:
                    await asyncio.sleep(0)
            except (OSError, ValueError, TypeError, RuntimeError):
                continue
            except Exception:
                continue

    def _record_scanned_region(
        self,
        mca_file: Path,
        scan_generation: int,
    ) -> bool:
        coord = parse_region_coords(mca_file)
        size = mca_file.stat().st_size if coord is not None else 0
        with self._data_lock:
            if not self._scan_is_current(scan_generation):
                return False
            if coord is not None:
                self._mca_data[coord] = size
                self._region_paths[coord] = str(mca_file)
                self._mark_data_dirty()
            self._scanned_count += 1
            if self._total_count > 0:
                self._scan_progress = self._scanned_count / self._total_count
        return True

    def _finish_silent_scan(self, scan_generation: int) -> None:
        with self._data_lock:
            if not self._scan_is_current(scan_generation):
                return
            self._scan_progress = 1.0
            self._is_scanning = False
            self._mark_data_dirty()

    def _scan_is_current(self, scan_generation: int) -> bool:
        return not self._closed and scan_generation == self._scan_generation

    async def cancel_scan(self) -> None:
        """取消当前扫描任务"""
        self._scan_generation += 1
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
            try:
                # 使用 shield 防止取消自己导致死锁
                await asyncio.shield(self._scan_task)
            except (asyncio.CancelledError, RuntimeError):
                pass

        self._is_scanning = False
        self._scan_task = None

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
            self._topview_failed_sizes.clear()
            self._topview_failed_mtimes.clear()
            self._topview_failed_file_sizes.clear()
            self._topview_failed_signatures.clear()
            self._topview_failure_counts.clear()
            self._topview_tile_revisions.clear()
            self._topview_tile_complete.clear()
        for task in meta_tasks:
            self._cancel_asyncio_task(task)
        executor = self._topview_executor
        self._topview_executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    async def start_scan_async(self, region_dir: str) -> None:
        """
        启动异步扫描（创建后台任务）

        Args:
            region_dir: region 目录路径
        """
        # 如果有旧的扫描任务，先取消
        if self._scan_task and not self._scan_task.done():
            await self.cancel_scan()

        # 创建新的后台任务
        self._scan_task = asyncio.create_task(
            self.start_silent_scan(region_dir)
        )

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取扫描统计信息（带缓存，仅数据变化时重算）

        Returns:
            包含统计数据的字典
        """
        with self._data_lock:
            if not self._stats_dirty and self._cached_stats is not None:
                return self._cached_stats

            if not self._mca_data:
                empty = {
                    "total_regions": 0,
                    "total_size": 0,
                    "avg_size": 0,
                    "min_size": 0,
                    "max_size": 0,
                    "min_coord": None,
                    "max_coord": None
                }
                self._cached_stats = empty
                self._stats_dirty = False
                return empty

            total_size = 0
            min_size = float('inf')
            max_size = 0
            min_coord = None
            max_coord = None

            for coord, size in self._mca_data.items():
                total_size += size
                if size < min_size:
                    min_size = size
                if size > max_size:
                    max_size = size
                if min_coord is None or coord < min_coord:
                    min_coord = coord
                if max_coord is None or coord > max_coord:
                    max_coord = coord

            count = len(self._mca_data)
            stats = {
                "total_regions": count,
                "total_size": total_size,
                "avg_size": total_size // count if count else 0,
                "min_size": min_size,
                "max_size": max_size,
                "min_coord": min_coord,
                "max_coord": max_coord,
            }
            self._cached_stats = stats
            self._stats_dirty = False
            return stats
