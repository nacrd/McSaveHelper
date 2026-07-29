"""区域目录扫描与统计快照。"""
from __future__ import annotations

from app.services.region_map.host import RegionMapHost
import asyncio
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    OperationHandle,
    TaskPriority,
)
from app.services.region_map.types import ScanProgress
from core.region_utils import parse_region_coords, scan_region_dir


class RegionMapScanMixin(RegionMapHost):
    """Mixin host contract is fulfilled by RegionMapService."""

    def _init_scan_state(self) -> None:
        self._mca_data: Dict[Tuple[int, int], int] = {}
        self._region_meta: Dict[Tuple[int, int], Dict[str, Any]] = {}
        # Metadata is intentionally loaded on demand.  Keep in-flight loads
        # per coordinate so two UI consumers cannot parse the same MCA twice.
        self._region_meta_tasks: Dict[
            Tuple[int, int], OperationHandle[Dict[str, Any]]
        ] = {}
        # region 坐标 → mca 文件路径（俯视图渲染用）
        self._region_paths: Dict[Tuple[int, int], str] = {}
        self._is_scanning: bool = False
        self._scan_progress: float = 0.0
        self._scan_task: Optional[asyncio.Task[Any]] = None
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

    def get_region_path(self, coord: Tuple[int, int]) -> Optional[str]:
        """返回区域 MCA 文件路径。

        Args:
            coord: ``(region_x, region_z)``。

        Returns:
            路径字符串；未知坐标为 None。
        """
        with self._data_lock:
            return self._region_paths.get(coord)

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
            mca_files = await self._scan_region_directory(region_path)
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

    async def _scan_region_directory(self, region_path: Path) -> list[Path]:
        """通过受限 I/O 通道枚举目录，不创建默认线程池。"""
        handle = self._execution_runtime.submit(
            "scan_region_directory",
            lambda token: self._load_region_paths(token, region_path),
            lane=ExecutionLane.IO,
            priority=TaskPriority.VISIBLE,
        )
        return await handle.wait_async()

    @staticmethod
    def _load_region_paths(
        token: CancellationToken,
        region_path: Path,
    ) -> list[Path]:
        """在 I/O 通道扫描 region 目录并在结果发布前检查取消。"""
        token.raise_if_cancelled()
        paths = scan_region_dir(region_path)
        token.raise_if_cancelled()
        return paths

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
