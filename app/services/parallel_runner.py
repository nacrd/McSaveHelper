"""将 core 并行端口绑定到应用级 ExecutionRuntime。"""
from __future__ import annotations

from typing import Callable, Optional, Sequence, TypeVar

from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
    TaskPriority,
)
from app.services.runtime_map import map_items
from core.parallel import ParallelCancelledError, ParallelRunner


ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")


class RuntimeParallelRunner:
    """使用共享运行时通道执行 core 条目映射。"""

    def __init__(
        self,
        runtime: ExecutionRuntime,
        *,
        lane: ExecutionLane = ExecutionLane.CPU,
        priority: TaskPriority = TaskPriority.BACKGROUND,
        feature: str = "parallel",
    ) -> None:
        """绑定共享运行时与默认任务维度。"""
        self._runtime = runtime
        self._lane = lane
        self._priority = priority
        self._feature = feature

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
        """在运行时有界通道中执行映射。

        Args:
            operation: 稳定操作名。
            items: 输入条目。
            worker: 单条目处理函数。
            max_workers: 最大在途任务数提示。
            cancel_check: 额外取消探针。
            on_item_done: 每项完成回调。

        Returns:
            与输入顺序一致的值或异常列表。

        Raises:
            ParallelCancelledError: 运行时通道观察到批量取消。
        """
        material = list(items)

        def runtime_worker(
            token: CancellationToken,
            item: ItemT,
        ) -> ResultT:
            if cancel_check is not None and cancel_check():
                token.cancel()
            token.raise_if_cancelled()
            return worker(item)

        try:
            return map_items(
                self._runtime,
                operation,
                material,
                runtime_worker,
                lane=self._lane,
                priority=self._priority,
                cancel_check=cancel_check,
                on_item_done=on_item_done,
                max_in_flight=max_workers,
                feature=self._feature,
            )
        except OperationCancelledError as exc:
            raise ParallelCancelledError(str(exc)) from exc


def create_runtime_parallel_runner(
    runtime: ExecutionRuntime,
) -> ParallelRunner:
    """创建迁移使用的共享运行时并行端口。"""
    return RuntimeParallelRunner(runtime, feature="migration")


__all__ = [
    "RuntimeParallelRunner",
    "create_runtime_parallel_runner",
]
