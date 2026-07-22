"""区域元数据按需加载与共享解析。"""
from __future__ import annotations

from app.services.region_map.host import RegionMapHost
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    OperationHandle,
    RuntimeClosedError,
    TaskPriority,
    TaskQueueFullError,
)
from core.mca.region_meta import scan_region_meta


class RegionMapMetaMixin(RegionMapHost):
    """Mixin host contract is fulfilled by RegionMapService."""

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
        handle: OperationHandle[Dict[str, Any]],
    ) -> None:
        """Publish or discard an on-demand parse and release its task."""
        try:
            meta = handle.result()
        except (OSError, RuntimeError, ValueError, TypeError):
            meta = None
        except Exception:
            meta = None
        with self._data_lock:
            if self._region_meta_tasks.get(coord) is handle:
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

        handle = self._get_or_create_region_meta_task(
            coord,
            path,
            generation,
            task,
        )
        meta = await self._await_region_meta_task(coord, handle)
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
        task: Optional[OperationHandle[Dict[str, Any]]],
    ) -> OperationHandle[Dict[str, Any]]:
        if task is not None:
            return task
        try:
            handle = self._execution_runtime.submit(
                "load_region_meta",
                lambda token: self._load_region_meta(token, path),
                lane=ExecutionLane.CPU,
                priority=TaskPriority.INTERACTIVE,
            )
        except (RuntimeClosedError, TaskQueueFullError):
            return self._completed_empty_meta_handle()
        with self._data_lock:
            existing = self._region_meta_tasks.get(coord)
            if existing is None:
                self._region_meta_tasks[coord] = handle
                handle.add_done_callback(
                    lambda completed: self._finish_region_meta_task(
                        coord,
                        path,
                        generation,
                        completed,
                    )
                )
                return handle
            handle.cancel()
            return existing

    @staticmethod
    def _load_region_meta(
        token: CancellationToken,
        path: str,
    ) -> Dict[str, Any]:
        """在受限计算通道解析一份 MCA 元数据。"""
        token.raise_if_cancelled()
        return scan_region_meta(Path(path))

    @staticmethod
    def _completed_empty_meta_handle() -> OperationHandle[Dict[str, Any]]:
        """为饱和时的可重试元数据请求创建空完成结果。"""
        from concurrent.futures import Future

        future: Future[Dict[str, Any]] = Future()
        future.set_result({})
        return OperationHandle(
            operation="load_region_meta",
            lane=ExecutionLane.CPU,
            priority=TaskPriority.INTERACTIVE,
            _future=future,
            _token=CancellationToken(),
        )

    async def _await_region_meta_task(
        self,
        coord: Tuple[int, int],
        handle: OperationHandle[Dict[str, Any]],
    ) -> Dict[str, Any]:
        try:
            # One caller cancelling its UI operation must not cancel a shared
            # parse still awaited by another consumer. Lifecycle methods can
            # still cancel the underlying task explicitly.
            meta = await asyncio.shield(handle.wait_async())
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
                if current is not None and current is handle and current.done:
                    self._region_meta_tasks.pop(coord, None)
        if handle.cancel_requested:
            raise asyncio.CancelledError
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
