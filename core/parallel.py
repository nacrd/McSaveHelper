"""core 层并行端口：默认串行，由应用显式注入统一运行时。"""
from __future__ import annotations

import os
from typing import Callable, Optional, Protocol, Sequence, TypeVar

ResultT = TypeVar("ResultT")
ItemT = TypeVar("ItemT")

# 应用并行端口接受的 worker 提示硬上限。
ABSOLUTE_MAX_WORKERS = 8


class ParallelCancelledError(RuntimeError):
    """并行端口在安全检查点观察到取消请求。"""


class ParallelRunner(Protocol):
    """由应用层实现的有界并行映射端口。"""

    def map(
        self,
        operation: str,
        items: Sequence[ItemT],
        worker: Callable[[ItemT], ResultT],
        *,
        max_workers: Optional[int] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_item_done: Optional[
            Callable[[int, ResultT | BaseException], None]
        ] = None,
    ) -> list[ResultT | BaseException]:
        """处理条目并返回与输入顺序一致的结果。"""
        ...


class SerialParallelRunner:
    """core 默认串行实现，不自行拥有线程或执行器。"""

    def map(
        self,
        operation: str,
        items: Sequence[ItemT],
        worker: Callable[[ItemT], ResultT],
        *,
        max_workers: Optional[int] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_item_done: Optional[
            Callable[[int, ResultT | BaseException], None]
        ] = None,
    ) -> list[ResultT | BaseException]:
        """在当前线程处理条目，并保持统一错误聚合语义。

        Args:
            operation: 稳定操作名，用于取消错误。
            items: 输入条目。
            worker: 单条目处理函数。
            max_workers: 兼容并行实现的提示；串行实现忽略。
            cancel_check: 可选取消探针。
            on_item_done: 每项结束后的轻量回调。

        Returns:
            与输入等长的值或异常列表。

        Raises:
            ParallelCancelledError: 处理下一项前观察到取消。
        """
        del max_workers
        results: list[ResultT | BaseException] = []
        for index, item in enumerate(items):
            if cancel_check is not None and cancel_check():
                raise ParallelCancelledError(f"并行操作已取消: {operation}")
            try:
                value: ResultT | BaseException = worker(item)
            except Exception as exc:
                value = exc
            results.append(value)
            if on_item_done is not None:
                on_item_done(index, value)
        return results


def clamp_workers(
    requested: Optional[int],
    *,
    item_count: int,
    absolute_max: int = ABSOLUTE_MAX_WORKERS,
) -> int:
    """将请求的工作线程数钳制到 ``[1, min(item_count, absolute_max, cpu)]``。"""
    if item_count < 1:
        return 1
    cpu = os.cpu_count() or 2
    ceiling = max(1, min(absolute_max, cpu, item_count))
    if requested is None:
        return ceiling
    return max(1, min(int(requested), ceiling))


__all__ = [
    "ABSOLUTE_MAX_WORKERS",
    "ParallelCancelledError",
    "ParallelRunner",
    "SerialParallelRunner",
    "clamp_workers",
]
