"""
存档区域地图后台扫描服务 (RegionMapService)

提供异步、非阻塞的区域文件扫描能力，
支持进度追踪和数据查询。
"""
import os
import threading
import asyncio
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Deque, Dict, Tuple, Optional
from dataclasses import dataclass

from core.region_utils import parse_region_coords, scan_region_dir
from core.perf_timing import PerfTimer
from core.mca.topview_renderer import render_region_topview


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

    def __init__(self) -> None:
        """初始化内部状态"""
        self._mca_data: Dict[Tuple[int, int], int] = {}
        self._region_meta: Dict[Tuple[int, int], Dict[str, Any]] = {}
        # region 坐标 → mca 文件路径（俯视图渲染用）
        self._region_paths: Dict[Tuple[int, int], str] = {}
        # region 坐标 → PNG bytes（顶视瓦片缓存）
        self._topview_tiles: Dict[Tuple[int, int], bytes] = {}
        self._is_scanning: bool = False
        self._scan_progress: float = 0.0
        self._scan_task: Optional[asyncio.Task] = None
        self._scan_generation: int = 0
        self._closed: bool = False
        self._scanned_count: int = 0
        self._total_count: int = 0
        self._error: Optional[str] = None
        # 统计/快照缓存：仅数据变化时重算，避免 _update_loop 每 0.2s 全量遍历
        self._stats_dirty: bool = True
        self._cached_stats: Optional[Dict[str, Any]] = None
        self._cached_data_snapshot: Optional[Dict[Tuple[int, int], int]] = None
        self._cached_snapshot_count: int = -1
        # anvil 扫描并发写保护（asyncio.to_thread 后多线程写 _mca_data）
        self._data_lock = threading.Lock()
        # 俯视图生成代数：clear/start 时递增，丢弃过期回调
        self._topview_generation: int = 0
        self._topview_pending: set = set()
        self._topview_tile_size: int = 32
        self._topview_enabled: bool = True
        # Track rendered tile size so we can upgrade 64→128 later if needed.
        self._topview_tile_sizes: Dict[Tuple[int, int], int] = {}
        # 瓦片变更回调（由 UI 注册，在 UI 线程调度）
        self._tile_ready_callback: Optional[Any] = None
        # Bounded topview queue: never spawn one thread per region.
        # anvil chunk decode is CPU+IO heavy; 2 workers keep hang detector calm.
        cpu = os.cpu_count() or 2
        self._topview_max_workers: int = max(2, min(4, (cpu or 2) // 2 or 2))
        self._topview_active: int = 0
        self._topview_queue: Deque[Tuple[Tuple[int, int], str, int, int]] = deque()
        self._topview_executor: Optional[ThreadPoolExecutor] = None

    def _ensure_topview_executor(self) -> ThreadPoolExecutor:
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
        with self._data_lock:
            return dict(self._region_meta.get(coord, {}))

    def get_all_region_meta(self) -> Dict[Tuple[int, int], Dict[str, Any]]:
        with self._data_lock:
            return {coord: dict(meta) for coord, meta in self._region_meta.items()}

    def get_data_snapshot(self) -> Dict[Tuple[int, int], int]:
        """
        获取数据快照（get_all_data 的别名，保持兼容性）
        """
        return self.get_all_data()

    def clear_data(self) -> None:
        """清空所有缓存数据"""
        with self._data_lock:
            self._mca_data.clear()
            self._region_meta.clear()
            self._region_paths.clear()
            self._topview_tiles.clear()
            self._topview_tile_sizes.clear()
            self._topview_pending.clear()
            self._topview_queue.clear()
            self._topview_generation += 1
            self._scanned_count = 0
            self._total_count = 0
            self._scan_progress = 0.0
            self._error = None
            self._stats_dirty = True
            self._cached_stats = None
            self._cached_data_snapshot = None
            self._cached_snapshot_count = -1

    def set_tile_ready_callback(self, callback: Optional[Any]) -> None:
        """Register callback(coord) invoked when a topview tile is ready."""
        self._tile_ready_callback = callback

    def get_region_path(self, coord: Tuple[int, int]) -> Optional[str]:
        with self._data_lock:
            return self._region_paths.get(coord)

    def get_topview_tile(self, coord: Tuple[int, int]) -> Optional[bytes]:
        with self._data_lock:
            return self._topview_tiles.get(coord)

    def has_topview_tile(self, coord: Tuple[int, int], min_size: int = 0) -> bool:
        with self._data_lock:
            if coord not in self._topview_tiles:
                return False
            if min_size <= 0:
                return True
            return int(self._topview_tile_sizes.get(coord, 0) or 0) >= min_size

    def get_topview_tile_size(self, coord: Tuple[int, int]) -> int:
        with self._data_lock:
            return int(self._topview_tile_sizes.get(coord, 0) or 0)

    def get_topview_generation(self) -> int:
        with self._data_lock:
            return self._topview_generation

    def request_topview_tiles(
        self,
        coords: list[Tuple[int, int]],
        tile_size: Optional[int] = None,
        *,
        force: bool = False,
        priority: bool = False,
    ) -> None:
        """Enqueue topview rendering for coords missing a cached tile.

        Uses a bounded worker pool instead of one thread per region. Visible
        tiles should be requested by the map view; scan itself does not flood
        the queue.

        Args:
            force: re-render even if a tile already exists (e.g. upgrade size).
            priority: put jobs at the front of the queue (selected region).
        """
        if self._closed or not self._topview_enabled:
            return
        size = int(tile_size or self._topview_tile_size)
        with self._data_lock:
            generation = self._topview_generation
            for coord in coords:
                if coord in self._topview_pending and not force:
                    # Already scheduled; if force-upgrade, still allow a second
                    # job only when existing scheduled size is smaller.
                    continue
                existing = self._topview_tiles.get(coord)
                existing_size = int(self._topview_tile_sizes.get(coord, 0) or 0)
                if existing is not None and not force and existing_size >= size:
                    continue
                if existing is not None and force and existing_size >= size:
                    continue
                path = self._region_paths.get(coord)
                if not path:
                    continue
                self._topview_pending.add(coord)
                job = (coord, path, size, generation)
                if priority:
                    self._topview_queue.appendleft(job)
                else:
                    self._topview_queue.append(job)
        self._pump_topview_queue()

    def _pump_topview_queue(self) -> None:
        """Start queued jobs up to the worker cap."""
        jobs: list[Tuple[Tuple[int, int], str, int, int]] = []
        with self._data_lock:
            while (
                self._topview_active < self._topview_max_workers
                and self._topview_queue
            ):
                job = self._topview_queue.popleft()
                # Drop stale jobs from a previous generation.
                if job[3] != self._topview_generation:
                    self._topview_pending.discard(job[0])
                    continue
                self._topview_active += 1
                jobs.append(job)

        if not jobs:
            return

        executor = self._ensure_topview_executor()
        for job in jobs:
            executor.submit(self._render_topview_worker, *job)

    def _render_topview_worker(
        self,
        coord: Tuple[int, int],
        path: str,
        tile_size: int,
        generation: int,
    ) -> None:
        png: Optional[bytes] = None
        try:
            # Skip work for superseded generations as early as possible.
            with self._data_lock:
                if generation != self._topview_generation:
                    return
            png = render_region_topview(path, tile_size=tile_size)
        except Exception:
            png = None
        finally:
            callback = None
            with self._data_lock:
                self._topview_pending.discard(coord)
                self._topview_active = max(0, self._topview_active - 1)
                if generation == self._topview_generation and png is not None:
                    self._topview_tiles[coord] = png
                    self._topview_tile_sizes[coord] = int(tile_size)
                    callback = self._tile_ready_callback
            if callback is not None and png is not None:
                try:
                    callback(coord)
                except Exception:
                    pass
            # Fill freed worker slots.
            try:
                self._pump_topview_queue()
            except Exception:
                pass

    def _mark_data_dirty(self) -> None:
        """标记数据变更，下次 get_statistics/get_all_data 时重算。"""
        self._stats_dirty = True
        self._cached_data_snapshot = None
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
        if self._closed:
            raise RuntimeError("区域地图服务已关闭")

        # 如果正在扫描，先取消
        if self._is_scanning:
            await self.cancel_scan()

        # 清空旧数据
        self.clear_data()
        self._scan_generation += 1
        scan_generation = self._scan_generation
        self._is_scanning = True
        self._error = None

        try:
            region_path = Path(region_dir)

            # 首先快速统计文件总数
            mca_files = scan_region_dir(region_path)
            self._total_count = len(mca_files)

            if self._total_count == 0:
                self._is_scanning = False
                self._scan_progress = 1.0
                return

            for mca_file in mca_files:
                if self._closed or scan_generation != self._scan_generation:
                    return
                try:
                    coord = parse_region_coords(mca_file)
                    if coord is not None:
                        size = mca_file.stat().st_size
                        # anvil 同步解析丢进线程池，await 期间 UI loop 可处理事件
                        meta = await asyncio.to_thread(
                            self._scan_region_meta, mca_file)
                        if (
                            self._closed
                            or scan_generation != self._scan_generation
                        ):
                            return
                        with self._data_lock:
                            self._mca_data[coord] = size
                            self._region_meta[coord] = meta
                            self._region_paths[coord] = str(mca_file)
                            self._mark_data_dirty()
                        # Topview tiles are requested by the map view for
                        # currently visible cells only (not every region).

                    with self._data_lock:
                        self._scanned_count += 1
                        if self._total_count > 0:
                            self._scan_progress = (
                                self._scanned_count / self._total_count)

                    if self._scanned_count % batch_size == 0:
                        await asyncio.sleep(0)
                except Exception:
                    continue

            # 最终更新
            if scan_generation == self._scan_generation:
                with self._data_lock:
                    self._scan_progress = 1.0
                    self._is_scanning = False
                    self._mark_data_dirty()

        except Exception as e:
            self._error = str(e)
            self._is_scanning = False
            raise

    def _scan_region_meta(self, region_file: Path) -> Dict[str, Any]:
        biomes: Counter[str] = Counter()
        structures: Counter[str] = Counter()
        structure_positions: list[Dict[str, Any]] = []
        chunk_count = 0
        with PerfTimer("heatmap._scan_region_meta"):
            try:
                from core.mca import NativeRegion
                with NativeRegion.from_file(region_file) as region:
                    sample_points = [(0, 0), (0, 16), (16, 0), (16, 16),
                                     (8, 8), (8, 24), (24, 8), (24, 24)]
                    for cx, cz in sample_points:
                        try:
                            chunk = region.get_chunk(cx, cz)
                            if chunk is None or chunk.data is None:
                                continue
                            chunk_count += 1
                            data = chunk.data
                            self._collect_biomes(data, biomes)
                            self._collect_structures(
                                data, structures, structure_positions)
                        except Exception:
                            continue
                    if not biomes and not structures:
                        for cx in range(0, 32, 4):
                            for cz in range(0, 32, 4):
                                if chunk_count >= 16:
                                    break
                                try:
                                    chunk = region.get_chunk(cx, cz)
                                    if chunk is None or chunk.data is None:
                                        continue
                                    chunk_count += 1
                                    data = chunk.data
                                    self._collect_biomes(data, biomes)
                                    self._collect_structures(
                                        data, structures, structure_positions)
                                except Exception:
                                    continue
                            if chunk_count >= 16:
                                break
            except Exception:
                pass

        dominant_biome = biomes.most_common(1)[0][0] if biomes else "unknown"
        dominant_structure = structures.most_common(
            1)[0][0] if structures else "none"
        return {
            "chunk_count": chunk_count,
            "dominant_biome": dominant_biome,
            "biomes": dict(biomes.most_common(8)),
            "structure_count": sum(structures.values()),
            "dominant_structure": dominant_structure,
            "structures": dict(structures.most_common(8)),
            "structure_positions": structure_positions[:12],
        }

    def _collect_biomes(self, data: Any, counter: Counter[str]) -> None:
        root = self._chunk_root(data)
        sections = self._first(root, "sections", "Sections")
        if self._is_sequence(sections):
            for section in self._iter_values(sections):
                biomes = self._first(section, "biomes", "Biomes")
                palette = self._first(
                    biomes, "palette", "Palette") if self._is_mapping(biomes) else None
                if self._is_sequence(palette):
                    for biome in list(self._iter_values(palette))[:16]:
                        name = self._tag_text(biome)
                        if name:
                            counter[name] += 1
        legacy_biomes = self._first(root, "Biomes", "biomes")
        if self._is_sequence(legacy_biomes):
            for biome in list(self._iter_values(legacy_biomes))[:64]:
                name = self._tag_text(biome)
                if name:
                    counter[name] += 1

    def _collect_structures(self,
                            data: Any,
                            counter: Counter[str],
                            positions: list[Dict[str,
                                                 Any]]) -> None:
        root = self._chunk_root(data)
        structures = self._first(root, "structures", "Structures")
        starts = self._first(
            structures,
            "starts",
            "Starts") if self._is_mapping(structures) else None
        if self._is_mapping(starts):
            for name, value in self._items(starts):
                if str(name).lower() not in {
                        "references", "starts"} and value is not None:
                    counter[str(name)] += 1
                    pos = self._extract_structure_position(str(name), value)
                    if pos:
                        positions.append(pos)
        refs = self._first(
            structures,
            "References",
            "references") if self._is_mapping(structures) else None
        if self._is_mapping(refs):
            for name, value in self._items(refs):
                try:
                    if len(value) > 0:
                        counter[str(name)] += 1
                except Exception:
                    counter[str(name)] += 1

    def _extract_structure_position(
            self, name: str, value: Any) -> Optional[Dict[str, Any]]:
        if not self._is_mapping(value):
            return None
        bb = self._first(value, "BB", "bb", "bounding_box")
        pos = self._position_from_bb(name, bb)
        if pos:
            return pos
        children = self._first(value, "Children", "children")
        if self._is_sequence(children):
            for child in self._iter_values(children):
                if not self._is_mapping(child):
                    continue
                pos = self._position_from_bb(
                    name, self._first(
                        child, "BB", "bb", "bounding_box"))
                if pos:
                    return pos
        chunk_x = self._first(value, "ChunkX", "chunkX", "chunk_x")
        chunk_z = self._first(value, "ChunkZ", "chunkZ", "chunk_z")
        if chunk_x is not None and chunk_z is not None:
            try:
                bx = int(self._tag_value(chunk_x)) * 16
                bz = int(self._tag_value(chunk_z)) * 16
                return {
                    "name": name,
                    "block_x": bx,
                    "block_z": bz,
                    "source": "chunk"}
            except Exception:
                return None
        return None

    def _position_from_bb(
            self, name: str, bb: Any) -> Optional[Dict[str, Any]]:
        raw = self._tag_value(bb)
        if self._is_sequence(raw):
            raw = list(self._iter_values(raw))
        if not isinstance(raw, list) or len(raw) < 6:
            return None
        try:
            return {
                "name": name,
                "block_x": int(self._tag_value(raw[0])),
                "block_y": int(self._tag_value(raw[1])),
                "block_z": int(self._tag_value(raw[2])),
                "source": "bb",
            }
        except Exception:
            return None

    def _chunk_root(self, data: Any) -> Any:
        level = self._first(data, "Level")
        if self._is_mapping(level):
            return level
        return data

    def _first(self, data: Any, *keys: str) -> Any:
        if not self._is_mapping(data):
            return None
        for key in keys:
            value = self._get(data, key)
            if value is not None:
                return value
        return None

    def _is_mapping(self, value: Any) -> bool:
        raw = self._tag_value(value)
        return isinstance(
            raw,
            dict) or hasattr(
            raw,
            "get") or hasattr(
            raw,
            "items")

    def _is_sequence(self, value: Any) -> bool:
        raw = self._tag_value(value)
        if isinstance(raw, (str, bytes, dict)):
            return False
        return isinstance(raw, (list, tuple)) or hasattr(raw, "__iter__")

    def _get(self, data: Any, key: str) -> Any:
        raw = self._tag_value(data)
        try:
            if hasattr(raw, "get"):
                return raw.get(key)
            return raw[key]
        except Exception:
            return None

    def _items(self, data: Any) -> list[tuple[Any, Any]]:
        raw = self._tag_value(data)
        try:
            if hasattr(raw, "items"):
                return list(raw.items())
        except Exception:
            pass
        return []

    def _iter_values(self, data: Any) -> list[Any]:
        raw = self._tag_value(data)
        try:
            return list(raw)
        except Exception:
            return []

    def _tag_text(self, value: Any) -> str:
        raw = getattr(value, "value", value)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            return raw
        if hasattr(value, "value") and raw is not None:
            return str(raw)
        return str(raw) if raw is not None else ""

    def _tag_value(self, value: Any) -> Any:
        return getattr(value, "value", value)

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
        """Release callbacks, queued jobs and worker resources idempotently."""
        if self._closed:
            return
        self._closed = True
        self._scan_generation += 1
        self._is_scanning = False
        scan_task = self._scan_task
        self._scan_task = None
        if scan_task is not None and not scan_task.done():
            scan_task.cancel()
        self.set_tile_ready_callback(None)
        with self._data_lock:
            self._topview_generation += 1
            self._topview_queue.clear()
            self._topview_pending.clear()
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


def get_region_map_service() -> RegionMapService:
    """Compatibility factory returning a fresh session-scoped service."""
    return RegionMapService()
