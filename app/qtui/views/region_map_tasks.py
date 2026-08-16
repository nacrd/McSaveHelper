"""Qt 区域地图后台扫描任务。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, TypeVar

from app.qtui.utils import run_on_ui
from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
    OperationContext,
    OperationHandle,
    TaskPriority,
)
from core.region_utils import parse_region_coords, scan_region_dir


ResultT = TypeVar("ResultT")
RegionCoord = tuple[int, int]
RegionSizeMap = dict[RegionCoord, int]


@dataclass(frozen=True)
class RegionScanResult:
    """一次区域目录扫描的不可变结果。"""

    region_dir: Path
    sizes: RegionSizeMap
    total_bytes: int


@dataclass(frozen=True)
class RegionMapTaskCallbacks:
    """区域扫描结果的 Qt 主线程投影回调。"""

    scan_ready: Callable[[RegionScanResult, int], None]
    scan_error: Callable[[Exception, int], None]
    scan_progress: Callable[[float, str, int], None]


class RegionMapTasks:
    """拥有区域扫描任务，并丢弃世界切换后的过期结果。"""

    def __init__(
        self,
        runtime: ExecutionRuntime,
        callbacks: RegionMapTaskCallbacks,
    ) -> None:
        """创建扫描任务作用域。

        Args:
            runtime: 应用共享后台运行时。
            callbacks: 主线程投影回调。
        """
        self._scope = runtime.create_scope("qt_explorer_region_map")
        self._callbacks = callbacks
        self._world_generation = 0
        self._scan_handle: Optional[OperationHandle[RegionScanResult]] = None
        self._disposed = False

    def scan_regions(self, region_dir: Path) -> int:
        """异步扫描指定 region 目录中的 MCA 文件大小。"""
        if self._disposed:
            raise RuntimeError("区域地图任务已经释放")
        self._world_generation += 1
        generation = self._world_generation
        self._cancel_handle(self._scan_handle)
        handle = self._scope.submit(
            "scan_regions",
            lambda context: self._scan(region_dir, generation, context),
            lane=ExecutionLane.IO,
            priority=TaskPriority.VISIBLE,
            feature="explorer.region_map",
            world_id=str(region_dir),
            generation=generation,
        )
        self._scan_handle = handle
        handle.add_done_callback(
            lambda completed: self._finish_scan(completed, generation)
        )
        return generation

    def _scan(
        self,
        region_dir: Path,
        generation: int,
        context: OperationContext,
    ) -> RegionScanResult:
        context.raise_if_cancelled()
        run_on_ui(
            self._deliver_progress,
            0.05,
            "listing",
            generation,
        )
        files = scan_region_dir(region_dir)
        context.raise_if_cancelled()
        sizes: RegionSizeMap = {}
        total = 0
        count = len(files)
        for index, path in enumerate(files):
            context.raise_if_cancelled()
            coord = parse_region_coords(path)
            if coord is None:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            sizes[coord] = size
            total += size
            if count and index % 8 == 0:
                run_on_ui(
                    self._deliver_progress,
                    0.1 + 0.85 * (index + 1) / count,
                    "scanning",
                    generation,
                )
        context.raise_if_cancelled()
        return RegionScanResult(
            region_dir=region_dir,
            sizes=sizes,
            total_bytes=total,
        )

    def _finish_scan(
        self,
        handle: OperationHandle[RegionScanResult],
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            run_on_ui(self._deliver_error, error, generation)
            return
        run_on_ui(self._deliver_ready, result, generation)

    def _deliver_ready(self, result: RegionScanResult, generation: int) -> None:
        if self.is_current(generation):
            self._callbacks.scan_ready(result, generation)

    def _deliver_error(self, error: Exception, generation: int) -> None:
        if self.is_current(generation):
            self._callbacks.scan_error(error, generation)

    def _deliver_progress(
        self,
        value: float,
        stage: str,
        generation: int,
    ) -> None:
        if self.is_current(generation):
            self._callbacks.scan_progress(value, stage, generation)

    def is_current(self, generation: int) -> bool:
        """返回扫描结果是否仍属于当前世代。"""
        return not self._disposed and generation == self._world_generation

    @property
    def world_generation(self) -> int:
        """返回当前扫描世代号。"""
        return self._world_generation

    def clear(self) -> None:
        """取消扫描并推进世代。"""
        if self._disposed:
            return
        self._world_generation += 1
        self._cancel_handle(self._scan_handle)
        self._scan_handle = None

    @staticmethod
    def _cancel_handle(handle: Optional[OperationHandle[ResultT]]) -> None:
        if handle is not None:
            handle.cancel()

    def close(self) -> None:
        """幂等释放扫描任务。"""
        if self._disposed:
            return
        self._disposed = True
        self._world_generation += 1
        self._scan_handle = None
        self._scope.close()


__all__ = [
    "RegionMapTaskCallbacks",
    "RegionMapTasks",
    "RegionScanResult",
]
