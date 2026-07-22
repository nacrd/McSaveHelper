"""运行时合成探针：取消延迟等可单元测试的验收指标。"""
from __future__ import annotations

import threading
import time
from typing import Optional

from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    TaskPriority,
)


def probe_cancel_latency_ms(
    runtime: ExecutionRuntime,
    *,
    lane: ExecutionLane = ExecutionLane.CPU,
    poll_interval_s: float = 0.001,
) -> float:
    """在受控场景测量「请求取消 → 工作函数观察到取消」的毫秒数。

    Args:
        runtime: 共享或测试用运行时。
        lane: 提交通道。
        poll_interval_s: 工作循环轮询间隔。

    Returns:
        取消延迟毫秒。

    Raises:
        TimeoutError: 工作未能在合理时间内启动或观察到取消。
    """
    started = threading.Event()
    observed = threading.Event()

    def work(token) -> bool:
        started.set()
        deadline = time.perf_counter() + 5.0
        while time.perf_counter() < deadline:
            if token.is_cancelled:
                observed.set()
                return True
            time.sleep(poll_interval_s)
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
    if not observed.wait(2.0):
        raise TimeoutError("取消探针未在时限内观察到取消标记")
    try:
        handle.result(timeout=1.0)
    except Exception:
        # 取消路径可能以 CancelledError 结束，探针只关心观察延迟。
        pass
    return (time.perf_counter() - t0) * 1000.0


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
