"""core 层有界并行：统一替代散落的 ThreadPoolExecutor。

core 不得依赖 app.ExecutionRuntime（依赖方向）；算法热路径通过本模块
获得**有硬上限**的线程池。嵌套调用方应显式传入较小的 ``max_workers``。
"""
from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Optional, TypeVar

ResultT = TypeVar("ResultT")
ItemT = TypeVar("ItemT")

# 进程内算法池硬上限，防止 core 自行创造线程风暴。
ABSOLUTE_MAX_WORKERS = 8


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


def map_unordered(
    items: Iterable[ItemT],
    worker: Callable[[ItemT], ResultT],
    *,
    max_workers: Optional[int] = None,
    absolute_max: int = ABSOLUTE_MAX_WORKERS,
) -> list[ResultT]:
    """并行映射并按完成顺序收集结果。

    Args:
        items: 待处理序列（会物化为 list 以计算规模）。
        worker: 单元素处理函数。
        max_workers: 请求并发；None 表示取上限。
        absolute_max: 硬上限。

    Returns:
        按完成顺序排列的结果列表。
    """
    material = list(items)
    if not material:
        return []
    if len(material) == 1:
        return [worker(material[0])]
    workers = clamp_workers(
        max_workers,
        item_count=len(material),
        absolute_max=absolute_max,
    )
    results: list[ResultT] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker, item) for item in material]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def submit_all(
    items: Iterable[ItemT],
    worker: Callable[[ItemT], ResultT],
    *,
    max_workers: Optional[int] = None,
    absolute_max: int = ABSOLUTE_MAX_WORKERS,
) -> tuple[list[Future[ResultT]], int]:
    """提交全部任务并返回 Future 列表与实际 worker 数。

    调用方负责 ``as_completed`` / 取消语义；本函数仅统一创建有界池。
    返回的 Future 在 with 块结束后仍有效（结果已缓冲于 Future）。
    """
    material = list(items)
    if not material:
        return [], 0
    workers = clamp_workers(
        max_workers,
        item_count=len(material),
        absolute_max=absolute_max,
    )
    # Caller needs futures after the pool context; collect results eagerly
    # via map_unordered would lose per-future identity. Keep short-lived pool
    # that waits for completion before exit.
    futures: list[Future[ResultT]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker, item) for item in material]
        # Force completion before pool shutdown so results remain available.
        for future in futures:
            future.result()
    return futures, workers


__all__ = [
    "ABSOLUTE_MAX_WORKERS",
    "clamp_workers",
    "map_unordered",
    "submit_all",
]
