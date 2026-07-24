"""运行时合成探针：取消延迟等可单元测试的验收指标。"""
from __future__ import annotations

import threading
import time
from concurrent.futures import CancelledError

from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
    TaskPriority,
)
from app.services.operation_progress import OperationState


def probe_cancel_latency_ms(
    runtime: ExecutionRuntime,
    *,
    lane: ExecutionLane = ExecutionLane.CPU,
) -> float:
    """测量「请求取消 → UI 可读状态更新」的毫秒数。

    Args:
        runtime: 共享或测试用运行时。
        lane: 提交通道。
    Returns:
        取消延迟毫秒。

    Raises:
        TimeoutError: 工作未能在合理时间内启动。
        AssertionError: 取消请求未同步更新任务状态。
    """
    started = threading.Event()
    release = threading.Event()

    def work(token: CancellationToken) -> bool:
        started.set()
        release.wait(5.0)
        token.raise_if_cancelled()
        return False

    handle = runtime.submit(
        "probe_cancel_latency",
        work,
        lane=lane,
        priority=TaskPriority.VISIBLE,
    )
    if not started.wait(2.0):
        handle.cancel()
        raise TimeoutError("取消探针工作未能启动")
    t0 = time.perf_counter()
    handle.cancel()
    state = handle.progress().state
    latency_ms = (time.perf_counter() - t0) * 1000.0
    if state is not OperationState.CANCEL_REQUESTED:
        raise AssertionError(f"取消状态未同步发布: {state.value}")
    release.set()
    try:
        handle.result(timeout=1.0)
    except (CancelledError, OperationCancelledError):
        pass
    return latency_ms


def cancel_within_budget(
    runtime: ExecutionRuntime,
    *,
    budget_ms: float = 100.0,
) -> float:
    """执行取消探针并要求延迟不超过预算。

    Returns:
        实测延迟毫秒。

    Raises:
        AssertionError: 超过预算时（供测试使用，消息可读）。
    """
    latency = probe_cancel_latency_ms(runtime)
    if latency > float(budget_ms):
        raise AssertionError(
            f"取消延迟 {latency:.3f}ms 超过预算 {budget_ms:.3f}ms"
        )
    return latency


__all__ = [
    "cancel_within_budget",
    "probe_cancel_latency_ms",
]
