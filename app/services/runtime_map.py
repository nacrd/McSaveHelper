"""在统一 ExecutionRuntime 上批量并行处理条目。"""
from __future__ import annotations

from typing import Callable, Optional, Sequence, TypeVar

from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
    OperationHandle,
    TaskPriority,
    TaskQueueFullError,
)

ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")


def _resolve_in_flight_limit(
    runtime: ExecutionRuntime,
    lane: ExecutionLane,
    total: int,
    max_in_flight: Optional[int],
) -> int:
    """计算批量任务允许的最大在途数量。"""
    if max_in_flight is not None:
        return max(1, int(max_in_flight))
    workers = runtime.snapshot().worker_count_by_lane.get(lane, 1) or 1
    return min(max(1, workers * 2), total)


def _should_cancel(cancel_check: Optional[Callable[[], bool]]) -> bool:
    """读取可选取消探针。"""
    return cancel_check is not None and cancel_check()


def _raise_if_batch_cancelled(
    operation: str,
    cancel_check: Optional[Callable[[], bool]],
) -> None:
    """在批量循环的安全检查点抛出取消。"""
    if _should_cancel(cancel_check):
        raise OperationCancelledError(f"批量操作已取消: {operation}")


def _make_item_worker(
    worker: Callable[[CancellationToken, ItemT], ResultT],
    item: ItemT,
    cancel_check: Optional[Callable[[], bool]],
) -> Callable[[CancellationToken], ResultT]:
    """绑定单个条目与取消探针到运行时工作函数。"""

    def work(token: CancellationToken) -> ResultT:
        if _should_cancel(cancel_check):
            token.cancel()
        token.raise_if_cancelled()
        return worker(token, item)

    return work


def _submit_more(
    *,
    runtime: ExecutionRuntime,
    operation: str,
    items: Sequence[ItemT],
    worker: Callable[[CancellationToken, ItemT], ResultT],
    lane: ExecutionLane,
    priority: TaskPriority,
    cancel_check: Optional[Callable[[], bool]],
    pending: dict[OperationHandle[ResultT], int],
    next_index: int,
    in_flight_limit: int,
) -> int:
    """在容量允许时继续提交条目，返回新的 next_index。"""
    total = len(items)
    while next_index < total and len(pending) < in_flight_limit:
        _raise_if_batch_cancelled(operation, cancel_check)
        item_index = next_index
        item = items[item_index]
        next_index += 1
        try:
            handle = runtime.submit(
                f"{operation}[{item_index}]",
                _make_item_worker(worker, item, cancel_check),
                lane=lane,
                priority=priority,
            )
        except TaskQueueFullError:
            if not pending:
                raise
            return next_index - 1
        pending[handle] = item_index
    return next_index


def _collect_done(
    pending: dict[OperationHandle[ResultT], int],
) -> list[OperationHandle[ResultT]]:
    """返回已完成句柄；若暂无完成则短暂等待其中一个。"""
    done_handles = [handle for handle in pending if handle.done]
    if done_handles:
        return done_handles
    first = next(iter(pending))
    try:
        first.result(timeout=0.05)
    except Exception:
        pass
    return [handle for handle in pending if handle.done]


def _publish_done(
    *,
    pending: dict[OperationHandle[ResultT], int],
    done_handles: list[OperationHandle[ResultT]],
    results: list[ResultT | BaseException | None],
    on_item_done: Optional[Callable[[int, ResultT | BaseException], None]],
) -> int:
    """把完成句柄写入结果槽，返回本次完成数量。"""
    finished = 0
    for handle in done_handles:
        item_index = pending.pop(handle)
        try:
            value: ResultT | BaseException = handle.result(timeout=0)
        except Exception as exc:  # noqa: BLE001 - 槽位聚合失败
            value = exc
        results[item_index] = value
        finished += 1
        if on_item_done is not None:
            on_item_done(item_index, value)
    return finished


def _cancel_pending(pending: dict[OperationHandle[ResultT], int]) -> None:
    """取消并尽量排空在途任务以释放容量。"""
    for handle in tuple(pending):
        handle.cancel()
        try:
            handle.result(timeout=0.01)
        except Exception:
            pass


def _finalize_results(
    results: list[ResultT | BaseException | None],
) -> list[ResultT | BaseException]:
    """把可空结果槽物化为最终列表。"""
    finalized: list[ResultT | BaseException] = []
    for index, value in enumerate(results):
        if value is None:
            finalized.append(RuntimeError(f"missing result at {index}"))
        else:
            finalized.append(value)
    return finalized


def map_items(
    runtime: ExecutionRuntime,
    operation: str,
    items: Sequence[ItemT],
    worker: Callable[[CancellationToken, ItemT], ResultT],
    *,
    lane: ExecutionLane = ExecutionLane.CPU,
    priority: TaskPriority = TaskPriority.BACKGROUND,
    cancel_check: Optional[Callable[[], bool]] = None,
    on_item_done: Optional[
        Callable[[int, ResultT | BaseException], None]
    ] = None,
    max_in_flight: Optional[int] = None,
) -> list[ResultT | BaseException]:
    """在有界通道中并行处理条目，结果顺序与输入一致。

    大批量不会一次灌满队列：仅保持有限在途任务，完成后再补提交。
    取消后停止新提交并取消在途任务。

    Args:
        runtime: 应用共享或本地拥有的执行运行时。
        operation: 稳定操作名前缀。
        items: 输入条目。
        worker: 接收取消标记与条目并返回结果。
        lane: 资源通道。
        priority: 任务优先级。
        cancel_check: 额外取消探针。
        on_item_done: 每个条目完成时回调。
        max_in_flight: 最大在途任务数。

    Returns:
        与输入等长的结果列表；失败项为异常实例。

    Raises:
        OperationCancelledError: 处理期间观察到取消请求。
        RuntimeClosedError: 运行时已关闭。
        TaskQueueFullError: 无在途任务时仍无法提交。
    """
    total = len(items)
    if total == 0:
        return []

    in_flight_limit = _resolve_in_flight_limit(
        runtime,
        lane,
        total,
        max_in_flight,
    )
    results: list[ResultT | BaseException | None] = [None] * total
    pending: dict[OperationHandle[ResultT], int] = {}
    next_index = 0
    completed = 0

    try:
        while completed < total:
            _raise_if_batch_cancelled(operation, cancel_check)
            next_index = _submit_more(
                runtime=runtime,
                operation=operation,
                items=items,
                worker=worker,
                lane=lane,
                priority=priority,
                cancel_check=cancel_check,
                pending=pending,
                next_index=next_index,
                in_flight_limit=in_flight_limit,
            )
            if not pending:
                continue
            done_handles = _collect_done(pending)
            if not done_handles:
                continue
            completed += _publish_done(
                pending=pending,
                done_handles=done_handles,
                results=results,
                on_item_done=on_item_done,
            )
    finally:
        _cancel_pending(pending)

    return _finalize_results(results)


__all__ = ["map_items"]
